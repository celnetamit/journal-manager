"""Tests for output-file retention cleanup."""

import os
import time

import config


def test_purge_removes_old_keeps_new(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    old = tmp_path / "user_1_old_redline.docx"
    new = tmp_path / "user_1_new_redline.docx"
    old.write_text("old")
    new.write_text("new")

    # Age the old file beyond the 30-day window.
    old_time = time.time() - 40 * 86400
    os.utime(old, (old_time, old_time))

    removed = config.purge_old_outputs(ttl_days=30)
    assert removed == 1
    assert not old.exists()
    assert new.exists()


def test_purge_disabled_when_ttl_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    f = tmp_path / "old.docx"
    f.write_text("x")
    old_time = time.time() - 100 * 86400
    os.utime(f, (old_time, old_time))

    assert config.purge_old_outputs(ttl_days=0) == 0
    assert f.exists()


def test_retention_days_env(monkeypatch):
    monkeypatch.setenv("OUTPUT_RETENTION_DAYS", "7")
    assert config.output_retention_days() == 7
    monkeypatch.setenv("OUTPUT_RETENTION_DAYS", "0")
    assert config.output_retention_days() == 0
