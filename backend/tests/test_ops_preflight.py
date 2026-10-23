"""scripts/ops_preflight.py: config rules that keep unsafe settings away from a public tunnel."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops_preflight.py"


def _load():
    spec = importlib.util.spec_from_file_location("ops_preflight", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ops_preflight"] = module
    spec.loader.exec_module(module)
    return module


pf = _load()

GOOD = {
    "SECRET_KEY": "s" * 32,
    "POSTGRES_PASSWORD": "a-long-database-password",
    "ENVIRONMENT": "production",
    "COOKIE_SECURE": "true",
    "LLM_ALLOW_HOSTED": "false",
}


def codes(env: dict[str, str], *, tunnel: bool, accept: bool = False, level: str | None = None):
    return {
        f.code
        for f in pf.check(env, tunnel=tunnel, accept_hosted=accept)
        if level in (None, f.level)
    }


def test_clean_env_has_no_findings_with_or_without_tunnel() -> None:
    assert pf.check(GOOD, tunnel=True, accept_hosted=False) == []
    assert pf.check(GOOD, tunnel=False, accept_hosted=False) == []


@pytest.mark.parametrize("secret", [None, "", "change-me", "s" * 31])
def test_weak_secret_is_an_error_with_a_tunnel_and_a_warning_without(secret) -> None:
    env = {k: v for k, v in GOOD.items() if k != "SECRET_KEY"}
    if secret is not None:
        env["SECRET_KEY"] = secret
    assert "weak_secret" in codes(env, tunnel=True, level="error")
    assert "weak_secret" in codes(env, tunnel=False, level="warning")
    assert "weak_secret" not in codes(env, tunnel=False, level="error")


def test_32_character_secret_is_accepted() -> None:
    assert codes({**GOOD, "SECRET_KEY": "s" * 32}, tunnel=True) == set()


def test_default_database_password_blocks_a_tunnel_only() -> None:
    env = {**GOOD, "POSTGRES_PASSWORD": "intel"}
    assert "default_db_password" in codes(env, tunnel=True, level="error")
    assert codes(env, tunnel=False) == set()
    env2 = {k: v for k, v in GOOD.items() if k != "POSTGRES_PASSWORD"}
    assert "default_db_password" in codes(env2, tunnel=True, level="error")


@pytest.mark.parametrize("environment", [None, "development", "staging"])
def test_tunnel_requires_production_environment(environment) -> None:
    env = {k: v for k, v in GOOD.items() if k != "ENVIRONMENT"}
    if environment:
        env["ENVIRONMENT"] = environment
    assert "not_production" in codes(env, tunnel=True, level="error")
    assert "not_production" not in codes(env, tunnel=False)


@pytest.mark.parametrize("value", [None, "false", "", "no"])
def test_tunnel_requires_secure_cookies(value) -> None:
    env = {k: v for k, v in GOOD.items() if k != "COOKIE_SECURE"}
    if value is not None:
        env["COOKIE_SECURE"] = value
    assert "insecure_cookie" in codes(env, tunnel=True, level="error")


def test_insecure_cookie_in_production_without_a_tunnel_is_a_warning() -> None:
    env = {**GOOD, "COOKIE_SECURE": "false"}
    assert "insecure_cookie" in codes(env, tunnel=False, level="warning")
    assert (
        codes({**GOOD, "ENVIRONMENT": "development", "COOKIE_SECURE": "false"}, tunnel=False)
        == set()
    )


def test_hosted_llm_with_a_tunnel_needs_explicit_acceptance() -> None:
    env = {**GOOD, "LLM_ALLOW_HOSTED": "true"}
    assert "hosted_llm_public" in codes(env, tunnel=True, level="error")
    assert "hosted_llm_public" in codes(env, tunnel=True, accept=True, level="warning")
    assert "hosted_llm_public" not in codes(env, tunnel=True, accept=True, level="error")
    assert "hosted_llm_public" not in codes(env, tunnel=False)


def test_findings_never_contain_values() -> None:
    env = {**GOOD, "SECRET_KEY": "super-secret-value", "POSTGRES_PASSWORD": "intel"}
    text = " ".join(f.message for f in pf.check(env, tunnel=True, accept_hosted=False))
    assert "super-secret-value" not in text and "intel" not in text.replace("IntelTPS", "")


def test_env_file_parsing(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text(
        "# comment\n\nSECRET_KEY='quoted-value'\nA=1 \nB = 2\nexport C=3\nBAD LINE\nD=\"x y\"\n",
        encoding="utf-8",
    )
    assert pf.parse_env_file(f) == {
        "SECRET_KEY": "quoted-value",
        "A": "1",
        "B": "2",
        "C": "3",
        "D": "x y",
    }


def test_missing_env_file_is_an_error_finding(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--env-file", str(tmp_path / "nope.env")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "nope.env" in result.stdout or "env file" in result.stdout.lower()


def test_cli_exit_codes_and_no_values_printed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.env"
    bad.write_text("SECRET_KEY=change-me\nENVIRONMENT=development\n", encoding="utf-8")
    good = tmp_path / "good.env"
    good.write_text("\n".join(f"{k}={v}" for k, v in GOOD.items()), encoding="utf-8")
    run = lambda *a: subprocess.run(  # noqa: E731
        [sys.executable, "-I", str(SCRIPT), *a], capture_output=True, text=True
    )
    r = run("--env-file", str(bad), "--tunnel")
    assert r.returncode == 1 and "change-me" not in r.stdout
    assert run("--env-file", str(good), "--tunnel").returncode == 0
    assert run("--env-file", str(bad)).returncode == 0  # warnings only without a tunnel
