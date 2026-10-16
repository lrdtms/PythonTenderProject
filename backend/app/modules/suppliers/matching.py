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

from .matching_config import ALIASES, CANONICAL_UNITS, DEFAULT, STOPWORDS, MatchConfig


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
    low = _normalise(text)
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


_SPEC_SPANS = (_VALUE_UNIT, _CORES, _IP, *_STRUCT.values())


def _normalise(text: str) -> str:
    return text.lower().replace("²", "2").replace("³", "3")


def _strip_specs(low: str) -> str:
    """Blank out the spans that `spec_tokens` consumed, so they are not also words or codes."""
    for pattern in _SPEC_SPANS:
        low = pattern.sub(" ", low)
    return low


def _compare_specs(
    a: dict[str, frozenset[str]], b: dict[str, frozenset[str]]
) -> tuple[float | None, dict[str, Any]]:
    if not a and not b:
        return None, {
            "matched": [],
            "conflicts": [],
            "multi_value": [],
            "boq_only": [],
            "quote_only": [],
        }
    matched, conflicts, multi, boq_only, quote_only = [], [], [], [], []
    for kind in sorted(set(a) | set(b)):
        if kind in a and kind in b:
            if a[kind] & b[kind]:
                matched.append(kind)
                if a[kind] != b[kind]:
                    multi.append(kind)
            else:
                conflicts.append(kind)
        elif kind in a:
            boq_only.append(kind)
        else:
            quote_only.append(kind)
    total = len(matched) + len(conflicts) + len(boq_only) + len(quote_only)
    detail = {
        "matched": matched,
        "conflicts": conflicts,
        "multi_value": multi,
        "boq_only": boq_only,
        "quote_only": quote_only,
    }
    return len(matched) / total, detail


# --- text --------------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")


def _tokens(text: str) -> frozenset[str]:
    """Descriptive words; spec values (`400 A`, `3C+E`) are scored by the spec signal instead."""
    out: set[str] = set()
    for raw in _WORD.findall(_strip_specs(_normalise(text))):
        for word in ALIASES.get(raw, raw).split():
            if word in STOPWORDS:
                continue
            out.add(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return frozenset(out)


_DICE_FLOOR = 0.2  # below this the (slow) sequence ratio cannot matter; text = dice


def _text_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    dice = 2 * len(a & b) / (len(a) + len(b))
    if dice < _DICE_FLOOR:
        return dice
    seq = SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b)), autojunk=False).ratio()
    return (dice + seq) / 2


_PREFIXED_CODE = re.compile(
    r"(?<![a-z0-9])(?:sku|part|code|pn|p/n)\s*[-:#]?\s*([a-z0-9][a-z0-9-]*)"
)
_MIXED_CODE = re.compile(r"(?<![a-z0-9-])([a-z0-9]+(?:-[a-z0-9]+)*)(?![a-z0-9])")
_PREFIX_HEAD = re.compile(r"^(?:sku|part|code|pn)-")
_BARE_UNIT = re.compile(r"^(?:m2|m3|mm2)$")


def _codes(text: str) -> frozenset[str]:
    """Product codes: explicit `sku/part/code` references, or tokens mixing letters and digits."""
    low = _strip_specs(_normalise(text))
    out = {c.rstrip("-") for c in _PREFIXED_CODE.findall(low)}
    for token in _MIXED_CODE.findall(low):
        if (
            re.search(r"\d", token)
            and re.search(r"[a-z]", token)
            and not _PREFIX_HEAD.match(token)
            and not _BARE_UNIT.match(token)
        ):
            out.add(token)
    return frozenset(c for c in out if c)


# --- scoring -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Prepared:
    """Everything derived from one description, computed once."""

    specs: dict[str, frozenset[str]]
    tokens: frozenset[str]
    codes: frozenset[str]
    spec_pairs: frozenset[tuple[str, str]]


def _prepare(description: str, sku: str | None = None) -> _Prepared:
    specs = spec_tokens(description)
    codes = _codes(description)
    if sku and sku.strip():
        codes = codes | _codes(sku) | {sku.strip().lower()}
    pairs = frozenset((k, v) for k, vs in specs.items() for v in vs)
    return _Prepared(specs, _tokens(description), codes, pairs)


@dataclass(frozen=True)
class _Scored:
    quote: QuoteLine
    score: float
    text: float
    spec: float | None
    spec_detail: dict[str, Any]
    unit_state: str
    unit_score: float
    code_hit: bool

    @property
    def conflict(self) -> bool:
        return bool(self.spec_detail["conflicts"])

    @property
    def multi_value(self) -> bool:
        return bool(self.spec_detail["multi_value"])

    @property
    def unit_mismatch(self) -> bool:
        return self.unit_state == "mismatch"


