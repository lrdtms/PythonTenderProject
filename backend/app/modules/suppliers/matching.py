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

from .matching_config import (
    ACCESSORY_WORDS,
    ALIASES,
    CANONICAL_UNITS,
    DEFAULT,
    DISCRIMINATING_WORDS,
    NEGATION_WORDS,
    STOPWORDS,
    MatchConfig,
)


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


# Every warning code an evidence dict can carry (the frontend label table is checked against it).
EVIDENCE_WARNING_CODES = (
    "spec_conflict", "spec_multi_value", "unit_mismatch", "core_notation_differs",
    "text_differs", "spec_one_sided", "accessory_word", "negation", "number_differs",
    "defining_word_missing", "word_one_sided", "quote_shared", "quote_expires_before_closing",
)  # fmt: skip


# --- spec tokens -------------------------------------------------------------------------------

# A value must not be glued to a preceding word or digit (`mcb20a` is a code, not 20 A); `2x58w`
# is the one glued form that still reads (the `x` follows a digit).
_VALUE_UNIT = re.compile(
    r"(?:(?<![a-z\d.,])|(?<=\dx))(\d+(?:[.,]\d+)?)\s*(ka|kv|kw|kva|mm2|mm|hz|va|a|v|w)(?![a-z0-9])"
)
# `4x16mm2`, `4 x 16 mm2`: N cores of S mm2 (same core convention as `4-core`).
_N_BY_S = re.compile(r"(?<![a-z\d.,])(\d+)\s*x\s*(\d+(?:[.,]\d+)?)\s*mm2(?![a-z0-9])")
# `1 500 W`, `1 200 mm`: space-grouped thousands before a unit.
_UNITS = r"(?:ka|kv|kw|kva|mm2|mm|hz|va|a|v|w)"
# Ambiguous (`2 100 W` is 2100 W or 2 x 100 W): both readings are kept, never one guessed.
_GROUPED = re.compile(r"(?<![\d.,])(\d{1,3})((?:[ \u00a0]\d{3})+)\s*(" + _UNITS + r")(?![a-z0-9])")
# `Type B`, `Type AC` (RCD / MCB classes); `a` is a stopword, so it needs its own kind.
_TYPE = re.compile(r"(?<![a-z0-9])type\s+(?!(?:of|to|in|on|or|an)\b)([a-z]{1,2})\b")
_CORES = re.compile(r"(\d+)\s*c\s*\+\s*e(?![a-z0-9])")
_CORE_WORD = re.compile(r"(?<![a-z0-9])(\d+)[\s-]*core(?![a-z0-9])")  # "4-core" == "4C+E"
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
    for cores, section in _N_BY_S.findall(low):
        kinds["core"].add(f"{cores}c+e")
        kinds["mm2"].add(_norm_number(section))
    low = _N_BY_S.sub(" ", low)
    for lead, groups, unit in _GROUPED.findall(low):
        digits = re.sub(r"\s", "", groups)
        kinds[unit].update((lead + digits, digits[-3:]))
    low = _GROUPED.sub(" ", low)
    for t in _TYPE.findall(low):
        kinds["type"].add(t)
    low = _TYPE.sub(" ", low)
    for number, unit in _VALUE_UNIT.findall(low):
        kinds[unit].add(_norm_number(number))
    for n in (*_CORES.findall(low), *_CORE_WORD.findall(low)):
        kinds["core"].add(f"{n}c+e")
    for n in _IP.findall(low):
        kinds["ip"].add(n)
    for kind, pattern in _STRUCT.items():
        for n in pattern.findall(low):
            kinds[kind].add(n)
    return {k: frozenset(v) for k, v in kinds.items()}


_SPEC_SPANS = (_N_BY_S, _GROUPED, _TYPE, _VALUE_UNIT, _CORES, _CORE_WORD, _IP, *_STRUCT.values())


def _normalise(text: str) -> str:
    return text.lower().replace("²", "2").replace("³", "3")


def _strip_specs(low: str) -> str:
    """Blank out the spans that `spec_tokens` consumed, so they are not also words or codes."""
    for pattern in _SPEC_SPANS:
        low = pattern.sub(" ", low)
    return low


# Words that exclude each other within one attribute of a product. They never add to the spec
# score; they only veto: one side says `single`, the other `double`, so it is not that item.
_QUALIFIERS: dict[str, dict[str, str]] = {
    "gang": {"single": "single", "double": "double", "triple": "triple"},
    "material": {
        "steel": "steel",
        "pvc": "pvc",
        "aluminium": "aluminium",
        "aluminum": "aluminium",
        "copper": "copper",
        "brass": "brass",
    },
    "mounting": {"surface": "surface", "flush": "flush", "recessed": "flush"},
    "placement": {"indoor": "indoor", "outdoor": "outdoor"},
}


def qualifier_tokens(text: str) -> dict[str, frozenset[str]]:
    words = set(_WORD.findall(_normalise(text)))
    found: dict[str, frozenset[str]] = {}
    for kind, vocabulary in _QUALIFIERS.items():
        values = frozenset(vocabulary[w] for w in words if w in vocabulary)
        if values:
            found[kind] = values
    return found


