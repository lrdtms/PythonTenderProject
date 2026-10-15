"""Requirement extraction over windows: validated, bounded, and free of document text in errors."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.kernel import LLMPort, LLMTimeout

from .prompts import MANDATORY_STATUSES, REQUIREMENT_TYPES, SCHEMA, SYSTEM, user_prompt
from .types import RequirementCandidate, Window


class InvalidOutput(Exception):
    """The model's answer did not fit the schema. The message is a short code only."""


@dataclass
class ExtractOutcome:
    candidates: list[RequirementCandidate] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _text(item: dict[str, Any], name: str) -> str:
    value = item.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidOutput(f"bad_field:{name}")
    return value.strip()


def parse_response(raw: str, max_items: int) -> tuple[list[RequirementCandidate], bool]:
    """Return (candidates, capped). Raises InvalidOutput with a code, never document text."""
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise InvalidOutput("not_json") from None
    items = data.get("requirements") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise InvalidOutput("no_requirements_list")
    out: list[RequirementCandidate] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            raise InvalidOutput("item_not_object")
        rtype = _text(item, "requirement_type")
        status = _text(item, "mandatory_status")
        if rtype not in REQUIREMENT_TYPES:
            raise InvalidOutput("bad_field:requirement_type")
        if status not in MANDATORY_STATUSES:
            raise InvalidOutput("bad_field:mandatory_status")
        out.append(
            RequirementCandidate(
                description=_text(item, "description"),
                requirement_type=rtype,
                mandatory_status=status,
                evidence_quote=_text(item, "evidence_quote"),
            )
        )
    return out, len(items) > max_items


def _run_window(
    window: Window, llm: LLMPort, max_items: int
) -> tuple[list[RequirementCandidate], str | None, bool]:
    """Return (candidates, failure_code, capped). LLMUnavailable propagates to the job."""
    error: str | None = None
    for attempt in range(2):
        try:
            result = llm.generate_structured(SYSTEM, user_prompt(window.text, error), SCHEMA)
        except LLMTimeout:
            if attempt == 0:
                continue
            return [], "WINDOW_TIMEOUT", False
        if result.done_reason == "length":
            error = "truncated"
            continue
        try:
            cands, capped = parse_response(result.raw_json, max_items)
            return cands, None, capped
        except InvalidOutput as exc:
            error = str(exc)
    return [], "WINDOW_INVALID_OUTPUT", False


def extract_requirements(
    windows: Sequence[Window],
    llm: LLMPort,
    *,
    max_items_per_response: int,
    progress: Callable[[int, int], None] | None = None,
) -> ExtractOutcome:
    outcome = ExtractOutcome()
    failed: dict[str, list[int]] = {}
    total = len(windows)
    for index, window in enumerate(windows):
        cands, code, capped = _run_window(window, llm, max_items_per_response)
        outcome.candidates.extend(cands)
        if code:
            failed.setdefault(code, []).append(index)
        if capped:
            failed.setdefault("RESPONSE_CAP_REACHED", []).append(index)
        if progress:
            progress(index + 1, total)
    outcome.warnings = [{"code": c, "windows": w} for c, w in failed.items()]
    return outcome


_EDGE_PUNCTUATION = "\"'.,;:!?()[]{}<>"


def _words(text: str) -> tuple[str, ...]:
    """Normalised words of a quote: whitespace-split, case-folded, edge punctuation stripped."""
    words = tuple(w for w in (t.strip(_EDGE_PUNCTUATION) for t in text.lower().split()) if w)
    return words or (re.sub(r"\s+", " ", text).strip().lower(),)


def _contains(big: tuple[str, ...], small: tuple[str, ...]) -> bool:
    """Whole-word containment: `small` occurs in `big` as a contiguous run of words."""
    n = len(small)
    return n <= len(big) and any(big[i : i + n] == small for i in range(len(big) - n + 1))


def merge_requirements(cands: Sequence[RequirementCandidate]) -> list[RequirementCandidate]:
    """Drop duplicates from overlapping windows: a quote equal to, or contained in (whole words),
    an earlier kept quote is the same requirement; a quote containing kept quotes replaces the
    first of them and drops the rest, so the longer wording is kept."""
    kept: list[tuple[tuple[str, ...], RequirementCandidate]] = []
    for cand in cands:
        q = _words(cand.evidence_quote)
        if any(_contains(o, q) for o, _ in kept):
            continue
        inside = [i for i, (o, _) in enumerate(kept) if _contains(q, o)]
        if inside:
            kept[inside[0]] = (q, cand)
            for i in reversed(inside[1:]):
                del kept[i]
        else:
            kept.append((q, cand))
    return [cand for _, cand in kept]
