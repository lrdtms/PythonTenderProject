"""Documents and their versions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

DOCUMENT_KINDS = ("tender_document", "boq", "quotation", "other")
VERSION_STATUSES = ("pending", "processing", "ready", "ready_with_warnings", "failed")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), nullable=False
    )
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_documents_org_id"),
        ForeignKeyConstraint(
            ["organisation_id", "tender_id"],
            ["tenders.organisation_id", "tenders.id"],
            name="fk_documents_tender",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "created_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_documents_creator_membership",
        ),
        Index("ix_documents_tender", "organisation_id", "tender_id"),
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)  # pdf|xlsx|csv|docx
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(25), nullable=False, default="pending")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_document_versions_org_id"),
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
        ForeignKeyConstraint(
            ["organisation_id", "document_id"],
            ["documents.organisation_id", "documents.id"],
            name="fk_document_versions_document",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "uploaded_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_document_versions_uploader_membership",
        ),
        # At most one current version per document (BR-06: analyse the current document).
        Index(
            "uq_document_versions_one_current",
            "document_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )
