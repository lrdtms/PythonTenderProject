"""Closed vocabularies shared by extraction (the LLM schema) and checklist (review edits)."""

from __future__ import annotations

REQUIREMENT_TYPES: tuple[str, ...] = (
    "deadline",
    "meeting",
    "eligibility",
    "document",
    "pricing",
    "technical",
    "other",
)
MANDATORY_STATUSES: tuple[str, ...] = ("mandatory", "conditional", "informational")
