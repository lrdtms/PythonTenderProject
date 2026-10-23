"""PDF renderer for a tender's requirement checklist: a pure function of `ChecklistExportInput`.

Every user string reaches a `Paragraph` through `safe_text.pdf_text` (markup is escaped); text drawn
on the canvas and the document metadata go through `pdf_plain`. Built-in Helvetica only.
"""

import io
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.kernel.vocab import REQUIREMENT_TYPES
from app.modules.reporting import words
from app.modules.reporting.safe_text import pdf_plain, pdf_text
from app.modules.reporting.schemas import ChecklistExportInput, ChecklistRow

RED = colors.HexColor("#C00000")
WATERMARK = colors.HexColor("#F4CCCC")
GREY = colors.HexColor("#D9D9D9")
MARGIN = 15 * mm
_COL_WIDTHS = (24 * mm, 80 * mm, 26 * mm, 50 * mm)
_COUNT_WIDTHS = (40 * mm, 30 * mm, 30 * mm, 35 * mm, 20 * mm)
_MANDATORY = {
    "mandatory": "MANDATORY",
    "conditional": "Conditional",
    "informational": "Information only",
}
_REVIEW = {"confirmed": "Confirmed", "corrected": "Corrected"}
_UNREVIEWED = "unreviewed"
_DRAFT_LINE = "DRAFT: not every requirement has been reviewed by a person"


def checklist_label(data: ChecklistExportInput) -> Literal["draft", "approved"]:
    if data.rows and all(r.review_status != _UNREVIEWED for r in data.rows):
        return "approved"
    return "draft"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _when(value: datetime) -> str:
    return _utc(value).strftime("%Y-%m-%d %H:%M UTC")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    cell = ParagraphStyle("cell", parent=base, fontName="Helvetica", fontSize=8.5, leading=11)
    return {
        "cell": cell,
        "head": ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold"),
        "title": ParagraphStyle(
            "title", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=6
        ),
        "tender": ParagraphStyle(
            "tender", parent=base, fontName="Helvetica-Bold", fontSize=13, leading=16
        ),
        "section": ParagraphStyle(
            "section",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            spaceBefore=12,
            spaceAfter=4,
            keepWithNext=1,
        ),
    }


def _numbered_canvas(data: ChecklistExportInput) -> Callable[..., Canvas]:
    """A two-pass canvas class that stamps the footer once the page count is known."""
    title = pdf_plain(data.tender_title, 70)
    export_id = pdf_plain(str(data.export_id))

    class NumberedCanvas(Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._saved: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 (ReportLab API)
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self._stamp(total)
                super().showPage()
            super().save()

        def _stamp(self, total: int) -> None:
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.black)
            self.drawString(MARGIN, 10 * mm, title)
            self.drawCentredString(A4[0] / 2, 10 * mm, f"Page {self._pageNumber} of {total}")
            self.drawRightString(A4[0] - MARGIN, 10 * mm, export_id)

    return NumberedCanvas


def _draft_decor(canvas: Canvas, _doc: object) -> None:
    canvas.saveState()
    canvas.setFillColor(WATERMARK)
    canvas.setFont("Helvetica-Bold", 120)
    canvas.translate(A4[0] / 2, A4[1] / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "DRAFT")
    canvas.restoreState()
    canvas.saveState()
    canvas.setFillColor(RED)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(MARGIN, A4[1] - 10 * mm, _DRAFT_LINE)
    canvas.restoreState()


def _no_decor(_canvas: Canvas, _doc: object) -> None:
    return None


def _para(text: str | None, style: ParagraphStyle) -> Paragraph:
    return Paragraph(pdf_text(text), style)


def _source(r: ChecklistRow) -> str:
    page = f"page {r.page_number}" if r.page_number is not None else "page not recorded"
    text = f"{r.document_title}, {page}"
    if not r.evidence_verified:
        text += " (source not verified)"
    return text


def _grid(table: Table) -> Table:
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), GREY),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _table(rows: list[ChecklistRow], st: dict[str, ParagraphStyle]) -> Table:
    cell = st["cell"]
    body: list[list[Flowable]] = [
        [_para(h, st["head"]) for h in ("Mandatory", "Requirement", "Review", "Source")]
    ]
    for r in rows:
        mandatory = _MANDATORY.get(r.mandatory_status) or words.mandatory_text(r.mandatory_status)
        review = _REVIEW.get(r.review_status) or words.review_status_text(r.review_status)
        body.append(
            [
                _para(mandatory, cell),
                _para(r.description, cell),
                _para(review, cell),
                _para(_source(r), cell),
            ]
        )
    return _grid(Table(body, colWidths=_COL_WIDTHS, repeatRows=1, splitByRow=1))


def _count_table(listed: list[ChecklistRow], st: dict[str, ParagraphStyle]) -> Table:
    statuses = tuple(_MANDATORY)
    head = ("Type", *(_MANDATORY[s] for s in statuses), "Total")
    body: list[list[Flowable]] = [[_para(h, st["head"]) for h in head]]
    for t in REQUIREMENT_TYPES:
        of_type = [r for r in listed if r.requirement_type == t]
        if not of_type:
            continue
        counts = [sum(1 for r in of_type if r.mandatory_status == s) for s in statuses]
        cells = [t.capitalize(), *map(str, counts), str(len(of_type))]
        body.append([_para(c, st["cell"]) for c in cells])
    return _grid(Table(body, colWidths=_COUNT_WIDTHS))


def render_checklist_pdf(data: ChecklistExportInput) -> bytes:
    if data.generated_at is None or data.export_id is None:
        raise ValueError("generated_at and export_id must be set before rendering")
    label = checklist_label(data)
    st = _styles()
    listed = [r for r in data.rows if r.review_status in _REVIEW]
    unreviewed = [r for r in data.rows if r.review_status == _UNREVIEWED]
    story: list[Flowable] = [
        _para("Requirements checklist", st["title"]),
        _para(data.tender_title, st["tender"]),
        Spacer(1, 4),
    ]
    facts = (
        ("Reference", data.tender_reference),
        ("Client", data.client_name),
        ("Closing", _when(data.closing_at) if data.closing_at else None),
        ("Generated by", data.generated_by_name),
        ("Generated at", _when(data.generated_at)),
        ("Export reference", str(data.export_id)),
    )
    for caption, value in facts:
        story.append(_para(f"{caption}: {value or 'not stated'}", st["cell"]))
    story.append(Spacer(1, 8))
    story.append(_para(f"{len(unreviewed)} not yet reviewed", st["cell"]))
    if data.rejected_count > 0:
        story.append(_para(f"{data.rejected_count} rejected, not listed", st["cell"]))
    story.append(Spacer(1, 6))
    if listed:
        story.append(_count_table(listed, st))
    if not data.rows:
        story.append(Spacer(1, 12))
        story.append(_para("No requirements to list.", st["tender"]))
    for t in REQUIREMENT_TYPES:
        of_type = [r for r in listed if r.requirement_type == t]
        if of_type:
            story.append(_para(f"{t.capitalize()} ({len(of_type)})", st["section"]))
            story.append(_table(of_type, st))
    if unreviewed:
        story.append(_para(f"Not yet reviewed ({len(unreviewed)})", st["section"]))
        story.append(_table(unreviewed, st))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=pdf_plain(f"Requirements checklist: {data.tender_title}"),
        author=pdf_plain(data.generated_by_name),
        invariant=1,
    )
    decor = _draft_decor if label == "draft" else _no_decor
    doc.build(story, onFirstPage=decor, onLaterPages=decor, canvasmaker=_numbered_canvas(data))
    return buf.getvalue()
