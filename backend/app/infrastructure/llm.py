"""LLM adapters: Ollama over HTTP (standard library only) and a scriptable fake for tests."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from app.config import get_settings
from app.kernel import LLMPort, LLMTimeout, LLMUnavailable, StructuredResult


def _count(value: object) -> int:
    """A token count from the reply; anything missing or malformed counts as 0, never fatal."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0
    try:
        return max(0, int(value))
    except (ValueError, OverflowError):
        return 0


class OllamaLLM:
    def __init__(
        self, base_url: str, model: str, timeout_s: float, num_ctx: int, num_predict: int
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.num_ctx = num_ctx
        self.num_predict = num_predict

    def generate_structured(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> StructuredResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "keep_alive": "10m",
            "think": False,  # Qwen3 spends its tokens on reasoning otherwise
            "format": json_schema,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {
                "temperature": 0,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
                **(options or {}),
            },
        }
        request = urllib.request.Request(  # noqa: S310 - the URL comes from settings
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        limit = get_settings().llm_max_response_bytes
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:  # noqa: S310
                raw = response.read(limit + 1)
        except TimeoutError:
            raise LLMTimeout from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise LLMTimeout from None
            raise LLMUnavailable from None
        except OSError:
            raise LLMUnavailable from None
        latency_ms = int((time.perf_counter() - started) * 1000)
        if len(raw) > limit:
            return StructuredResult("", "length", 0, 0, latency_ms, self.model)
        try:
            body = json.loads(raw)
            content = str(body["message"]["content"])
        except (ValueError, KeyError, TypeError):
            raise LLMUnavailable from None
        return StructuredResult(
            raw_json=content,
            done_reason=reason if isinstance(reason := body.get("done_reason"), str) else None,
            tokens_in=_count(body.get("prompt_eval_count")),
            tokens_out=_count(body.get("eval_count")),
            latency_ms=latency_ms,
            model=self.model,
        )


class FakeLLM:
    """Scripted responses, popped in order. An item may be a JSON string, an exception to
    raise, or a callable `(system, user) -> str`. After the script runs out, `default`."""

    def __init__(
        self,
        responses: list[str | Exception | Callable[[str, str], str]] | None = None,
        default: str = '{"requirements": []}',
    ) -> None:
        self.responses = list(responses or [])
        self.default = default
        self.calls: list[tuple[str, str]] = []

    def generate_structured(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> StructuredResult:
        self.calls.append((system, user))
        item = self.responses.pop(0) if self.responses else self.default
        if isinstance(item, Exception):
            raise item
        text = item(system, user) if callable(item) else item
        return StructuredResult(text, "stop", 0, 0, 0, "fake")


_override: LLMPort | None = None


def set_llm_override(llm: LLMPort | None) -> None:
    global _override
    _override = llm


def get_llm() -> LLMPort:
    if _override is not None:
        return _override
    settings = get_settings()
    if settings.llm_provider == "fake":
        return FakeLLM()
    return OllamaLLM(
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_timeout_s,
        settings.llm_num_ctx,
        settings.llm_num_predict,
    )
