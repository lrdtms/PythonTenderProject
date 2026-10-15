"""Public surface of the knowledge module."""

from .ocr import OcrFailed, OcrRunner, TesseractOcr
from .schemas import IngestResult, PageDetailDTO, PageDTO, SearchHitDTO
from .service import get_page, ingest_version, list_pages, mark_failed, search_tender

__all__ = [
    "IngestResult",
    "OcrFailed",
    "OcrRunner",
    "PageDTO",
    "PageDetailDTO",
    "SearchHitDTO",
    "TesseractOcr",
    "get_page",
    "ingest_version",
    "list_pages",
    "mark_failed",
    "search_tender",
]
