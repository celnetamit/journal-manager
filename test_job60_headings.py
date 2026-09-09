"""Word's own heading numbers, which no text edit can reach.

Job #60 removed `2.1` from `2.1 Overview of the Field:` correctly and still showed
"1. Introduction" in Word, because that "1." is not in the text — the paragraph carries
Word's automatic list numbering and Word draws the number at display time.

The document is built here rather than loaded, because the manuscript's own input file
is deleted after a run and the redline is not a fair substitute: its text sits in
tracked-change elements, so reading it gives a different answer than the pipeline sees.
"""

from __future__ import annotations

import io

from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

import house_layout as H
from docxmodel import read_structure


def _number(paragraph, num_id: int = 1, level: int = 0) -> None:
    """Apply Word's automatic list numbering, the way the manuscript does."""
    pPr = paragraph._p.get_or_add_pPr()
    numPr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), str(level))
    nid = OxmlElement("w:numId")
    nid.set(qn("w:val"), str(num_id))
    numPr.append(ilvl)
    numPr.append(nid)
    pPr.append(numPr)


def _doc(*paras):
    doc = Document()
    for text, numbered in paras:
        p = doc.add_paragraph(text)
        if numbered:
            _number(p)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return read_structure(buf)


def _flagged(structure):
    return {f.paragraph for f in H.check_auto_numbered_headings(structure)}


def test_a_one_word_heading_carrying_word_numbering_is_reported():
    """"Introduction" is the case the team actually complained about.

    An earlier version of this check required a space in the text, to keep one-word
    bullets out, and so was silent on every heading anyone would notice.
    """
    s = _doc(("Introduction", True),
             ("Digital pedagogies have transformed the classroom.", False))
    assert 0 in _flagged(s)


def test_a_multi_word_heading_is_reported():
    s = _doc(("Results and Discussion", True), ("The findings show a gap.", False))
    assert 0 in _flagged(s)


def test_a_genuine_list_item_is_left_alone():
    """43 of job #60's 76 numbered paragraphs are the author's real lists.

    Turning numbering off for those to tidy the headings would destroy the lists, so
    this check has to stay away from them — which is also why it only ever reports.
    """
    s = _doc(("Adaptive learning platforms adjust to each learner's pace.", True),
             ("Collaborative tools support group work across distances.", True))
    assert _flagged(s) == set()


def test_an_unnumbered_heading_is_not_reported():
    """Nothing to say about a heading that carries no automatic number."""
    s = _doc(("Introduction", False), ("The field has grown.", False))
    assert _flagged(s) == set()


def test_a_long_sentence_is_never_a_heading():
    s = _doc(("This review focuses on analyzing tools and strategies that address "
              "these challenges and foster inclusivity across contexts", True),)
    assert _flagged(s) == set()


# ---------------------------------------- the abbreviation repeats job #60 reported

def test_a_plural_bracket_is_still_a_definition():
    """`Open Educational Resources (OERs)` -> `OER (OERs)`, an acronym plus its plural.

    The guard excused only "(OER)" from being treated as a stray expansion, so the
    plural form was rewritten into nonsense in the middle of job #60's ¶35.
    """
    import edit_guards as G

    orig = ["Open Educational Resources (OERs): Organizations promote free materials.",
            "Open Educational Resources (OER): Platforms provide free access."]
    out, _q = G.enforce_abbreviation_first_use(orig, list(orig))
    assert out[0].startswith("Open Educational Resources (OERs)")
    assert "OER (OERs)" not in out[0]


def test_a_term_defined_seven_times_is_defined_once():
    """ICT was expanded at seven paragraphs of job #60 and OER at eight.

    The branch that recognised "expansion (ABBR)" marked the term seen and moved on
    without touching it, so every repeat after the first survived every pass.
    """
    import edit_guards as G

    orig = [
        "Information and Communication Technology (ICT) supports inclusion.",
        "The growing role of Information and Communication Technology (ICT) is clear.",
        "Analysis of Information and Communication Technology (ICT) tools follows.",
    ]
    out, queries = G.enforce_abbreviation_first_use(orig, list(orig))
    assert out[0] == orig[0]                      # the author's first mention stands
    assert out[1] == "The growing role of ICT is clear."
    assert out[2] == "Analysis of ICT tools follows."
    assert any("already been defined" in q["query"] for q in queries)


def test_an_acronym_that_skips_joining_words_is_learned():
    """`Information and Communication Technology` is ICT, not IaCT.

    Initials were taken from every word, so any acronym that skips an "and" or an "of"
    was never learned — and an abbreviation the guard has not learned is one it does
    nothing about. That is why job #60 could expand ICT at seven paragraphs and UNESCO
    at two with the first-use rule switched on and reporting itself as applied.
    """
    import edit_guards as G

    assert G.learn_abbreviations(
        ["Information and Communication Technology (ICT) supports inclusion."]
    ) == {"ICT": "Information and Communication Technology"}

    # A comma inside the name, which used to make the match start after it.
    assert G.learn_abbreviations(
        ["The United Nations Educational, Scientific and Cultural Organization "
         "(UNESCO) reports a widening gap."]
    ) == {"UNESCO": "United Nations Educational, Scientific and Cultural Organization"}


def test_a_bracket_that_defines_nothing_is_still_rejected():
    """The widening must not turn every parenthesis into a definition."""
    import edit_guards as G

    for text in ("the model (SEM) was fitted",
                 "in the year (2025) the study ran",
                 "Results were mixed, however (Fig. 2) shows the trend.",
                 "Two groups were used, and control (CTRL) values were stable."):
        assert G.learn_abbreviations([text]) == {}, text
