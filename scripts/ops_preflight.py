"""Configuration checks run by scripts/ops/start-demo.ps1 and tunnel.ps1 before the stack is
exposed. Standard library only. Findings name the setting, never its value.

    python scripts/ops_preflight.py [--tunnel] [--accept-hosted-llm] [--env-file .env]

Exit code 1 when there is at least one error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

MIN_SECRET_LENGTH = 32
WEAK_SECRETS = {"", "change-me"}


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    code: str
    message: str


def parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and " " not in key:
            env[key] = value
    return env


def _true(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def check(env: Mapping[str, str], *, tunnel: bool, accept_hosted: bool) -> list[Finding]:
    out: list[Finding] = []
    strict = "error" if tunnel else "warning"

    secret = env.get("SECRET_KEY", "")
    if secret in WEAK_SECRETS or len(secret) < MIN_SECRET_LENGTH:
        out.append(
            Finding(
                strict,
                "weak_secret",
                f"SECRET_KEY must be set to a random value of at least {MIN_SECRET_LENGTH} characters.",
            )
        )

    if tunnel and env.get("POSTGRES_PASSWORD", "intel") == "intel":
        out.append(
            Finding(
                "error",
                "default_db_password",
                "POSTGRES_PASSWORD is the development default; set a real one before opening a tunnel.",
            )
        )

    production = env.get("ENVIRONMENT", "") == "production"
    if tunnel and not production:
        out.append(
            Finding("error", "not_production", "ENVIRONMENT must be production while a tunnel is open.")
        )

    if not _true(env.get("COOKIE_SECURE")) and (tunnel or production):
        out.append(
            Finding(
                strict,
                "insecure_cookie",
                "COOKIE_SECURE must be true when the site is served over HTTPS.",
            )
        )

    if tunnel and _true(env.get("LLM_ALLOW_HOSTED")):
        out.append(
            Finding(
                "warning" if accept_hosted else "error",
                "hosted_llm_public",
                "A hosted language model is enabled while the site is public. Use synthetic data "
                "only; pass --accept-hosted-llm to confirm.",
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tunnel", action="store_true")
    parser.add_argument("--accept-hosted-llm", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)

    path = Path(args.env_file)
    if not path.is_file():
        print(f"error: env file not found: {path}")
        return 1
    findings = check(parse_env_file(path), tunnel=args.tunnel, accept_hosted=args.accept_hosted_llm)
    for f in findings:
        print(f"{f.level}: {f.code}: {f.message}")
    errors = sum(1 for f in findings if f.level == "error")
    if not findings:
        print("preflight: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
