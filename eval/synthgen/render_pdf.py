"""PDF rendering with reportlab. Records the physical page each label lands on."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

STYLES = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=STYLES["BodyText"], fontSize=10, leading=13, spaceAfter=6)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.5, leading=10.5, spaceAfter=2)
H1 = ParagraphStyle("h1", parent=STYLES["Heading1"], fontSize=15, spaceAfter=8)
H2 = ParagraphStyle("h2", parent=STYLES["Heading2"], fontSize=12, spaceAfter=6, spaceBefore=8)
WATERMARK = "Synthetic test document - fictional data"


class Tagged(Paragraph):
    """A paragraph that is never split across pages, tagged with the label ids it carries."""

    def __init__(self, text: str, style: ParagraphStyle, ids: list[str] | None = None):
        super().__init__(text, style)
        self._gt_ids = ids or []

    def split(self, availWidth, availHeight):  # noqa: N803 - reportlab signature
        return []


class _Doc(BaseDocTemplate):
    def __init__(self, path: Path, title: str, label_offset: int, track_items: set[str]):
        super().__init__(
            str(path),
            pagesize=A4,
            title=title,
            author="IntelTPS synthgen",
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="f")
        self.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=self._decorate)])
        self.label_offset = label_offset
        self.track_items = track_items
        self.page_of: dict[str, int] = {}
        self.item_page: dict[str, int] = {}

    def printed_label(self, page: int) -> str:
        n = page - self.label_offset
        return str(n) if n > 0 else ""

    def _decorate(self, canvas, doc):  # noqa: ANN001
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        label = self.printed_label(doc.page)
        right = f"Page {label}" if label else ""
        canvas.drawString(20 * mm, 12 * mm, WATERMARK)
        canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, right)
        canvas.restoreState()

    def afterFlowable(self, flowable):  # noqa: N802 - reportlab hook
        for gid in getattr(flowable, "_gt_ids", []):
            self.page_of[gid] = self.page
        if isinstance(flowable, Table):
            for row in flowable._cellvalues:  # noqa: SLF001
                first = row[0]
                if isinstance(first, str) and first in self.track_items:
                    self.item_page[first] = self.page


@dataclass
class TenderResult:
    page_of: dict[str, int]  # requirement/non-requirement id -> physical page
    item_page: dict[str, int]  # BoQ item number -> physical page (PDF BoQ only)
    pages: int
    label_offset: int

    def printed(self, page: int) -> str:
        n = page - self.label_offset
        return str(n) if n > 0 else ""


def _paragraphs_for_filler(rng: random.Random, facts: dict, n_sentences: int) -> str:
    from .catalogue import FILLER_SENTENCES

    picks = rng.sample(FILLER_SENTENCES, k=min(n_sentences, len(FILLER_SENTENCES)))
    return " ".join(s.format(site=facts["site"], town=facts["town"]) for s in picks)


def render_tender(
    path: Path,
    facts: dict,
    requirements: list[dict],
    non_requirements: list[dict],
    distractors: list[dict],
    boq_rows: list[dict] | None,
    rng: random.Random,
    style: str,
    messy_boq: bool,
    filler_paragraphs: int,
    label_offset: int,
) -> TenderResult:
    """requirements: dicts with id, sentence. boq_rows: dicts for the PDF pricing table."""
    track = {r["item_number"] for r in boq_rows} if boq_rows else set()
    doc = _Doc(path, facts["reference"], label_offset, track)
    flow: list = []

    # Cover page (physical page 1, no printed label).
    flow += [
        Spacer(1, 60 * mm),
        Paragraph("TENDER DOCUMENT", H1),
        Paragraph(escape(facts["reference"]), H2),
        Paragraph(f"Supply and installation of electrical works at {escape(facts['site'])}", BODY),
        Paragraph(f"Employer: {escape(facts['client'])}", BODY),
        Paragraph(WATERMARK, SMALL),
        PageBreak(),
    ]

    reqs = list(requirements)
    rng.shuffle(reqs)
    parts = [
        "Part C1: Tender notice and conditions",
        "Part C3: Scope of work and conditions of contract",
    ]
    blocks = max(len(reqs) + 2, filler_paragraphs)
    # Spread requirements through the document at random positions.
    slots: dict[int, list[dict]] = {}
    for r, b in zip(reqs, sorted(rng.sample(range(blocks), k=len(reqs))), strict=True):
        slots.setdefault(b, []).append(r)
    injections = list(non_requirements)
    spots: dict[int, list[dict]] = {}
    for d, b in zip(distractors, rng.choices(range(blocks), k=len(distractors)), strict=True):
        spots.setdefault(b, []).append(d)

    for b in range(blocks):
        if b == 0 or b == blocks // 2:
            flow.append(Paragraph(escape(parts[0 if b == 0 else 1]), H2))
        filler = _paragraphs_for_filler(rng, facts, rng.randint(3, 5))
        flow.append(Tagged(escape(filler), BODY))
        for r in slots.get(b, []):
            sentence = escape(r["sentence"])
            if style == "dense":
                before = _paragraphs_for_filler(rng, facts, 2)
                after = _paragraphs_for_filler(rng, facts, 2)
                flow.append(Tagged(f"{escape(before)} {sentence} {escape(after)}", BODY, [r["id"]]))
            else:
                flow.append(Tagged(f"<b>{r['clause']}</b> {sentence}", BODY, [r["id"]]))
        for d in spots.get(b, []):
            extra = _paragraphs_for_filler(rng, facts, 2)
            flow.append(Tagged(f"{escape(d['text'])} {escape(extra)}", BODY, [d["id"]]))
        if injections and b == blocks // 2:
            inj = injections.pop(0)
            flow.append(Tagged(escape(inj["text"]), BODY, [inj["id"]]))

    if boq_rows:
        flow += [
            PageBreak(),
            Paragraph("Part C2: Pricing data - Bill of Quantities", H1),
            Paragraph("Rates and amounts are to be completed by the tenderer.", SMALL),
            Spacer(1, 4 * mm),
            _boq_table(boq_rows, messy_boq, doc.width),
        ]

    doc.build(flow)
    return TenderResult(doc.page_of, doc.item_page, doc.page, label_offset)


def _boq_table(rows: list[dict], messy: bool, width: float) -> Table:
    data: list[list] = [["Item", "Description", "Unit", "Qty", "Rate", "Amount"]]
    spans: list[tuple] = []
    heading_rows: list[int] = []
    last_section = None
    for r in rows:
        if r["section"] != last_section:
            last_section = r["section"]
            data.append([f"SECTION: {r['section'].upper()}", "", "", "", "", ""])
            spans.append(("SPAN", (0, len(data) - 1), (-1, len(data) - 1)))
            heading_rows.append(len(data) - 1)
        data.append(
            [
                r["item_number"],
                Paragraph(escape(r["description"]), SMALL),
                r["raw_unit"] or "",
                r["raw_quantity"] or "",
                r["unit_price_text"] or "",
                "",
            ]
        )
    col_widths = [
        18 * mm,
        width - 18 * mm - 14 * mm - 20 * mm - 22 * mm - 24 * mm,
        14 * mm,
        20 * mm,
        22 * mm,
        24 * mm,
    ]
    t = Table(data, colWidths=col_widths, repeatRows=1, splitByRow=1)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (3, 1), (5, -1), "RIGHT"),
    ] + spans
    for hr in heading_rows:
        style.append(("BACKGROUND", (0, hr), (-1, hr), colors.whitesmoke))
        style.append(("FONTNAME", (0, hr), (-1, hr), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    return t


def render_quotation(
    path: Path,
    supplier: str,
    reference: str,
    date: str,
    valid_until: str,
    items: list[dict],
    currency: str = "ZAR",
) -> tuple[int, dict[str, int]]:
    """A simple supplier quotation. Returns (pages, row number -> physical page)."""
    doc = _Doc(path, f"Quotation {reference}", 0, {str(i["row"]) for i in items})
    flow: list = [
        Paragraph(escape(supplier.upper()), H1),
        Paragraph(f"QUOTATION {escape(reference)}", H2),
        Paragraph(
            f"Date: {date} &nbsp;&nbsp; Valid until: {valid_until} "
            f"&nbsp;&nbsp; Currency: {currency}",
            BODY,
        ),
        Paragraph(
            "Prices exclude value-added tax unless stated. Subject to availability of stock.", SMALL
        ),
        Spacer(1, 4 * mm),
    ]
    data: list[list] = [["#", "Description", "Unit", "Qty", "Unit price"]]
    for i in items:
        data.append(
            [
                str(i["row"]),
                Paragraph(escape(i["description"]), SMALL),
                i["unit"] or "",
                i["quantity"] or "",
                i["unit_price"] or "",
            ]
        )
    t = Table(data, colWidths=[10 * mm, 100 * mm, 16 * mm, 20 * mm, 24 * mm], repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (3, 1), (4, -1), "RIGHT"),
            ]
        )
    )
    flow.append(t)
    doc.build(flow)
    return doc.page, doc.item_page
