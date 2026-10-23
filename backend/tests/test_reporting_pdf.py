"""PDF checklist renderer: content, DRAFT label, text safety, pagination, determinism, speed."""

import io
import re
import time
from datetime import UTC, datetime
from uuid import UUID

import pdfplumber
import pytest

from app.kernel.vocab import REQUIREMENT_TYPES
from app.modules.reporting.pdf import checklist_label, render_checklist_pdf
from app.modules.reporting.schemas import ChecklistExportInput, ChecklistRow

EXPORT_ID = UUID("12345678-1234-5678-1234-567812345678")
WHEN = datetime(2026, 10, 23, 8, 30, tzinfo=UTC)


def row(**kw: object) -> ChecklistRow:
    base: dict[str, object] = {
        "requirement_type": "technical",
        "mandatory_status": "mandatory",
        "description": "Supply 10 kVA UPS units",
        "review_status": "confirmed",
        "document_title": "Tender Spec",
        "page_number": 4,
        "evidence_verified": True,
    }
    base.update(kw)
    return ChecklistRow(**base)  # type: ignore[arg-type]


def data(rows: tuple[ChecklistRow, ...] | None = None, **kw: object) -> ChecklistExportInput:
    base: dict[str, object] = {
        "tender_title": "Greenvale Hall Upgrade",
        "tender_reference": "GV/2026/17",
        "client_name": "Greenvale Municipality",
        "closing_at": datetime(2026, 11, 30, 11, 0, tzinfo=UTC),
        "generated_by_name": "Thandi Nkosi",
        "rows": rows if rows is not None else (row(),),
        "rejected_count": 0,
        "generated_at": WHEN,
        "export_id": EXPORT_ID,
    }
    base.update(kw)
    return ChecklistExportInput(**base)  # type: ignore[arg-type]


