"""Repeated changes, counted once.

Amit, 15 Sep 2026: "pattern recognition daal do, isse kaam aur asaan ho jayega". A
manuscript that writes "Fig." forty times has one habit, not forty problems — and a
reviewer asked to approve it forty times stops reading by the sixth.

A pattern here is countable, not described: a pair of (what was there, what replaced it)
that provably happened N times, with the paragraph numbers to check it in.
"""

import editor


def test_a_repeated_substitution_is_reported_once():
    before = [f"See Fig. {i} for the result." for i in range(6)]
    after = [f"See Figure {i} for the result." for i in range(6)]
    patterns = editor.recurring_changes(before, after)

    assert len(patterns) == 1
    assert patterns[0]["from"] == "Fig." and patterns[0]["to"] == "Figure"
    assert patterns[0]["count"] == 6
    assert patterns[0]["paragraphs"][:3] == [1, 2, 3]


def test_twice_is_not_a_pattern():
    """Two is a coincidence on a long manuscript; three is a habit."""
    before = ["Fig. 1 here.", "Fig. 2 here.", "Nothing to change."]
    after = ["Figure 1 here.", "Figure 2 here.", "Nothing to change."]
    assert editor.recurring_changes(before, after) == []


def test_a_rewritten_sentence_is_not_a_pattern():
    before = ["The methodology employed within this study was of a nature that was novel."] * 4
    after = ["The method was novel."] * 4
    assert all(len(p["from"]) <= 60 for p in editor.recurring_changes(before, after))


def test_sentence_initial_occurrences_group_with_the_rest():
    before = ["Fig. 1 shows this.", "As in Fig. 2.", "Compare Fig. 3."]
    after = ["Figure 1 shows this.", "As in Figure 2.", "Compare Figure 3."]
    patterns = editor.recurring_changes(before, after)
    assert len(patterns) == 1 and patterns[0]["count"] == 3


def test_an_untouched_manuscript_has_no_patterns():
    same = ["Nothing changes here."] * 5
    assert editor.recurring_changes(same, list(same)) == []


def test_the_biggest_habit_comes_first():
    before = ["Fig. a &c"] * 5 + ["&d"] * 3
    after = ["Figure a andc"] * 5 + ["andd"] * 3
    patterns = editor.recurring_changes(before, after)
    assert patterns[0]["count"] >= patterns[-1]["count"]
