"""Find where a quote is, by code (ADR-0004). Offsets are into the page's whitespace-collapsed,
case-folded text. A quote that crosses a page break belongs to the page where it starts."""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from .types import PageInput, RequirementCandidate

FUZZY_THRESHOLD = 0.9
MIN_FUZZY_CHARS = 20


@dataclass(frozen=True)
class Location:
    page_number: int
    start: int
    end: int
    exact: bool


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _fuzzy_in(haystack: str, needle: str) -> tuple[int, int] | None:
    """Anchor on the longest common blocks, then score nearby slices of about the quote's length."""
    size = len(needle)
    grams = {needle[i : i + 5] for i in range(size - 4)}
    if sum(1 for g in grams if g in haystack) < len(grams) * 0.4:
        return None  # cheap gate: most of the quote's 5-grams must occur on the page
    matcher = difflib.SequenceMatcher(None, haystack, needle, autojunk=False)
    blocks = [m for m in matcher.get_matching_blocks() if m.size >= 4]
    if sum(m.size for m in blocks) < size * FUZZY_THRESHOLD * 0.8:
        return None
    anchor = max(blocks, key=lambda m: m.size)
    estimate = anchor.a - anchor.b
    slack = max(3, size // 10)
    best: tuple[float, int, int] = (0.0, 0, 0)
    for start in range(max(0, estimate - slack), estimate + slack + 1):
        for length in range(size - slack, size + slack + 1):
            chunk = haystack[start : start + length]
            if not chunk:
                continue
            ratio = difflib.SequenceMatcher(None, chunk, needle, autojunk=False).ratio()
            if ratio > best[0]:
                best = (ratio, start, start + len(chunk))
    return (best[1], best[2]) if best[0] >= FUZZY_THRESHOLD else None


def locate(quote: str, pages: Sequence[PageInput]) -> Location | None:
    needle = _squash(quote)
    if not needle:
        return None
    squashed = [(p.page_number, _squash(p.text)) for p in pages]
    joined = " ".join(text for _, text in squashed)
    index = joined.find(needle)
    if index >= 0:
        offset = 0
        for number, text in squashed:
            if index < offset + len(text) or (index == offset and not text):
                start = index - offset
                return Location(number, start, start + len(needle), True)
            offset += len(text) + 1
    if len(needle) >= MIN_FUZZY_CHARS:
        for number, text in squashed:
            found = _fuzzy_in(text, needle) if text else None
            if found:
                return Location(number, found[0], found[1], False)
    return None


def attach_provenance(
    cands: Sequence[RequirementCandidate], pages: Sequence[PageInput]
) -> list[RequirementCandidate]:
    low_confidence = {p.page_number for p in pages if p.status == "low_confidence"}
    for cand in cands:
        found = locate(cand.evidence_quote, pages)
        if found is None:
            cand.evidence_status = "evidence_unverified"
            cand.page_number = cand.quote_start = cand.quote_end = None
            cand.needs_review = False
            continue
        cand.evidence_status = "verified"
        cand.page_number, cand.quote_start, cand.quote_end = (
            found.page_number,
            found.start,
            found.end,
        )
        cand.needs_review = found.page_number in low_confidence
    return list(cands)
