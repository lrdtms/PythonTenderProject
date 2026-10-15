"""Architecture fitness functions F1 (cross-tenant sweep), F2 (raw SQL and boundaries),
F3 (schema tenancy), plus a check that migrations match the models."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import ForeignKeyConstraint, create_engine

from app.api.main import app as fastapi_app
from app.db.base import Base
from app.db.session import get_engine

# Import every module's models so Base.metadata is complete (side effects only).
from app.modules.audit import models as _audit_models  # noqa: F401
from app.modules.documents import models as _documents_models  # noqa: F401
from app.modules.identity import models as _identity_models  # noqa: F401
from app.modules.jobs import models as _jobs_models  # noqa: F401
from app.modules.knowledge import models as _knowledge_models  # noqa: F401
from app.modules.tenders import models as _tenders_models  # noqa: F401
from tests.conftest import add_member, make_pdf, make_tender, register, upload

APP_DIR = Path(__file__).resolve().parents[1] / "app"


# --- F1: cross-tenant route sweep --------------------------------------------------------------


# Per-route request keyword arguments, so a request gets past validation and reaches the
# ownership check. Upload routes need full multipart bodies.
def _pdf_upload() -> dict:
    return {
        "files": {"file": ("x.pdf", make_pdf(["probe"]), "application/pdf")},
        "data": {"kind": "tender_document"},
    }


REQUESTS = {
    ("PATCH", "/api/v1/tenders/{tender_id}"): lambda: {"json": {"title": "hijacked"}},
    ("PATCH", "/api/v1/members/{membership_id}/role"): lambda: {"json": {"role": "reviewer"}},
    ("POST", "/api/v1/members/{membership_id}/reset-password"): lambda: {
        "json": {"password": "a-long-enough-pass"}
    },
    ("POST", "/api/v1/tenders/{tender_id}/documents"): _pdf_upload,
    ("POST", "/api/v1/documents/{document_id}/versions"): _pdf_upload,
}
SEARCH_PARAMS = {("GET", "/api/v1/tenders/{tender_id}/search"): lambda: {"params": {"q": "secret"}}}


def _routes_with_params() -> list[tuple[str, str, set[str]]]:
    """Every (method, path template, path parameter names) from the OpenAPI schema. Included
    routers are lazy objects in current FastAPI, so app.routes is not reliable."""
    out = []
    for path, operations in fastapi_app.openapi()["paths"].items():
        params = set(re.findall(r"\{(\w+)\}", path))
        if params:
            out.extend((method.upper(), path, params) for method in operations)
    return out


def test_f1_every_route_with_an_id_refuses_another_organisations_data() -> None:
    org_a = register("a@example.com", org="Org A")
    org_b = register("b@example.com", org="Org B")
    tender_b = make_tender(org_b, "B-only secret")
    uploaded = upload(org_b, tender_b, make_pdf(["B-only secret clause"]), "b-secret.pdf").json()
    member_b = add_member(org_b, "b2@example.com", "estimator")
    membership_b = next(
        m["membership_id"]
        for m in org_b.client.get("/api/v1/members").json()
        if m["email"] == "b2@example.com"
    )
    known = {
        "tender_id": tender_b,
        "document_id": uploaded["document"]["id"],
        "version_id": uploaded["version"]["id"],
        "job_id": str(uploaded["job_id"]),
        "membership_id": membership_b,
        "page_number": 1,
    }
    forbidden = ("B-only secret", "b2@example.com", "b-secret.pdf", known["version_id"])

    routes = _routes_with_params()
    swept = 0
    for method, path, params in routes:
        missing = params - known.keys()
        assert not missing, f"{method} {path}: add {missing} to the F1 id registry"
        url = path.format(**{k: known[k] for k in params})
        kwargs = {**SEARCH_PARAMS, **REQUESTS}.get((method, path), dict)()
        r = org_a.client.request(method, url, **kwargs)
        assert r.status_code == 404, f"{method} {path} returned {r.status_code}: {r.text[:200]}"
        assert not any(f in r.text for f in forbidden), f"{method} {path} leaked data"
        swept += 1
    assert swept == len(routes) and swept >= 18, f"swept only {swept} method/path combinations"
    paths = {p for _, p, _ in routes}
    for needle in ("documents", "document-versions", "pages/{page_number}", "jobs"):
        assert any(needle in p for p in paths), f"no {needle} route was swept"

    # Org B's data is intact after Org A's attempts.
    assert org_b.client.get(f"/api/v1/tenders/{tender_b}").json()["title"] == "B-only secret"
    assert len(org_b.client.get(f"/api/v1/documents/{known['document_id']}/versions").json()) == 1
    assert org_b.client.get(f"/api/v1/jobs/{known['job_id']}").json()["status"] == "queued"
    assert member_b.client.get("/api/v1/me").status_code == 200


def test_f1_lists_never_mix_organisations() -> None:
    a = register("a@example.com", org="Org A")
    b = register("b@example.com", org="Org B")
    a.client.post("/api/v1/tenders", json={"title": "A tender"})
    b.client.post("/api/v1/tenders", json={"title": "B tender"})
    assert [t["title"] for t in a.client.get("/api/v1/tenders").json()] == ["A tender"]
    assert [t["title"] for t in b.client.get("/api/v1/tenders").json()] == ["B tender"]
    assert [m["email"] for m in a.client.get("/api/v1/members").json()] == ["a@example.com"]


# --- F2: raw SQL only in repositories; layering helpers ----------------------------------------

RAW_SQL = re.compile(r"\.(execute|scalar|scalars|query)\(")
ALLOWED_RAW_SQL = {"repo.py"}  # plus everything under app/db


def test_f2_no_raw_database_calls_outside_repositories() -> None:
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        rel = path.relative_to(APP_DIR)
        if rel.parts[0] == "db" or path.name in ALLOWED_RAW_SQL:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if RAW_SQL.search(line) and not line.lstrip().startswith("#"):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, "raw database calls outside repo.py / app/db:\n" + "\n".join(offenders)


def test_f2_api_layer_does_not_import_sqlalchemy_models() -> None:
    for path in (APP_DIR / "api").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert ".models import" not in text, f"{path.name} imports ORM models"


# --- F3: schema tenancy ------------------------------------------------------------------------

# Tables that are not organisation-owned: the tenant itself, global users, and sessions (which
# reference the organisation through a composite foreign key to memberships).
NOT_ORG_OWNED = {"organisations", "users", "sessions"}
NULLABLE_ORG = {"audit_events"}  # events outside an organisation (failed login)


def test_f3_every_org_owned_table_has_organisation_id() -> None:
    for name, table in Base.metadata.tables.items():
        if name in NOT_ORG_OWNED:
            continue
        assert "organisation_id" in table.c, f"{name} has no organisation_id"
        if name not in NULLABLE_ORG:
            assert not table.c.organisation_id.nullable, f"{name}.organisation_id must be NOT NULL"


def test_f3_foreign_keys_to_org_owned_tables_are_composite() -> None:
    org_owned = {n for n, t in Base.metadata.tables.items() if "organisation_id" in t.c}
    for name, table in Base.metadata.tables.items():
        for fk in (c for c in table.constraints if isinstance(c, ForeignKeyConstraint)):
            target = fk.referred_table.name
            if target in org_owned:
                cols = {c.name for c in fk.columns}
                assert cols & {"organisation_id", "active_organisation_id"}, (
                    f"{name} -> {target} must be a composite FK including the organisation"
                )


def test_f3_sessions_are_tied_to_memberships() -> None:
    fks = [
        c
        for c in Base.metadata.tables["sessions"].constraints
        if isinstance(c, ForeignKeyConstraint)
    ]
    assert any(
        {c.name for c in fk.columns} == {"active_organisation_id", "user_id"}
        and fk.referred_table.name == "memberships"
        for fk in fks
    )


# --- Migrations match the models ---------------------------------------------------------------


def test_migrations_match_the_models() -> None:
    engine = create_engine(get_engine().url)
    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
        )
    engine.dispose()
    assert diff == [], f"models changed without a migration: {diff[:3]}"


# --- Roles -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "allowed", "denied"),
    [
        (
            "reviewer",
            {"read"},
            {"edit_tenders", "manage_members", "upload_documents", "review_data"},
        ),
        (
            "estimator",
            {"read", "edit_tenders", "upload_documents", "review_data"},
            {"manage_members"},
        ),
        (
            "project_manager",
            {"read", "edit_tenders", "manage_tasks"},
            {"upload_documents", "manage_members"},
        ),
        ("admin", {"read", "manage_members", "edit_tenders", "view_audit"}, set()),
    ],
)
def test_role_permission_matrix(role: str, allowed: set[str], denied: set[str]) -> None:
    from uuid import uuid4

    from app.kernel import OrgContext, Permission, Role

    ctx = OrgContext(uuid4(), uuid4(), Role(role))
    assert all(ctx.can(Permission(p)) for p in allowed)
    assert not any(ctx.can(Permission(p)) for p in denied)
