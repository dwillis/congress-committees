"""Tests for atomic file writes used by the on-disk caches."""

import pytest

import congress_committees.atomic_io as aio
from congress_committees.atomic_io import atomic_write_bytes, atomic_write_text


def test_atomic_write_text_creates_file_and_parents(tmp_path):
    target = tmp_path / "sub" / "data.json"
    atomic_write_text(target, '{"a": 1}')
    assert target.read_text() == '{"a": 1}'


def test_atomic_write_bytes_overwrites_existing(tmp_path):
    target = tmp_path / "data.bin"
    target.write_bytes(b"old")
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "data.json"
    atomic_write_text(target, "hello")
    # Only the destination remains; the temp file was renamed away.
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


def test_failed_replace_keeps_old_file_and_cleans_temp(tmp_path, monkeypatch):
    # If the final rename fails, the destination keeps its prior content and no
    # half-written temp file is left behind -- a reader never sees corruption.
    target = tmp_path / "data.json"
    target.write_text("OLD")

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(aio.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "NEW")

    assert target.read_text() == "OLD"
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]
