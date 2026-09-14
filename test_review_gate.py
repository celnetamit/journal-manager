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
        #: Decisions the gate wrote back itself — the ones that arrived from the
        #: platform. They land in the same row a reviewer sitting in ce4 writes to.
        self.written: dict = {}

    # --- the auth surface the gate uses ---
    def ask_job(self, job_id, payload):
        self.asked = payload

    def clear_job_ask(self, job_id):
        self.cleared = True

    def job_is_cancelled(self, job_id):
        return self.cancelled_at is not None and self.now >= self.cancelled_at

    def answer_job(self, job_id, decisions):
        self.written.update({str(k): str(v) for k, v in (decisions or {}).items()})
        return dict(self.written)

    def read_job_answer(self, job_id):
        current = {}
        for t, ans in sorted(self.answers_at.items()):
            if self.now >= t:
                current = ans
        return {**current, **self.written}


class FakeReporter:
    """The platform end: what it was shown, and what it says people clicked.

    `answers_at` maps a clock reading to the decisions that arrive from then on. They are
    handed over once, as the real one does — `take_answers` empties itself, because the
    gate records them and the job row is then the only place they live.
    """

    def __init__(self, jobs, answers_at=None, raises=False):
        self.jobs = jobs
        self.answers_at = answers_at or {}
        self.raises = raises
        self.ask = None
        self.asks: list = []
        self.stages: list = []
        self.delivered: set = set()

    def set_ask(self, payload):
        self.ask = dict(payload) if payload else None
        self.asks.append(self.ask)

    def update_ask(self, **fields):
        if self.ask is not None:
            self.ask.update(fields)

    def send(self, progress, stage, events, force=False):
        if self.raises:
            raise RuntimeError("the platform went away")
        self.stages.append((stage, dict(self.ask) if self.ask else None))
        return True

    def take_answers(self):
        out = {}
        for t, answers in sorted(self.answers_at.items()):
            if self.jobs.now >= t and t not in self.delivered:
                self.delivered.add(t)
                out.update(answers)
        return out


def run_gate(originals, edited, jobs, idle=30, max_seconds=600, reporter=None):
    """Drive the gate with a clock that only moves when the gate sleeps."""
    def clock():
        return jobs.now

    def sleep(seconds):
        jobs.now += seconds

    return pipeline.review_gate(
        1, originals, edited, None, idle_seconds=idle, max_seconds=max_seconds,
        auth_mod=jobs, sleep=sleep, clock=clock, reporter=reporter)


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


# ----------------------------------------------------------------------------------
# Answered from manuscript-ngine
# ----------------------------------------------------------------------------------
#
# The manuscript came from the platform, so the person who can answer is looking at it
# there — not at ce4, which no editor has ever opened. The question rides out on the
# progress report and the decisions come back in its response; these tests pin that the
# gate treats one of those decisions exactly as it treats a click on its own panel.


def test_the_question_is_put_on_the_platform_too():
    jobs = FakeJobs()
    reporter = FakeReporter(jobs)
    run_gate(ORIGINAL, EDITED, jobs, idle=5, reporter=reporter)

    first = reporter.asks[0]
    assert first is not None and [p["para"] for p in first["paragraphs"]] == [1, 2]
    assert first["asked"] == 2
    assert jobs.asked is not None, "and ce4's own panel still asks it as well"


def test_a_decision_taken_on_the_platform_is_honoured():
    jobs = FakeJobs()
    reporter = FakeReporter(jobs, answers_at={3: {"0": "reject"}})
    out, summary = run_gate(ORIGINAL, EDITED, jobs, idle=30, reporter=reporter)

    assert out[0] == ORIGINAL[0], "the editor said no; the author's words stand"
    assert out[1] == EDITED[1]
    assert summary["rejected"] == 1
    assert jobs.written == {"0": "reject"}, "recorded in the job row, not held in memory"


def test_a_platform_decision_restarts_the_clock_like_any_other():
    jobs = FakeJobs()
    reporter = FakeReporter(jobs, answers_at={25: {"0": "reject"}})
    _, summary = run_gate(ORIGINAL, EDITED, jobs, idle=30, reporter=reporter)

    assert summary["waited_seconds"] >= 55, (
        "a reviewer working in the platform must not be timed out at 30s")


def test_deciding_everything_from_the_platform_ends_the_wait():
    jobs = FakeJobs()
    reporter = FakeReporter(jobs, answers_at={2: {"0": "keep", "1": "reject"}})
    out, summary = run_gate(ORIGINAL, EDITED, jobs, idle=30, reporter=reporter)

    assert summary["decided_by"] == "reviewer"
    assert summary["waited_seconds"] <= 6
    assert out == [EDITED[0], ORIGINAL[1], ORIGINAL[2]]


def test_the_countdown_the_platform_shows_is_the_real_one():
    jobs = FakeJobs()
    reporter = FakeReporter(jobs)
    run_gate(ORIGINAL, EDITED, jobs, idle=10, reporter=reporter)

    seconds = [ask["seconds_left"] for _, ask in reporter.stages if ask]
    assert seconds[0] > seconds[-1], "it counts down"
    assert min(seconds) <= 1


def test_the_question_comes_off_the_platform_when_the_gate_ends():
    jobs = FakeJobs()
    reporter = FakeReporter(jobs)
    run_gate(ORIGINAL, EDITED, jobs, idle=5, reporter=reporter)

    assert reporter.asks[-1] is None, (
        "a question left standing can be answered after the answer stops mattering")


def test_a_cancelled_job_takes_its_question_off_the_platform():
    jobs = FakeJobs(cancelled_at=4)
    reporter = FakeReporter(jobs)
    with pytest.raises(pipeline.JobCancelled):
        run_gate(ORIGINAL, EDITED, jobs, idle=30, reporter=reporter)

    assert reporter.asks[-1] is None


def test_a_platform_that_falls_over_mid_review_does_not_fail_the_job():
    """Every part of this is decoration over a pass that is already running."""
    jobs = FakeJobs()
    reporter = FakeReporter(jobs, raises=True)
    out, summary = run_gate(ORIGINAL, EDITED, jobs, idle=5, reporter=reporter)

    assert out == EDITED, "unanswered means applied, exactly as with nobody watching"
    assert summary["decided_by"] == "timeout"


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
