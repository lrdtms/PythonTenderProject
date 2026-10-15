"""The request transaction commits before the response is sent (review item I-1)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.modules.tenders.models import Tender
from tests.conftest import CSRF


def _titles() -> list[str]:
    with session_scope() as s:
        return list(s.scalars(select(Tender.title)).all())


def test_a_failing_commit_is_a_500_and_nothing_is_saved(admin, monkeypatch) -> None:
    from app.api.main import app

    client = TestClient(app, headers=CSRF, raise_server_exceptions=False)
    client.cookies.update(admin.client.cookies)

    def broken_commit(self: Session) -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(Session, "commit", broken_commit)
    r = client.post("/api/v1/tenders", json={"title": "Never saved"})
    monkeypatch.undo()

    assert r.status_code == 500, r.text
    assert r.json()["error"]["code"] == "internal_error"
    assert _titles() == []


def test_a_normal_request_still_persists(admin) -> None:
    assert admin.client.post("/api/v1/tenders", json={"title": "Saved"}).status_code == 201
    assert _titles() == ["Saved"]
