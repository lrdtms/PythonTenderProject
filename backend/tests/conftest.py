"""Test setup: a throwaway Postgres database migrated from scratch with Alembic.

Needs a running Postgres with the pgvector extension (docker compose up -d db). Point the tests
at it with TEST_DATABASE_URL, or with DB_HOST_PORT when it is not on 5432. The database
`inteltps_test` is dropped and recreated at the start of every run.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_port = os.environ.get("DB_HOST_PORT", "5432")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", f"postgresql+psycopg://intel:intel@127.0.0.1:{_port}/inteltps_test"
)
# Must be set before the application reads its settings.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "development"
os.environ["STORAGE_PATH"] = tempfile.mkdtemp(prefix="inteltps-test-files-")

BACKEND_DIR = Path(__file__).resolve().parents[1]
CSRF = {"X-Requested-With": "IntelTPS"}
STRONG_PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")
    yield

    from app.db.session import get_engine

    get_engine().dispose()


@pytest.fixture(autouse=True)
def clean_state() -> Iterator[None]:
    from app.api.ratelimit import limiter

    limiter.reset()
    yield
    from app.db.session import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        tables = (
            conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        if tables:
            conn.execute(
                text(
                    "TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"
                )
            )


def make_client() -> TestClient:
    from app.api.main import app

    return TestClient(app, headers=CSRF)


@pytest.fixture
def client() -> TestClient:
    return make_client()


class Actor:
    """A signed-in user with their own cookie jar."""

    def __init__(self, client: TestClient, me: dict):
        self.client = client
        self.me = me

    @property
    def org_id(self) -> str:
        return self.me["organisation_id"]


def register(
    email: str = "owner@example.com", org: str = "Acme Electrical", name: str = "Owner"
) -> Actor:
    c = make_client()
    r = c.post(
        "/api/v1/auth/register",
        json={"organisation_name": org, "name": name, "email": email, "password": STRONG_PASSWORD},
    )
    assert r.status_code == 201, r.text
    return Actor(c, r.json())


def add_member(admin: Actor, email: str, role: str, name: str = "Member") -> Actor:
    r = admin.client.post(
        "/api/v1/members",
        json={"name": name, "email": email, "role": role, "password": STRONG_PASSWORD},
    )
    assert r.status_code == 201, r.text
    c = make_client()
    login = c.post("/api/v1/auth/login", json={"email": email, "password": STRONG_PASSWORD})
    assert login.status_code == 200, login.text
    return Actor(c, login.json())


@pytest.fixture
def admin() -> Actor:
    return register()


# --- file builders (self-contained: PyMuPDF, openpyxl and python-docx are runtime dependencies) -----


def make_pdf(pages: list[str]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 790), text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def make_scanned_pdf(texts: list[str]) -> bytes:
    """A PDF whose pages are images only (no text layer), like a scan."""
    import pymupdf

    source = pymupdf.open(stream=make_pdf(texts), filetype="pdf")
    out = pymupdf.open()
    for page in source:
        png = page.get_pixmap(dpi=100).tobytes("png")
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=png)
    data = out.tobytes()
    out.close()
    source.close()
    return data


def make_xlsx(rows: list[list[object]], sheet: str = "BoQ") -> bytes:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(
    actor: Actor,
    tender_id: str,
    data: bytes,
    name: str = "tender.pdf",
    kind: str = "tender_document",
):
    return actor.client.post(
        f"/api/v1/tenders/{tender_id}/documents",
        files={"file": (name, data, "application/octet-stream")},
        data={"kind": kind},
    )


def make_tender(actor: Actor, title: str = "Hall wiring") -> str:
    return actor.client.post("/api/v1/tenders", json={"title": title}).json()["id"]
