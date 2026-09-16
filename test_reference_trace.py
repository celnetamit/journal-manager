"""What the reference guards could see, recorded on the job.

Three days running the question "did this guard run, and on what" could not be answered
from anything the job kept:

* #67, #69, #70 — the census was blind to an unnumbered bibliography and said nothing.
* #45, #68 — blind to an initials-first one, and said nothing.
* #91, #94 — delivered references whose links had been deleted; handed those files
  afterwards the guard restores them, so the state it saw during the run was not the
  state on disk, and there was no record of either.

A guard that finds no bibliography returns silently and looks exactly like a guard that
found nothing wrong. The trace is the difference.
"""

from __future__ import annotations

import docx
import pytest

import pipeline

_OPTS = dict(
    edit_style="Chicago Manual of Style (CMOS)", ref_style="Vancouver",
    lang_type="UK English", enabled_rule_ids=None, reorder_citations=False,
    use_crossref=False, use_serper=False, ai_review_enabled=False,
    cover_letter_enabled=False, journals_enabled=False,
    plagiarism_scan_enabled=False, polish_enabled=False, edit_tables=False,
    custom_dict="", custom_rules="", user_id=None, filename="t.docx",
)

_URL = "https://doi.org/10.36676/jmk"


def _doc(tmp_path, paragraphs):
    d = docx.Document()
    for t in paragraphs:
        d.add_paragraph(t)
    p = tmp_path / "t.docx"
    d.save(str(p))
    return str(p)


@pytest.fixture(autouse=True)
def _no_model(monkeypatch, tmp_path):
    """The trace is about what the guards saw, so the copyedit is a no-op."""
    import editor
    monkeypatch.setattr(editor, "_generate_text", lambda *a, **k: "{}")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_the_trace_records_what_the_bibliography_held(tmp_path):
    """Job #94's last two entries, which arrived with links and were delivered
    without them."""
    path = _doc(tmp_path, [
        "1. Introduction",
        "Digital finance reaches farmers through several channels [1].",
        "REFERENCES: ",
        "Vasudevan, A., Rani, P. J., & Qian, C. (2025). Fintech for sustainable "
        f"agriculture. Frontiers in Sustainable Food Systems, 9. {_URL}1614553",
        "Sethi, N. (2024). Role of banks in scaling digital finance for rural growth "
        f"in India. Journal of Multidisciplinary Knowledge, 4(2), 29-33. {_URL}",
    ])
    trace = pipeline.run_pipeline(_OPTS, path, lambda *a, **k: None)["reference_trace"]
    assert trace["bibliography_found"] is True
    assert trace["entries"] == 2
    assert trace["works_readable"] == 2
    assert trace["links_in_original"] == 2
    assert trace["links_missing_at_redline"] == 0, "nothing removed them here"


def test_a_manuscript_with_no_bibliography_says_so(tmp_path):
    """The silent case. `bibliography_found: False` is the answer that was missing on
    #67 and #45 — the guard did not pass the list, it never saw one."""
    path = _doc(tmp_path, ["1. Introduction", "A manuscript with no reference list."])
    trace = pipeline.run_pipeline(_OPTS, path, lambda *a, **k: None)["reference_trace"]
    assert trace["bibliography_found"] is False
    assert trace["entries"] == 0
    assert trace["links_in_original"] == 0


def test_an_unreadable_entry_is_counted_apart_from_a_readable_one(tmp_path):
    """Job #70 ¶524 carries no year, so it has no identity and sits outside the
    census. That is correct and it should be visible, not inferred."""
    path = _doc(tmp_path, [
        "1. Introduction",
        "Body text citing something [1].",
        "References",
        "Barot, M. B., & Japee, G. (2021). Indian Rural Banking. A Global Journal of "
        "Social Sciences, 4(2), 56-59.",
        "VIRANI, D. V. A STUDY ON THE ANALYSIS OF FINANCIAL PERFORMANCE WITH "
        "REFERENCE TO REGIONAL RURAL BANKS (RRBS). MULTIDISCIPLINARY RESEARCH.",
    ])
    trace = pipeline.run_pipeline(_OPTS, path, lambda *a, **k: None)["reference_trace"]
    assert trace["entries"] == 2
    assert trace["works_readable"] == 1
