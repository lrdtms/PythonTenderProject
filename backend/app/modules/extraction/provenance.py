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
GRAM = 5
MAX_GRAM_HITS = 8
MIN_VOTE_SHARE = 0.3


@dataclass(frozen=True)
class Location:
    page_number: int
    start: int
    end: int
    exact: bool


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _ratio(chunk: str, needle: str) -> float:
    if not chunk:
        return 0.0
    return difflib.SequenceMatcher(None, chunk, needle, autojunk=False).ratio()


def _anchor(haystack: str, needle: str) -> int | None:
    """Estimate where the quote starts: n-gram hits vote for a diagonal (haystack - needle pos)."""
    size = len(needle)
    n_grams = size - GRAM + 1
    bucket = max(4, size // 8)
    votes: dict[int, list[int]] = {}
    stride = 2 if n_grams > 40 else 1
    for i in range(0, n_grams, stride):
        gram = needle[i : i + GRAM]
        at = haystack.find(gram)
        seen = 0
        while at >= 0 and seen < MAX_GRAM_HITS:
            votes.setdefault((at - i) // bucket, []).append(at - i)
            seen += 1
            at = haystack.find(gram, at + 1)
    best_key, best_count = None, 0
    for key in votes:
        count = len(votes[key]) + len(votes.get(key + 1, ()))
        if count > best_count:
            best_key, best_count = key, count
    if best_key is None or best_count < n_grams / stride * MIN_VOTE_SHARE:
        return None
    pooled = sorted(votes[best_key] + votes.get(best_key + 1, []))
    return pooled[len(pooled) // 2]


def _fuzzy_in(haystack: str, needle: str) -> tuple[float, int, int] | None:
    """Best (ratio, start, end) of a slice scoring >= FUZZY_THRESHOLD, with bounded work:
    an n-gram vote picks the anchor, then a halving-step search refines start and length."""
    size = len(needle)
    estimate = _anchor(haystack, needle)
    if estimate is None:
        return None
    step = max(2, size // 10)
    start, length = max(0, estimate), size
    best = _ratio(haystack[start : start + length], needle)
    cache: dict[tuple[int, int], float] = {(start, length): best}
    while step >= 1:
        improved = True
        while improved:
            improved = False
            for ds in (-step, 0, step):
                for dl in (-step, 0, step):
                    s, n = max(0, start + ds), max(1, length + dl)
                    if (s, n) not in cache:
                        cache[(s, n)] = _ratio(haystack[s : s + n], needle)
                    if cache[(s, n)] > best:
                        best, start, length = cache[(s, n)], s, n
                        improved = True
        step //= 2
    if best < FUZZY_THRESHOLD:
        return None
    return best, start, min(len(haystack), start + length)


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
        best: tuple[float, Location] | None = None
        for number, text in squashed:
            found = _fuzzy_in(text, needle) if text else None
            if found and (best is None or found[0] > best[0]):  # ties keep the earliest page
                best = (found[0], Location(number, found[1], found[2], False))
        if best:
            return best[1]
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
