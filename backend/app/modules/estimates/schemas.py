"""Value objects of the estimates module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from .calc import Settings, validate_settings

DecimalText = Annotated[str, StringConstraints(pattern=r"^-?\d{1,14}(\.\d{1,4})?$")]
RateText = Annotated[str, StringConstraints(pattern=r"^\d{1,4}(\.\d{1,2})?$")]
ReasonText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class PricingDefaultsDTO(BaseModel):
    currency: str
    vat_rate: str
    markup_basis: Literal["cost", "selling_price"]
    default_markup_percent: str
    updated_at: datetime


class PricingDefaultsPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Currency
    vat_rate: RateText
    markup_basis: Literal["cost", "selling_price"]
    default_markup_percent: RateText

    @model_validator(mode="after")
    def _check(self) -> PricingDefaultsPut:
        validate_settings(
            Settings(
                Decimal(self.vat_rate), self.markup_basis, Decimal(self.default_markup_percent)
            )
        )
        return self


class LinePut(BaseModel):
    """Choose the line's price: exactly one of a confirmed match, a manual price or an exclusion."""

    model_config = ConfigDict(extra="forbid")

    match_suggestion_id: UUID | None = None
    manual_unit_price: DecimalText | None = None
    exclude_reason: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
        | None
    ) = None
    labour_rate: DecimalText | None = None
    markup_override_percent: RateText | None = None
    unit_mismatch_acknowledged: bool = False

    @model_validator(mode="after")
    def _check(self) -> LinePut:
        given = [
            self.match_suggestion_id,
            self.manual_unit_price,
            self.exclude_reason,
        ]
        if sum(v is not None for v in given) != 1:
            raise ValueError(
                "give exactly one of match_suggestion_id, manual_unit_price, exclude_reason"
            )
        if self.manual_unit_price is not None and Decimal(self.manual_unit_price) <= 0:
            raise ValueError("manual_unit_price must be above 0")
        if self.labour_rate is not None and Decimal(self.labour_rate) < 0:
            raise ValueError("labour_rate must not be negative")
        return self


class EstimatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Currency | None = None
    vat_rate: RateText | None = None
    markup_basis: Literal["cost", "selling_price"] | None = None
    markup_percent: RateText | None = None

    @model_validator(mode="after")
    def _check(self) -> EstimatePatch:
        if not self.model_fields_set or any(
            getattr(self, f) is None for f in self.model_fields_set
        ):
            raise ValueError("give at least one setting, none of them null")
        return self


@dataclass(frozen=True)
class BoqInput:
    """A current BoQ line, as the router reads it from the estimating module."""

    id: UUID
    section: str | None
    item_no: str | None
    description: str
    unit: str | None
    quantity: Decimal | None
    review_status: str


@dataclass(frozen=True)
class CandidateInput:
    """A confirmed, current match, as the router reads it from the suppliers module."""

    match_id: UUID
    boq_item_id: UUID
    quotation_item_id: UUID
    supplier_id: UUID
    supplier_name: str
    unit_price: Decimal | None
    currency: str | None
    includes_vat: bool | None
    unit_mismatch: bool
    quote_item_reviewed: bool


@dataclass(frozen=True)
class LiveInputs:
    boq: dict[UUID, BoqInput] = field(default_factory=dict)
    candidates: dict[UUID, list[CandidateInput]] = field(default_factory=dict)


LineStatus = Literal["priced", "excluded", "unresolved", "changed"]


class CandidateDTO(BaseModel):
    match_id: UUID
    supplier_id: UUID
    supplier_name: str
    quotation_item_id: UUID
    unit_price: str | None
    currency: str | None
    includes_vat: bool | None
    warnings: list[str]


class EstimateLineDTO(BaseModel):
    id: UUID
    boq_item_id: UUID
    position: int
    section: str | None
    item_no: str | None
    description: str
    unit: str | None
    quantity: str | None
    status: LineStatus
    price_source: str
    match_suggestion_id: UUID | None
    supplier_id: UUID | None
    supplier_name: str | None
    quoted_unit_price: str | None
    quoted_currency: str | None
    quoted_includes_vat: bool | None
    unit_price_ex_vat: str | None
    labour_rate: str | None
    markup_override_percent: str | None
    exclude_reason: str | None
    unit_mismatch_acknowledged: bool
    material_cost: str | None
    labour_cost: str | None
    cost: str | None
    markup: str | None
    total: str | None
    flags: list[str]
    candidates: list[CandidateDTO]


class TotalsDTO(BaseModel):
    subtotal_cost: str
    markup_total: str
    subtotal_ex_vat: str
    vat_total: str
    total_inc_vat: str


class EstimateSummaryDTO(BaseModel):
    id: UUID
    tender_id: UUID
    version: int
    status: str
    currency: str
    totals: TotalsDTO | None
    created_at: datetime
    reviewed_at: datetime | None
    approved_at: datetime | None
    is_current_approved: bool = False


class EstimateDTO(BaseModel):
    id: UUID
    tender_id: UUID
    version: int
    status: str
    currency: str
    vat_rate: str
    markup_basis: Literal["cost", "selling_price"]
    markup_percent: str
    based_on_version: int | None
    totals: TotalsDTO | None
    priced: int
    excluded: int
    unresolved: int
    changed: int
    incomplete: bool
    created_by: UUID
    created_at: datetime
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    currency_locked: bool
    reviewed_by_name: str | None = None  # filled by the API layer
    approved_by_name: str | None = None  # filled by the API layer


BlockerCode = Literal["unresolved", "source_changed", "unreviewed_source", "no_lines"]


class Blocker(BaseModel):
    line_id: UUID | None
    code: BlockerCode
    item_no: str | None = None
    description: str | None = None  # truncated to 120 characters
    reasons: list[str] = []  # the line's flag codes, live ones included; empty when none apply
