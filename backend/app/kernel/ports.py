"""Ports: interfaces the core depends on. Adapters live in app/infrastructure."""

from __future__ import annotations

from typing import BinaryIO, Protocol


class StoragePort(Protocol):
    """Original and generated files. Keys are server-generated (org/{organisation_id}/...)."""

    def put(self, key: str, data: bytes) -> None: ...

    def open(self, key: str) -> BinaryIO: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...
