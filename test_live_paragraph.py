"""The live view shows the paragraph, not just a note that something changed.

Amit, 15 Sep 2026: "ye paragraph ko padh raha ho toh exact paragraph bhi samne dikhe,
usme change kar raha hai toh wo change hota hua dikhe" — the VS Code diff, for a
manuscript. These pin the two things that make that readable and are easy to get wrong:
the diff is on words, and the feed cannot grow without bound.
"""

import editor


def test_a_changed_paragraph_travels_with_its_text():
    before = ["The results shows a clear trend."]
    after = ["The results show a clear trend."]
    events = editor._chunk_edits(before, after, [0])

    assert events[0]["para"] == 1
    assert events[0]["spans"], "the paragraph itself must be in the feed"
    rebuilt = "".join(s["text"] for s in events[0]["spans"] if s["op"] != "del")
    assert rebuilt.strip() == after[0]


def test_the_diff_is_on_words_not_characters():
    """A character diff renders H2O -> H₂O as "2" -> "₂", which teaches a reader nothing."""
    spans = editor.word_spans("We measured H2O uptake.", "We measured H₂O uptake.")
    changed = [s["text"].strip() for s in spans if s["op"] in ("del", "ins")]
    assert "H2O" in changed and "H₂O" in changed


def test_an_untouched_paragraph_produces_no_event():
    same = ["Nothing here needs changing."]
    assert editor._chunk_edits(same, list(same), [0]) == []


def test_the_text_is_capped():
    """Forty of these are read every two seconds; the row is a progress view, not a copy
    of the manuscript."""
    long_para = "word " * 4000
    spans = editor.word_spans(long_para, long_para.replace("word", "term", 1))
    assert sum(len(s["text"]) for s in spans) <= editor.FEED_TEXT_LIMIT + 8


def test_deletions_and_insertions_are_both_kept():
    spans = editor.word_spans("All the tests was performed at once.",
                              "All the tests were performed.")
    ops = {s["op"] for s in spans}
    assert "del" in ops and "ins" in ops
    assert "".join(s["text"] for s in spans if s["op"] != "ins").strip() == \
        "All the tests was performed at once."


def test_a_chunk_is_capped_at_four_paragraphs():
    before = [f"Paragraph {i} with an error is here." for i in range(9)]
    after = [f"Paragraph {i} without an error is here." for i in range(9)]
    assert len(editor._chunk_edits(before, after, list(range(9)))) == 4
