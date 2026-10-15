"""Pages and chunks data access (tenant-scoped). Search SQL lives here."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, text

from app.db.scoped import ScopedRepository

from .models import DocumentChunk, DocumentPage


class PageRepo(ScopedRepository[DocumentPage]):
    model = DocumentPage

    def for_version(self, version_id: UUID) -> Sequence[DocumentPage]:
        return self.find(
            DocumentPage.document_version_id == version_id, order_by=DocumentPage.page_number
        )

    def one(self, version_id: UUID, page_number: int) -> DocumentPage | None:
        rows = self.find(
            DocumentPage.document_version_id == version_id,
            DocumentPage.page_number == page_number,
            limit=1,
        )
        return rows[0] if rows else None

    def replace_for_version(self, version_id: UUID, rows: list[dict[str, Any]]) -> None:
        self.session.execute(
            delete(DocumentPage).where(
                DocumentPage.organisation_id == self.ctx.organisation_id,
                DocumentPage.document_version_id == version_id,
            )
        )
        if rows:
            owner = {
                "organisation_id": self.ctx.organisation_id,
                "document_version_id": version_id,
            }
            self.session.execute(insert(DocumentPage), [{**r, **owner} for r in rows])


class ChunkRepo(ScopedRepository[DocumentChunk]):
    model = DocumentChunk

    def replace_for_version(self, version_id: UUID, rows: list[dict[str, Any]]) -> None:
        """Replace a version's chunks as a set (FR-59): re-running never duplicates."""
        self.session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.organisation_id == self.ctx.organisation_id,
                DocumentChunk.document_version_id == version_id,
            )
        )
        if rows:
            owner = {
                "organisation_id": self.ctx.organisation_id,
                "document_version_id": version_id,
            }
            self.session.execute(insert(DocumentChunk), [{**r, **owner} for r in rows])

    def search(self, tender_id: UUID, query: str, limit: int) -> list[dict[str, Any]]:
        """Full-text search over the CURRENT versions of a tender's documents, in this
        organisation only. Organisation, tender and current-version filters are all in the query."""
        rows = self.session.execute(
            text(
                """
                SELECT c.id AS chunk_id, d.id AS document_id, d.title AS document_title,
                       v.id AS version_id, v.version_number, c.page_number, c.section,
                       ts_headline('simple', c.text, q,
                                   'MaxWords=40, MinWords=15, MaxFragments=1') AS snippet,
                       ts_rank_cd(c.tsv, q) AS rank
                FROM document_chunks c
                JOIN document_versions v
                  ON v.id = c.document_version_id AND v.organisation_id = c.organisation_id
                JOIN documents d
                  ON d.id = v.document_id AND d.organisation_id = v.organisation_id,
                websearch_to_tsquery('simple', :query) AS q
                WHERE c.organisation_id = :org
                  AND d.tender_id = :tender
                  AND v.is_current
                  AND c.tsv @@ q
                ORDER BY rank DESC, c.page_number, c.ordinal
                LIMIT :limit
                """
            ),
            {
                "org": self.ctx.organisation_id,
                "tender": tender_id,
                "query": query,
                "limit": limit,
            },
        ).mappings()
        return [dict(r) for r in rows]