def _qualifier_conflicts(a: dict[str, frozenset[str]], b: dict[str, frozenset[str]]) -> list[str]:
    return [k for k in sorted(set(a) & set(b)) if not a[k] & b[k]]


def _compare_specs(
    a: dict[str, frozenset[str]],
    b: dict[str, frozenset[str]],
    qual_conflicts: Sequence[str] = (),
) -> tuple[float | None, dict[str, Any]]:
    if not a and not b and not qual_conflicts:
        return None, {
            "matched": [],
            "conflicts": [],
            "multi_value": [],
            "boq_only": [],
            "quote_only": [],
        }
    matched, conflicts, multi, boq_only, quote_only = [], list(qual_conflicts), [], [], []
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
            out.add(_stem(word))
    return frozenset(out)


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_PREFIXED_CODE = re.compile(
    r"(?<![a-z0-9])(?:sku|part|code|pn|p/n)\s*[-:#]?\s*([a-z0-9][a-z0-9-]*)"
)


def number_multiset(text: str) -> tuple[str, ...]:
    """Every number in the description, repeats kept, sorted: `600 x 600 40 W` -> 40, 600, 600.

    Space-grouped thousands before a unit (`1 500 W`) are joined first, so they read as one number.
    A set of words loses repeats (`600 x 600` == `1200 x 600`) and a one-sided number; this keeps
    both."""
    low = _PREFIXED_CODE.sub(" ", _normalise(text))  # `SKU-4453` names a catalogue, not a size
    low = _GROUPED.sub(lambda m: m.group(1) + re.sub(r"\s", "", m.group(2)) + " " + m.group(3), low)
    return tuple(sorted(_norm_number(n) for n in _NUMBER.findall(low)))


_ACCESSORY_STEMS = frozenset(_stem(w) for w in ACCESSORY_WORDS)
_DISCRIMINATING_STEMS = frozenset(_stem(w) for w in DISCRIMINATING_WORDS)
_NEGATION = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in NEGATION_WORDS) + r")(?![a-z0-9])"
)


_DICE_FLOOR = 0.2  # below this the (slow) sequence ratio cannot matter; text = dice


def _text_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    dice = 2 * len(a & b) / (len(a) + len(b))
    if dice < _DICE_FLOOR:
        return dice
    seq = SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b)), autojunk=False).ratio()
    return (dice + seq) / 2


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
    quals: dict[str, frozenset[str]]
    core_notation: frozenset[str]  # which spellings were used: "word" (3-core), "plus" (3C+E)
    numbers: tuple[str, ...] = ()  # every number, repeats kept
    negated: bool = False
    unit: str | None = None  # canonical unit, computed once per line


def _core_notation(low: str) -> frozenset[str]:
    out = set()
    if _CORES.search(low):
        out.add("plus")
    if _CORE_WORD.search(low) or _N_BY_S.search(low):
        out.add("word")
    return frozenset(out)


def _prepare(description: str, sku: str | None = None, unit: str | None = None) -> _Prepared:
    specs = spec_tokens(description)
    codes = _codes(description)
    if sku and sku.strip():
        codes = codes | _codes(sku) | {sku.strip().lower()}
    pairs = frozenset((k, v) for k, vs in specs.items() for v in vs)
    return _Prepared(
        specs,
        _tokens(description),
        codes,
        pairs,
        qualifier_tokens(description),
        _core_notation(_normalise(description)),
        number_multiset(description),
        bool(_NEGATION.search(_normalise(description))),
        canon_unit(unit),
    )


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
    unit_neutral: float  # the score if the unit matched: the margin must not rest on units alone
    core_notation_differs: bool = False
    vetoes: tuple[str, ...] = ()

    @property
    def conflict(self) -> bool:
        return bool(self.spec_detail["conflicts"])

    @property
    def multi_value(self) -> bool:
        return bool(self.spec_detail["multi_value"])

    @property
    def unit_mismatch(self) -> bool:
        return self.unit_state == "mismatch"


def _unit_state(a: str | None, b: str | None) -> str:
    if not a or not b:
        return "unknown"
    return "equal" if a == b else "mismatch"


def _known_unit(raw: str | None) -> str | None:
    """The canonical unit, or None: free text must never be echoed into the evidence."""
    unit = canon_unit(raw)
    return unit if unit in CANONICAL_UNITS else None


def _vetoes(
    boq_p: _Prepared, quote_p: _Prepared, spec_detail: dict[str, Any], cfg: MatchConfig = DEFAULT
) -> tuple[str, ...]:
    """Reasons a pair must not be `clear` even though it scores well: the score never moves.

    The spec parser reads only a few kinds, so two products that differ in an unread word (Type B
    vs Type C, a lid vs the tray) can share every parsed spec. These checks catch that.
    """
    out = []
    if boq_p.tokens - quote_p.tokens and quote_p.tokens - boq_p.tokens:
        out.append("text_differs")  # each side has a word the other lacks (one-sided extras are ok)
    if spec_detail["boq_only"] or spec_detail["quote_only"]:
        out.append("spec_one_sided")
    if (boq_p.tokens ^ quote_p.tokens) & _ACCESSORY_STEMS:
        out.append("accessory_word")
    if boq_p.negated or quote_p.negated:
        out.append("negation")
    if boq_p.numbers != quote_p.numbers:
        out.append("number_differs")  # 600 x 600 vs 1200 x 600; a number only one side states
    differing = boq_p.tokens ^ quote_p.tokens
    if differing & _DISCRIMINATING_STEMS:
        out.append("defining_word_missing")  # emergency, dimmable, stainless ... on one side only
    elif cfg.one_sided_word_veto and differing:
        out.append("word_one_sided")
    return tuple(out)


