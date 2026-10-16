"""The evaluation helper's excusal rule for ground-truth trap items that are spec-exact."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.modules.suppliers import matching as m
from tests.matching_eval import is_spec_exact


def _clear_evidence(boq_desc: str, quote_desc: str) -> dict:
    line = m.BoqLine(uuid4(), "1", boq_desc, "no")
    q = m.QuoteLine(
        uuid4(), uuid4(), uuid4(), quote_desc, None, "no", Decimal("1"), date(2030, 1, 1)
    )
    [s] = m.suggest([line], [q])
    assert s.classification == "clear"
    return s.evidence


def test_a_spec_exact_clear_pair_is_excused() -> None:
    ev = _clear_evidence("MCB, 1-pole, 20 A, 6 kA", "MCB, 1-pole, 20 A, 6 kA")
    assert is_spec_exact(ev, 0.5)


def test_a_clear_pair_with_an_unmatched_spec_kind_is_not_excused() -> None:
    ev = _clear_evidence(
        "Miniature circuit breaker, 1-pole, 20 A, 6 kA, DIN rail mounted",
        "Miniature circuit breaker, 1-pole, 20 A, DIN rail mounted",
    )
    assert ev["spec"]["boq_only"] and not is_spec_exact(ev, 0.5)


def test_conflicts_multi_value_and_low_text_are_not_excused() -> None:
    base = {
        "spec": {
            "matched": ["a"],
            "conflicts": [],
            "multi_value": [],
            "boq_only": [],
            "quote_only": [],
        },
        "signals": {"text": 0.9},
    }
    assert is_spec_exact(base, 0.5)
    for key in ("conflicts", "multi_value", "boq_only", "quote_only"):
        bad = {**base, "spec": {**base["spec"], key: ["x"]}}
        assert not is_spec_exact(bad, 0.5)
    assert not is_spec_exact({**base, "spec": {**base["spec"], "matched": []}}, 0.5)
    assert not is_spec_exact({**base, "signals": {"text": 0.4}}, 0.5)
