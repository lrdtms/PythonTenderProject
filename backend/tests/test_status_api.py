"""GET /api/v1/health/status: public, minimal, rate-limited, model check cached."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import status
from app.api.main import app
from app.config import Settings

URL = "/api/v1/health/status"


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    status.reset_cache()


@pytest.fixture
def ollama(monkeypatch: pytest.MonkeyPatch):
    """Provider 'ollama' with the HTTP call replaced; returns the list of calls made."""
    calls: list[tuple[str, float]] = []
    monkeypatch.setattr(
        status, "get_settings", lambda: Settings(llm_provider="ollama", llm_base_url="http://llm:1")
    )

    def fake(url: str, timeout: float) -> bool:
        calls.append((url, timeout))
        return True

    monkeypatch.setattr(status, "_fetch_tags", fake)
    return calls


def test_no_login_needed_and_exactly_three_keys(client: TestClient) -> None:
    r = client.get(URL)
    assert r.status_code == 200
    assert set(r.json()) == {"api", "database", "model"}
    assert r.json()["api"] == "ok"
    assert r.json()["database"] == "ok"


def test_body_leaks_no_version_host_or_model_name(client: TestClient, ollama) -> None:
    text = client.get(URL).text.lower()
    for secret in ("qwen", "llm:1", "0.1.0", "postgres", "localhost", "/data"):
        assert secret not in text


def test_database_down_is_reported_with_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise RuntimeError("secret connection string")

    monkeypatch.setattr(status, "ping", boom)
    r = client.get(URL)
    assert r.status_code == 200
    assert r.json()["database"] == "down"
    assert "secret" not in r.text


def test_model_not_configured_when_provider_is_fake(client: TestClient) -> None:
    assert client.get(URL).json()["model"] == "not_configured"


def test_hosted_provider_still_reports_the_local_model_server(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kimi falls back to the local Ollama, so the local server is what the status reports."""
    monkeypatch.setattr(
        status, "get_settings", lambda: Settings(llm_provider="kimi", llm_base_url="http://llm:1")
    )
    monkeypatch.setattr(status, "_fetch_tags", lambda url, timeout: True)
    assert client.get(URL).json()["model"] == "ok"


def test_model_ok_and_down_with_a_two_second_timeout(
    client: TestClient, ollama, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.get(URL).json()["model"] == "ok"
    assert ollama == [("http://llm:1/api/tags", 2.0)]
    status.reset_cache()
    monkeypatch.setattr(status, "_fetch_tags", lambda url, timeout: False)
    assert client.get(URL).json()["model"] == "down"


def test_model_check_is_cached_for_ten_seconds(
    client: TestClient, ollama, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(status.time, "monotonic", lambda: now[0])
    client.get(URL)
    client.get(URL)
    assert len(ollama) == 1
    now[0] += 11
    client.get(URL)
    assert len(ollama) == 2


def test_thirty_first_call_in_a_minute_is_429(client: TestClient) -> None:
    codes = [client.get(URL).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30
    assert codes[30] == 429


def test_status_route_is_the_only_unauthenticated_health_detail() -> None:
    paths = {r.path for r in app.routes if "health" in getattr(r, "path", "")}
    assert paths == {"/api/v1/health", "/api/v1/health/db", URL}
