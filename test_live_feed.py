"""The live feed: what a running job shows about the work it is doing.

Before this, a job in flight showed a bar and one unchanging line of text for the whole
copyedit — which answers "is it finished?" and nothing else. These tests cover the two
things that make the feed worth having and are easy to get quietly wrong:

* the edit lines are **readable** — diffed on words, not characters, because a character
  diff renders "H2O" → "H₂O" as `"2" → "₂"` and a reader learns nothing from it;
* the feed is **bounded and ordered** — a long manuscript must not grow the row without
  limit, and the newest edit must survive the trim.
"""

from __future__ import annotations

import difflib
import json
import os
import re

import pytest


@pytest.fixture()
def auth_mod(tmp_path, monkeypatch):
    """Isolated SQLite DB per test — the same fixture the job-queue tests use."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import auth
    return auth


def _helpers():
    """Load the two feed helpers without importing all of editor.py's dependencies."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "editor.py"),
               encoding="utf-8").read()
    ns = {"difflib": difflib, "re": re}
    exec(src[src.index("def _edit_summary("):src.index("def process_document_async(")], ns)
    return ns["_edit_summary"], ns["_chunk_edits"]


def test_summary_is_word_level_not_character_level():
    summary, _ = _helpers()
    assert summary("The H2O content", "The H₂O content") == "…The “H2O” → “H₂O”"
    assert summary("data was analysed", "data were analysed") == "…data “was” → “were”"


def test_unchanged_and_whitespace_only_produce_nothing():
    """A feed that reports non-edits is noise, and noise is what stops people reading it."""
    summary, _ = _helpers()
    assert summary("Same text.", "Same text.") == ""
    assert summary("  padded  ", "padded") == ""


def test_chunk_edits_skips_untouched_paragraphs_and_numbers_from_one():
    _, chunk_edits = _helpers()
    paras = ["The H2O content", "Untouched.", "Results shows growth"]
    edited = ["The H₂O content", "Untouched.", "Results show growth"]
    out = chunk_edits(paras, edited, [0, 1, 2])
    assert [e["para"] for e in out] == [1, 3]          # 1-based, and no row for para 2
    assert "H₂O" in out[0]["change"]


def test_feed_is_capped_and_keeps_the_newest(auth_mod):
    """The row must not grow with the manuscript, and the trim must drop the oldest."""
    job_id = auth_mod.create_job(1, "m.docx", "/tmp/m.docx", "{}")
    for i in range(auth_mod.LIVE_FEED_MAX + 15):
        auth_mod.append_job_events(job_id, [{"para": i + 1, "change": f"edit {i}"}])

    feed = json.loads(auth_mod.get_job(job_id)["live_json"])
    assert len(feed) == auth_mod.LIVE_FEED_MAX
    assert feed[-1]["change"] == f"edit {auth_mod.LIVE_FEED_MAX + 14}"   # newest kept
    assert feed[0]["change"] != "edit 0"                                 # oldest dropped


def test_appending_nothing_is_a_no_op(auth_mod):
    """An empty chunk (nothing changed) must not touch the row or raise."""
    job_id = auth_mod.create_job(1, "m.docx", "/tmp/m.docx", "{}")
    auth_mod.append_job_events(job_id, [])
    auth_mod.append_job_events(job_id, None)
    assert auth_mod.get_job(job_id).get("live_json") in (None, "")
