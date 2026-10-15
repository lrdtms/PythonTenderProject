"""OCR through the Tesseract command line. Input goes in on stdin, no shell is involved."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Protocol


class OcrFailed(Exception):
    """OCR crashed, timed out or produced nothing usable for this page."""


class OcrRunner(Protocol):
    def available(self) -> bool: ...

    def run(self, png: bytes) -> tuple[str, float]:
        """Return (text, mean word confidence 0-100). Raise OcrFailed on failure."""
        ...


class TesseractOcr:
    def __init__(self, command: str = "tesseract", timeout_s: int = 60, language: str = "eng"):
        self.command = command
        self.timeout_s = timeout_s
        self.language = language

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def run(self, png: bytes) -> tuple[str, float]:
        args = [self.command, "stdin", "stdout", "-l", self.language, "--psm", "3", "tsv"]
        # One OpenMP thread: a single OCR must not saturate every core of a small VM.
        env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argument list, no shell
                args, input=png, capture_output=True, timeout=self.timeout_s, check=False, env=env
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrFailed("timeout") from exc
        except OSError as exc:
            raise OcrFailed("not_runnable") from exc
        if proc.returncode != 0:
            raise OcrFailed(f"exit_{proc.returncode}")
        return parse_tsv(proc.stdout.decode("utf-8", errors="replace"))


def parse_tsv(tsv: str) -> tuple[str, float]:
    """Rebuild text (line by line) and the mean confidence from Tesseract TSV output."""
    lines: dict[tuple[str, str, str], list[str]] = {}
    confidences: list[float] = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":  # level 5 = word
            continue
        word, conf = cols[11].strip(), cols[10]
        if not word:
            continue
        lines.setdefault((cols[2], cols[3], cols[4]), []).append(word)
        try:
            value = float(conf)
        except ValueError:
            continue
        if value >= 0:
            confidences.append(value)
    text = "\n".join(" ".join(words) for words in lines.values())
    return text, (sum(confidences) / len(confidences) if confidences else 0.0)
