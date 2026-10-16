"""Deterministic supplier matching (FR-63): no LLM, no I/O, no clock (Slice 5a spec section 5)."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Literal
from uuid import UUID

from app.modules.extraction.public import canon_unit

from .matching_config import ALIASES, DEFAULT, STOPWORDS, MatchConfig


@dataclass(frozen=True)
class BoqLine:
    id: UUID
    item_no: str | None
    description: str
    unit: str | None


@dataclass(frozen=True)
class QuoteLine:
    id: UUID
    supplier_id: UUID
    quotation_id: UUID
    description: str
    sku: str | None
    unit: str | None
    unit_price: Decimal | None
    valid_until: date | None


@dataclass(frozen=True)
class Suggestion:
    boq_id: UUID
    quote_id: UUID
    supplier_id: UUID
    score: Decimal
    classification: Literal["clear", "ambiguous"]
    rank: int
    evidence: dict[str, Any]


# --- spec tokens -------------------------------------------------------------------------------

_VALUE_UNIT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ka|kv|kw|kva|mm2|mm|hz|va|a|v|w)(?![a-z0-9])")
_CORES = re.compile(r"(\d+)\s*c\s*\+\s*e(?![a-z0-9])")
_IP = re.compile(r"(?<![a-z0-9])ip\s?(\d{2})(?![a-z0-9])")
_STRUCT = {
    "pole": re.compile(r"(\d+)[\s-]*pole"),
    "way": re.compile(r"(\d+)[\s-]*way"),
    "phase": re.compile(r"(\d+)[\s-]*phase"),
}


def _norm_number(raw: str) -> str:
    return format(Decimal(raw.replace(",", ".")).normalize(), "f")


def spec_tokens(text: str) -> dict[str, frozenset[str]]:
    """Electrical specifics as {kind: values}: `400 A` -> a:{400}, `3C+E` -> core:{3c+e}."""
    low = text.lower().replace("²", "2").replace("³", "3")
    kinds: dict[str, set[str]] = defaultdict(set)
    for number, unit in _VALUE_UNIT.findall(low):
        kinds[unit].add(_norm_number(number))
    for n in _CORES.findall(low):
        kinds["core"].add(f"{n}c+e")
    for n in _IP.findall(low):
        kinds["ip"].add(n)
    for kind, pattern in _STRUCT.items():
        for n in pattern.findall(low):
            kinds[kind].add(n)
    return {k: frozenset(v) for k, v in kinds.items()}


def _compare_specs(
    a: dict[str, frozenset[str]], b: dict[str, frozenset[str]]
) -> tuple[float | None, dict[str, Any]]:
    if not a and not b:
        return None, {"matched": [], "conflicts": [], "boq_only": [], "quote_only": []}
    matched, conflicts, boq_only, quote_only = [], [], [], []
    for kind in sorted(set(a) | set(b)):
        if kind in a and kind in b:
            (matched if a[kind] & b[kind] else conflicts).append(kind)
        elif kind in a:
            boq_only.append(kind)
        else:
            quote_only.append(kind)
    total = len(matched) + len(conflicts) + len(boq_only) + len(quote_only)
    detail = {
        "matched": matched,
        "conflicts": conflicts,
        "boq_only": boq_only,
        "quote_only": quote_only,
    }
    return len(matched) / total, detail


# --- text --------------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")


def _tokens(text: str) -> frozenset[str]:
    out: set[str] = set()
    for raw in _WORD.findall(text.lower().replace("²", "2")):
        for word in ALIASES.get(raw, raw).split():
            if word in STOPWORDS:
                continue
            out.add(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return frozenset(out)


def _text_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    dice = 2 * len(a & b) / (len(a) + len(b))
    seq = SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b)), autojunk=False).ratio()
    return (dice + seq) / 2


_CODE = re.compile(r"\b(?:sku[-\s]?)?([a-z]{0,6}-?\d{3,}[a-z0-9-]*)\b", re.I)


def _codes(text: str) -> set[str]:
    return {c.lower() for c in _CODE.findall(text) if re.search(r"\d", c)}


# --- scoring -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Scored:
    boq: BoqLine
    quote: QuoteLine
    score: float
    conflict: bool
    unit_mismatch: bool
    evidence: dict[str, Any]


def _unit_state(boq_unit: str | None, quote_unit: str | None) -> str:
    a, b = canon_unit(boq_unit), canon_unit(quote_unit)
    if not a or not b:
        return "unknown"
    return "equal" if a == b else "mismatch"


def _score_pair(
    boq: BoqLine, quote: QuoteLine, boq_data: tuple, closing: date | None, cfg: MatchConfig
) -> _Scored:
    boq_specs, boq_tokens, boq_codes = boq_data
    quote_specs = spec_tokens(quote.description)
    spec_score, spec_detail = _compare_specs(boq_specs, quote_specs)
    text_score = _text_similarity(boq_tokens, _tokens(quote.description))
    state = _unit_state(boq.unit, quote.unit)
    unit_score = {"equal": 1.0, "mismatch": 0.0, "unknown": 0.5}[state]
    if spec_score is None:
        score = (
            (cfg.w_text * text_score + cfg.w_unit * unit_score)
            / (cfg.w_text + cfg.w_unit)
            * cfg.no_spec_factor
        )
    else:
        score = cfg.w_spec * spec_score + cfg.w_text * text_score + cfg.w_unit * unit_score
    code_hit = bool(quote.sku and (_codes(quote.sku) | {quote.sku.lower()}) & boq_codes) or bool(
        boq_codes & _codes(quote.description)
    )
    if code_hit:
        score += cfg.code_bonus
    conflict = bool(spec_detail["conflicts"])
    if conflict:
        score -= cfg.conflict_penalty
    score = max(0.0, min(1.0, score))
    warnings = []
    if conflict:
        warnings.append("spec_conflict")
    if state == "mismatch":
        warnings.append("unit_mismatch")
    if closing and quote.valid_until and quote.valid_until < closing:
        warnings.append("quote_expires_before_closing")
    evidence = {
        "signals": {
            "text": round(text_score, 4),
            "spec": None if spec_score is None else round(spec_score, 4),
            "unit": unit_score,
            "code": code_hit,
        },
        "spec": spec_detail,
        "unit": {"boq": canon_unit(boq.unit), "quote": canon_unit(quote.unit), "state": state},
        "price": {"unit_price": None if quote.unit_price is None else str(quote.unit_price)},
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "warnings": warnings,
    }
    return _Scored(boq, quote, score, conflict, state == "mismatch", evidence)


def suggest(
    boq: Sequence[BoqLine],
    quotes: Sequence[QuoteLine],
    closing_date: date | None = None,
    config: MatchConfig = DEFAULT,
) -> list[Suggestion]:
    out: list[Suggestion] = []
    by_supplier: dict[UUID, list[QuoteLine]] = defaultdict(list)
    for q in quotes:
        by_supplier[q.supplier_id].append(q)
    for line in boq:
        data = (spec_tokens(line.description), _tokens(line.description), _codes(line.description))
        if not data[1] and not data[0]:
            continue
        for supplier_id in sorted(by_supplier, key=str):
            scored = [
                _score_pair(line, q, data, closing_date, config) for q in by_supplier[supplier_id]
            ]
            scored = [s for s in scored if s.score >= config.ambiguous_min]
            scored.sort(key=lambda s: (-s.score, str(s.quote.id)))
            for rank, s in enumerate(scored[: config.top_n], start=1):
                runner_up = scored[1].score if rank == 1 and len(scored) > 1 else None
                clear = (
                    rank == 1
                    and s.score >= config.suggest_min
                    and not s.conflict
                    and not s.unit_mismatch
                    and (runner_up is None or s.score - runner_up >= config.margin)
                )
                evidence = {**s.evidence, "rank": rank}
                out.append(
                    Suggestion(
                        line.id,
                        s.quote.id,
                        supplier_id,
                        Decimal(str(round(s.score, 4))),
                        "clear" if clear else "ambiguous",
                        rank,
                        evidence,
                    )
                )
    return out
