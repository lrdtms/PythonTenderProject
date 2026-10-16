# Slice 5a, Phase 2: Rule-Based Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For a tender, deterministic matching suggests which supplier quotation item prices which BoQ line, with evidence and a clear/ambiguous classification, scored against the ground truth; decisions already made by a human survive every re-run (matching, BoQ re-extraction, quotation re-extraction).

**Architecture:** A pure `suppliers.matching` core (`suggest(boq_lines, quote_lines, config) -> list[Suggestion]`, no I/O) with its numbers in one `matching_config.py`. A persistence use case in the `suppliers` module (`match_tender`) replaces only `suggested` rows and never touches decided ones. A tender-level `match_suppliers` job is enqueued after `extract_quotation` and `extract_boq`; the worker handler orchestrates reading BoQ lines (via `estimating`/`documents` public APIs) and calls the suppliers use case. BoQ items referenced by a confirmed/rejected match are protected from `replace_unreviewed`. An offline scoring helper measures the matcher on the committed packs.

**Tech Stack:** Python 3.12, SQLAlchemy 2, PostgreSQL (advisory locks), pytest + Hypothesis (backend under `backend/`, `uv run`).

**Spec:** `docs/superpowers/specs/2026-10-16-slice-5a-suppliers-matching-design.md` sections 5 (matching, persistence rules), 8 (evaluation), 10. Phase 1 (tables, parser, `extract_quotation`) is merged into `main`. Later phases: 3 API, 4 comparison UI, 5 suppliers page and gate.

## Global Constraints

- **Matching is deterministic and pure** (FR-63): no LLM, no embeddings, no clock/random/DB in `matching.py`. Same input gives the same output in any input order. Money and scores are `Decimal` (scores quantised to 4 places); never `float` in stored values (floats inside the pure scoring maths are fine, converted with `Decimal(str(round(x, 4)))` at the boundary).
- **Price and date never change a score** (spec section 5). They appear in `evidence` only. The lowest price is never selected or highlighted.
- **Safety first:** a pair with a spec conflict or a unit mismatch is never `clear`. A `clear` suggestion must beat the runner-up for the same (BoQ line, supplier) by `MARGIN`.
- **Decisions are sacred:** `confirmed` and `rejected` match rows are never deleted or overwritten by any re-run; a rejected pair is not re-suggested; once a BoQ line has a `confirmed` match for a supplier, no further suggestions are stored for that (BoQ line, supplier).
- **Tenancy:** all queries through `ScopedRepository` subclasses; modules import each other only through `public.py`; `app.modules.extraction` stays free of sqlalchemy/fastapi (F2 and import-linter). No raw database calls outside repositories (`pg_advisory_xact_lock` lives in a repo method).
- **Privacy:** `evidence` holds numbers, ids, units, normalised spec tokens and flags only; no description text, supplier names or file names. Job warnings and logs carry codes and counts only.
- **Tests:** `cd backend && DB_HOST_PORT=5433 uv run pytest -q` (about 3-4 minutes; iterate on single files); `uv run ruff check . && uv run ruff format --check . && uv run lint-imports`. Fixtures: `backend/tests/fixtures/packs/pack0{1..4}/` (BoQ + quotations + `ground_truth.json`). Do not run two full backend suites at once (shared test database).
- **Shell:** the Bash tool here mishandles long heredocs; create files with the editor tools and run short commands.
- **Branch:** `feat/slice-5a-phase-2-matching` (exists). Commit messages end with the attribution lines from the session's system reminder (`Co-Authored-By: ...` and `Claude-Session: ...`).

## Review Focus

1. Two quote items that differ only by a spec value (1.5 mm2 vs 2.5 mm2 cable, 20 A vs 32 A breaker): never both `clear` for the same BoQ line; the wrong one is dropped or `ambiguous` (Tasks 1, 2).
2. A BoQ line with no candidate above the floor for a supplier, a quotation with no items, an empty tender, a BoQ line with no description tokens: no crash, no invented match, "no match" is simply no row (Tasks 1, 3).
3. Re-running matching after a human confirmed or rejected: decided rows, and the BoQ/quotation items they refer to, survive; the confirmed pair is not re-suggested; a rejected pair is not re-suggested (Task 3).
4. BoQ re-extraction with a decided match on an unreviewed BoQ item: the item survives (`protected`), its match survives, the duplicate is not re-inserted (Task 3).
5. `match_suggestions.supplier_id` always equals the quotation's supplier; matching only considers items of the tender's **current** document versions and skips rejected items (Task 3).

---

### Task 1: The matching core (pure)

**Files:**
- Create: `backend/app/modules/suppliers/matching_config.py`, `backend/app/modules/suppliers/matching.py`
- Modify: `backend/pyproject.toml` (dev dependency `hypothesis`), `backend/uv.lock`
- Test: `backend/tests/test_matching.py`

