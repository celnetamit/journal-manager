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
    def __init__(self, status_code=200, text="ok", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json here")
        return self._payload


@pytest.fixture
def wired(monkeypatch):
    """A configured bridge whose HTTP calls are recorded instead of made.

    `wired.reply` is what the platform answers with next — the decisions channel rides
    home on the response to our own report, so a test that cares about answers sets it.
    """
    monkeypatch.setattr(mng_bridge, "base_url", lambda: "https://mng.example")
    monkeypatch.setattr(mng_bridge, "secret", lambda: "s3cret")

    class Sent(list):
        reply = {"ok": True}
        status = 200          # set to 500 to make the platform refuse the next report

    sent = Sent()

    def fake_post(url, data=None, timeout=None, headers=None):
        sent.append({"url": url, "body": json.loads(data.decode()), "headers": headers})
        if sent.status != 200:
            return FakeResponse(sent.status, "gateway")
        return FakeResponse(payload=sent.reply)

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


def test_the_last_edits_stay_on_screen_after_the_copyedit_stage(wired):
    """Proofreading produces no edits; a panel that empties itself looks stopped."""
    r, clock = reporter()
    r.send(0.4, "Copyediting — paragraph 4 of 9", [EVENT])
    clock.t += 5
    r.send(0.7, "Proofreading...", [])

    assert wired[-1]["body"]["stage"] == "Proofreading..."
    assert wired[-1]["body"]["events"][0]["para"] == 4, "the last change is still shown"


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
# Asking the platform, and being answered by it
# ----------------------------------------------------------------------------------


ASK = {"kind": "review_changes", "idle_seconds": 30, "asked": 2, "decided": 0,
       "paragraphs": [{"index": 3, "para": 4, "spans": [{"op": "del", "text": "Fig. "}]}]}


def test_the_question_travels_on_the_progress_report(wired):
    r, _ = reporter()
    r.set_ask(ASK)
    r.send(0.6, "Your review", [], force=True)

    ask = wired[-1]["body"]["ask"]
    assert ask["asked"] == 2
    assert ask["paragraphs"][0]["para"] == 4, "the first report carries the paragraphs"


def test_the_paragraphs_are_sent_once_not_every_second(wired):
    """Forty paragraphs of somebody's manuscript, every 1.5s for ten minutes, otherwise."""
    r, clock = reporter()
    r.set_ask(ASK)
    r.send(0.6, "a", [], force=True)
    clock.t += 2
    r.send(0.6, "b", [])

    assert "paragraphs" not in wired[-1]["body"]["ask"]
    assert wired[-1]["body"]["ask"]["asked"] == 2, "the tally still goes every time"


def test_a_question_the_platform_never_received_is_sent_again(wired):
    """A report that failed did not ask anybody anything."""
    r, clock = reporter()
    r.set_ask(ASK)
    wired.status = 500
    r.send(0.6, "a", [], force=True)

    wired.status = 200                       # the platform comes back
    clock.t += 2
    r.send(0.6, "b", [], force=True)
    assert "paragraphs" in wired[-1]["body"]["ask"]


def test_the_countdown_is_refreshed_without_resending_the_question(wired):
    r, clock = reporter()
    r.set_ask(ASK)
    r.send(0.6, "a", [], force=True)
    r.update_ask(seconds_left=11, decided=1)
    clock.t += 2
    r.send(0.6, "b", [])

    assert wired[-1]["body"]["ask"]["seconds_left"] == 11
    assert wired[-1]["body"]["ask"]["decided"] == 1


def test_a_standing_question_makes_this_side_speak_more_often(wired):
    """Three seconds is fine for a bar and far too slow for a countdown."""
    r, clock = reporter()
    r.set_ask(ASK)
    r.send(0.6, "a", [], force=True)
    clock.t += 1.6
    assert r.send(0.6, "b", []) is True, "1.6s is enough while somebody is being asked"

    r.set_ask(None)
    clock.t += 1.6
    assert r.send(0.7, "c", []) is False, "and not enough once the question is gone"


def test_the_question_is_taken_off_the_screen_when_it_ends(wired):
    r, clock = reporter()
    r.set_ask(ASK)
    r.send(0.6, "a", [], force=True)
    r.set_ask(None)
    clock.t += 5
    r.send(0.62, "Applying your decisions...", [])

    assert "ask" not in wired[-1]["body"], (
        "no key at all — a question carried forward is one that can still be answered")


def test_decisions_come_back_on_the_response(wired):
    r, _ = reporter()
    wired.reply = {"ok": True, "answers": {"3": "reject", "5": "keep"}}
    r.send(0.6, "a", [], force=True)

    assert r.take_answers() == {"3": "reject", "5": "keep"}
    assert r.take_answers() == {}, "taken once; the gate records them itself"


def test_only_the_two_words_the_gate_acts_on_are_kept(wired):
    """A platform answering with anything else must not be able to invent a decision."""
    r, _ = reporter()
    wired.reply = {"ok": True, "answers": {"3": "maybe", "4": {"op": "drop"}, "5": "keep"}}
    r.send(0.6, "a", [], force=True)

    assert r.take_answers() == {"5": "keep"}


def test_a_platform_that_answers_with_a_login_page_costs_nothing(monkeypatch):
    monkeypatch.setattr(mng_bridge, "base_url", lambda: "https://mng.example")
    monkeypatch.setattr(mng_bridge, "secret", lambda: "s3cret")
    monkeypatch.setattr(mng_bridge.requests, "post",
                        lambda *a, **k: FakeResponse(200, "<html>Sign in</html>"))
    r, _ = reporter()

    assert r.send(0.6, "a", [], force=True) is True
    assert r.take_answers() == {}


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
