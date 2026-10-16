"""Ports: interfaces the core depends on. Adapters live in app/infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol


class StoragePort(Protocol):
    """Original and generated files. Keys are server-generated (org/{organisation_id}/...)."""

    def put(self, key: str, data: bytes) -> None: ...

    def open(self, key: str) -> BinaryIO: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...


@dataclass(frozen=True)
class StructuredResult:
    raw_json: str
    done_reason: str | None
    tokens_in: int
    tokens_out: int
    latency_ms: int
    model: str


class LLMUnavailable(Exception):
    """The model server cannot be reached or answered with an error. Retry the job later."""


class LLMTimeout(Exception):
    """One call took longer than the configured timeout."""


class LLMPort(Protocol):
    """Structured generation (ADR-0003). Adapters live in app/infrastructure."""

    def generate_structured(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> StructuredResult: ...