**Interfaces (Produces):**
- `matching_config.MatchConfig` (frozen dataclass) and `DEFAULT: MatchConfig` with: `w_spec=0.5`, `w_text=0.4`, `w_unit=0.1`, `no_spec_factor=0.9`, `code_bonus=0.1`, `conflict_penalty=0.25`, `suggest_min=0.70`, `ambiguous_min=0.45`, `margin=0.08`, `top_n=3`, plus `ALIASES: dict[str, str]` (token aliases, e.g. `mcb -> "miniature circuit breaker"`, `db -> "distribution board"`, `cct -> "circuit"`), `STOPWORDS: frozenset[str]`. These numbers are the starting point; Task 2 tunes them against the ground truth.
- `matching.BoqLine(id: UUID, item_no: str | None, description: str, unit: str | None)`; `matching.QuoteLine(id: UUID, supplier_id: UUID, quotation_id: UUID, description: str, sku: str | None, unit: str | None, unit_price: Decimal | None, valid_until: date | None)`.
- `matching.Suggestion(boq_id: UUID, quote_id: UUID, supplier_id: UUID, score: Decimal, classification: Literal["clear", "ambiguous"], rank: int, evidence: dict[str, Any])`.
- `matching.spec_tokens(text: str) -> dict[str, frozenset[str]]` (kind -> values), `matching.suggest(boq: Sequence[BoqLine], quotes: Sequence[QuoteLine], closing_date: date | None = None, config: MatchConfig = DEFAULT) -> list[Suggestion]` (ordered by BoQ line order, then supplier id, then rank).

- [ ] **Step 1: Add Hypothesis**

