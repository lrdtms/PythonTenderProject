"""Value objects of the estimates module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from .calc import Settings, validate_settings

DecimalText = Annotated[str, StringConstraints(pattern=r"^-?\d{1,14}(\.\d{1,4})?$")]
RateText = Annotated[str, StringConstraints(pattern=r"^\d{1,4}(\.\d{1,2})?$")]
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
