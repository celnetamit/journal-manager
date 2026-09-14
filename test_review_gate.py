"""Manual mode: the gate that asks, and the clock that guarantees it never waits forever.

Everything here runs on a fake clock and a fake job store, so the suite does not spend
thirty real seconds proving that thirty seconds pass. The rule being pinned is the one
Amit gave on 15 Sep 2026: wait 30 seconds for an answer, and if none comes, apply what
the AI proposed.
"""

from __future__ import annotations

import pytest

import pipeline


class FakeJobs:
    """The two columns the gate talks to, and a script of what the reviewer does.

    `answers_at` maps a clock reading to the answers visible from then on — which is
    how a test says "somebody clicked Undo on paragraph 2 at t=10".
    """

    def __init__(self, answers_at=None, cancelled_at=None):
        self.asked = None
        self.cleared = False
        self.answers_at = answers_at or {}
        self.cancelled_at = cancelled_at
        self.now = 0.0

    # --- the auth surface the gate uses ---
    def ask_job(self, job_id, payload):
        self.asked = payload

    def clear_job_ask(self, job_id):
        self.cleared = True

    def job_is_cancelled(self, job_id):
        return self.cancelled_at is not None and self.now >= self.cancelled_at

    def read_job_answer(self, job_id):
        current = {}
        for t, ans in sorted(self.answers_at.items()):
            if self.now >= t:
                current = ans
        return dict(current)


def run_gate(originals, edited, jobs, idle=30, max_seconds=600):
    """Drive the gate with a clock that only moves when the gate sleeps."""
    def clock():
        return jobs.now

    def sleep(seconds):
        jobs.now += seconds

    return pipeline.review_gate(
        1, originals, edited, None, idle_seconds=idle, max_seconds=max_seconds,
        auth_mod=jobs, sleep=sleep, clock=clock)


ORIGINAL = ["The results shows a trend.", "Fig. 1 is here.", "Untouched line."]
EDITED = ["The results show a trend.", "Figure 1 is here.", "Untouched line."]


def test_nothing_changed_asks_nobody():
    """A manuscript the copyedit left alone must not stop to ask about nothing."""
    jobs = FakeJobs()
    out, summary = run_gate(ORIGINAL, list(ORIGINAL), jobs)
    assert out == ORIGINAL
    assert jobs.asked is None
    assert summary["asked"] == 0


def test_only_changed_paragraphs_are_put_to_the_reviewer():
    jobs = FakeJobs(answers_at={0: {"0": "accept", "1": "accept"}})
    _, summary = run_gate(ORIGINAL, EDITED, jobs)
    assert [p["para"] for p in jobs.asked["paragraphs"]] == [1, 2]
    assert summary["asked"] == 2
    # The question carries the diff, not two blobs of text to compare by eye.
    assert any(s["op"] == "ins" for s in jobs.asked["paragraphs"][0]["spans"])


def test_silence_applies_what_the_ai_proposed():
    """The rule itself: nobody answers, the timer runs out, the edits stand."""
    jobs = FakeJobs()
    out, summary = run_gate(ORIGINAL, EDITED, jobs, idle=30)
    assert out == EDITED
    assert summary["decided_by"] == "timeout"
    assert summary["accepted"] == 2 and summary["rejected"] == 0
    # And it did not wait appreciably longer than it promised.
    assert 30 <= summary["waited_seconds"] <= 32
    assert jobs.cleared, "the question must come down when the job stops waiting"


def test_a_rejected_change_restores_the_author_exactly():
    jobs = FakeJobs(answers_at={0: {"0": "reject", "1": "accept"}})
    out, summary = run_gate(ORIGINAL, EDITED, jobs)
    assert out[0] == ORIGINAL[0], "rejected paragraph must be the author's own words"
    assert out[1] == EDITED[1]
    assert summary["rejected"] == 1 and summary["accepted"] == 1
    assert summary["decided_by"] == "reviewer"


def test_deciding_everything_ends_the_wait_immediately():
    """A reviewer who answers every paragraph should not then sit out the timer."""
    jobs = FakeJobs(answers_at={0: {"0": "accept", "1": "reject"}})
    _, summary = run_gate(ORIGINAL, EDITED, jobs, idle=30)
    assert summary["waited_seconds"] <= 2


def test_each_decision_restarts_the_clock():
    """Thirty seconds is per decision, not for the whole review.

    Answering one paragraph at t=25 and the next at t=50 must not be cut off at 30 —
    otherwise the panel is taken away from the only person using it.
    """
    jobs = FakeJobs(answers_at={25: {"0": "reject"}, 50: {"0": "reject", "1": "reject"}})
    out, summary = run_gate(ORIGINAL, EDITED, jobs, idle=30)
    assert summary["decided_by"] == "reviewer"
    assert out == ORIGINAL, "both changes were refused"
    assert summary["waited_seconds"] >= 50


def test_partial_review_keeps_the_answers_it_got():
    """Answer one, walk away: that answer stands and the rest apply as proposed."""
    jobs = FakeJobs(answers_at={5: {"1": "reject"}})
    out, summary = run_gate(ORIGINAL, EDITED, jobs, idle=30)
    assert out[0] == EDITED[0], "undecided change applies"
    assert out[1] == ORIGINAL[1], "the decision that was made is honoured"
    assert summary["decided_by"] == "partly reviewed"


def test_a_busy_reviewer_still_hits_the_ceiling():
    """Constant activity must not hold the worker thread for ever."""
    jobs = FakeJobs(answers_at={t: {"0": f"accept{t}"} for t in range(0, 400, 5)})
    _, summary = run_gate(ORIGINAL, EDITED, jobs, idle=30, max_seconds=60)
    assert summary["decided_by"] == "time limit"
    assert summary["waited_seconds"] <= 62


def test_cancelling_the_job_stops_the_wait():
    jobs = FakeJobs(cancelled_at=4)
    with pytest.raises(pipeline.JobCancelled):
        run_gate(ORIGINAL, EDITED, jobs, idle=30)
    assert jobs.cleared, "a cancelled job must not leave a question on the page"


def test_an_unreadable_answer_is_not_treated_as_activity():
    """A failed read returns None; that must neither reset the clock nor lose a decision."""
    class Flaky(FakeJobs):
        def read_job_answer(self, job_id):
            self.reads = getattr(self, "reads", 0) + 1
            return None if self.reads % 2 else super().read_job_answer(job_id)

    jobs = Flaky(answers_at={2: {"0": "reject"}})
    out, summary = run_gate(ORIGINAL, EDITED, jobs, idle=30)
    assert out[0] == ORIGINAL[0], "the decision survived the flaky reads"
    # Still finished on the idle rule rather than hanging on the dropped polls.
    assert summary["waited_seconds"] <= 40