Run: `cd backend && uv add --dev hypothesis` — expect `pyproject.toml` and `uv.lock` to change.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_matching.py`:

```python
"""The matching core: spec tokens, signals, classification, determinism."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.suppliers import matching as m

SUP_A, SUP_B = uuid4(), uuid4()


def boq(desc: str, unit: str | None = "no", item_no: str = "1") -> m.BoqLine:
    return m.BoqLine(uuid4(), item_no, desc, unit)


def quote(desc: str, unit: str | None = "no", sku: str | None = None, price: str = "10.00",
          supplier: UUID = SUP_A, valid_until: date | None = None) -> m.QuoteLine:
    return m.QuoteLine(uuid4(), supplier, uuid4(), desc, sku, unit, Decimal(price), valid_until)


# --- spec tokens -------------------------------------------------------------------------------


def test_spec_tokens_read_electrical_specifics() -> None:
    t = m.spec_tokens("Main distribution board, 400 A, 3-phase, IP65, 100 W, 1200 mm, 6 kA, 12-way")
    assert t["a"] == {"400"} and t["ka"] == {"6"} and t["w"] == {"100"} and t["mm"] == {"1200"}
    assert t["phase"] == {"3"} and t["ip"] == {"65"} and t["way"] == {"12"}


def test_spec_tokens_cores_and_cross_section_with_unicode_and_spacing() -> None:
    t = m.spec_tokens("3C+E 2.5mm² PVC/PVC copper cable")
    assert t["core"] == {"3c+e"} and t["mm2"] == {"2.5"}
    assert m.spec_tokens("3 c + e 2,5 mm2")["mm2"] == {"2.5"}


def test_spec_tokens_pole_and_empty() -> None:
    assert m.spec_tokens("Miniature circuit breaker, 3-pole, 63 A")["pole"] == {"3"}
    assert m.spec_tokens("Site establishment, offices and storage") == {}


# --- signals and classification ----------------------------------------------------------------


def test_identical_description_is_a_clear_match() -> None:
    line, q = boq("Main distribution board, 400 A, 3-phase, wall mounted"), quote(
        "Main distribution board, 400 A, 3-phase, wall mounted, with busbars", sku="SKU-1")
    [s] = m.suggest([line], [q])
    assert (s.classification, s.rank, s.boq_id, s.quote_id) == ("clear", 1, line.id, q.id)
    assert s.supplier_id == SUP_A and 0 < s.score <= 1
    assert s.evidence["unit"]["state"] == "equal"


def test_spec_conflict_is_never_clear_and_usually_dropped() -> None:
    line = boq("Miniature circuit breaker, 1-pole, 20 A, 6 kA")
    wrong = quote("MCB, 1-pole, 32 A, 6 kA")
    assert all(s.classification != "clear" for s in m.suggest([line], [wrong]))


def test_correct_candidate_beats_the_confusable_one() -> None:
    line = boq("3C+E 1.5 mm2 PVC/PVC copper cable, for conduit installation", unit="m")
    right = quote("3C+E 1.5 mm2 PVC/PVC copper cable, for conduit installation [SKU-4453]", unit="m", price="36")
    wrong = quote("3C+E 2.5 mm2 PVC/PVC copper cable, for conduit installation [SKU-9]", unit="m", price="31")
    out = m.suggest([line], [wrong, right])
    top = next(s for s in out if s.rank == 1)
    assert top.quote_id == right.id and top.classification == "clear"
    assert all(s.classification != "clear" for s in out if s.quote_id == wrong.id)


def test_unit_mismatch_forces_ambiguous_and_is_flagged() -> None:
    line = boq("3C+E 2.5 mm2 PVC/PVC copper cable", unit="m")
    [s] = m.suggest([line], [quote("3C+E 2.5 mm2 PVC/PVC copper cable", unit="roll")])
    assert s.classification == "ambiguous" and "unit_mismatch" in s.evidence["warnings"]


def test_two_near_identical_candidates_from_one_supplier_are_both_ambiguous() -> None:
    line = boq("LED batten light fitting, 1200 mm, 36 W")
    a = quote("LED batten light fitting, 1200 mm, 36 W [SKU-1]")
    b = quote("LED batten light fitting, 1200 mm, 36 W [SKU-2]")
    out = m.suggest([line], [a, b])
    assert len(out) == 2 and {s.classification for s in out} == {"ambiguous"}


def test_candidates_are_ranked_per_supplier_and_limited_to_top_n() -> None:
    line = boq("Emergency light fitting, 3-hour maintained")
    quotes = [quote(f"Emergency light fitting, 3-hour maintained variant {i}") for i in range(6)]
    out = m.suggest([line], quotes)
    assert len(out) <= m.DEFAULT.top_n and [s.rank for s in out] == sorted(s.rank for s in out)


def test_each_supplier_is_judged_separately() -> None:
    line = boq("Single switched socket, 16 A")
    a = quote("Single switched socket, 16 A", supplier=SUP_A)
    b = quote("Single switched socket, 16 A", supplier=SUP_B)
    out = m.suggest([line], [a, b])
    assert {(s.supplier_id, s.classification) for s in out} == {(SUP_A, "clear"), (SUP_B, "clear")}


def test_unrelated_items_produce_no_suggestion() -> None:
    assert m.suggest([boq("Site establishment, offices and storage", unit="sum")],
                     [quote("MCB, 1-pole, 32 A, 6 kA")]) == []


def test_sku_shared_with_the_boq_line_adds_a_code_signal() -> None:
    line = boq("Isolator switch SKU-777 rated 63 A")
    [s] = m.suggest([line], [quote("Isolator 63 A", sku="SKU-777")])
    assert s.evidence["signals"]["code"] is True


def test_price_and_validity_are_evidence_only() -> None:
    line = boq("Single switched socket, 16 A")
    cheap = quote("Single switched socket, 16 A", price="1.00", valid_until=date(2026, 10, 1))
    dear = quote("Single switched socket, 16 A", price="900.00", valid_until=date(2027, 1, 1))
    [a] = m.suggest([line], [cheap], closing_date=date(2026, 11, 1))
    [b] = m.suggest([line], [dear], closing_date=date(2026, 11, 1))
    assert a.score == b.score
    assert "quote_expires_before_closing" in a.evidence["warnings"]
    assert "quote_expires_before_closing" not in b.evidence["warnings"]
    assert a.evidence["price"]["unit_price"] == "1.00"


def test_missing_price_and_unit_do_not_crash() -> None:
    out = m.suggest([boq("Conduit 20 mm", unit=None)], [m.QuoteLine(uuid4(), SUP_A, uuid4(), "Conduit 20 mm", None, None, None, None)])
    assert out and out[0].evidence["price"]["unit_price"] is None and out[0].evidence["unit"]["state"] == "unknown"


def test_degenerate_inputs() -> None:
    assert m.suggest([], []) == []
    assert m.suggest([boq("Cable")], []) == []
    assert m.suggest([boq("")], [quote("")]) == []
    assert m.suggest([boq("!!! ---")], [quote("!!! ---")]) == []


# --- determinism and properties ----------------------------------------------------------------

WORDS = ["cable", "socket", "mcb", "board", "light", "led", "conduit", "isolator", "16", "a", "20", "32", "mm2", "2.5", "3-pole", "1-pole"]
descs = st.lists(st.sampled_from(WORDS), min_size=1, max_size=8).map(" ".join)


@settings(max_examples=60, deadline=None)
@given(st.lists(descs, min_size=1, max_size=4), st.lists(descs, min_size=1, max_size=6), st.integers(0, 10_000))
def test_result_does_not_depend_on_input_order(boqs: list[str], quotes: list[str], seed: int) -> None:
    lines = [m.BoqLine(UUID(int=i + 1), str(i), d, "no") for i, d in enumerate(boqs)]
    qs = [m.QuoteLine(UUID(int=100 + i), SUP_A, UUID(int=500), d, None, "no", Decimal("1"), None) for i, d in enumerate(quotes)]
    first = m.suggest(lines, qs)
    shuffled_q, shuffled_b = qs[:], lines[:]
    random.Random(seed).shuffle(shuffled_q)
    random.Random(seed + 1).shuffle(shuffled_b)
    key = lambda out: sorted((str(s.boq_id), str(s.quote_id), s.score, s.classification, s.rank) for s in out)  # noqa: E731
    assert key(first) == key(m.suggest(shuffled_b, shuffled_q))


@settings(max_examples=60, deadline=None)
@given(descs, descs, st.decimals(min_value=0, max_value=100000, places=2), st.decimals(min_value=0, max_value=100000, places=2))
def test_price_never_changes_the_score(a: str, b: str, p1: Decimal, p2: Decimal) -> None:
    line = m.BoqLine(UUID(int=1), "1", a, "no")
    q1 = m.QuoteLine(UUID(int=2), SUP_A, UUID(int=9), b, None, "no", p1, None)
    q2 = m.QuoteLine(UUID(int=2), SUP_A, UUID(int=9), b, None, "no", p2, None)
    assert [(s.score, s.classification) for s in m.suggest([line], [q1])] == [(s.score, s.classification) for s in m.suggest([line], [q2])]


@settings(max_examples=80, deadline=None)
@given(st.lists(descs, min_size=1, max_size=3), st.lists(descs, min_size=1, max_size=6))
def test_a_spec_conflict_is_never_clear(boqs: list[str], quotes: list[str]) -> None:
    lines = [m.BoqLine(UUID(int=i + 1), str(i), d, "no") for i, d in enumerate(boqs)]
    qs = [m.QuoteLine(UUID(int=100 + i), SUP_A, UUID(int=500), d, None, "no", None, None) for i, d in enumerate(quotes)]
    for s in m.suggest(lines, qs):
        if "spec_conflict" in s.evidence["warnings"]:
            assert s.classification != "clear"
        assert Decimal(0) <= s.score <= Decimal(1)
```

- [ ] **Step 3: Run it and see it fail**

Run: `cd backend && uv run pytest tests/test_matching.py -q`
Expected: FAIL (`ImportError`: matching module missing).

- [ ] **Step 4: Implement the config**

Create `backend/app/modules/suppliers/matching_config.py`:

```python
"""Every number and word list the matcher uses, in one place (tuned in Task 2)."""

from __future__ import annotations

from dataclasses import dataclass

ALIASES: dict[str, str] = {
    "mcb": "miniature circuit breaker",
    "mccb": "moulded case circuit breaker",
    "db": "distribution board",
    "rcd": "residual current device",
    "elcb": "earth leakage circuit breaker",
    "pvc": "pvc",
    "cct": "circuit",
}
STOPWORDS: frozenset[str] = frozenset(
    {"a", "an", "and", "for", "with", "the", "of", "to", "in", "on", "or", "incl", "including", "supply", "install", "installation"}
)


@dataclass(frozen=True)
class MatchConfig:
    w_spec: float = 0.5
    w_text: float = 0.4
    w_unit: float = 0.1
    no_spec_factor: float = 0.9  # applied when neither description carries spec tokens
    code_bonus: float = 0.1
    conflict_penalty: float = 0.25
    suggest_min: float = 0.70
    ambiguous_min: float = 0.45
    margin: float = 0.08
    top_n: int = 3


DEFAULT = MatchConfig()
```

- [ ] **Step 5: Implement the matcher**

Create `backend/app/modules/suppliers/matching.py`:

```python
"""Deterministic supplier matching (FR-63): no LLM, no I/O, no clock. See the Slice 5a spec section 5."""

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
_STRUCT = {"pole": re.compile(r"(\d+)[\s-]*pole"), "way": re.compile(r"(\d+)[\s-]*way"), "phase": re.compile(r"(\d+)[\s-]*phase")}


def _norm_number(raw: str) -> str:
    return str(Decimal(raw.replace(",", ".")).normalize())


def spec_tokens(text: str) -> dict[str, frozenset[str]]:
    """Electrical specifics as {kind: values}: `400 A` -> {"a": {"400"}}, `3C+E` -> {"core": {"3c+e"}}."""
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


def _compare_specs(a: dict[str, frozenset[str]], b: dict[str, frozenset[str]]) -> tuple[float | None, dict[str, Any]]:
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
    detail = {"matched": matched, "conflicts": conflicts, "boq_only": boq_only, "quote_only": quote_only}
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


def _score_pair(boq: BoqLine, quote: QuoteLine, boq_data: tuple, closing: date | None, cfg: MatchConfig) -> _Scored:
    boq_specs, boq_tokens, boq_codes = boq_data
    quote_specs = spec_tokens(quote.description)
    spec_score, spec_detail = _compare_specs(boq_specs, quote_specs)
    text_score = _text_similarity(boq_tokens, _tokens(quote.description))
    state = _unit_state(boq.unit, quote.unit)
    unit_score = {"equal": 1.0, "mismatch": 0.0, "unknown": 0.5}[state]
    if spec_score is None:
        score = (cfg.w_text * text_score + cfg.w_unit * unit_score) / (cfg.w_text + cfg.w_unit) * cfg.no_spec_factor
    else:
        score = cfg.w_spec * spec_score + cfg.w_text * text_score + cfg.w_unit * unit_score
    code_hit = bool(quote.sku and (quote.sku.lower() in boq_codes)) or bool(boq_codes & _codes(quote.description))
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
        "signals": {"text": round(text_score, 4), "spec": None if spec_score is None else round(spec_score, 4), "unit": unit_score, "code": code_hit},
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
            scored = [_score_pair(line, q, data, closing_date, config) for q in by_supplier[supplier_id]]
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
                out.append(Suggestion(line.id, s.quote.id, supplier_id, Decimal(str(round(s.score, 4))),
                                      "clear" if clear else "ambiguous", rank, evidence))
    return out
```

(`canon_unit` is exported by `extraction.public`; the suppliers module may import another module's `public`.)

- [ ] **Step 6: Run the tests; fix until green**

Run: `cd backend && uv run pytest tests/test_matching.py -q`
Expected: PASS. If a hand-written case disagrees with the defaults (for example `test_identical_description_is_a_clear_match` scoring below 0.70, or the two-near-identical test not both ambiguous), fix the matcher or the config in a general way, never by special-casing a test string. The Task 2 ground-truth run will tune further.

- [ ] **Step 7: Lint and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
git add -A && git commit -m "feat: deterministic supplier matching core"
```

---

### Task 2: Scoring against the ground truth, tuning and the report

**Files:**
- Create: `backend/tests/matching_eval.py`, `backend/tests/test_matching_ground_truth.py`, `scripts/score_slice5a.py`, `docs/spikes/slice-5a-scores.md`
- Modify (tuning only): `backend/app/modules/suppliers/matching_config.py`, and `matching.py` where a general fix is needed

**Interfaces:**
- Produces `matching_eval.load_pack(pack_dir: Path) -> Pack` and `matching_eval.evaluate(packs: Sequence[Path], config=DEFAULT) -> EvalReport`. `EvalReport` (dataclass): `top_accuracy: float`, `wrong_clear: int` (clear suggestions whose BoQ line differs from `expected_match`, including any clear suggestion for an item whose `expected_match` is null), `unit_mismatch_unflagged: int`, `ambiguous_cases_clear: int`, `per_pack: dict[str, dict]`, `misses: list[str]` (human-readable ids only, no description text), method `render() -> str`.

Ground-truth semantics (from `ground_truth.json`): each quotation item has `expected_match` (a BoQ `item_number` or null), `unit_mismatch` (true: the match is right but units differ, so a correct top suggestion must be `ambiguous` with `unit_mismatch` flagged), `ambiguous` + `confusable_with` (a look-alike that must NOT be offered as `clear`; `expected_match` is null for these). Quote items are located in the parsed output by the SKU in their description (`[SKU-xxxx]`), BoQ lines by `item_no` from `parse_boq`.

- [ ] **Step 1: Write the evaluation helper**

Create `backend/tests/matching_eval.py`. Load each pack like `tests/test_quotation_parser.py` and `tests/test_boq_parser.py` do (`parse_document(doc["format"], bytes)` -> `extraction.PageInput` -> `parse_boq` over documents of kind `boq`/`tender_document` that are not scanned, `parse_quotation` over kind `quotation` documents). Build `matching.BoqLine(uuid5(namespace, item_no), item_no, description, unit)` and one `QuoteLine` per quotation item (`supplier_id` = uuid5 of the supplier name, `quotation_id` = uuid5 of the document name, `sku` and `unit_price`). Run `matching.suggest` once per pack. For each ground-truth quotation item find its parsed `QuoteLine` by SKU and compute:
- `top_accuracy`: among items with `expected_match` not null and `ambiguous` false, the share whose best suggestion (highest score across BoQ lines for that quote item) has `BoqLine.item_no == expected_match`;
- `wrong_clear`: number of `clear` suggestions where the quote item's `expected_match` is null or differs from the suggestion's BoQ `item_no`;
- `unit_mismatch_unflagged`: items with `unit_mismatch` true whose correct suggestion is missing, or is `clear`, or lacks `unit_mismatch` in `evidence["warnings"]`;
- `ambiguous_cases_clear`: items with `ambiguous` true that appear in any `clear` suggestion.
Write `render()` as a small text table per pack and overall. Never print descriptions; print item numbers, SKUs and counts.

- [ ] **Step 2: Write the ground-truth test**

Create `backend/tests/test_matching_ground_truth.py`:

```python
"""Matching accuracy on the committed packs (PRD target: >= 80% correct, ambiguous cases flagged)."""

from __future__ import annotations

from pathlib import Path

from tests.matching_eval import evaluate

PACKS = sorted((Path(__file__).parent / "fixtures" / "packs").glob("pack0*"))


def test_matcher_meets_the_prd_targets_on_the_committed_packs() -> None:
    report = evaluate(PACKS)
    assert report.top_accuracy >= 0.85, report.render()
    assert report.wrong_clear == 0, report.render()
    assert report.unit_mismatch_unflagged == 0, report.render()
    assert report.ambiguous_cases_clear == 0, report.render()
```

- [ ] **Step 3: Run it; tune generally until green**

Run: `cd backend && uv run pytest tests/test_matching_ground_truth.py -q -s`
Expected first: probably FAIL. Print `report.render()` and look at each miss. Allowed levers, all general and all covered by a unit test in `tests/test_matching.py` when behaviour changes: the weights, thresholds and margin in `matching_config.py`; `ALIASES` and `STOPWORDS` (real electrical-trade synonyms only); spec-token patterns; tokenisation/stemming; a quote-competition rule (a quote item that is the top candidate for two BoQ lines from the same supplier downgrades both to `ambiguous` with warning `quote_shared`), if needed. Forbidden: matching on item numbers, SKUs-to-BoQ lookups from the ground truth, per-file special cases, or weakening the assertions. The four packs hold about 70 quote items; do not over-fit: after tuning, also run the same evaluation on the 43-seed set if `eval/generated_s43` exists locally (Step 5) and report both.

- [ ] **Step 4: The script and the report**

Create `scripts/score_slice5a.py` (offline; no Docker, no Ollama):

```python
"""Score supplier matching on the synthetic packs (offline).

    cd backend && uv run python ../scripts/score_slice5a.py                       # committed packs
    cd backend && uv run python ../scripts/score_slice5a.py --packs ../eval/generated_s43/pack01 ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from tests.matching_eval import evaluate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packs", nargs="*", type=Path)
    args = parser.parse_args()
    packs = args.packs or sorted((BACKEND / "tests" / "fixtures" / "packs").glob("pack0*"))
    print(evaluate(packs).render())


