"""The day's record: written once per day, re-runnable, and readable on a phone."""
import datetime
import json

import daily_findings as D

DAY = datetime.date(2026, 9, 17)


def _job(job_id, guards=(), status="done", day=DAY, proof=()):
    return {
        "id": job_id, "status": status,
        "created_at": f"{day.isoformat()} 10:00:00",
        "result_json": json.dumps({
            "guard_findings": [{"guard": g, "audience": a} for g, a in guards],
            "findings": {"proofreading": [{"rule": r} for r in proof], "layout": []},
        }),
    }


def test_the_day_is_counted_by_guard():
    jobs = [_job(1, [("keep_caption_values", "author"),
                     ("keep_caption_values", "author"),
                     ("restore_reference_numbering", "internal")]),
            _job(2, [("keep_every_equation", "internal")])]
    s = D.summarise(DAY, lambda n: jobs)
    assert s["jobs"] == 2
    assert s["guard_findings"] == {"keep_caption_values": 2,
                                   "restore_reference_numbering": 1,
                                   "keep_every_equation": 1}
    assert s["for_the_author"] == 2


def test_another_day_is_not_counted():
    jobs = [_job(1, [("keep_every_equation", "internal")],
                 day=datetime.date(2026, 9, 16))]
    assert D.summarise(DAY, lambda n: jobs)["jobs"] == 0


def test_a_failed_job_is_counted_and_not_read():
    jobs = [_job(1, status="error")]
    s = D.summarise(DAY, lambda n: jobs)
    assert s["jobs"] == 1 and s["failed"] == 1 and s["guard_findings"] == {}


def test_writing_the_same_day_twice_leaves_one_record(tmp_path):
    """A day can be summarised at 23:00 and again by hand; the file must not grow two
    different answers for it."""
    path = str(tmp_path / "record.jsonl")
    D.append({"date": "2026-09-16", "jobs": 1}, path)
    D.append({"date": "2026-09-17", "jobs": 2}, path)
    D.append({"date": "2026-09-17", "jobs": 5}, path)
    rows = D.history(path=path)
    assert [r["date"] for r in rows] == ["2026-09-16", "2026-09-17"]
    assert rows[-1]["jobs"] == 5


def test_the_summary_names_a_guard_that_fired_for_the_first_time():
    """The second derivative is the point: a class that appears, or stops."""
    today = {"date": "2026-09-17", "jobs": 1, "failed": 0, "for_the_author": 1,
             "guard_findings": {"keep_caption_values": 1, "keep_subscript_markers": 2}}
    yesterday = {"guard_findings": {"keep_caption_values": 3}}
    words = D.in_words(today, yesterday)
    assert "new today" in words and "keep subscript markers" in words


def test_a_quiet_day_says_so():
    s = {"date": "2026-09-17", "jobs": 0, "failed": 0, "guard_findings": {},
         "for_the_author": 0}
    assert "no guard fired" in D.in_words(s)
