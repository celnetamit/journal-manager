"""Three things job #52 shipped with, each of which nothing was looking at.

*Compatative Catalytic Study of Oxidation of Thiourea…* — the strings are from that
manuscript and its redline.
"""

from __future__ import annotations

import io

from docx import Document

import proofread as P


# ------------------------------------------------- superscript reference markers


def _superscript_doc(word: str, sup: str, superscript: bool = True):
    """A paragraph ending in a superscript number, the way job #52 cites."""
    doc = Document()
    doc.add_paragraph("Abstract")
    p = doc.add_paragraph()
    p.add_run(word)
    r = p.add_run(sup)
    r.font.superscript = superscript
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def test_a_superscript_reference_becomes_a_citation_marker():
    """`…was allowed to react` + superscript `45, 48` arrived as `react45, 48`.

    Every downstream rule reads text, so a citation that is only a superscript is a
    citation nothing can see — which is why the team's superscript references came back
    with none of the reference rules applied to them.
    """
    import editor

    out = editor.read_docx(_superscript_doc("was allowed to react", "45, 48"))
    assert out[-1] == "was allowed to react [45, 48]"


def test_an_exponent_is_not_a_citation():
    """`10` + superscript `5` is a power, and bracketing it would corrupt a number."""
    import editor

    out = editor.read_docx(_superscript_doc("the rate rose to 10", "5"))
    assert "[5]" not in out[-1]


def test_an_ordinary_number_in_the_text_is_left_alone():
    import editor

    out = editor.read_docx(_superscript_doc("was allowed to react", "45", superscript=False))
    assert out[-1] == "was allowed to react45"


def test_affiliation_markers_in_the_front_matter_are_left_alone():
    """`Susan Kumar` + superscript `2` is an affiliation, not a citation of reference 2."""
    import editor

    doc = Document()
    p = doc.add_paragraph()
    p.add_run("Saniya Jose")
    r = p.add_run("1")
    r.font.superscript = True
    doc.add_paragraph("Abstract")
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    assert editor.read_docx(buf)[0] == "Saniya Jose1"


# ------------------------------------------------------ equations cited but bare


def test_an_equation_cited_but_never_numbered_is_reported():
    """Job #52 argues from "equation 2"; not one of its equations carries a number."""
    paras = [
        "The kinetics were followed by measuring the absorbance intensity.",
        "k2 = k1/[Thiourea]",
        "Substituting in equation 2 gives the second-order rate constant.",
    ]
    hits = [f for f in P._equation_number_findings(paras)
            if f.rule == "crossref.equation-unnumbered"]
    assert len(hits) == 1
    assert hits[0].paragraph == 2                     # reported where the reader is sent
    assert "Equation 2" in hits[0].message


def test_a_numbered_equation_is_not_reported():
    paras = [
        "Thus the net reaction can be represented by (1)",
        "k2 = k1/[Thiourea]     (2)",
        "Substituting in Eq. (2) gives the second-order rate constant.",
    ]
    assert P._equation_number_findings(paras) == []


def test_an_unnumbered_equation_nobody_cites_is_not_reported():
    """A chemistry paper is full of bare display lines; only a stranded reader matters."""
    assert P._equation_number_findings(["k2 = k1/[Thiourea]", "The rate rose."]) == []


# ------------------------------------------------------------ table cells get read


def test_a_short_column_heading_is_offered_to_the_proofreader():
    """`CONCETRATION (M)` is two words, so the copyeditor is never given it.

    That threshold is deliberate — a model handed `0.15` may return `0.150` — so the
    heading is picked up for *reading* instead, on a rule that admits headings and
    still excludes numbers.
    """
    import editor
    from docxmodel import read_structure

    doc = Document()
    t = doc.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text = "CATALYST"
    t.rows[0].cells[1].text = "CONCETRATION (M)"
    t.rows[1].cells[0].text = "SDS"
    t.rows[1].cells[1].text = "0.15"
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    texts = [txt for _addr, txt in
             editor.collect_table_texts_for_proofing(read_structure(buf))]
    assert "CONCETRATION (M)" in texts
    assert "0.15" not in texts                        # numbers stay out of it
    assert not editor.is_editable_cell("CONCETRATION (M)")   # still not copyedited


def test_one_citation_split_across_runs_becomes_one_marker():
    """Word breaks `45, 48, 49, 51, 54` into separate runs; the citation is still one.

    Bracketing each run on its own produced `[15, [45] [48] [49]` when this was first
    run over the real manuscript — markers nested inside each other. Found by looking at
    the output, not by the tests, which is why the real file is in this suite's loop.
    """
    import editor

    doc = Document()
    doc.add_paragraph("Abstract")
    p = doc.add_paragraph()
    p.add_run("also observed by many researchers")
    for piece in ("45,", " 48,", " 51"):
        r = p.add_run(piece)
        r.font.superscript = True
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    assert editor.read_docx(buf)[-1] == "also observed by many researchers [45, 48, 51]"


def test_a_citation_the_author_already_bracketed_is_not_bracketed_twice():
    """`[15,` in ordinary text with the rest superscript — leave the author's bracket."""
    import editor

    doc = Document()
    doc.add_paragraph("Abstract")
    p = doc.add_paragraph()
    p.add_run("observed by many researchers [15,")
    r = p.add_run("45]")
    r.font.superscript = True
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    assert editor.read_docx(buf)[-1] == "observed by many researchers [15,45]"
