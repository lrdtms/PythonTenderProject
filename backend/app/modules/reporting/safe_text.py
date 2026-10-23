"""The single funnel for user-controlled text that reaches an export file.

Excel text goes through `xlsx_text`; PDF text through `pdf_text` (markup) or `pdf_plain`
(canvas text and metadata). Nothing else may put a user string into a file.
"""

import re
import unicodedata
from datetime import date

_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_FORMULA_START = ("=", "+", "-", "@")
_PDF_MARKER = "... (truncated, see source)"


def _clean(value: str | None) -> str:
    return _ILLEGAL.sub("", value) if value else ""


def _cp1252(text: str) -> str:
    return "".join(ch if _encodable(ch) else "?" for ch in text)


def _encodable(ch: str) -> bool:
    try:
        ch.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def xlsx_text(value: str | None, limit: int = 32_000) -> str:
    text = _clean(value)
    if len(text) > limit - 4:
        text = text[: limit - 4] + "..."
    if text.lstrip(" \t\r\n").startswith(_FORMULA_START) or text.startswith(("\t", "\r")):
        return "'" + text
    return text


def xlsx_header_text(value: str | None, limit: int = 60) -> str:
    return _clean(value).replace("&", "&&")[:limit]


def pdf_plain(value: str | None, limit: int = 300) -> str:
    return _cp1252(_clean(value)[:limit])


def pdf_text(value: str | None, limit: int = 2_000) -> str:
    text = _clean(value)
    # Escaping can grow the text, so cut on the escaped length.
    escaped = _escape(_cp1252(text))
    if len(escaped) <= limit:
        return escaped
    room = limit - len(_PDF_MARKER)
    cut = text
    while True:
        cut = cut[: max(0, len(cut) - max(1, len(escaped) - room))]
        escaped = _escape(_cp1252(cut))
        if len(escaped) <= room:
            return escaped + _PDF_MARKER


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _slug(title: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-")[:40].strip("-")
    return slug or "tender"


def export_filename(
    tender_title: str, kind: str, version: int | None, draft: bool, on: date
) -> str:
    parts = [_slug(tender_title), "estimate" if kind == "estimate" else "checklist"]
    if kind == "estimate":
        parts[-1] += f"-v{version}"
    if draft:
        parts.append("DRAFT")
    parts.append(on.strftime("%Y%m%d"))
    ext = "xlsx" if kind == "estimate" else "pdf"
    return f"{'-'.join(parts)}.{ext}"
