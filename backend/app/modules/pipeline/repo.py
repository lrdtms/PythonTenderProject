"""Extraction run data access (tenant-scoped)."""

from __future__ import annotations

from uuid import UUID

from app.db.scoped import ScopedRepository

from .models import ExtractionRun


class RunRepo(ScopedRepository[ExtractionRun]):
    model = ExtractionRun

    def for_job(self, job_id: UUID, kind: str) -> ExtractionRun | None:
        rows = self.find(ExtractionRun.job_id == job_id, ExtractionRun.kind == kind, limit=1)
        return rows[0] if rows else None

    def locked_for_job(self, job_id: UUID, *, skip_locked: bool) -> list[ExtractionRun]:
        """The job's runs, row-locked. With `skip_locked`, rows another transaction holds are
        left out instead of waited for."""
        stmt = self._select().where(ExtractionRun.job_id == job_id)
        stmt = stmt.with_for_update(skip_locked=skip_locked)
        return list(self.session.scalars(stmt).all())

    def current_for_version(self, version_id: UUID) -> dict[str, ExtractionRun]:
        """The latest run per kind (later rows overwrite earlier ones)."""
        rows = self.find(
            ExtractionRun.document_version_id == version_id, order_by=ExtractionRun.created_at
        )
        return {r.kind: r for r in rows}

    def lock_version(self, version_id: UUID, kind: str) -> None:
        """Serialise re-runs and (in Slice 4) review updates for one version and kind."""
        self.session.execute(
            self._select()
            .where(ExtractionRun.document_version_id == version_id, ExtractionRun.kind == kind)
            .order_by(ExtractionRun.id)  # one lock order for every locker
            .with_for_update()
        ).all()