if __name__ == "__main__":
    main()
```

Run it for the committed packs and, when `eval/generated_s43/pack0*` exist, for those too. Write `docs/spikes/slice-5a-scores.md`: date, the final thresholds and weights (copy from `matching_config.py`), the overall and per-pack numbers for both sets, every remaining miss as ids only, what was tuned and what it traded off, and the caveat that the data is synthetic and small (about 70 quote items on the committed packs).

- [ ] **Step 5: Full suite, lint, commit**

```bash
cd backend && DB_HOST_PORT=5433 uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
git add -A && git commit -m "feat: matching scored against the ground truth, tuned, with report"
```

---

### Task 3: Persistence, the `match_suppliers` job and decision protection

**Files:**
- Modify: `backend/app/modules/suppliers/repo.py`, `service.py`, `public.py`, `schemas.py`
- Modify: `backend/app/modules/estimating/repo.py`, `service.py`, `public.py`
- Modify: `backend/app/modules/documents/service.py`, `public.py` (job constant), `backend/app/worker/handlers.py`
- Test: `backend/tests/test_matching_persistence.py`, `backend/tests/test_matching_pipeline.py`; update existing tests that enumerate job types if any fail

**Interfaces:**
- Consumes: Task 1 `matching.suggest`, `BoqLine`, `QuoteLine`; Phase 1 models and repos.
- Produces:
  - `documents.MATCH_SUPPLIERS_JOB = "match_suppliers"` (a tender-level job: `subject_type="tender"`, `subject_id=tender_id`).
  - `suppliers.BoqInput(id: UUID, item_no: str | None, description: str, unit: str | None)` (re-export of `matching.BoqLine`) and `suppliers.match_tender(session, ctx, tender_id: UUID, boq_lines: Sequence[BoqLine], quote_version_ids: Sequence[UUID], closing_date: date | None) -> MatchResult` where `MatchResult(suggested: int, kept_decided: int, removed_suggested: int)`.
  - `suppliers.decided_boq_item_ids(session, ctx) -> set[UUID]` (BoQ items referenced by a `confirmed` or `rejected` match).
  - `estimating.replace_unreviewed(session, ctx, version_id, run_id, cands, protected_ids: Collection[UUID] = ())`: items in `protected_ids` count as reviewed (kept; their keys count as duplicates).
  - Worker: handler `match_suppliers`; `extract_quotation` and `extract_boq` enqueue the tender's matching job (one active per tender) in their own transaction.
  - `MatchRepo.lock_tender(tender_id)` taking `pg_advisory_xact_lock` for the tender (Phase 3 decisions will take the same lock).

- [ ] **Step 1: Write the failing persistence tests**

Create `backend/tests/test_matching_persistence.py` using `tests.quotation_helpers.quotation_context` (Phase 1 helper: an organisation with documents and runs; extend it if needed, see below). Cases (write the assertions fully):
1. `match_tender` stores `suggested` rows with `supplier_id == quotation.supplier_id` for every row, `classification`, `score` as Decimal, `evidence` JSON without description text.
2. A second `match_tender` call replaces `suggested` rows (same count, new ids) and leaves a `confirmed` and a `rejected` row (inserted by the test) untouched.
3. A rejected pair is not re-suggested; for a BoQ line with a `confirmed` match for supplier S, no `suggested` rows for (that BoQ line, S) exist after the re-run, while other suppliers' candidates for that line still appear.
4. Quote items with `review_status == "rejected"` and BoQ lines not passed in are ignored; quotations of non-current versions are ignored (only `quote_version_ids` count).
5. `decided_boq_item_ids` returns exactly the BoQ items with a confirmed/rejected match.
6. Empty inputs (`boq_lines=[]`, no quotation items) return `MatchResult(0, 0, 0)` and do not fail.
7. Lock: `MatchRepo(session, ctx).lock_tender(tender_id)` runs (a smoke test that it executes `pg_advisory_xact_lock`; and calling it twice in one transaction is fine).

The helper `quotation_context(with_boq=True)` already yields `boq_item_id`; extend it (add a parameter `quotation_rows: list[dict] | None` that calls `store_quotation` with the given rows for each version) so tests can build real quotation items without the worker.

- [ ] **Step 2: Write the failing pipeline tests**

Create `backend/tests/test_matching_pipeline.py` using the real worker (`drain`, `register`, `make_tender`, `upload`, fixtures from `tests/fixtures/packs/pack02`):
1. Upload `pack02/boq.xlsx` (kind `boq`), then both pack02 quotations (kind `quotation`), `drain()`: `match_suggestions` rows exist; at least one `clear` and at least one `ambiguous`; every row's `supplier_id` equals its quotation's supplier; the job `match_suppliers` for the tender is `succeeded`.
2. Decision protection through BoQ re-extraction: confirm one match directly in the database (insert/update status `confirmed`, `decided_by` = the member, `decided_at`), then re-extract BoQ via `POST /document-versions/{boq_version}/extract` and `drain()`: the BoQ item the match refers to still exists (same id), the match row still exists and is `confirmed`, the BoQ item count is unchanged (no duplicate inserted), and matching re-ran without error.
3. Quotation re-extraction keeps a decided match's quotation item (Phase 1 behaviour) and matching afterwards does not re-suggest the decided pair.
4. A tender with only a BoQ (no quotations) runs `match_suppliers` to success with zero rows; a tender with quotations but no BoQ likewise.
5. Archived tender: `match_suppliers` fails with `TENDER_ARCHIVED` (use the existing way tests archive a tender, e.g. `POST /tenders/{id}/archive`, then enqueue the job directly through `jobs.enqueue`) and writes nothing.
6. Two quick uploads enqueue only one active `match_suppliers` job for the tender (assert at most one non-terminal job at a time).

- [ ] **Step 3: Run both files and see them fail**

Run: `cd backend && DB_HOST_PORT=5433 uv run pytest tests/test_matching_persistence.py tests/test_matching_pipeline.py -q`
Expected: FAIL (missing functions/job type).

- [ ] **Step 4: Implement repo, service, public**

In `suppliers/repo.py` add:

```python
class MatchRepo(ScopedRepository[MatchSuggestion]):
    model = MatchSuggestion

    def lock_tender(self, tender_id: UUID) -> None:
        """Serialise matching and (Phase 3) match decisions for one tender."""
        key = int.from_bytes(tender_id.bytes[:8], "big", signed=True)
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def for_items(self, boq_ids: Collection[UUID], quote_item_ids: Collection[UUID]) -> Sequence[MatchSuggestion]: ...
    def delete_suggested(self, ids: Collection[UUID]) -> int: ...
    def insert_many(self, rows: Sequence[Mapping[str, Any]]) -> None: ...
    def decided_boq_item_ids(self) -> set[UUID]: ...