def _score_pair(
    boq: BoqLine, boq_p: _Prepared, quote: QuoteLine, quote_p: _Prepared, cfg: MatchConfig
) -> _Scored:
    spec_score, spec_detail = _compare_specs(
        boq_p.specs, quote_p.specs, _qualifier_conflicts(boq_p.quals, quote_p.quals)
    )
    text_score = _text_similarity(boq_p.tokens, quote_p.tokens)
    state = _unit_state(boq_p.unit, quote_p.unit)
    unit_score = {"equal": 1.0, "mismatch": 0.0, "unknown": 0.5}[state]
    code_hit = bool(boq_p.codes & quote_p.codes)
    conflict = bool(spec_detail["conflicts"])

    def total(unit_part: float) -> float:
        if spec_score is None:
            raw = (
                (cfg.w_text * text_score + cfg.w_unit * unit_part)
                / (cfg.w_text + cfg.w_unit)
                * cfg.no_spec_factor
            )
        else:
            raw = cfg.w_spec * spec_score + cfg.w_text * text_score + cfg.w_unit * unit_part
        if code_hit:
            raw += cfg.code_bonus
        if conflict:
            raw -= cfg.conflict_penalty
        return max(0.0, min(1.0, raw))

    return _Scored(
        quote,
        total(unit_score),
        text_score,
        spec_score,
        spec_detail,
        state,
        unit_score,
        code_hit,
        total(1.0),
        bool(
            "core" in spec_detail["matched"]
            and boq_p.core_notation
            and quote_p.core_notation
            and boq_p.core_notation != quote_p.core_notation
        ),
        _vetoes(boq_p, quote_p, spec_detail, cfg) if cfg.clear_vetoes else (),
    )


def _evidence(
    boq: BoqLine, s: _Scored, rank: int, closing: date | None, shared: bool = False
) -> dict[str, Any]:
    quote = s.quote
    warnings = []
    if s.conflict:
        warnings.append("spec_conflict")
    if s.multi_value:
        warnings.append("spec_multi_value")
    if s.unit_mismatch:
        warnings.append("unit_mismatch")
    if s.core_notation_differs:
        warnings.append("core_notation_differs")
    warnings.extend(s.vetoes)
    if shared:
        warnings.append("quote_shared")
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
        prepared = [_prepare(q.description, q.sku, q.unit) for q in qs]
        suppliers.append((supplier_id, qs, prepared, _build_index(prepared)))
    groups: list[tuple[BoqLine, UUID, list[_Scored]]] = []
    fits: dict[UUID, list[tuple[UUID, float]]] = defaultdict(list)  # quote -> (boq id, neutral)
    for line in boq:
        line_p = _prepare(line.description, None, line.unit)
        if not line_p.tokens and not line_p.specs and not line_p.quals:
            continue
        for supplier_id, qs, prepared, index in suppliers:
            scored = [
                _score_pair(line, line_p, qs[i], prepared[i], config)
                for i in _candidate_indices(line_p, index)
            ]
            scored = [s for s in scored if s.score >= config.ambiguous_min]
            scored.sort(key=lambda s: (-s.score, str(s.quote.id)))
            groups.append((line, supplier_id, scored))
            for s in scored:
                fits[s.quote.id].append((line.id, s.unit_neutral))
    for line, supplier_id, scored in groups:
        for rank, s in enumerate(scored[: config.top_n], start=1):
            # Competition: a quote that fits another BoQ line as well (or better) is not a
            # clear answer for this one; the buyer decides which line it prices.
            rival = max((n for b, n in fits[s.quote.id] if b != line.id), default=None)
            shared = rival is not None and rival > s.unit_neutral - config.margin
            # A runner-up that differs only by unit (a "roll" vs "m" offer of the same cable)
            # is still a rival: the buyer must choose, so the margin ignores the unit signal.
            runner_up = (
                max(o.unit_neutral for o in scored[1:]) if rank == 1 and len(scored) > 1 else None
            )
            clear = (
                rank == 1
                and s.score >= config.suggest_min
                and s.text >= config.clear_text_min
                and not s.conflict
                and not s.multi_value
                and not s.unit_mismatch
                and not s.vetoes
                and not shared
                and (runner_up is None or s.unit_neutral - runner_up >= config.margin)
            )
            out.append(
                Suggestion(
                    line.id,
                    s.quote.id,
                    supplier_id,
                    Decimal(str(round(s.score, 4))),
                    "clear" if clear else "ambiguous",
                    rank,
                    _evidence(line, s, rank, closing_date, shared),
                )
            )
    return out
