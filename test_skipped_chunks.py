"""What happens when the model cannot answer for a chunk.

The old behaviour was to return the paragraphs unchanged and `print` a warning to a
container log. On a real 70-paragraph manuscript that happened four times — twenty
paragraphs that were never copyedited — and the job finished `done`, the report said
nothing, and an untouched paragraph is indistinguishable from one that needed no
changes. The author would have been handed a manuscript with a hole in it.

These tests are mostly about the reporting, not the retry. A retry that works and a
silence that hides the failures still ships holes; the reporting is what makes the
hole visible.
"""

import editor as E


def _generate(*responses):
    """A stand-in for `_generate_text` that returns each response in turn."""
    calls = {"n": 0}

    def gen(prompt, settings=None, response_mime_type=None):
        i = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        out = responses[i]
        if isinstance(out, Exception):
            raise out
        return out

    gen.calls = calls
    return gen


GOOD = '[{"edited": "The result was significant."}, {"edited": "A second one."}]'
CHUNK = ["The result was signifcant.", "A second one."]


def test_a_good_response_reports_no_failure(monkeypatch):
    monkeypatch.setattr(E, "_generate_text", _generate(GOOD))
    texts, queries, failure = E.ai_edit_chunk(
        CHUNK, {}, "CMOS", "Vancouver", "US English", "", False)
    assert failure is None
    assert texts[0] == "The result was significant."


def test_a_malformed_response_is_retried_once(monkeypatch):
    """A bad response is usually a one-off; the same prompt answered again parses.
    Retrying is cheaper than shipping the chunk unedited."""
    gen = _generate("this is not json at all", GOOD)
    monkeypatch.setattr(E, "_generate_text", gen)
    texts, _, failure = E.ai_edit_chunk(
        CHUNK, {}, "CMOS", "Vancouver", "US English", "", False)
    assert gen.calls["n"] == 2
    assert failure is None
    assert texts[0] == "The result was significant."


def test_two_failures_report_a_reason_and_change_nothing(monkeypatch):
    monkeypatch.setattr(E, "_generate_text", _generate("nonsense", "still nonsense"))
    texts, queries, failure = E.ai_edit_chunk(
        CHUNK, {}, "CMOS", "Vancouver", "US English", "", False)
    assert failure and "no JSON array" in failure
    # Unchanged is the only safe outcome — but it must not be a silent one.
    assert texts == CHUNK
    assert queries == []


def test_a_short_array_is_a_failure_not_a_partial_edit(monkeypatch):
    """Two paragraphs in, one out. Zipping that would apply the first paragraph's
    edit and leave the second — or worse, shift them by one."""
    short = '[{"edited": "only one"}]'
    monkeypatch.setattr(E, "_generate_text", _generate(short, short))
    texts, _, failure = E.ai_edit_chunk(
        CHUNK, {}, "CMOS", "Vancouver", "US English", "", False)
    assert failure and "1 items for 2 paragraphs" in failure
    assert texts == CHUNK


def test_an_exception_is_reported_rather_than_swallowed(monkeypatch):
    monkeypatch.setattr(E, "_generate_text",
                        _generate(RuntimeError("upstream 503")))
    texts, _, failure = E.ai_edit_chunk(
        CHUNK, {}, "CMOS", "Vancouver", "US English", "", False)
    assert failure and "upstream 503" in failure
    assert texts == CHUNK


def test_the_orchestrator_names_which_paragraphs_were_missed(monkeypatch):
    """The count alone is not enough — an editor needs to know *which* paragraphs to
    read themselves."""
    monkeypatch.setattr(E, "_generate_text", _generate("nonsense", "nonsense"))
    paras = [f"Paragraph number {i} with enough text in it to be a real one."
             for i in range(7)]

    edited, queries, skipped = E.process_document_async(
        paras, {}, "CMOS", "Vancouver", "US English", "", False, None)

    assert edited == paras                       # nothing was changed
    missed = sorted(i for c in skipped for i in c["indices"])
    assert missed == list(range(7))
    assert all(c["reason"] for c in skipped)


def test_a_fully_successful_run_reports_nothing_skipped(monkeypatch):
    def gen(prompt, settings=None, response_mime_type=None):
        import json
        # The prompt ends with "Input JSON:\n<array>". Matching the first "[" in the
        # whole prompt instead picks up the "[1]" in the house-rule examples — which
        # is a bug in the fake, not in the code, and it took a failing test that
        # looked like a real defect to notice.
        payload = json.loads(prompt.rsplit("Input JSON:", 1)[1].strip())
        return json.dumps([{"edited": t} for t in payload])

    monkeypatch.setattr(E, "_generate_text", gen)
    paras = [f"Paragraph {i} with enough text to count as a real one." for i in range(6)]

    edited, _, skipped = E.process_document_async(
        paras, {}, "CMOS", "Vancouver", "US English", "", False, None)

    assert skipped == []
    assert edited == paras
