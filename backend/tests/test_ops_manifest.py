"""scripts/ops_manifest.py: a restore is only 'tested' if it is compared with the manifest."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops_manifest.py"


def _load():
    spec = importlib.util.spec_from_file_location("ops_manifest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ops_manifest"] = module
    spec.loader.exec_module(module)
    return module


om = _load()

MANIFEST = {
    "db_sha256": "a" * 64,
    "files_sha256": "b" * 64,
    "file_count": 3,
    "table_counts": {"tenders": 5, "documents": 7},
}


def same() -> dict:
    return json.loads(json.dumps(MANIFEST))


def test_equal_restore_has_no_problems() -> None:
    assert om.verify_manifest(MANIFEST, same()) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda a: a.update(db_sha256="c" * 64), "db_sha256 differs from the manifest"),
        (lambda a: a.update(files_sha256="c" * 64), "files_sha256 differs from the manifest"),
        (lambda a: a.update(file_count=2), "file_count: manifest 3, restored 2"),
        (
            lambda a: a["table_counts"].update(tenders=4),
            "table_counts[tenders]: manifest 5, restored 4",
        ),
        (
            lambda a: a["table_counts"].pop("documents"),
            "table_counts[documents]: missing from the restored database",
        ),
        (
            lambda a: a["table_counts"].update(extra=1),
            "table_counts[extra]: not in the manifest",
        ),
    ],
)
def test_each_kind_of_mismatch_is_named(mutate, expected: str) -> None:
    actual = same()
    mutate(actual)
    assert om.verify_manifest(MANIFEST, actual) == [expected]


def _backup_dir(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "db.dump").write_bytes(b"dump-bytes")
    (tmp_path / "files.tar.gz").write_bytes(b"archive-bytes")
    counts = tmp_path / "counts.tsv"
    counts.write_text("tenders\t5\ndocuments\t7\n", encoding="utf-8")
    return tmp_path, counts


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True
    )


def _write(directory: Path, counts: Path):
    return _run(
        "write", "--dir", str(directory), "--counts-tsv", str(counts), "--file-count", "3",
        "--alembic-head", "0008", "--git-commit", "abc1234",
    )  # fmt: skip


def _verify(directory: Path, counts: Path, files: str = "3"):
    return _run(
        "verify", "--dir", str(directory), "--counts-tsv", str(counts), "--file-count", files
    )


def test_write_then_verify_round_trip(tmp_path: Path) -> None:
    directory, counts = _backup_dir(tmp_path)
    assert _write(directory, counts).returncode == 0
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["alembic_head"] == "0008" and manifest["git_commit"] == "abc1234"
    assert manifest["table_counts"] == {"documents": 7, "tenders": 5}
    assert manifest["db_sha256"] == om.sha256_file(directory / "db.dump")
    result = _verify(directory, counts)
    assert result.returncode == 0, result.stdout
    assert "verified" in result.stdout


def test_a_flipped_byte_in_the_dump_fails_verification(tmp_path: Path) -> None:
    directory, counts = _backup_dir(tmp_path)
    _write(directory, counts)
    (directory / "db.dump").write_bytes(b"dump-bytez")
    result = _verify(directory, counts)
    assert result.returncode == 1 and "db_sha256 differs" in result.stdout


def test_a_truncated_archive_fails_verification(tmp_path: Path) -> None:
    directory, counts = _backup_dir(tmp_path)
    _write(directory, counts)
    (directory / "files.tar.gz").write_bytes(b"archive")
    result = _verify(directory, counts)
    assert result.returncode == 1 and "files_sha256 differs" in result.stdout


def test_a_count_mismatch_fails_verification(tmp_path: Path) -> None:
    directory, counts = _backup_dir(tmp_path)
    _write(directory, counts)
    counts.write_text("tenders\t4\ndocuments\t7\n", encoding="utf-8")
    result = _verify(directory, counts)
    assert (
        result.returncode == 1 and "table_counts[tenders]: manifest 5, restored 4" in result.stdout
    )


def test_missing_pieces_are_reported_not_crashed(tmp_path: Path) -> None:
    directory, counts = _backup_dir(tmp_path)
    assert _verify(directory, counts).returncode == 1  # no manifest yet
    _write(directory, counts)
    (directory / "files.tar.gz").unlink()
    result = _verify(directory, counts)
    assert result.returncode == 1 and "files.tar.gz is missing" in result.stdout
