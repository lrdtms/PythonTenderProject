"""Extracted pages (text and tables) and searchable chunks of a document version."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Computed,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

PAGE_STATUSES = ("ok", "empty", "ocr_failed", "ocr_unavailable", "low_confidence")


class DocumentPage(Base):
    """One physical page of a PDF (1-based, what PDF.js opens), or one sheet of a workbook."""

    __tablename__ = "document_pages"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))  # sheet name for spreadsheets
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    text_source: Mapped[str] = mapped_column(String(10), nullable=False, default="embedded")
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    tables: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("document_version_id", "page_number", name="uq_document_pages_number"),
        ForeignKeyConstraint(
            ["organisation_id", "document_version_id"],
            ["document_versions.organisation_id", "document_versions.id"],
            name="fk_document_pages_version",
        ),
    )


class DocumentChunk(Base):
    """A searchable slice of a page. Replaced as a set per version (idempotent re-ingestion)."""

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # `simple` configuration so codes such as "SANS 10142-1" are matched literally.
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True)
    )
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal", name="uq_document_chunks_ordinal"),
        ForeignKeyConstraint(
            ["organisation_id", "document_version_id"],
            ["document_versions.organisation_id", "document_versions.id"],
            name="fk_document_chunks_version",
        ),
        Index("ix_document_chunks_tsv", "tsv", postgresql_using="gin"),
    )
