"""LLM adapters against a real local HTTP server (no mocks of the transport)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.infrastructure.llm import FakeLLM, OllamaLLM, get_llm, set_llm_override
from app.kernel import LLMTimeout, LLMUnavailable

SCHEMA = {"type": "object"}


@pytest.fixture
def server() -> Iterator[Callable[[Callable[[dict], tuple[int, dict]]], str]]:
    servers: list[ThreadingHTTPServer] = []

    def start(respond: Callable[[dict], tuple[int, dict]]) -> str:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                status, payload = respond(body)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        servers.append(httpd)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start
    for s in servers:
        s.shutdown()


def _ollama(url: str, timeout: float = 5) -> OllamaLLM:
    return OllamaLLM(url, "qwen3:4b", timeout, 4096, 512)


def test_ollama_request_and_response(server) -> None:
    seen: dict = {}

    def respond(body: dict) -> tuple[int, dict]:
        seen.update(body)
        return 200, {
            "message": {"content": '{"requirements": []}'},
            "done_reason": "stop",
            "prompt_eval_count": 11,
            "eval_count": 3,
        }

    result = _ollama(server(respond)).generate_structured("sys", "usr", SCHEMA)
    assert result.raw_json == '{"requirements": []}'
    assert (result.done_reason, result.tokens_in, result.tokens_out) == ("stop", 11, 3)
    assert seen["think"] is False and seen["format"] == SCHEMA and seen["stream"] is False
    assert seen["options"]["temperature"] == 0 and seen["options"]["num_ctx"] == 4096
    assert seen["messages"][0] == {"role": "system", "content": "sys"}


def test_unreachable_server_is_unavailable() -> None:
    with pytest.raises(LLMUnavailable):
        _ollama("http://127.0.0.1:9").generate_structured("s", "u", SCHEMA)


def test_http_error_is_unavailable(server) -> None:
    with pytest.raises(LLMUnavailable):
        _ollama(server(lambda body: (500, {"error": "model not loaded"}))).generate_structured(
            "s", "u", SCHEMA
        )


def test_slow_server_is_a_timeout(server) -> None:
    def slow(body: dict) -> tuple[int, dict]:
        time.sleep(1.0)
        return 200, {"message": {"content": "{}"}}

    with pytest.raises(LLMTimeout):
        _ollama(server(slow), timeout=0.2).generate_structured("s", "u", SCHEMA)


def test_oversized_response_is_reported_as_length(server, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_max_response_bytes", 50)
    big = lambda body: (200, {"message": {"content": "x" * 500}})  # noqa: E731
    result = _ollama(server(big)).generate_structured("s", "u", SCHEMA)
    assert result.done_reason == "length" and result.raw_json == ""


def test_fake_llm_scripts_responses_and_errors() -> None:
    llm = FakeLLM(['{"requirements": [1]}', LLMTimeout(), lambda s, u: u.upper()])
    assert llm.generate_structured("s", "u", SCHEMA).raw_json == '{"requirements": [1]}'
    with pytest.raises(LLMTimeout):
        llm.generate_structured("s", "u", SCHEMA)
    assert llm.generate_structured("s", "abc", SCHEMA).raw_json == "ABC"
    assert llm.generate_structured("s", "u", SCHEMA).raw_json == '{"requirements": []}'  # default
    assert len(llm.calls) == 4


def test_factory_returns_fake_in_tests_and_honours_override() -> None:
    assert isinstance(get_llm(), FakeLLM)  # LLM_PROVIDER=fake is set by conftest
    mine = FakeLLM()
    set_llm_override(mine)
    try:
        assert get_llm() is mine
    finally:
        set_llm_override(None)


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({"prompt_eval_count": None, "eval_count": None, "done_reason": None}, (None, 0, 0)),
        ({"prompt_eval_count": "lots", "eval_count": [1], "done_reason": 7}, (None, 0, 0)),
        ({"prompt_eval_count": "12", "eval_count": 3.0, "done_reason": "stop"}, ("stop", 12, 3)),
        ({"prompt_eval_count": {"a": 1}, "eval_count": "1e999"}, (None, 0, 0)),
    ],
)
def test_malformed_metadata_fields_are_coerced_not_fatal(server, extra, expected) -> None:
    reply = {"message": {"content": '{"requirements": []}'}, **extra}
    result = _ollama(server(lambda body: (200, reply))).generate_structured("s", "u", SCHEMA)
    assert result.raw_json == '{"requirements": []}'
    assert (result.done_reason, result.tokens_in, result.tokens_out) == expected
