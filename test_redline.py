"""What the redline writer puts in the file.

Written **before** `generate_redline_docx` was touched, so it describes the behaviour
that already worked rather than the behaviour I hoped for. Extending that function is the
riskiest change in this repository: it pairs `doc.paragraphs` with `edited_paragraphs` by
index, and a mistake there does not raise — it writes each track change onto the wrong
paragraph, in a file that opens cleanly and looks like a redline.

The table tests are the new part. Table cells are not in `doc.paragraphs`, which is why
11.3% of a real manuscript has never been copyedited; they are edited through a separate
address (table, row, cell, paragraph) so the body list keeps its exact meaning.
"""

import docx
import pytest
from docx.oxml.ns import qn

import editor as E


def _changes(path):
    """Every insertion and deletion in the file, in document order."""
    doc = docx.Document(path)
    ins, dele = [], []
    for el in doc.element.body.iter():
        if el.tag == qn("w:ins"):
            ins.append("".join(t.text or "" for t in el.iter(qn("w:t"))))
        elif el.tag == qn("w:del"):
            dele.append("".join(t.text or "" for t in el.iter(qn("w:delText"))))
    return ins, dele


def _body_text(path):
    return [p.text for p in docx.Document(path).paragraphs]


def _paragraph_insertions(path, index):
    """Text inserted into one paragraph.

    Not `paragraph.text` — python-docx only walks `w:r` elements that are direct
    children of `w:p`, and an insertion is wrapped in `w:ins`. Reading `.text` shows
    the deletion took effect and the insertion silently missing, which looks exactly
    like a broken redline and is not one.
    """
    p = docx.Document(path).paragraphs[index]
    return "".join(t.text or ""
                   for ins in p._p.iter(qn("w:ins"))
                   for t in ins.iter(qn("w:t")))


def _comment_text(path):
    """Comments live in `word/comments.xml`; the body only carries the anchor."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        if "word/comments.xml" not in z.namelist():
            return ""
        return z.read("word/comments.xml").decode("utf8", "replace")


@pytest.fixture
def source(tmp_path):
    d = docx.Document()
    d.add_paragraph("The result was significant.")
    d.add_paragraph("Scale inhibitors are the primary defence.")
    d.add_paragraph("Table 1. Reagents.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Reagent"
    t.cell(0, 1).text = "Purity"
    t.cell(1, 0).text = "Sodium chlorid"          # a typo, inside a table
    t.cell(1, 1).text = "99%"
    path = tmp_path / "src.docx"
    d.save(str(path))
    return str(path)


# ------------------------------------------------------------------- body, unchanged

def test_an_unchanged_paragraph_produces_no_track_change(source, tmp_path):
    out = tmp_path / "a.docx"
    E.generate_redline_docx(source, _body_text(source), str(out))
    ins, dele = _changes(str(out))
    assert ins == [] and dele == []


def test_an_edited_paragraph_is_marked_up(source, tmp_path):
    edits = list(_body_text(source))
    edits[0] = "The result was highly significant."
    out = tmp_path / "b.docx"
    E.generate_redline_docx(source, edits, str(out))

    ins, dele = _changes(str(out))
    assert "highly" in "".join(ins)
    # The rest of the sentence is not deleted and re-inserted: only what changed.
    assert "significant" not in "".join(dele)


def test_edits_land_on_the_paragraph_they_belong_to(source, tmp_path):
    """The failure this whole file exists for. If the pairing ever slips, this is
    what catches it — the second paragraph's edit appearing in the first."""
    edits = list(_body_text(source))
    edits[1] = "Scale inhibitors are the principal defence."
    out = tmp_path / "c.docx"
    E.generate_redline_docx(source, edits, str(out))

    assert "principal" in _paragraph_insertions(str(out), 1)
    assert "principal" not in _paragraph_insertions(str(out), 0)


def test_a_query_becomes_a_comment_on_its_paragraph(source, tmp_path):
    out = tmp_path / "d.docx"
    E.generate_redline_docx(
        source, _body_text(source), str(out),
        queries=[{"index": 1, "query": "Confirm the year.", "suggestion": "2002"}])
    comments = _comment_text(str(out))
    assert "Confirm the year." in comments
    assert "2002" in comments


# --------------------------------------------------------------------------- tables

def test_table_text_can_be_edited(source, tmp_path):
    """The 11.3%. Cell paragraphs are addressed separately from the body list."""
    out = tmp_path / "e.docx"
    E.generate_redline_docx(
        source, _body_text(source), str(out),
        table_edits={(0, 1, 0, 0): "Sodium chloride"})

    ins, dele = _changes(str(out))
    assert "chloride" in "".join(ins)
    assert "chlorid" in "".join(dele)


def test_editing_a_table_leaves_the_body_alone(source, tmp_path):
    out = tmp_path / "f.docx"
    E.generate_redline_docx(
        source, _body_text(source), str(out),
        table_edits={(0, 1, 0, 0): "Sodium chloride"})

    doc = docx.Document(str(out))
    assert doc.paragraphs[0].text == "The result was significant."
    assert doc.paragraphs[1].text == "Scale inhibitors are the primary defence."


def test_an_unchanged_cell_produces_no_track_change(source, tmp_path):
    out = tmp_path / "g.docx"
    E.generate_redline_docx(source, _body_text(source), str(out),
                            table_edits={(0, 1, 0, 0): "Sodium chlorid"})
    ins, dele = _changes(str(out))
    assert ins == [] and dele == []


def test_an_address_that_does_not_exist_is_ignored(source, tmp_path):
    """A stale address must not raise mid-write and lose the whole redline, and must
    not silently write into a neighbouring cell either."""
    out = tmp_path / "h.docx"
    E.generate_redline_docx(source, _body_text(source), str(out),
                            table_edits={(9, 9, 9, 9): "nonsense"})
    ins, dele = _changes(str(out))
    assert ins == [] and dele == []
    assert docx.Document(str(out)).tables[0].cell(1, 0).text == "Sodium chlorid"


def test_table_addresses_round_trip_through_the_reader():
    """`collect_table_texts` must produce addresses `generate_redline_docx` accepts.
    Two halves invented separately is how the edits end up nowhere."""
    import docxmodel as M
    import tempfile
    import os

    d = docx.Document()
    d.add_paragraph("Body.")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "alpha"
    t.cell(0, 1).text = "beta"
    path = os.path.join(tempfile.mkdtemp(), "r.docx")
    d.save(path)

    items = E.collect_table_texts(M.read_structure(path))
    assert [text for _, text in items] == ["alpha", "beta"]

    out = os.path.join(os.path.dirname(path), "out.docx")
    E.generate_redline_docx(path, [p.text for p in docx.Document(path).paragraphs],
                            out, table_edits={items[0][0]: "alphabet"})
    ins, _ = _changes(out)
    assert "alphabet" in "".join(ins)
