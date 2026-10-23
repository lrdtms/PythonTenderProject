"""Backup manifest: write it at backup time, verify it at restore time. Standard library only.

    python scripts/ops_manifest.py write  --dir D --counts-tsv F --file-count N --alembic-head H --git-commit C
    python scripts/ops_manifest.py verify --dir D --counts-tsv F --file-count N

`--counts-tsv` holds one `table<TAB>row count` line per table. `verify` re-hashes the dump and
the archive in D (catching a tampered or truncated file) and compares the counts from the
restored copy with the ones recorded at backup time. Exit code 1 on any mismatch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

DUMP = "db.dump"
ARCHIVE = "files.tar.gz"
MANIFEST = "manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        name, _, number = line.partition("\t")
        counts[name.strip()] = int(number)
    return counts


def build_manifest(
    directory: Path, counts: dict[str, int], file_count: int, alembic_head: str, git_commit: str
) -> dict:
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit,
        "alembic_head": alembic_head,
        "db_sha256": sha256_file(directory / DUMP),
        "files_sha256": sha256_file(directory / ARCHIVE),
        "file_count": file_count,
        "table_counts": dict(sorted(counts.items())),
    }


def verify_manifest(manifest: dict, actual: dict) -> list[str]:
    """Differences between what the backup recorded and what a restore produced. `actual` has
    db_sha256, files_sha256, file_count and table_counts. Empty list means a faithful restore."""
    problems: list[str] = []
    for key in ("db_sha256", "files_sha256"):
        if manifest.get(key) != actual.get(key):
            problems.append(f"{key} differs from the manifest")
    if manifest.get("file_count") != actual.get("file_count"):
        problems.append(
            f"file_count: manifest {manifest.get('file_count')}, restored {actual.get('file_count')}"
        )
    recorded: dict[str, int] = manifest.get("table_counts", {})
    restored: dict[str, int] = actual.get("table_counts", {})
    for table in sorted(recorded.keys() | restored.keys()):
        if table not in restored:
            problems.append(f"table_counts[{table}]: missing from the restored database")
        elif table not in recorded:
            problems.append(f"table_counts[{table}]: not in the manifest")
        elif recorded[table] != restored[table]:
            problems.append(
                f"table_counts[{table}]: manifest {recorded[table]}, restored {restored[table]}"
            )
    return problems


def _write(args: argparse.Namespace) -> int:
    directory = Path(args.dir)
    manifest = build_manifest(
        directory,
        read_counts(Path(args.counts_tsv)),
        args.file_count,
        args.alembic_head,
        args.git_commit,
    )
    (directory / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest written: {len(manifest['table_counts'])} tables, {args.file_count} files")
    return 0


def _verify(args: argparse.Namespace) -> int:
    directory = Path(args.dir)
    manifest_path = directory / MANIFEST
    if not manifest_path.is_file():
        print(f"error: no {MANIFEST} in {directory}")
        return 1
    for name in (DUMP, ARCHIVE):
        if not (directory / name).is_file():
            print(f"error: {name} is missing from {directory}")
            return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = {
        "db_sha256": sha256_file(directory / DUMP),
        "files_sha256": sha256_file(directory / ARCHIVE),
        "file_count": args.file_count,
        "table_counts": read_counts(Path(args.counts_tsv)),
    }
    problems = verify_manifest(manifest, actual)
    for problem in problems:
        print(f"mismatch: {problem}")
    if problems:
        return 1
    print(
        f"verified: checksums match, {len(actual['table_counts'])} tables and "
        f"{actual['file_count']} files agree with the manifest"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("write", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--dir", required=True)
        p.add_argument("--counts-tsv", required=True)
        p.add_argument("--file-count", type=int, required=True)
        if name == "write":
            p.add_argument("--alembic-head", required=True)
            p.add_argument("--git-commit", default="unknown")
    args = parser.parse_args(argv)
    return _write(args) if args.command == "write" else _verify(args)


if __name__ == "__main__":
    sys.exit(main())
