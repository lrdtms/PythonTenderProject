"""Local-volume implementation of StoragePort (ADR-0007). A blob/S3 adapter can replace it."""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from app.config import get_settings


class LocalVolumeStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        """Resolve a key inside the root. Keys are server-generated, but never trust that."""
        if not key or key.startswith(("/", "\\")) or ".." in Path(key).parts or ":" in key:
            raise ValueError("invalid storage key")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("storage key escapes the storage root")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)  # atomic: readers never see a partial file
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


@lru_cache
def get_storage() -> LocalVolumeStorage:
    return LocalVolumeStorage(Path(get_settings().storage_path))
