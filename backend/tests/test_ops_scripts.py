"""The PowerShell ops scripts: present, parse, and carry the guards the spec requires."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
SCRIPTS = ["common.ps1", "start-demo.ps1", "tunnel.ps1", "backup.ps1", "restore.ps1"]


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_exists(name: str) -> None:
    assert (OPS / name).is_file()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 (pwsh) is not installed")
@pytest.mark.parametrize("name", SCRIPTS)
def test_script_parses(name: str) -> None:
    command = (
        "$e = $null; $t = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{OPS / name}', [ref]$t, [ref]$e) | Out-Null; "
        "if ($e.Count -gt 0) { $e | ForEach-Object { $_.Message }; exit 1 }"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_start_demo_has_the_documented_switches_and_runs_preflight() -> None:
    text = (OPS / "start-demo.ps1").read_text(encoding="utf-8")
    for token in (
        "$Tunnel",
        "$Stop",
        "$SkipModel",
        "Invoke-Preflight",
        "docker compose up -d --build",
    ):
        assert token in text
    assert "COOKIE_SECURE=false" not in text


def test_tunnel_runs_preflight_in_tunnel_mode_and_reports_missing_cloudflared() -> None:
    text = (OPS / "tunnel.ps1").read_text(encoding="utf-8")
    assert "Invoke-Preflight -Tunnel" in text
    assert "exit 2" in text and "winget install" in text
    assert "$Stop" in text


def test_ops_state_directories_are_ignored_by_git() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "backups/" in ignored and ".demo/" in ignored


def test_restore_refuses_apply_without_a_named_project_and_guards_the_live_one() -> None:
    text = (OPS / "restore.ps1").read_text(encoding="utf-8")
    assert "-Apply needs -Project" in text
    assert "IKnowThisReplacesLiveData" in text and "Refusing to replace the live project" in text
    assert "exactly one of -Verify or -Apply" in text


def test_restore_verify_never_touches_the_live_database() -> None:
    text = (OPS / "restore.ps1").read_text(encoding="utf-8")
    verify_branch = text.split("if ($Verify) {", 2)[1].split("} else {", 1)[0]
    assert "inteltps_verify" in text and "$scratchDb" in verify_branch
    assert "DROP DATABASE IF EXISTS $name" not in verify_branch


def test_backup_removes_a_partial_directory_and_records_the_manifest() -> None:
    text = (OPS / "backup.ps1").read_text(encoding="utf-8")
    assert "Remove-Item $dir -Recurse" in text
    assert "ops_manifest.py" in text and "files.tar.gz" in text and "pg_dump -Fc" in text


def _invoke_preflight(tmp_path: Path, env_text: str, *flags: str) -> str:
    env = tmp_path / "test.env"
    env.write_text(env_text, encoding="utf-8")
    command = (
        f". '{OPS / 'common.ps1'}'; "
        f"$r = Invoke-Preflight {' '.join(flags)} -EnvFile '{env}'; "
        "Write-Output ('RESULT=' + $r.GetType().Name + ':' + $r)"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True
    )
    return result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 (pwsh) is not installed")
def test_invoke_preflight_returns_a_plain_false_for_an_unsafe_tunnel_config(tmp_path: Path) -> None:
    out = _invoke_preflight(tmp_path, "SECRET_KEY=change-me\nENVIRONMENT=development\n", "-Tunnel")
    assert "RESULT=Boolean:False" in out
    assert "weak_secret" in out  # the findings are shown to the person, not swallowed


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 (pwsh) is not installed")
def test_invoke_preflight_returns_a_plain_true_for_a_safe_config(tmp_path: Path) -> None:
    safe = (
        f"SECRET_KEY={'s' * 32}\nPOSTGRES_PASSWORD=a-long-database-password\n"
        "ENVIRONMENT=production\nCOOKIE_SECURE=true\n"
    )
    assert "RESULT=Boolean:True" in _invoke_preflight(tmp_path, safe, "-Tunnel")
