"""Public surface of the knowledge module."""

from .ocr import OcrFailed, OcrRunner, TesseractOcr
from .schemas import (
    HIGHLIGHT_END,
    HIGHLIGHT_START,
    ExtractionPageDTO,
    IngestResult,
    PageDetailDTO,
    PageDTO,
    SearchHitDTO,
)
from .service import (
    get_extraction_input,
    get_page,
    ingest_version,
    list_pages,
    mark_failed,
    mark_processing,
    search_tender,
)

__all__ = [
    "HIGHLIGHT_END",
    "HIGHLIGHT_START",
    "ExtractionPageDTO",
    "IngestResult",
    "OcrFailed",
    "OcrRunner",
    "PageDTO",
    "PageDetailDTO",
    "SearchHitDTO",
    "TesseractOcr",
    "get_extraction_input",
    "get_page",
    "ingest_version",
    "list_pages",
    "mark_failed",
    "mark_processing",
    "search_tender",
]