```

(`for_items`: rows whose `boq_item_id` or `quotation_item_id` is in the given sets; `delete_suggested`: delete only rows with `status == 'suggested'`; `decided_boq_item_ids`: distinct `boq_item_id` where status in `('confirmed','rejected')`. Implement each with `self._select()`/`self._delete()` and add `from sqlalchemy import text`.) Add to `QuotationItemRepo` a method `for_versions(version_ids) -> Sequence[tuple[QuotationItem, Quotation]]` joining `quotations` (org-scoped) and excluding `review_status == 'rejected'`.

In `suppliers/service.py` add `match_tender`:

```python
def match_tender(session, ctx, tender_id, boq_lines, quote_version_ids, closing_date) -> MatchResult:
    matches = MatchRepo(session, ctx)
    matches.lock_tender(tender_id)
    pairs = QuotationItemRepo(session, ctx).for_versions(quote_version_ids)
    quote_lines = [matching.QuoteLine(i.id, q.supplier_id, q.id, i.description, i.sku, i.unit,
                                       i.unit_price, q.valid_until) for i, q in pairs]
    boq_ids = {b.id for b in boq_lines}
    quote_ids = {q.id for q in quote_lines}
    existing = matches.for_items(boq_ids, quote_ids)
    decided = [m for m in existing if m.status != "suggested"]
    removed = matches.delete_suggested([m.id for m in existing if m.status == "suggested"])
    decided_pairs = {(m.boq_item_id, m.quotation_item_id) for m in decided}
    confirmed_slots = {(m.boq_item_id, m.supplier_id) for m in decided if m.status == "confirmed"}
    rows = []
    for s in matching.suggest(boq_lines, quote_lines, closing_date):
        if (s.boq_id, s.quote_id) in decided_pairs or (s.boq_id, s.supplier_id) in confirmed_slots:
            continue
        rows.append({"boq_item_id": s.boq_id, "quotation_item_id": s.quote_id, "supplier_id": s.supplier_id,
                     "score": s.score, "classification": s.classification, "evidence": s.evidence})
    matches.insert_many(rows)
    return MatchResult(suggested=len(rows), kept_decided=len(decided), removed_suggested=removed)

