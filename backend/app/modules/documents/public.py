"""Public surface of the documents module."""

from .schemas import DocumentDTO, ProcessingInfo, UploadResultDTO, VersionDTO
from .service import (
    EXTRACT_BOQ_JOB,
    EXTRACT_QUOTATION_JOB,
    EXTRACT_REQUIREMENTS_JOB,
    EXTRACTION_JOBS,
    INGEST_JOB,
    ensure_job_retry_allowed,
    get_document,
    get_version,
    list_documents,
    list_versions,
    open_version_file,
    processing_info,
    set_processing_status,
    upload_document,
    upload_new_version,
)

__all__ = [
    "EXTRACTION_JOBS",
    "EXTRACT_BOQ_JOB",
    "EXTRACT_QUOTATION_JOB",
    "EXTRACT_REQUIREMENTS_JOB",
    "INGEST_JOB",
    "DocumentDTO",
    "ProcessingInfo",
    "UploadResultDTO",
    "VersionDTO",
    "ensure_job_retry_allowed",
    "get_document",
    "get_version",
    "list_documents",
    "list_versions",
    "open_version_file",
    "processing_info",
    "set_processing_status",
    "upload_document",
    "upload_new_version",
]
