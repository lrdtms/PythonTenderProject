"""LLM adapters: Ollama over HTTP (standard library only) and a scriptable fake for tests."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from app.config import get_settings
from app.kernel import LLMPort, LLMTimeout, LLMUnavailable, StructuredResult

log = logging.getLogger("llm")


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


class KimiLLM:
    """OpenAI-compatible adapter for the Kimi (Moonshot) API.

    Raises LLMUnavailable on network errors, timeouts, and HTTP 4xx/5xx so that
    FallbackLLM can retry on Ollama. Malformed JSON responses raise ValueError
    (a prompt/schema bug, not a transport failure).
    """

    def __init__(self, api_key: str, base_url: str, model: str, timeout_s: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self._auth = f"Bearer {api_key}"

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
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema},
            },
            # Thinking off: extraction does not need it and it blows the per-call timeout.
            "thinking": {"type": "disabled"},
            # Some hosted models ignore the flag above and reason until they run out of tokens
            # (billed, no JSON). A hard output cap, the same as Ollama's, bounds every call.
            "max_tokens": get_settings().llm_num_predict,
            # No temperature: kimi-k2.x only accepts its fixed default and 400s on anything else.
            **(options or {}),
        }
        request = urllib.request.Request(  # noqa: S310 - the URL comes from settings
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": self._auth,
                # urllib's default "Python-urllib" agent is refused by some gateways (Mammouth
                # answers 403, Cloudflare error 1010), so identify the application instead.
                "User-Agent": "IntelTPS/1.0",
            },
        )
        limit = get_settings().llm_max_response_bytes
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:  # noqa: S310
                raw = response.read(limit + 1)
        except TimeoutError:
            raise LLMTimeout from None
        except urllib.error.HTTPError as exc:
            # The body says why (bad parameter, auth, quota); keep it out of the exception
            # chain but not out of the logs, or the fallback hides the cause.
            detail = exc.read(500).decode(errors="replace")
            log.warning("Kimi HTTP %s, falling back: %s", exc.code, detail)
            raise LLMUnavailable from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                log.warning("Kimi timed out, falling back")
                raise LLMTimeout from None
            log.warning("Kimi unreachable, falling back: %s", exc.reason)
            raise LLMUnavailable from None
        except OSError:
            raise LLMUnavailable from None
        latency_ms = int((time.perf_counter() - started) * 1000)
        if len(raw) > limit:
            return StructuredResult("", "length", 0, 0, latency_ms, self.model)
        try:
            body = json.loads(raw)
        except ValueError as exc:
            raise ValueError(f"Kimi returned non-JSON: {raw[:200]!r}") from exc
        try:
            choice = body["choices"][0]
            content = str(choice["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Kimi response missing choices[0].message.content: {body!r}") from exc
        usage = body.get("usage") or {}
        return StructuredResult(
            raw_json=content,
            done_reason=choice.get("finish_reason"),
            tokens_in=_count(usage.get("prompt_tokens")),
            tokens_out=_count(usage.get("completion_tokens")),
            latency_ms=latency_ms,
            model=self.model,
        )


class FallbackLLM:
    """Tries the primary LLM first; on LLMUnavailable or LLMTimeout, retries on the fallback."""

    def __init__(self, primary: LLMPort, fallback: LLMPort) -> None:
        self.primary = primary
        self.fallback = fallback

    def generate_structured(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> StructuredResult:
        try:
            return self.primary.generate_structured(system, user, json_schema, options)
        except (LLMUnavailable, LLMTimeout) as exc:
            log.warning("primary LLM failed (%s), using fallback", type(exc).__name__)
            return self.fallback.generate_structured(system, user, json_schema, options)


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
    ollama = OllamaLLM(
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_timeout_s,
        settings.llm_num_ctx,
        settings.llm_num_predict,
    )
    if settings.llm_provider == "kimi":
        if not settings.llm_allow_hosted:
            raise RuntimeError("LLM_PROVIDER=kimi requires LLM_ALLOW_HOSTED=true")
        if not settings.llm_kimi_api_key:
            raise RuntimeError("LLM_PROVIDER=kimi requires LLM_KIMI_API_KEY to be set")
        kimi = KimiLLM(
            settings.llm_kimi_api_key,
            settings.llm_kimi_base_url,
            settings.llm_kimi_model,
            settings.llm_timeout_s,
        )
        return FallbackLLM(kimi, ollama)
    return ollama
