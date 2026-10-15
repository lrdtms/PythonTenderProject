"""Test setup: a throwaway Postgres database migrated from scratch with Alembic.

Needs a running Postgres with the pgvector extension (docker compose up -d db). Point the tests
at it with TEST_DATABASE_URL, or with DB_HOST_PORT when it is not on 5432. The database
`inteltps_test` is dropped and recreated at the start of every run.
"""

from __future__ import annotations

import os
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
