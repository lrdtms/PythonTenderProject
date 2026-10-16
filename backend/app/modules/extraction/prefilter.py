"""Deterministic pre-filter (docs/spikes/m2-1b-prefilter-experiment.md): trigger sentences plus
one sentence of context, batched into windows. `deep_scan` sends every sentence instead."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .types import PageInput, Window

FOOTER = re.compile(r"Synthetic test document - fictional data|Page \d+")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
TRIGGERS = [
    re.compile(
        r"\b(must|shall|required?|requires?|compulsory|mandatory|disqualif\w*|should|"
        r"only tenderers|no later than|not later than|at least|not less than|minimum of|"
        r"will not be considered|will be rejected|will be held)\b",
        re.I,
    ),
    re.compile(rf"\b\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}}\b", re.I),
    re.compile(r"\b\d{1,2}:\d{2}\b"),
    re.compile(r"\b\d[A-Z]{1,2}\b|\bgrading\b|\bregistered\b", re.I),
    re.compile(r"\bR\s?\d[\d ,.]*\s*(million|thousand)?\b", re.I),
    re.compile(
        r"\bSANS\s?\d+|\bB-BBEE\b|certificate of compliance|tax compliance|good standing", re.I
    ),
    re.compile(r"\b\d+\s+(?:days|weeks|months)\b", re.I),
]
LOW_YIELD_MIN_SENTENCES = 30
LOW_YIELD_MAX_CANDIDATES = 2


@dataclass(frozen=True)
class PrefilterResult:
    windows: list[Window]
    candidate_sentences: int
    total_sentences: int
    low_yield: bool
    capped: bool


def _sentences(pages: Sequence[PageInput], exclude: frozenset[int]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for page in pages:
        if page.page_number in exclude:
            continue
        cleaned = FOOTER.sub(" ", re.sub(r"\s+", " ", page.text)).strip()
        if not cleaned:
            continue
        for part in re.split(r"(?<=[.;])\s+(?=[A-Z0-9(<])", cleaned):
            if len(part.strip()) > 3:
                out.append((page.page_number, part.strip()))
    return out


def _split(text: str, limit: int) -> list[str]:
    """Cut a chunk longer than `limit` at word boundaries (a hard cut inside a longer word), so
    text without sentence punctuation (sheets, lists, dense OCR) still fits a window."""
    pieces: list[str] = []
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit + 1)
        if cut <= 0:
            pieces.append(text[:limit])
            text = text[limit:]
        else:
            pieces.append(text[:cut])
            text = text[cut + 1 :]
    if text:
        pieces.append(text)
    return pieces


def _pack(chunks: list[tuple[int, str]], limit: int) -> list[Window]:
    windows: list[Window] = []
    text: list[str] = []
    pages: list[int] = []
    size = 0
    for page, chunk in chunks:
        if text and size + len(chunk) > limit:
            windows.append(Window("\n".join(text), tuple(dict.fromkeys(pages))))
            text, pages, size = [], [], 0
        text.append(chunk)
        pages.append(page)
        size += len(chunk) + 1
    if text:
        windows.append(Window("\n".join(text), tuple(dict.fromkeys(pages))))
    return windows


def prefilter(
    pages: Sequence[PageInput],
    exclude_pages: frozenset[int] | set[int] = frozenset(),
    deep_scan: bool = False,
    max_windows: int = 200,
    window_chars: int = 5400,
) -> PrefilterResult:
    sentences = _sentences(pages, frozenset(exclude_pages))
    selected = {i for i, (_, s) in enumerate(sentences) if any(t.search(s) for t in TRIGGERS)}
    if deep_scan:
        chunks = list(sentences)
    else:
        keep: set[int] = set()
        for i in selected:
            keep.update({max(0, i - 1), i, min(len(sentences) - 1, i + 1)})
        chunks = [sentences[i] for i in sorted(keep)]
    pieces = [(page, piece) for page, chunk in chunks for piece in _split(chunk, window_chars)]
    windows = _pack(pieces, window_chars)
    capped = len(windows) > max_windows
    low_yield = (
        not deep_scan
        and len(sentences) >= LOW_YIELD_MIN_SENTENCES
        and len(selected) <= LOW_YIELD_MAX_CANDIDATES
    )
    return PrefilterResult(windows[:max_windows], len(selected), len(sentences), low_yield, capped)
