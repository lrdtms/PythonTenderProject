from __future__ import annotations

import ast
from decimal import Decimal as D
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.estimates.calc import (
    LineAmounts,
    LineInput,
    Settings,
    to_ex_vat,
    totals,
    validate_settings,
)
from app.modules.estimates.calc import line_amounts as calc_line

COST = Settings(vat_rate=D("15"), markup_basis="cost", markup_percent=D("10"))
SELL = Settings(vat_rate=D("15"), markup_basis="selling_price", markup_percent=D("10"))


def line(q="10", p="125.5000", labour="20.0000", override=None) -> LineInput:
    return LineInput(
        quantity=None if q is None else D(q),
        unit_price_ex_vat=None if p is None else D(p),
        labour_rate=None if labour is None else D(labour),
        markup_override=None if override is None else D(override),
    )


def test_to_ex_vat():
    assert to_ex_vat(D("115"), True, D("15")) == D("100.0000")
    assert to_ex_vat(D("100"), False, D("15")) == D("100.0000")


def test_cost_basis():
    a = calc_line(line(), COST)
    assert a == LineAmounts(D("1255.00"), D("200.00"), D("1455.00"), D("145.50"), D("1600.50"))


def test_selling_price_basis():
    a = calc_line(line(), SELL)
    assert a is not None
    assert a.markup == D("161.67")
    assert a.total == D("1616.67")


def test_half_cent():
    a = calc_line(line("1", "0.0050", None), COST)
    assert a is not None
    assert a.material_cost == D("0.01")


def test_large():
    a = calc_line(line("10000", "0.3333", None), COST)
    assert a is not None
    assert a.material_cost == D("3333.00")


def test_override_zero():
    a = calc_line(line(override="0"), COST)
    assert a is not None
    assert a.markup == D("0.00")


@pytest.mark.parametrize("q,p", [(None, "1"), ("1", None)])
def test_missing_returns_none(q, p):
    assert calc_line(line(q, p), COST) is None


def test_totals_vat():
    a = calc_line(line(), COST)
    assert a is not None
    t = totals([a], COST)
    assert t.vat_total == D("240.08")
    assert t.total_inc_vat == D("1840.58")
    assert t.subtotal_ex_vat == t.subtotal_cost + t.markup_total


def test_totals_empty():
    t = totals([], COST)
    zero = D("0.00")
    assert (t.subtotal_cost, t.markup_total, t.subtotal_ex_vat) == (zero, zero, zero)
    assert (t.vat_total, t.total_inc_vat) == (zero, zero)


def test_validate_settings():
    validate_settings(COST)
    with pytest.raises(ValueError):
        validate_settings(Settings(D("101"), "cost", D("10")))
    with pytest.raises(ValueError):
        validate_settings(Settings(D("15"), "cost", D("-1")))
    with pytest.raises(ValueError):
        validate_settings(Settings(D("15"), "selling_price", D("100")))


qty = st.decimals(min_value=D("0.0001"), max_value=D("100000"), places=4)
price = st.decimals(min_value=D("0"), max_value=D("100000"), places=4)
inputs = st.builds(
    LineInput,
    quantity=qty,
    unit_price_ex_vat=price,
    labour_rate=st.none() | price,
    markup_override=st.none() | st.decimals(min_value=D("0"), max_value=D("99.99"), places=2),
)


def _amounts(ls, s):
    return [a for a in (calc_line(x, s) for x in ls) if a is not None]


@given(st.lists(inputs, max_size=8), st.randoms())
def test_order_independent(ls, rnd):
    shuffled = list(ls)
    rnd.shuffle(shuffled)
    assert totals(_amounts(ls, COST), COST) == totals(_amounts(shuffled, COST), COST)


@given(st.lists(inputs, max_size=8))
def test_excluded_empty_changes_nothing(ls):
    base = _amounts(ls, COST)
    assert totals(base + [], COST) == totals(base, COST)


@given(st.lists(inputs, max_size=8))
def test_subtotal_is_sum_of_totals(ls):
    am = _amounts(ls, COST)
    assert totals(am, COST).subtotal_ex_vat == sum((a.total for a in am), D("0.00"))


@given(inputs)
def test_selling_price_markup_never_negative(x):
    a = calc_line(x, SELL)
    assert a is not None
    assert a.markup >= 0


@given(st.decimals(min_value=D("0"), max_value=D("100000"), places=4), st.integers(0, 100))
def test_to_ex_vat_close_to_exact(quoted, rate):
    r = D(rate)
    exact = quoted / (1 + r / 100)
    assert abs(to_ex_vat(quoted, True, r) - exact) <= D(
        "0.00005"
    )  # a half-way tie rounds up by exactly half a unit


def test_no_float_in_estimates_module():
    root = Path(__file__).resolve().parent.parent / "app" / "modules" / "estimates"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            assert not (isinstance(node, ast.Name) and node.id == "float"), path
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), path


def test_validate_settings_markup_cap_on_cost_basis():
    validate_settings(Settings(D("15"), "cost", D("1000")))
    with pytest.raises(ValueError):
        validate_settings(Settings(D("15"), "cost", D("1000.01")))
    validate_settings(Settings(D("15"), "selling_price", D("99.99")))