def pages(pdf: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [p.extract_text() or "" for p in doc.pages]


def flat(pdf: bytes) -> str:
    return re.sub(r"\s+", " ", " ".join(pages(pdf)))


def test_opens_and_page_one_content() -> None:
    d = data(
        (
            row(),
            row(mandatory_status="conditional", requirement_type="pricing"),
            row(mandatory_status="informational", review_status="corrected"),
        ),
        rejected_count=2,
    )
    pdf = render_checklist_pdf(d)
    assert pdf.startswith(b"%PDF")
    first = pages(pdf)[0]
    for needle in (
        "Greenvale Hall Upgrade",
        "GV/2026/17",
        "Greenvale Municipality",
        "Requirements checklist",
        "2026-10-23 08:30 UTC",
        str(EXPORT_ID),
        "Thandi Nkosi",
        "2 rejected, not listed",
    ):
        assert needle in first
    assert checklist_label(d) == "approved"
    assert "Type MANDATORY Conditional Information only Other Total" in first
    assert "Technical 1 0 1 0 2" in first
    assert "0 not yet reviewed" in first


def test_type_order_words_and_source_cell() -> None:
    rows = (
        row(requirement_type="other", mandatory_status="informational"),
        row(requirement_type="deadline", mandatory_status="conditional", review_status="corrected"),
        row(requirement_type="technical", page_number=None),
        row(requirement_type="pricing", evidence_verified=False),
    )
    text = flat(render_checklist_pdf(data(rows)))
    positions = [text.find(f"{t.capitalize()} (") for t in REQUIREMENT_TYPES]
    present = [p for p in positions if p >= 0]
    assert len(present) == 4 and present == sorted(present)
    for absent in ("meeting", "eligibility", "document"):
        assert f"{absent.capitalize()} (" not in text
    for word in ("MANDATORY", "Conditional", "Information only", "Confirmed", "Corrected"):
        assert word in text
    assert "Tender Spec, page 4" in text
    assert "Tender Spec, page not recorded" in text
    assert "(source not verified)" in text


def test_unknown_requirement_type_is_listed_under_other_not_dropped() -> None:
    d = data(
        (row(requirement_type="weird", description="Strange row"), row(mandatory_status="odd"))
    )
    text = flat(render_checklist_pdf(d))
    assert "Strange row" in text
    assert "Other (1)" in text
    # the unknown mandatory status is counted in the Other column, so the row sums to the total
    assert "Technical 0 0 0 1 1" in text


def test_approved_has_no_draft_anywhere() -> None:
    pdf = render_checklist_pdf(data((row(), row(review_status="corrected"))))
    assert all("DRAFT" not in p for p in pages(pdf))
    assert "Not yet reviewed" not in flat(pdf)


def test_unreviewed_row_forces_draft_and_own_section() -> None:
    d = data((row(), row(description="Unique unreviewed thing", review_status="unreviewed")))
    assert checklist_label(d) == "draft"
    pdf = render_checklist_pdf(d)
    ps = pages(pdf)
    assert all("DRAFT" in p for p in ps)
    text = flat(pdf)
    head = text.rindex("Not yet reviewed")
    assert "Unique unreviewed thing" in text[head:]
    assert "Unique unreviewed thing" not in text[:head]


def test_empty_is_draft() -> None:
    d = data(())
    assert checklist_label(d) == "draft"
    pdf = render_checklist_pdf(d)
    assert "No requirements to list" in flat(pdf)
    assert "DRAFT" in pages(pdf)[0]


def test_markup_renders_literally() -> None:
    img = '<img src="file:///etc/passwd"/>'
    d = data(
        (
            row(description=f"see {img} and <font color=red>x</font> &amp; y"),
            row(description="range ≤ 5 Ω"),
        ),
        tender_title="Smith & Sons",
    )
    pdf = render_checklist_pdf(d)
    text = flat(pdf)
    assert img in text
    # the table cell wraps mid-tag and the Review column interleaves, so check the pieces
    assert "<font" in text and "color=red>x</font> &amp; y" in text
    assert "? 5 ?" in text
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert all(p.images == [] for p in doc.pages)
        page = doc.pages[0]
        footer = page.within_bbox((0, page.height - 40, page.width, page.height)).extract_text()
        assert "Smith & Sons" in footer and "&amp;" not in footer
        assert "Smith & Sons" in (doc.metadata.get("Title") or "")


def test_long_text_truncates_and_lays_out() -> None:
    d = data((row(description="word " * 1000, document_title="D" * 300),))
    text = flat(render_checklist_pdf(d))
    assert "(truncated, see source)" in text
    unbroken = data((row(description="x" * 5000, document_title="y" * 300),))
    assert "(truncated, see source)" in flat(render_checklist_pdf(unbroken))


def test_footer_page_numbers_and_repeated_header() -> None:
    rows = tuple(row(description=f"Requirement number {i}") for i in range(300))
    pdf = render_checklist_pdf(data(rows))
    ps = pages(pdf)
    n = len(ps)
    assert n > 1
    for i, p in enumerate(ps, 1):
        assert f"Page {i} of {n}" in p
        assert str(EXPORT_ID) in p
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for page in doc.pages[1:]:
            top = page.within_bbox((0, 55, page.width, 95)).extract_text()
            assert "Mandatory Requirement Review Source" in top


def test_deterministic() -> None:
    d = data((row(), row(review_status="unreviewed")))
    a, b = render_checklist_pdf(d), render_checklist_pdf(d)
    assert pages(a) == pages(b)
    assert a == b


def test_perf_1000_rows() -> None:
    rows = tuple(
        row(requirement_type=REQUIREMENT_TYPES[i % 7], description=f"Requirement {i} " * 8)
        for i in range(1000)
    )
    start = time.perf_counter()
    pdf = render_checklist_pdf(data(rows))
    assert time.perf_counter() - start < 8
    assert pdf.startswith(b"%PDF")


def test_rejected_row_raises() -> None:
    d = data((row(), row(review_status="rejected")))
    with pytest.raises(ValueError, match="unsupported review status"):
        render_checklist_pdf(d)
    with pytest.raises(ValueError, match="unsupported review status"):
        checklist_label(d)


def test_long_footer_title_stays_clear_of_page_number() -> None:
    pdf = render_checklist_pdf(data(tender_title="W" * 70))
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        page = doc.pages[0]
        words_ = page.within_bbox((0, page.height - 40, page.width, page.height)).extract_words()
        title = next(w for w in words_ if w["text"].startswith("W"))
        number = next(w for w in words_ if w["text"] == "Page")
        assert title["x1"] < number["x0"]