def decided_boq_item_ids(session, ctx) -> set[UUID]:
    return MatchRepo(session, ctx).decided_boq_item_ids()
```

`MatchResult` goes in `schemas.py`; export `match_tender`, `decided_boq_item_ids`, `MatchResult`, `BoqLine` (as `BoqInput`) from `public.py`. Rank is stored inside `evidence["rank"]`.

In `estimating/repo.py` add `BoqRepo.protected(version_id, ids)` (rows of the version whose id is in `ids`) and change `delete_unreviewed(version_id, keep_ids=())` to also exclude `keep_ids`. In `estimating/service.py` extend `replace_unreviewed(..., protected_ids: Collection[UUID] = ())`: treat `reviewed(version_id)` plus `protected(version_id, protected_ids)` as reviewed for the duplicate keys, and pass their ids as `keep_ids` to `delete_unreviewed`. Existing callers keep working because the argument defaults to empty.

- [ ] **Step 5: Implement the job and handler**

`documents/service.py`: add `MATCH_SUPPLIERS_JOB = "match_suppliers"` (export in `public.py`); do NOT add it to `EXTRACTION_JOBS` (it is not a per-version extraction; check `ensure_job_retry_allowed`: a tender-level job retry should still be refused on an archived tender, so extend that function for `MATCH_SUPPLIERS_JOB` using `subject_id` as the tender id and `_ensure_tender_open`).

`worker/handlers.py`:

```python
def _tender_boq_lines(session, ctx, tender_id) -> tuple[list[suppliers.BoqInput], list[UUID], date | None]:
    docs = documents.list_documents(session, ctx, tender_id)
    boq_lines: list[suppliers.BoqInput] = []
    quote_versions: list[UUID] = []
    for d in docs:
        v = d.current_version
        if v is None:
            continue
        if d.kind == "quotation":
            quote_versions.append(v.id)
        elif d.kind in ("boq", "tender_document"):
            offset = 0
            while True:
                page = estimating.list_boq_items(session, ctx, v.id, 1000, offset)
                boq_lines += [suppliers.BoqInput(i.id, i.item_no, i.description, i.unit)
                              for i in page if i.review_status != "rejected"]
                if len(page) < 1000:
                    break
                offset += 1000
    tender = tenders.get_tender(session, ctx, tender_id)
    return boq_lines, quote_versions, tender.closing_at.date() if tender.closing_at else None


