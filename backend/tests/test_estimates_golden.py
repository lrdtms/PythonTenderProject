from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.modules.estimates.calc import LineInput, Settings, line_amounts, totals

FIXTURES = Path(__file__).parent / "fixtures" / "estimates"


def _dec(value: str | None) -> D | None:
    return None if value is None else D(value)


@pytest.mark.parametrize("name", ["a", "b", "c"])
def test_golden(name: str):
    data = json.loads((FIXTURES / f"golden_{name}.json").read_text(encoding="utf-8"))
    s = data["settings"]
    settings = Settings(D(s["vat_rate"]), s["markup_basis"], D(s["markup_percent"]))
    priced = []
    for raw, expected in zip(data["lines"], data["expected"]["lines"], strict=True):
        if raw["excluded"]:
            assert expected is None
            continue
        got = line_amounts(
            LineInput(
                _dec(raw["quantity"]),
                _dec(raw["unit_price_ex_vat"]),
                _dec(raw["labour_rate"]),
                _dec(raw["markup_override"]),
            ),
            settings,
        )
        assert got is not None
        for key, value in expected.items():
            assert getattr(got, key) == D(value), (name, key)
        priced.append(got)
    got_totals = totals(priced, settings)
    for key, value in data["expected"]["totals"].items():
        assert getattr(got_totals, key) == D(value), (name, key)


def test_all_lines_excluded():
    t = totals([], Settings(D("15"), "cost", D("10")))
    zero = D("0.00")
    assert (t.subtotal_cost, t.markup_total, t.subtotal_ex_vat) == (zero, zero, zero)
    assert (t.vat_total, t.total_inc_vat) == (zero, zero)
