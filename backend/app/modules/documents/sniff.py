"""File type detection from content. Filenames and client-supplied MIME types are not trusted."""

from __future__ import annotations

import io
import re
import zipfile

MIME = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_UNCOMPRESSED = 300 * 1024 * 1024  # zip-bomb guard for xlsx/docx
MAX_ZIP_ENTRIES = 5000


def sniff(data: bytes) -> str | None:
    """Return 'pdf', 'xlsx', 'docx' or 'csv', or None if the content is none of those."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        return _sniff_zip(data)
    return "csv" if _looks_like_csv(data) else None


def _sniff_zip(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
                return None
            names = {i.filename for i in infos}
    except zipfile.BadZipFile:
        return None
    if "xl/workbook.xml" in names:
        return "xlsx"
    if "word/document.xml" in names:
        return "docx"
    return None


def _looks_like_csv(data: bytes) -> bool:
    head = data[:8192]
    if not head or b"\x00" in head:
        return False
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = head.decode(encoding, errors="strict" if encoding == "utf-8-sig" else "replace")
        except UnicodeDecodeError:
            continue
        return bool(re.search(r"[,;\t]", text)) and "\n" in text
    return False


def safe_filename(name: str, limit: int = 120) -> str:
    """A display- and storage-safe file name: no directories, no odd characters."""
    base = re.split(r"[/\\]", name)[-1].strip()
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .") or "document"
    if len(cleaned) > limit:
        stem, dot, ext = cleaned.rpartition(".")
        cleaned = (stem[: limit - len(ext) - 1] + dot + ext) if dot else cleaned[:limit]
    return cleaned
