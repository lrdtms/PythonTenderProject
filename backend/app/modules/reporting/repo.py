"""Export data access (tenant-scoped)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.db.scoped import ScopedRepository

from .models import Export


class ExportRepo(ScopedRepository[Export]):
    model = Export

    def count_since(self, since: datetime) -> int:
        return (
            self.session.scalar(
                select(func.count(Export.id)).where(
                    Export.organisation_id == self.ctx.organisation_id, Export.generated_at >= since
                )
            )
            or 0
        )
