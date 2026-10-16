"""Version detail and the sheet row window."""

from __future__ import annotations

import pytest

from tests.conftest import make_tender, make_xlsx, register, upload
from tests.review_helpers import boq_version
from tests.test_extraction_pipeline import API, drain


def _sheet_version():
    admin = register("sheet@example.com")
    tid = make_tender(admin)
    rows = [["Item", "Description", "Unit", "Quantity"]] + [
        [f"{n}", f"Line {n}", "m", f"{n}"] for n in range(1, 31)
    ]
    body = upload(admin, tid, make_xlsx(rows), "big.xlsx", kind="boq").json()
    drain()
    return admin, body["version"]["id"]


def test_version_detail_matches_the_list_entry() -> None:
    admin, tid, vid = boq_version()
    r = admin.client.get(f"{API}/document-versions/{vid}")
    assert r.status_code == 200
    doc = admin.client.get(f"{API}/tenders/{tid}/documents").json()[0]
    assert r.json() == doc["current_version"]
    assert r.json()["job_id"] and r.json()["processing_status"].startswith("ready")


def test_row_window_slices_a_sheet() -> None:
    admin, vid = _sheet_version()
    url = f"{API}/document-versions/{vid}/pages/1"
    whole = admin.client.get(url).json()["tables"][0]
    assert whole["first_row"] == 1 and len(whole["rows"]) == 31
    part = admin.client.get(url, params={"row_from": 10, "row_to": 12}).json()["tables"][0]
    assert part["first_row"] == 10 and part["rows"] == whole["rows"][9:12]
    only_from = admin.client.get(url, params={"row_from": 30}).json()["tables"][0]
    assert only_from["first_row"] == 30 and len(only_from["rows"]) == 2


def test_a_window_past_the_end_is_empty_not_an_error() -> None:
    admin, vid = _sheet_version()
    url = f"{API}/document-versions/{vid}/pages/1"
    table = admin.client.get(url, params={"row_from": 500, "row_to": 510}).json()["tables"][0]
    assert table["rows"] == []


@pytest.mark.parametrize(
    "params", [{"row_from": 10, "row_to": 5}, {"row_from": 1, "row_to": 6000}, {"row_from": 0}]
)
def test_bad_windows_are_422(params) -> None:
    admin, vid = _sheet_version()
    assert (
        admin.client.get(f"{API}/document-versions/{vid}/pages/1", params=params).status_code == 422
    )


def test_the_window_leaves_non_sheet_tables_alone() -> None:
    from app.modules.knowledge.service import window_tables

    table = {"kind": "table", "rows": [["a"], ["b"]]}
    assert window_tables([table], 2, 2) == [table]
