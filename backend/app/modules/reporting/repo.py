"""Export data access (tenant-scoped)."""

from __future__ import annotations

from app.db.scoped import ScopedRepository

from .models import Export


class ExportRepo(ScopedRepository[Export]):
    model = Export
