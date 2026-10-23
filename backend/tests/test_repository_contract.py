"""Repository contract: every ScopedRepository subclass isolates organisations on its own.

The F1 sweep goes through the API, where an ownership check in front of a repository (for
example the version lookup before PageRepo.one) can hide a missing organisation filter inside
the repository. This test calls every repository directly with another organisation's ids.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

import app.modules
from app.db.scoped import ScopedRepository
from app.db.session import session_scope
from app.kernel import NotFound, OrgContext, Role
from app.modules.checklist import public as checklist
from app.modules.estimates.models import Estimate, EstimateLine
from app.modules.estimates.repo import EstimateRepo
from app.modules.estimating import public as estimating
from app.modules.estimating.models import BoqItem
from app.modules.identity.models import Membership
from app.modules.pipeline.models import ExtractionRun
from app.modules.suppliers import public as suppliers
from app.modules.suppliers.models import MatchSuggestion, QuotationItem
from app.modules.suppliers.models import Supplier as suppliers_model
from app.worker import handlers
from app.worker.runner import process_one
from tests.conftest import Actor, add_member, make_pdf, make_tender, register, upload


def _import_every_repo_module() -> list[str]:
    names = []
    for info in pkgutil.iter_modules(app.modules.__path__):
        name = f"{app.modules.__name__}.{info.name}.repo"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
            continue
        names.append(name)
    return names


def _subclasses(cls: type) -> Iterator[type]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


REPO_MODULES = _import_every_repo_module()
REPOSITORIES = {cls.__name__: cls for cls in _subclasses(ScopedRepository)}
EXERCISED = {
    "TenderRepo",
    "DocumentRepo",
    "VersionRepo",
    "PageRepo",
    "ChunkRepo",
    "JobRepo",
    "MembershipRepo",
    "RunRepo",
    "BoqRepo",
    "RequirementRepo",
    "SupplierRepo",
    "QuotationRepo",
    "QuotationItemRepo",
    "MatchRepo",
    "EstimateRepo",
}


def test_every_scoped_repository_is_exercised() -> None:
    assert REPO_MODULES, "no repo.py modules were found"
    defined_in_repo_modules = {
        cls.__name__ for cls in REPOSITORIES.values() if cls.__module__ in REPO_MODULES
    }
    assert defined_in_repo_modules == set(REPOSITORIES), "a ScopedRepository outside repo.py"
    missing = set(REPOSITORIES) - EXERCISED
    assert not missing, f"add {missing} to the repository contract test"
    assert not EXERCISED - set(REPOSITORIES), "EXERCISED names a repository that is gone"


def _seed(email: str, org: str, secret: str) -> Actor:
    """An organisation with a tender, a document version, its pages and chunks (via the
    worker), a finished job and two memberships."""
    actor = register(email, org=org)
    tender = make_tender(actor, f"{secret} tender")
    r = upload(actor, tender, make_pdf([f"{secret} clause on page one"]), f"{secret}.pdf")
    assert r.status_code == 201, r.text
    assert process_one(handlers.HANDLERS) is True
    # Drain the extraction jobs ingest queued, or the next seed's process_one would run them and
    # their re-run would replace the rows seeded below.
    while process_one(handlers.HANDLERS):
        pass
    body = r.json()
    ctx = _ctx(actor)
    with session_scope() as s:
        for kind in ("boq", "requirements", "quotation"):
            run = ExtractionRun(
                organisation_id=ctx.organisation_id,
                document_version_id=UUID(body["version"]["id"]),
                job_id=UUID(body["job_id"]),
                kind=kind,
            )
            s.add(run)
            s.flush()
            if kind == "boq":
                estimating.replace_unreviewed(
                    s, ctx, run.document_version_id, run.id,
                    [{"item_no": "1", "description": f"{secret} cable"}],
                )  # fmt: skip
            elif kind == "quotation":
                suppliers.store_quotation(
                    s, ctx, run.document_version_id, run.id,
                    {"supplier_name": f"{secret} supplies"},
                    [{"description": f"{secret} conduit", "source_order": 0}], "file",
                )  # fmt: skip
                s.flush()
                s.add(MatchSuggestion(
                    organisation_id=ctx.organisation_id,
                    boq_item_id=s.scalars(select(BoqItem.id).where(
                        BoqItem.organisation_id == ctx.organisation_id)).first(),
                    quotation_item_id=s.scalars(select(QuotationItem.id).where(
                        QuotationItem.organisation_id == ctx.organisation_id)).first(),
                    supplier_id=s.scalars(select(suppliers_model.id).where(
                        suppliers_model.organisation_id == ctx.organisation_id)).first(),
                    score=0.9, classification="clear", evidence={},
                ))  # fmt: skip
            else:
                checklist.replace_unreviewed(
                    s, ctx, run.document_version_id, run.id,
                    [{"description": f"{secret} rule", "requirement_type": "other",
                      "mandatory_status": "mandatory", "evidence_quote": f"{secret} clause"}],
                )  # fmt: skip
        _seed_estimate(s, ctx, UUID(tender), secret)
    add_member(actor, f"member-{email}", "estimator")
    return actor


def _seed_estimate(s, ctx: OrgContext, tender_id: UUID, secret: str) -> None:
    """Saved pricing defaults and a draft estimate with one line over the seeded BoQ item."""
    repo = EstimateRepo(s, ctx)
    repo.save_defaults("ZAR", Decimal("15.00"), "cost", Decimal("10.00"), ctx.user_id)
    estimate = repo.add(
        Estimate(
            organisation_id=ctx.organisation_id,
            tender_id=tender_id,
            version=1,
            currency="ZAR",
            vat_rate=Decimal("15.00"),
            markup_basis="cost",
            markup_percent=Decimal("10.00"),
            created_by=ctx.user_id,
        )
    )
    boq_item_id = s.scalars(
        select(BoqItem.id).where(BoqItem.organisation_id == ctx.organisation_id)
    ).first()
    repo.add_lines([
        EstimateLine(
            estimate_id=estimate.id,
            boq_item_id=boq_item_id,
            position=0,
            description=f"{secret} cable",
            price_source="manual",
            updated_by=ctx.user_id,
        )
    ])  # fmt: skip


def _ctx(actor: Actor) -> OrgContext:
    me = actor.me
    with session_scope() as s:
        membership_id = s.scalar(
            select(Membership.id).where(
                Membership.organisation_id == UUID(me["organisation_id"]),
                Membership.user_id == UUID(me["user_id"]),
            )
        )
    return OrgContext(UUID(me["user_id"]), UUID(me["organisation_id"]), Role.ADMIN, membership_id)


def test_repositories_never_return_another_organisations_rows() -> None:
    b = _seed("b@example.com", "Org B", "Bravo")
    c = _seed("c@example.com", "Org C", "Charlie")
    org_b, ctx_c = UUID(b.org_id), _ctx(c)

    with session_scope() as s:
        b_ids = {
            name: s.scalars(select(cls.model.id).where(cls.model.organisation_id == org_b)).all()
            for name, cls in REPOSITORIES.items()
        }
        empty = [name for name, ids in b_ids.items() if not ids]
        assert not empty, f"the seed has no organisation B rows for {empty}"

        # Generic contract: find() and get() on every repository.
        for name, cls in REPOSITORIES.items():
            repo = cls(s, ctx_c)
            rows = repo.find()
            assert rows, f"{name}.find() returned nothing for organisation C"
            assert all(r.organisation_id == ctx_c.organisation_id for r in rows), name
            assert not {r.id for r in rows} & set(b_ids[name]), f"{name}.find() leaked B rows"
            for b_id in b_ids[name]:
                with pytest.raises(NotFound):
                    repo.get(b_id)

        # Query methods that take ids: organisation B's ids give nothing back.
        repos = {name: cls(s, ctx_c) for name, cls in REPOSITORIES.items()}
        tender_b, document_b = b_ids["TenderRepo"][0], b_ids["DocumentRepo"][0]
        version_b = b_ids["VersionRepo"][0]
        job_subject_b = s.scalar(
            select(REPOSITORIES["JobRepo"].model.subject_id).where(
                REPOSITORIES["JobRepo"].model.id == b_ids["JobRepo"][0]
            )
        )
        b_tenders = set(b_ids["TenderRepo"])
        assert not {t.id for t in repos["TenderRepo"].list_for_org(True)} & b_tenders
        assert repos["DocumentRepo"].for_tender(tender_b) == []
        assert repos["VersionRepo"].for_document(document_b) == []
        assert repos["VersionRepo"].current_for_documents([document_b]) == {}
        assert repos["VersionRepo"].next_number(document_b) == 1
        assert repos["PageRepo"].for_version(version_b) == []
        assert repos["PageRepo"].one(version_b, 1) is None
        assert repos["ChunkRepo"].search(tender_b, "Bravo", 50) == []
        assert repos["BoqRepo"].for_version(version_b, 50, 0) == []
        with pytest.raises(NotFound):
            repos["BoqRepo"].version_id_of(b_ids["BoqRepo"][0])
        assert repos["BoqRepo"].fresh(b_ids["BoqRepo"][0]) is None
        assert repos["RequirementRepo"].for_version(version_b, 50, 0) == []
        assert repos["RequirementRepo"].for_versions([version_b], None, None, 50, 0) == []
        with pytest.raises(NotFound):
            repos["RequirementRepo"].version_id_of(b_ids["RequirementRepo"][0])
        assert repos["RequirementRepo"].fresh(b_ids["RequirementRepo"][0]) is None
        assert repos["SupplierRepo"].by_key("bravo supplies") is None
        supplier_b = b_ids["SupplierRepo"][0]
        listed = repos["SupplierRepo"].list_with_counts()
        assert listed and not {x.id for x, _ in listed} & set(b_ids["SupplierRepo"])
        assert repos["SupplierRepo"].quotation_count(supplier_b) == 0
        assert repos["SupplierRepo"].version_ids(supplier_b) == set()
        assert repos["SupplierRepo"].confirmed_boq_ids(supplier_b) == set()
        mine = repos["SupplierRepo"].find()[0]
        theirs = s.get(suppliers_model, supplier_b)
        old_name, old_key = mine.name, mine.name_key
        repos["SupplierRepo"].rename(mine, "Renamed", theirs.name_key)  # B's key is no clash for C
        repos["SupplierRepo"].rename(mine, old_name, old_key)
        created, was_created = repos["SupplierRepo"].get_or_create("X", theirs.name_key)
        assert was_created and created.organisation_id == ctx_c.organisation_id
        assert created.id != supplier_b
        assert repos["QuotationRepo"].for_version(version_b) is None
        quotation_b = b_ids["QuotationRepo"][0]
        assert repos["QuotationItemRepo"].for_quotation(quotation_b) == []
        item_b = b_ids["QuotationItemRepo"][0]
        assert repos["QuotationRepo"].list_for_versions([version_b]) == []
        assert repos["QuotationRepo"].list_for_versions([]) == []
        assert repos["QuotationRepo"].confirmed_boq_ids(quotation_b) == set()
        assert repos["QuotationItemRepo"].for_version(version_b, 50, 0) == []
        with pytest.raises(NotFound):
            repos["QuotationItemRepo"].version_id_of(item_b)
        assert repos["QuotationItemRepo"].fresh(item_b) is None
        mine_c = repos["QuotationRepo"].find()[0]
        name_c, count_c = repos["QuotationRepo"].with_supplier_name(mine_c)
        assert name_c == "Charlie supplies" and count_c == 1
        assert [n for _, n, _ in repos["QuotationRepo"].list_for_versions(
            [mine_c.document_version_id])] == ["Charlie supplies"]  # fmt: skip
        # a scoped write aimed at B's quotation moves none of B's matches
        repos["QuotationRepo"].move_matches(quotation_b, mine_c.supplier_id)
        assert repos["QuotationItemRepo"].reviewed_or_pinned(quotation_b) == []
        repos["QuotationItemRepo"].delete_replaceable(quotation_b, [])
        match_b = b_ids["MatchRepo"][0]
        boq_b, quote_b = b_ids["BoqRepo"], b_ids["QuotationItemRepo"]
        assert repos["MatchRepo"].for_items(boq_b, quote_b) == []
        assert repos["MatchRepo"].decided_boq_item_ids() == set()
        assert repos["MatchRepo"].delete_suggested([match_b]) == 0
        assert repos["QuotationItemRepo"].for_versions([version_b]) == []
        assert repos["BoqRepo"].protected(version_b, boq_b) == []
        repos["MatchRepo"].lock_tender(UUID(int=1))
        estimate_b = b_ids["EstimateRepo"][0]
        est_tender_b = s.get(Estimate, estimate_b).tender_id
        line_b = s.scalars(
            select(EstimateLine.id).where(EstimateLine.organisation_id == org_b)
        ).all()
        assert line_b
        with pytest.raises(NotFound):
            repos["EstimateRepo"].get_for_update(estimate_b)
        assert repos["EstimateRepo"].latest_version(est_tender_b) == 0
        assert repos["EstimateRepo"].draft_for(est_tender_b) is None
        assert repos["EstimateRepo"].for_tender(est_tender_b) == []
        assert repos["EstimateRepo"].lines(estimate_b, 50, 0) == []
        assert repos["EstimateRepo"].lines(estimate_b, 50, 0, "manual") == []
        assert repos["EstimateRepo"].all_lines(estimate_b) == []
        for line_id in line_b:
            for refresh in (False, True):
                with pytest.raises(NotFound):
                    repos["EstimateRepo"].line(line_id, refresh)
        defaults_c = repos["EstimateRepo"].defaults()
        assert defaults_c is not None and defaults_c.organisation_id == ctx_c.organisation_id
        assert repos["RunRepo"].current_for_version(version_b) == {}
        assert repos["RunRepo"].for_job(job_subject_b, "boq") is None
        assert repos["JobRepo"].latest_for_subject(job_subject_b) is None
        members = repos["MembershipRepo"].list_with_users()
        assert {m.organisation_id for m, _ in members} == {ctx_c.organisation_id}
        assert repos["MembershipRepo"].count_active_admins() == 1
        user_b = s.scalar(select(Membership.user_id).where(Membership.organisation_id == org_b))
        assert repos["MembershipRepo"].names_for({user_b}) == {}

        # Scoped writes aimed at B's ids change nothing of B's.
        repos["PageRepo"].replace_for_version(version_b, [])
        repos["ChunkRepo"].replace_for_version(version_b, [])
        repos["VersionRepo"].clear_current(document_b)

    with session_scope() as s:
        for name in ("PageRepo", "ChunkRepo", "QuotationItemRepo", "MatchRepo"):
            model = REPOSITORIES[name].model
            assert s.scalars(select(model.id).where(model.organisation_id == org_b)).all()
        version = REPOSITORIES["VersionRepo"].model
        assert s.scalar(select(version.is_current).where(version.id == version_b)) is True
        match_supplier = s.scalar(
            select(MatchSuggestion.supplier_id).where(MatchSuggestion.organisation_id == org_b)
        )
        assert match_supplier == s.scalar(
            select(suppliers_model.id).where(suppliers_model.organisation_id == org_b)
        )  # the move aimed at B's quotation changed nothing