def match_suppliers(session, ctx, job, progress):
    tender = tenders.get_tender(session, ctx, job.subject_id)
    if tender.status == "archived":
        raise ProcessingFailed("TENDER_ARCHIVED", "The tender is archived.")
    boq_lines, quote_versions, closing = _tender_boq_lines(session, ctx, job.subject_id)
    result = suppliers.match_tender(session, ctx, job.subject_id, boq_lines, quote_versions, closing)
    progress(1, 1)
    return []
```

Register `documents.MATCH_SUPPLIERS_JOB: JobHandler(run=match_suppliers)` (no run lifecycle hooks: matching has no extraction run). Enqueue: at the end of `extract_quotation` and `extract_boq`, `jobs.enqueue(session, ctx, documents.MATCH_SUPPLIERS_JOB, "tender", <tender id>, {})` where the tender id comes from `documents.processing_info(session, ctx, job.subject_id).tender_id`. In `extract_boq` also pass `protected_ids=suppliers.decided_boq_item_ids(session, ctx)` to `estimating.replace_unreviewed`. Import `tenders` and `suppliers` public APIs at the top of the file (`from datetime import date`, `from app.modules.tenders import public as tenders`).

Pitfall to check while implementing: `jobs.enqueue` returns the existing active job for the same (type, subject); if a matching job is already `running`, the data written after it started is not picked up until the next trigger. Accept this (the Phase 3 `POST /tenders/{id}/match` re-runs it) and record it under known limitations in Task 4.

- [ ] **Step 6: Run the new files, then the suite; fix regressions**

Run: `cd backend && DB_HOST_PORT=5433 uv run pytest tests/test_matching_persistence.py tests/test_matching_pipeline.py -q` then the full suite once. Existing tests that count jobs after uploads (for example in `test_extraction_pipeline.py`, `test_quotation_pipeline.py`, `test_jobs.py`, `test_worker_isolation.py`, the F1 sweep) may see one extra `match_suppliers` job per tender: update only those expectations and say so in the report. The F1 sweep must still pass; `match_suppliers` jobs of org A must never appear for org B.

- [ ] **Step 7: Lint and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
git add -A && git commit -m "feat: match_suppliers job, match persistence and decision protection"
```

