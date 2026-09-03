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

    def gen(prompt, settings=None, response_mime_type=None, **kwargs):
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


def test_a_short_array_at_the_smallest_size_is_still_a_failure(monkeypatch):
    """One paragraph in, none out, and nothing left to split. The reason must reach
    the caller and the text must be untouched."""
    monkeypatch.setattr(E, "_generate_text", _generate("[]", "[]"))
    texts, _, failure = E.ai_edit_chunk(
        ["The result was signifcant."], {}, "CMOS", "Vancouver", "US English", "", False)
    assert failure and "0 items for 1 paragraphs" in failure
    assert texts == ["The result was signifcant."]


def test_a_short_array_is_retried_in_halves(monkeypatch):
    """Measured on real manuscripts: the model returns an array one element short —
    "19 items for 20 paragraphs" — and the old behaviour abandoned all twenty after two
    identical retries. A shorter list is easier to answer correctly, so the chunk is
    halved and retried; here both halves come back right and nothing is lost."""
    def gen(prompt, settings=None, response_mime_type=None, **kwargs):
        # Answers with one element, which is wrong for the pair and right for a single.
        return '[{"edited": "edited text"}]'

    monkeypatch.setattr(E, "_generate_text", gen)
    texts, _, failure = E.ai_edit_chunk(
        CHUNK, {}, "CMOS", "Vancouver", "US English", "", False)
    assert failure is None
    assert texts == ["edited text", "edited text"]


def test_the_returned_list_is_always_the_length_of_the_input(monkeypatch):
    """The contract the redline depends on. `generate_redline_docx` walks
    `zip(doc.paragraphs, edited_paragraphs)`, so a list that loses or gains an entry
    writes every later tracked change onto the wrong paragraph — in a file that still
    opens and still looks like a redline. Whatever the model does, this must hold."""
    for response in ("[]", "not json", '[{"edited": "one"}]',
                     '[{"edited": "a"}, {"edited": "b"}, {"edited": "c"}]'):
        monkeypatch.setattr(E, "_generate_text", _generate(response, response))
        texts, _, _ = E.ai_edit_chunk(
            CHUNK, {}, "CMOS", "Vancouver", "US English", "", False)
        assert len(texts) == len(CHUNK), response


def test_a_query_from_the_second_half_keeps_its_real_index(monkeypatch):
    """`local_index` is relative to the chunk it was raised in. When a chunk is split,
    the right half's indices have to move up by the length of the left one, or every
    query lands on the wrong paragraph."""
    def gen(prompt, settings=None, response_mime_type=None, **kwargs):
        if "A second one." in prompt:
            return '[{"edited": "A second one.", "query": "check this"}]'
        return '[{"edited": "The result was significant."}]'

    monkeypatch.setattr(E, "_generate_text", gen)
    _, queries, failure = E.ai_edit_chunk(
        CHUNK, {}, "CMOS", "Vancouver", "US English", "", False)
    assert failure is None
    assert len(queries) == 1
    assert queries[0]["local_index"] == 1


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
    def gen(prompt, settings=None, response_mime_type=None, **kwargs):
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


# ------------------------------------------------------------- reasoning-token cap

def test_the_reasoning_cap_has_a_default(monkeypatch):
    """Measured on a real chunk: uncapped, the model burned 3,924 completion tokens
    reasoning and returned empty content — which reaches the parser as "no JSON
    array" and skipped 25 of 154 paragraphs. Capped, the same chunk answers."""
    monkeypatch.delenv("REASONING_MAX_TOKENS", raising=False)
    assert E._reasoning_max_tokens() == 512


def test_the_cap_can_be_raised_or_removed(monkeypatch):
    monkeypatch.setenv("REASONING_MAX_TOKENS", "2048")
    assert E._reasoning_max_tokens() == 2048
    monkeypatch.setenv("REASONING_MAX_TOKENS", "0")
    assert E._reasoning_max_tokens() == 0


def test_a_nonsense_cap_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("REASONING_MAX_TOKENS", "lots")
    assert E._reasoning_max_tokens() == 512


def test_the_cap_is_sent_to_the_provider(monkeypatch):
    sent = {}

    def fake_post(url, payload, headers=None, **kw):
        sent.update(payload)
        return {"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(E, "_post_json", fake_post)
    monkeypatch.delenv("REASONING_MAX_TOKENS", raising=False)
    E._generate_text("hello", settings={
        "provider": "openrouter", "base_url": "https://x/api/v1",
        "text_model": "m", "api_key": "k"}, response_mime_type="application/json")
    assert sent["reasoning"] == {"max_tokens": 512}
    assert sent["response_format"] == {"type": "json_object"}


def test_no_cap_is_sent_when_it_is_switched_off(monkeypatch):
    sent = {}

    def fake_post(url, payload, headers=None, **kw):
        sent.update(payload)
        return {"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(E, "_post_json", fake_post)
    monkeypatch.setenv("REASONING_MAX_TOKENS", "0")
    E._generate_text("hello", settings={
        "provider": "openrouter", "base_url": "https://x/api/v1",
        "text_model": "m", "api_key": "k"})
    assert "reasoning" not in sent


def test_empty_content_is_named_rather_than_returned_as_an_empty_string(monkeypatch):
    """This is the actual production failure. Returning "" makes the caller report
    "no JSON array", which describes the symptom and hides the cause."""
    def fake_post(url, payload, headers=None, **kw):
        return {"choices": [{"message": {"content": ""}, "finish_reason": "error"}],
                "usage": {"completion_tokens": 3924,
                          "completion_tokens_details": {"reasoning_tokens": 3900}}}

    monkeypatch.setattr(E, "_post_json", fake_post)
    try:
        E._generate_text("hello", settings={
            "provider": "openrouter", "base_url": "https://x/api/v1",
            "text_model": "m", "api_key": "k"})
    except RuntimeError as exc:
        msg = str(exc)
        assert "empty content" in msg
        assert "finish_reason=error" in msg
        assert "reasoning_tokens=3900" in msg
    else:
        raise AssertionError("an empty answer must not pass as a valid response")