def _unit_state(boq_unit: str | None, quote_unit: str | None) -> str:
    a, b = canon_unit(boq_unit), canon_unit(quote_unit)
    if not a or not b:
        return "unknown"
    return "equal" if a == b else "mismatch"


def _known_unit(raw: str | None) -> str | None:
    """The canonical unit, or None: free text must never be echoed into the evidence."""
    unit = canon_unit(raw)
    return unit if unit in CANONICAL_UNITS else None


def _score_pair(
    boq: BoqLine, boq_p: _Prepared, quote: QuoteLine, quote_p: _Prepared, cfg: MatchConfig
) -> _Scored:
    spec_score, spec_detail = _compare_specs(boq_p.specs, quote_p.specs)
    text_score = _text_similarity(boq_p.tokens, quote_p.tokens)
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
    code_hit = bool(boq_p.codes & quote_p.codes)
    if code_hit:
        score += cfg.code_bonus
    if spec_detail["conflicts"]:
        score -= cfg.conflict_penalty
    score = max(0.0, min(1.0, score))
    return _Scored(quote, score, text_score, spec_score, spec_detail, state, unit_score, code_hit)


def _evidence(boq: BoqLine, s: _Scored, rank: int, closing: date | None) -> dict[str, Any]:
    quote = s.quote
    warnings = []
    if s.conflict:
        warnings.append("spec_conflict")
    if s.multi_value:
        warnings.append("spec_multi_value")
    if s.unit_mismatch:
        warnings.append("unit_mismatch")
    if closing and quote.valid_until and quote.valid_until < closing:
        warnings.append("quote_expires_before_closing")
    return {
        "signals": {
            "text": round(s.text, 4),
            "spec": None if s.spec is None else round(s.spec, 4),
            "unit": s.unit_score,
            "code": s.code_hit,
        },
        "spec": s.spec_detail,
        "unit": {
            "boq": _known_unit(boq.unit),
            "quote": _known_unit(quote.unit),
            "state": s.unit_state,
        },
        "price": {"unit_price": None if quote.unit_price is None else str(quote.unit_price)},
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "warnings": warnings,
        "rank": rank,
    }


@dataclass
class _Index:
    """Inverted index over one supplier's quotes: which quotes share a word, a spec or a code."""

    size: int
    by_token: dict[str, list[int]]
    by_spec: dict[tuple[str, str], list[int]]
    by_code: dict[str, list[int]]


def _build_index(prepared: Sequence[_Prepared]) -> _Index:
    index = _Index(len(prepared), defaultdict(list), defaultdict(list), defaultdict(list))
    for i, p in enumerate(prepared):
        for t in p.tokens:
            index.by_token[t].append(i)
        for pair in p.spec_pairs:
            index.by_spec[pair].append(i)
        for c in p.codes:
            index.by_code[c].append(i)
    return index


def _candidate_indices(line: _Prepared, index: _Index) -> Sequence[int]:
    """Quotes that share a word, a (kind, value) spec or a code with the line.

    A pair sharing none of these scores at most `w_unit + code_bonus`, far below `ambiguous_min`.
    """
    found: set[int] = set()
    for t in line.tokens:
        found.update(index.by_token.get(t, ()))
    for pair in line.spec_pairs:
        found.update(index.by_spec.get(pair, ()))
    for c in line.codes:
        found.update(index.by_code.get(c, ()))
    return sorted(found)


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
    suppliers = []
    for supplier_id in sorted(by_supplier, key=str):
        qs = sorted(by_supplier[supplier_id], key=lambda q: str(q.id))
        prepared = [_prepare(q.description, q.sku) for q in qs]
        suppliers.append((supplier_id, qs, prepared, _build_index(prepared)))
    for line in boq:
        line_p = _prepare(line.description)
        if not line_p.tokens and not line_p.specs:
            continue
        for supplier_id, qs, prepared, index in suppliers:
            scored = [
                _score_pair(line, line_p, qs[i], prepared[i], config)
                for i in _candidate_indices(line_p, index)
            ]
            scored = [s for s in scored if s.score >= config.ambiguous_min]
            scored.sort(key=lambda s: (-s.score, str(s.quote.id)))
            for rank, s in enumerate(scored[: config.top_n], start=1):
                runner_up = scored[1].score if rank == 1 and len(scored) > 1 else None
                clear = (
                    rank == 1
                    and s.score >= config.suggest_min
                    and s.text >= config.clear_text_min
                    and not s.conflict
                    and not s.multi_value
                    and not s.unit_mismatch
                    and (runner_up is None or s.score - runner_up >= config.margin)
                )
                out.append(
                    Suggestion(
                        line.id,
                        s.quote.id,
                        supplier_id,
                        Decimal(str(round(s.score, 4))),
                        "clear" if clear else "ambiguous",
                        rank,
                        _evidence(line, s, rank, closing_date),
                    )
                )
    return out
