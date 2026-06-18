"""Tests for the DB-backed background job queue."""

import json

import pytest


@pytest.fixture()
def auth_mod(tmp_path, monkeypatch):
    # Isolated SQLite DB per test: auth uses DATA_DIR/analytics.db for SQLite.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import auth
    return auth


def test_create_and_get_job(auth_mod):
    jid = auth_mod.create_job(1, "m.docx", "/tmp/in.docx", json.dumps({"x": 1}))
    job = auth_mod.get_job(jid)
    assert job["status"] == "queued"
    assert job["filename"] == "m.docx"
    assert json.loads(job["options_json"]) == {"x": 1}


def test_claim_marks_running_and_is_exclusive(auth_mod):
    jid = auth_mod.create_job(1, "m.docx", "/tmp/in.docx", "{}")
    claimed = auth_mod.claim_next_job()
    assert claimed["id"] == jid and claimed["status"] == "running"
    # nothing else queued -> second claim returns None
    assert auth_mod.claim_next_job() is None


def test_progress_complete_and_fail(auth_mod):
    jid = auth_mod.create_job(1, "m.docx", "/tmp/in.docx", "{}")
    auth_mod.claim_next_job()
    auth_mod.update_job_progress(jid, 0.4, "Halfway")
    j = auth_mod.get_job(jid)
    assert abs(j["progress"] - 0.4) < 1e-6 and j["stage"] == "Halfway"

    auth_mod.complete_job(jid, json.dumps({"duration": 2.0}))
    j = auth_mod.get_job(jid)
    assert j["status"] == "done" and j["progress"] == 1.0
    assert json.loads(j["result_json"])["duration"] == 2.0

    jid2 = auth_mod.create_job(1, "b.docx", "/tmp/x", "{}")
    auth_mod.claim_next_job()
    auth_mod.fail_job(jid2, "boom")
    j2 = auth_mod.get_job(jid2)
    assert j2["status"] == "error" and j2["error_message"] == "boom"


def test_requeue_running_jobs(auth_mod):
    jid = auth_mod.create_job(1, "m.docx", "/tmp/in.docx", "{}")
    auth_mod.claim_next_job()  # -> running
    assert auth_mod.get_job(jid)["status"] == "running"
    assert auth_mod.requeue_running_jobs() == 1
    assert auth_mod.get_job(jid)["status"] == "queued"


def test_fifo_order(auth_mod):
    a = auth_mod.create_job(1, "a.docx", "/tmp/a", "{}")
    b = auth_mod.create_job(1, "b.docx", "/tmp/b", "{}")
    assert auth_mod.claim_next_job()["id"] == a
    assert auth_mod.claim_next_job()["id"] == b


def test_fetch_user_jobs_scoped(auth_mod):
    auth_mod.create_job(1, "u1.docx", "/tmp/a", "{}")
    auth_mod.create_job(2, "u2.docx", "/tmp/b", "{}")
    rows = auth_mod.fetch_user_jobs(1)
    assert all(r["filename"] != "u2.docx" for r in rows)
    assert any(r["filename"] == "u1.docx" for r in rows)
