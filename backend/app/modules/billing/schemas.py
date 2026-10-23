"""Billing DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlanOption(BaseModel):
    code: str
    name: str


class UsageItem(BaseModel):
    resource: Literal["tenders", "uploads", "storage_mb", "exports", "members"]
    label: str
    used: int
    limit: int
    period: Literal["current", "month"]


class UsageDTO(BaseModel):
    plan_code: str
    plan_name: str
    items: list[UsageItem]
    available_plans: list[PlanOption]


class PlanChange(BaseModel):
    plan_code: str = Field(min_length=1, max_length=20)
