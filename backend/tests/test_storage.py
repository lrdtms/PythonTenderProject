"""LocalVolumeStorage: key validation, round trip, and atomic writes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.infrastructure.storage import LocalVolumeStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalVolumeStorage:
    return LocalVolumeStorage(tmp_path / "root")


@pytest.mark.parametrize(
    "key",
    [
        "../escape",
        "a/../../escape",
        "a/..",
        "/etc/passwd",
        r"C:\x",
        "C:x",
        r"\leading-backslash",
        "",
    ],
)
def test_bad_keys_are_rejected_by_every_operation(storage: LocalVolumeStorage, key: str) -> None:
    for call in (
        lambda: storage.put(key, b"x"),
        lambda: storage.open(key),
        lambda: storage.exists(key),
        lambda: storage.delete(key),
    ):
        with pytest.raises(ValueError):
            call()


def test_put_open_exists_delete_round_trip(storage: LocalVolumeStorage) -> None:
    key = "org/doc/v1/file.bin"
    assert storage.exists(key) is False
    storage.put(key, b"hello")
    assert storage.exists(key) is True
    with storage.open(key) as fh:
        assert fh.read() == b"hello"
    storage.put(key, b"replaced")  # overwrite
    with storage.open(key) as fh:
        assert fh.read() == b"replaced"
    storage.delete(key)
    assert storage.exists(key) is False
    storage.delete(key)  # deleting a missing key is fine


def test_failed_write_leaves_no_partial_file(
    storage: LocalVolumeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        storage.put("org/file.bin", b"data")
    directory = storage.root / "org"
    assert list(directory.glob(".upload-*")) == []
    assert list(directory.iterdir()) == []
    monkeypatch.undo()
    assert storage.exists("org/file.bin") is False
