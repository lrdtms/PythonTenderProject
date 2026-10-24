"""Document data access (tenant-scoped)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import desc, func

from app.db.scoped import ScopedRepository

from .models import Document, DocumentVersion


class DocumentRepo(ScopedRepository[Document]):
    model = Document

    def for_tender(self, tender_id: UUID) -> Sequence[Document]:
        return self.find(Document.tender_id == tender_id, order_by=desc(Document.created_at))


class VersionRepo(ScopedRepository[DocumentVersion]):
    model = DocumentVersion

    def for_document(self, document_id: UUID) -> Sequence[DocumentVersion]:
        return self.find(
            DocumentVersion.document_id == document_id,
            order_by=desc(DocumentVersion.version_number),
        )

    def current_for_documents(self, document_ids: Sequence[UUID]) -> dict[UUID, DocumentVersion]:
        if not document_ids:
            return {}
        rows = self.find(DocumentVersion.document_id.in_(document_ids), DocumentVersion.is_current)
        return {v.document_id: v for v in rows}

    def next_number(self, document_id: UUID) -> int:
        top = self.session.scalar(
            self._select()
            .with_only_columns(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == document_id)
        )
        return (top or 0) + 1

    def clear_current(self, document_id: UUID) -> None:
        for version in self.find(
            DocumentVersion.document_id == document_id, DocumentVersion.is_current
        ):
            version.is_current = False
        self.session.flush()

    def count_since(self, since: datetime) -> int:
        return (
            self.session.scalar(
                self._select()
                .with_only_columns(func.count(DocumentVersion.id))
                .where(DocumentVersion.created_at >= since)
            )
            or 0
        )

    def total_bytes(self) -> int:
        return int(
            self.session.scalar(
                self._select().with_only_columns(
                    func.coalesce(func.sum(DocumentVersion.file_size), 0)
                )
            )
            or 0
        )
