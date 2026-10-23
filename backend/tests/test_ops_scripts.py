"""The PowerShell ops scripts: present, parse, and carry the guards the spec requires."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
SCRIPTS = ["common.ps1", "start-demo.ps1", "tunnel.ps1"]


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
