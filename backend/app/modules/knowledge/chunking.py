"""Section-aware chunking for search. Pure functions; chunks never cross a page."""

from __future__ import annotations

import re
from dataclasses import dataclass

TARGET_CHARS = 1500  # about 375 tokens
MAX_CHARS = 1900
OVERLAP_SENTENCES = 1

# "3.2 Eligibility", "PART C1: Tender notice", "SECTION B: CABLES"
HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{2,80}|(?:PART|SECTION|SCHEDULE|ANNEXURE)\b[^\n]{0,80})\s*$"
)
SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z0-9(])")


@dataclass
class ChunkDraft:
    page_number: int
    section: str | None
    text: str


def _split_units(text: str) -> list[str]:
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n|\n(?=\s*(?:\d+(?:\.\d+)*\.?\s))", text):
        flat = re.sub(r"\s+", " ", paragraph).strip()
        if not flat:
            continue
        units.extend(s.strip() for s in SENTENCE_END.split(flat) if s.strip())
    return units


def chunk_page(
    page_number: int, text: str, section: str | None
) -> tuple[list[ChunkDraft], str | None]:
    """Chunks for one page, and the section heading in force at its end (carried on)."""
    for line in text.splitlines():
        if HEADING.match(line):
            section = line.strip()[:200]
    chunks: list[ChunkDraft] = []
    current: list[str] = []
    size = 0
    for unit in _split_units(text):
        if current and size + len(unit) > TARGET_CHARS:
            chunks.append(ChunkDraft(page_number, section, " ".join(current)[: MAX_CHARS * 2]))
            current = current[-OVERLAP_SENTENCES:] if OVERLAP_SENTENCES else []
            size = sum(len(u) for u in current)
        current.append(unit)
        size += len(unit)
    if current:
        chunks.append(ChunkDraft(page_number, section, " ".join(current)[: MAX_CHARS * 2]))
    return chunks, section


def chunk_document(pages: list[tuple[int, str]]) -> list[ChunkDraft]:
    """pages: (page_number, text) in order. Section headings carry across pages."""
    out: list[ChunkDraft] = []
    section: str | None = None
    for number, text in pages:
        if not text.strip():
            continue
        chunks, section = chunk_page(number, text, section)
        out.extend(chunks)
    return out
