"""Pure estimate arithmetic. Decimal only, no I/O, no imports outside the stdlib."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Literal

MarkupBasis = Literal["cost", "selling_price"]

_CTX = Context(prec=40, rounding=ROUND_HALF_UP)
_HUNDRED = Decimal(100)
_ONE = Decimal(1)
_CENT = Decimal("0.01")
_FOUR_DP = Decimal("0.0001")


@dataclass(frozen=True)
class Settings:
    vat_rate: Decimal
    markup_basis: MarkupBasis
    markup_percent: Decimal


@dataclass(frozen=True)
class LineInput:
    quantity: Decimal | None
    unit_price_ex_vat: Decimal | None
    labour_rate: Decimal | None
    markup_override: Decimal | None


@dataclass(frozen=True)
class LineAmounts:
    material_cost: Decimal
    labour_cost: Decimal
    cost: Decimal
    markup: Decimal
    total: Decimal


@dataclass(frozen=True)
class Totals:
    subtotal_cost: Decimal
    markup_total: Decimal
    subtotal_ex_vat: Decimal
    vat_total: Decimal
    total_inc_vat: Decimal


def _round2(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP, context=_CTX)


def validate_settings(settings: Settings) -> None:
    if not Decimal(0) <= settings.vat_rate <= _HUNDRED:
        raise ValueError("vat_rate must be between 0 and 100")
    if settings.markup_percent < 0:
        raise ValueError("markup_percent must not be negative")
    if settings.markup_basis == "selling_price" and settings.markup_percent >= _HUNDRED:
        raise ValueError("markup_percent must be below 100 on the selling_price basis")


def to_ex_vat(quoted: Decimal, includes_vat: bool, vat_rate: Decimal) -> Decimal:
    value = _CTX.divide(quoted, _ONE + _CTX.divide(vat_rate, _HUNDRED)) if includes_vat else quoted
    return value.quantize(_FOUR_DP, rounding=ROUND_HALF_UP, context=_CTX)


def line_amounts(line: LineInput, settings: Settings) -> LineAmounts | None:
    if line.quantity is None or line.unit_price_ex_vat is None:
        return None
    material = _round2(_CTX.multiply(line.quantity, line.unit_price_ex_vat))
    labour = (
        _round2(_CTX.multiply(line.quantity, line.labour_rate))
        if line.labour_rate is not None
        else Decimal("0.00")
    )
    cost = _CTX.add(material, labour)
    pct = line.markup_override if line.markup_override is not None else settings.markup_percent
    ratio = _CTX.divide(pct, _HUNDRED)
    if settings.markup_basis == "cost":
        markup = _round2(_CTX.multiply(cost, ratio))
    else:
        markup = _CTX.subtract(_round2(_CTX.divide(cost, _CTX.subtract(_ONE, ratio))), cost)
    return LineAmounts(material, labour, cost, markup, _CTX.add(cost, markup))


def totals(amounts: Sequence[LineAmounts], settings: Settings) -> Totals:
    zero = Decimal("0.00")
    subtotal_cost = zero
    markup_total = zero
    subtotal = zero
    for a in amounts:
        subtotal_cost = _CTX.add(subtotal_cost, a.cost)
        markup_total = _CTX.add(markup_total, a.markup)
        subtotal = _CTX.add(subtotal, a.total)
    vat = _round2(_CTX.multiply(subtotal, _CTX.divide(settings.vat_rate, _HUNDRED)))
    return Totals(subtotal_cost, markup_total, subtotal, vat, _CTX.add(subtotal, vat))
