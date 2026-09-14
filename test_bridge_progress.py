"""What ce4 tells the platform while a job is running.

The rule that matters most is the one about failure: a progress report is decoration, and
decoration must never be able to fail the copy edit it is decorating. The rest is about
not shouting — one report every few seconds, and one log line per outage rather than one
per tick.
"""

from __future__ import annotations

import json

import pytest

import mng_bridge
from editor import group_changes, pairs_from_spans, recurring_changes


class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def wired(monkeypatch):
    """A configured bridge whose HTTP calls are recorded instead of made."""
    monkeypatch.setattr(mng_bridge, "base_url", lambda: "https://mng.example")
    monkeypatch.setattr(mng_bridge, "secret", lambda: "s3cret")
    sent = []

    def fake_post(url, data=None, timeout=None, headers=None):
        sent.append({"url": url, "body": json.loads(data.decode()), "headers": headers})
        return FakeResponse()

    monkeypatch.setattr(mng_bridge.requests, "post", fake_post)
    return sent


class Clock:
    """A clock the test moves by hand, so a throttle test costs no wall-clock time."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def reporter():
    clock = Clock()
    return mng_bridge.ProgressReporter("job-1", clock=clock), clock


EVENT = {"para": 4, "change": "shows → show", "spans": [
    {"op": "same", "text": "The results "},
    {"op": "del", "text": "shows "},
    {"op": "ins", "text": "show "},
    {"op": "same", "text": "a trend."},
]}


def test_a_report_is_signed_and_carries_the_work(wired):
    r, _ = reporter()
    assert r.send(0.4, "Copyediting — paragraph 4 of 9", [EVENT]) is True, (
        "the first report of a job goes at once")

    call = wired[0]
    assert call["url"].endswith("/api/v1/copyedit/bridge/progress/job-1/")
    assert call["headers"]["X-CE4-Signature"], "signed like every other bridge call"
    assert call["body"]["stage"].startswith("Copyediting")
    assert call["body"]["events"][0]["para"] == 4


def test_reports_are_throttled(wired):
    """The pool can finish several paragraphs a second; the screen cannot read them."""
    r, clock = reporter()
    assert r.send(0.1, "a", [EVENT]) is True
    clock.t += 1
    assert r.send(0.2, "b", [EVENT]) is False, "one second later is too soon"
    clock.t += 5
    assert r.send(0.3, "c", [EVENT]) is True, "and five seconds later is not"
    assert len(wired) == 2


def test_nothing_is_lost_by_being_throttled(wired):
    """A skipped report still counts towards the patterns the next one carries."""
    r, clock = reporter()
    r.send(0.1, "a", [dict(EVENT, para=1)])
    clock.t += 1
    r.send(0.2, "b", [dict(EVENT, para=2)])   # throttled away
    clock.t += 5
    r.send(0.3, "c", [dict(EVENT, para=3)])

    patterns = wired[-1]["body"]["patterns"]
    assert patterns and patterns[0]["count"] == 3, (
        "the paragraph nobody reported still happened")
    assert patterns[0]["from"] == "shows" and patterns[0]["to"] == "show"


def test_an_unreachable_platform_does_not_raise(monkeypatch, wired):
    def explode(*_a, **_k):
        raise mng_bridge.requests.RequestException("connection refused")

    monkeypatch.setattr(mng_bridge.requests, "post", explode)
    r, _ = reporter()
    assert r.send(0.5, "s", [EVENT]) is False, "a failed report is not a failed job"


def test_a_refusal_is_logged_once_not_once_per_tick(monkeypatch, capsys):
    monkeypatch.setattr(mng_bridge, "base_url", lambda: "https://mng.example")
    monkeypatch.setattr(mng_bridge, "secret", lambda: "s3cret")
    monkeypatch.setattr(mng_bridge.requests, "post",
                        lambda *a, **k: FakeResponse(400, "no claimed job"))
    r = mng_bridge.ProgressReporter("job-1", clock=lambda: 10_000)
    for _ in range(5):
        r.send(0.5, "s", [EVENT], force=True)

    assert capsys.readouterr().out.count("not accepted") == 1


def test_only_platform_jobs_get_a_reporter(monkeypatch):
    monkeypatch.setattr(mng_bridge, "base_url", lambda: "https://mng.example")
    monkeypatch.setattr(mng_bridge, "secret", lambda: "s3cret")
    assert mng_bridge.reporter_for({"mng_job_id": "abc"}) is not None
    assert mng_bridge.reporter_for({}) is None, "a local upload reports to nobody"


def test_an_unconfigured_bridge_gives_no_reporter(monkeypatch):
    monkeypatch.setattr(mng_bridge, "base_url", lambda: "")
    monkeypatch.setattr(mng_bridge, "secret", lambda: "")
    assert mng_bridge.reporter_for({"mng_job_id": "abc"}) is None


# ----------------------------------------------------------------------------------
# One pattern implementation, two sources
# ----------------------------------------------------------------------------------


def test_spans_and_paragraphs_count_the_same_patterns():
    """The running number and the final number must not be able to disagree.

    The live path only ever sees diff spans; the report sees both versions of the
    paragraph. They go through the same grouping, so the same manuscript gives the same
    answer either way — which is the whole reason the pair extraction was split out.
    """
    before = ["Fig. 1 shows it."] * 4
    after = ["Figure 1 shows it."] * 4
    from_paragraphs = recurring_changes(before, after)

    spans = [{"op": "del", "text": "Fig. "}, {"op": "ins", "text": "Figure "},
             {"op": "same", "text": "1 shows it."}]
    from_spans = group_changes(
        [(i + 1, old, new) for i in range(4) for old, new in pairs_from_spans(spans)])

    assert from_paragraphs == from_spans
    assert from_paragraphs[0]["from"] == "Fig." and from_paragraphs[0]["count"] == 4


def test_an_insertion_with_no_deletion_before_it_is_not_a_pair():
    """"Added 'the' forty times" is not a pattern anybody can act on."""
    assert pairs_from_spans([{"op": "same", "text": "x "},
                             {"op": "ins", "text": "the "}]) == []