---

### Task 4: Docs and real-stack check

**Files:**
- Modify: `docs/plan.md`, `docs/known-limitations.md`, `docs/superpowers/specs/2026-10-16-slice-5a-suppliers-matching-design.md` (only if behaviour differs from the spec)

- [ ] **Step 1: Docs**

- `docs/plan.md` Slice 5 row: append a Phase 2 status sentence (matching core, thresholds in `matching_config.py`, scores from `docs/spikes/slice-5a-scores.md`, job and protection).
- `docs/known-limitations.md`, Slice 5a section: add: matching job enqueued while a previous one runs is not re-run until the next trigger (Phase 3 adds `POST /tenders/{id}/match`); matching ignores quantity and price by design; no unit conversion; synonyms list is small and trade-specific; accuracy measured on synthetic data only (numbers in the scores report); single worker means a long requirements job delays matching.
- Spec: if any rule was implemented differently from section 5 (for example a quote-competition rule added during tuning), update the section so it states what is built.

- [ ] **Step 2: Real-stack check (controller-run)**

Rebuild and restart the stack (`docker compose up -d --build api worker web`). In the browser or through the API with the admin account: create a tender, upload `backend/tests/fixtures/packs/pack02/boq.xlsx` (kind BoQ) and the two pack02 quotations (kind Quotation); wait for the jobs; read the counts with psql (`select classification, status, count(*) from match_suggestions group by 1,2`), expect clear and ambiguous rows and zero confirmed/rejected; then, with psql, mark one match `confirmed`, re-run BoQ extraction from the tender page, and confirm the BoQ item and the match survive and no duplicate BoQ items appear. Record the result in the plan status line.

- [ ] **Step 3: Final suite and commit**

```bash
cd backend && DB_HOST_PORT=5433 uv run pytest -q && uv run ruff check . && uv run lint-imports
git add -A && git commit -m "docs: Slice 5a phase 2 status and limitations"
```
