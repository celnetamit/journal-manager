"""A job whose worker died must not look busy for ever.

14 Sep 2026, measured: a rolling deploy ran both containers for nine seconds. The new one
swept the table clean at 20:24:29; the old one claimed a job at 20:24:38 and was then
stopped. The row said `running` and every thread in the surviving process was idle — the
platform showed "With ce4" indefinitely and nothing was wrong enough to notice.

The tests run against a real SQLite database, because the thing being tested is the SQL:
a NULL heartbeat compares false to everything, which is exactly how a job that never got
as far as reporting would have stayed invisible.
"""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A throwaway SQLite database, so these tests never touch a real queue."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "")
    import config

    importlib.reload(config)
    import auth

    importlib.reload(auth)
    return auth


def make_running(auth, *, heartbeat: str | None, started: str = "-30 minutes") -> int:
    job_id = auth.create_job(1, "p.docx", "/tmp/p.docx", json.dumps({}))
    beat = "NULL" if heartbeat is None else f"datetime('now', '{heartbeat}')"
    with auth._connect() as conn:                                     # noqa: SLF001
        conn.cursor().execute(
            f"UPDATE jobs SET status='running', started_at=datetime('now', '{started}'), "
            f"heartbeat_at={beat} WHERE id=?", (job_id,))
        conn.commit()
    return job_id


def status_of(auth, job_id: int) -> str:
    return auth.get_job(job_id)["status"]


def test_a_silent_job_is_returned_to_the_queue(db):
    job_id = make_running(db, heartbeat="-40 minutes")

    assert db.requeue_stalled_jobs(minutes=15) == [job_id]
    assert status_of(db, job_id) == "queued"
    assert db.get_job(job_id)["stage"] == "Re-queued after a stall"


def test_a_job_that_is_still_reporting_is_left_alone(db):
    """Re-queueing a live job copy edits the same manuscript twice and pays twice."""
    job_id = make_running(db, heartbeat="-2 minutes")

    assert db.requeue_stalled_jobs(minutes=15) == []
    assert status_of(db, job_id) == "running"


def test_a_job_that_never_reported_is_judged_on_when_it_started(db):
    """NULL compares false to everything, so this one would have been immune."""
    job_id = make_running(db, heartbeat=None, started="-30 minutes")

    assert db.requeue_stalled_jobs(minutes=15) == [job_id]
    assert status_of(db, job_id) == "queued"


def test_a_job_that_started_moments_ago_is_not_swept(db):
    job_id = make_running(db, heartbeat=None, started="-1 minutes")

    assert db.requeue_stalled_jobs(minutes=15) == []
    assert status_of(db, job_id) == "running"


def test_a_finished_job_is_never_resurrected(db):
    job_id = make_running(db, heartbeat="-40 minutes")
    db.complete_job(job_id, json.dumps({"ok": True}))

    assert db.requeue_stalled_jobs(minutes=15) == []
    assert status_of(db, job_id) == "done"


def test_progress_updates_are_what_keep_a_job_alive(db):
    """The heartbeat is not a separate thing to remember to send."""
    job_id = make_running(db, heartbeat="-40 minutes")
    db.update_job_progress(job_id, 0.5, "Copyediting — paragraph 12 of 30")

    assert db.requeue_stalled_jobs(minutes=15) == [], "it just spoke"
    assert status_of(db, job_id) == "running"
