"""Architecture fitness functions F1 (cross-tenant sweep), F2 (raw SQL and boundaries),
F3 (schema tenancy), plus a check that migrations match the models."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from uuid import UUID

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import ForeignKeyConstraint, create_engine, select

from app.api.main import app as fastapi_app
from app.db.base import Base
from app.db.session import get_engine, session_scope

# Import every module's models so Base.metadata is complete (side effects only).
from app.modules.audit import models as _audit_models  # noqa: F401
from app.modules.documents import models as _documents_models  # noqa: F401
from app.modules.identity import models as _identity_models  # noqa: F401
from app.modules.jobs import models as _jobs_models  # noqa: F401
from app.modules.knowledge import models as _knowledge_models  # noqa: F401
from app.modules.reporting.models import Export
from app.modules.tenders import models as _tenders_models  # noqa: F401
from app.worker import handlers
from app.worker.runner import process_one
from tests.conftest import add_member, make_pdf, make_tender, register, upload
from tests.review_helpers import seed_review_rows, seed_supplier_rows

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
    ("POST", "/api/v1/document-versions/{version_id}/extract"): lambda: {
        "json": {"deep_scan": False}
    },
    ("PATCH", "/api/v1/boq-items/{boq_item_id}"): lambda: {"json": {"description": "hijacked"}},
    ("PATCH", "/api/v1/requirements/{requirement_id}"): lambda: {
        "json": {"description": "hijacked"}
    },
    ("PATCH", "/api/v1/quotations/{quotation_id}"): lambda: {"json": {"reference": "hijacked"}},
    ("PATCH", "/api/v1/quotation-items/{quotation_item_id}"): lambda: {
        "json": {"description": "hijacked"}
    },
    ("PATCH", "/api/v1/suppliers/{supplier_id}"): lambda: {"json": {"name": "hijacked"}},
    ("PATCH", "/api/v1/estimates/{estimate_id}"): lambda: {"json": {"vat_rate": "1"}},
    ("PUT", "/api/v1/estimate-lines/{line_id}"): lambda: {"json": {"exclude_reason": "hijacked"}},
    ("POST", "/api/v1/suppliers/{supplier_id}/merge"): lambda: {
        "json": {"into_id": "00000000-0000-0000-0000-000000000001"}
    },
    ("POST", "/api/v1/tenders/{tender_id}/exports"): lambda: {"json": {"kind": "checklist_pdf"}},
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
    assert process_one(handlers.HANDLERS) is True  # B now has page 1 and searchable chunks
    seeded = seed_review_rows(org_b, uploaded["version"]["id"], str(uploaded["job_id"]))
    member_b = add_member(org_b, "b2@example.com", "estimator")
    membership_b = next(
        m["membership_id"]
        for m in org_b.client.get("/api/v1/members").json()
        if m["email"] == "b2@example.com"
    )
    assert (
        org_b.client.put(
            "/api/v1/pricing-defaults",
            json={
                "currency": "ZAR",
                "vat_rate": "15",
                "markup_basis": "cost",
                "default_markup_percent": "10",
            },
        ).status_code
        == 200
    )
    estimate_b = org_b.client.post(f"/api/v1/tenders/{tender_b}/estimates")
    assert estimate_b.status_code == 201, estimate_b.text
    line_b = org_b.client.get(f"/api/v1/estimates/{estimate_b.json()['id']}/lines").json()
    export_b = org_b.client.post(
        f"/api/v1/tenders/{tender_b}/exports", json={"kind": "checklist_pdf"}
    )
    assert export_b.status_code == 201, export_b.text
    known = {
        "estimate_id": estimate_b.json()["id"],
        "export_id": export_b.json()["id"],
        "line_id": line_b[0]["id"],
        "tender_id": tender_b,
        "document_id": uploaded["document"]["id"],
        "version_id": uploaded["version"]["id"],
        "job_id": str(uploaded["job_id"]),
        "membership_id": membership_b,
        "page_number": 1,
        **seeded,
        **seed_supplier_rows(org_b),
    }
    forbidden = (
        "B-only secret",
        "b2@example.com",
        "b-secret.pdf",
        known["version_id"],
        "seeded-b-line",
        "seeded-b-rule",
        "seeded-b-quote-line",
        "Seeded B Supplies",
        export_b.json()["file_name"],
    )

    routes = _routes_with_params()
    swept = 0
    failures: list[str] = []
    for method, path, params in routes:
        missing = params - known.keys()
        assert not missing, f"{method} {path}: add {missing} to the F1 id registry"
        url = path.format(**{k: known[k] for k in params})
        kwargs = {**SEARCH_PARAMS, **REQUESTS}.get((method, path), dict)()
        r = org_a.client.request(method, url, **kwargs)
        if r.status_code != 404:
            failures.append(f"{method} {path} returned {r.status_code}: {r.text[:120]!r}")
        elif any(f in r.text for f in forbidden):
            failures.append(f"{method} {path} leaked data")
        swept += 1
    assert not failures, f"cross-tenant access not refused: {failures}"
    schema_count = sum(
        len(ops) for path, ops in fastapi_app.openapi()["paths"].items() if "{" in path
    )
    assert swept == schema_count >= 30, f"swept {swept} of {schema_count} routes with an id"
    paths = {p for _, p, _ in routes}
    for needle in (
        "documents",
        "document-versions",
        "pages/{page_number}",
        "jobs",
        "extract",
        "extraction",
        "boq-items",
        "requirements",
        "suppliers",
        "quotations",
        "quotation-items",
        "match-suggestions",
        "estimates",
        "estimate-lines",
        "exports",
    ):
        assert any(needle in p for p in paths), f"no {needle} route was swept"

    # Org B's data is intact after Org A's attempts.
    download_b = org_b.client.get(f"/api/v1/exports/{known['export_id']}/download")
    assert download_b.status_code == 200
    with session_scope() as s:
        row_b = s.scalar(select(Export).where(Export.id == UUID(known["export_id"])))
        assert hashlib.sha256(download_b.content).hexdigest() == row_b.sha256
        # Org A's attempts created no export for org B: B still has exactly the one it made.
        assert len(s.scalars(select(Export).where(Export.tender_id == UUID(tender_b))).all()) == 1
    assert (
        org_b.client.get(f"/api/v1/document-versions/{known['version_id']}/pages/1").status_code
        == 200
    )
    assert org_b.client.get(f"/api/v1/tenders/{tender_b}/search", params={"q": "secret"}).json()
    assert org_b.client.get(f"/api/v1/tenders/{tender_b}").json()["title"] == "B-only secret"
    assert len(org_b.client.get(f"/api/v1/documents/{known['document_id']}/versions").json()) == 1
    assert org_b.client.get(f"/api/v1/jobs/{known['job_id']}").json()["status"] == "succeeded"
    status_b = org_b.client.get(f"/api/v1/document-versions/{known['version_id']}/extraction")
    assert status_b.status_code == 200
    # Org A's extract attempt queued nothing: B's jobs are only the ones its own ingest queued.
    kinds = {k["kind"]: k for k in status_b.json()["kinds"]}
    assert all(k["job"]["status"] == "queued" for n, k in kinds.items() if n != "quotation")
    assert kinds["quotation"]["job"] is None  # a non-quotation upload has no quotation job
    assert member_b.client.get("/api/v1/me").status_code == 200
    b_lines = org_b.client.get(f"/api/v1/document-versions/{known['version_id']}/boq-items").json()
    assert [(x["description"], x["review_status"]) for x in b_lines] == [
        ("seeded-b-line", "unreviewed")
    ]
    b_rules = org_b.client.get(
        f"/api/v1/document-versions/{known['version_id']}/requirements"
    ).json()
    assert [(x["description"], x["review_status"]) for x in b_rules] == [
        ("seeded-b-rule", "unreviewed")
    ]


def test_f1_lists_never_mix_organisations() -> None:
    a = register("a@example.com", org="Org A")
    b = register("b@example.com", org="Org B")
    a.client.post("/api/v1/tenders", json={"title": "A tender"})
    b.client.post("/api/v1/tenders", json={"title": "B tender"})
    assert [t["title"] for t in a.client.get("/api/v1/tenders").json()] == ["A tender"]
    assert [t["title"] for t in b.client.get("/api/v1/tenders").json()] == ["B tender"]
    assert [m["email"] for m in a.client.get("/api/v1/members").json()] == ["a@example.com"]


# --- F2: raw SQL only in repositories; layering helpers ----------------------------------------

RAW_SQL = re.compile(
    r"\.(execute|scalar|scalars|query)\("  # executing anything
    r"|\bsession\.(get|delete|merge)\("  # identity-map lookups and deletes skip the org filter
    r"|\.get\(\s*[A-Z][a-z]\w*\s*,"  # <anything>.get(Model, id)
    r"|(?<![\w.])(?<!def )(select|insert|update|delete|pg_insert)\("  # builders, not methods
)
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


@pytest.mark.parametrize(
    "line",
    [
        "rows = session.execute(stmt)",
        "x = self.session.scalar(q)",
        "session.scalars(select(Tender)).all()",
        "db.query(Tender)",
        "stmt = select(Tender).where(Tender.id == tid)",
        "tender = session.get(Tender, tender_id)",
        "row = self.session.get(Document, doc_id)",
        "x = s.get(Tender, tid)",
        "session.delete(tender)",
        "session.merge(tender)",
        "stmt = delete(DocumentPage).where(x)",
        "stmt = update(Tender).values(title='x')",
        "stmt = insert(DocumentChunk)",
        "stmt = pg_insert(Job).values(x=1)",
    ],
)
def test_f2_rule_flags_database_access(line: str) -> None:
    assert RAW_SQL.search(line), line


@pytest.mark.parametrize(
    "line",
    [
        "    def delete(self, key: str) -> None:",
        "storage.delete(key)",
        "value = settings.get('x', 1)",
        "kind = STATUS.get(code, 400)",
        'status = changes.get("status")',
        "session.add(entity)",
        "session.flush()",
        "selected = selection(items)",
    ],
)
def test_f2_rule_ignores_ordinary_code(line: str) -> None:
    assert not RAW_SQL.search(line), line


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
            {
                "edit_tenders",
                "manage_members",
                "upload_documents",
                "review_data",
                "approve_estimate",
                "manage_pricing",
            },
        ),
        (
            "estimator",
            {"read", "edit_tenders", "upload_documents", "review_data"},
            {"manage_members", "approve_estimate", "manage_pricing"},
        ),
        (
            "project_manager",
            {"read", "edit_tenders", "manage_tasks", "approve_estimate"},
            {"upload_documents", "manage_members", "manage_pricing"},
        ),
        (
            "admin",
            {
                "read",
                "manage_members",
                "edit_tenders",
                "view_audit",
                "approve_estimate",
                "manage_pricing",
            },
            set(),
        ),
    ],
)
def test_role_permission_matrix(role: str, allowed: set[str], denied: set[str]) -> None:
    from uuid import uuid4

    from app.kernel import OrgContext, Permission, Role

    ctx = OrgContext(uuid4(), uuid4(), Role(role))
    assert all(ctx.can(Permission(p)) for p in allowed)
    assert not any(ctx.can(Permission(p)) for p in denied)


MODULE_IMPORT = re.compile(r"^\s*from app\.modules\.(\w+)(?:\.(\w+))? import (.+)$")


def test_f2_modules_are_imported_only_through_public() -> None:
    """Outside a module, `from app.modules.<m> import public` or `app.modules.<m>.public` only."""
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        rel = path.relative_to(APP_DIR)
        own = rel.parts[1] if rel.parts[0] == "modules" and len(rel.parts) > 2 else None
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            m = MODULE_IMPORT.match(line)
            if not m or m.group(1) == own:
                continue
            via_public = m.group(2) == "public" or (
                m.group(2) is None and m.group(3).split(" as ")[0].strip() == "public"
            )
            if not via_public:
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, "imports of module internals:\n" + "\n".join(offenders)


def test_every_compose_service_restarts_after_a_crash() -> None:
    """A worker killed by the kernel (or a crash) must come back on its own (I-1)."""
    import yaml

    compose = yaml.safe_load((APP_DIR.parents[1] / "docker-compose.yml").read_text("utf-8"))
    policies = {name: svc.get("restart") for name, svc in compose["services"].items()}
    assert policies and all(p == "unless-stopped" for p in policies.values()), policies


def test_routers_never_use_the_unscoped_worker_job_lookup() -> None:
    """jobs.get_for_worker is system level (no organisation filter): worker and tests only."""
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in (APP_DIR / "api").rglob("*.py")
        if "get_for_worker" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders
    from app.modules.jobs import public as jobs

    assert "never call it from a router" in (jobs.get_for_worker.__doc__ or "")
