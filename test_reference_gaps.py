"""A missing field marked where the field belongs, in its own colour."""

from __future__ import annotations

import zipfile

import docx
import editor
import reference_gaps as R


def test_missing_authors_are_marked_at_the_head_after_the_number():
    entry = ("[17] Study on induction hardening performance of 34CrNi3MoA steel "
             "crankshaft. Front Mater. 2023; 10: 1240087.")
    out = R.mark(entry, ["author names"])
    assert out.startswith("[17] [author names missing] Study on induction")


def test_missing_volume_and_pages_are_marked_at_the_end_before_the_stop():
    entry = "Wang X, Li D. Analysis of distortion on locomotive gear ring. JOSL. 2023."
    out = R.mark(entry, ["volume", "issue", "page numbers"])
    assert out.endswith("JOSL. 2023 [volume, issue, page numbers missing].")


def test_an_entry_with_no_number_is_still_marked_at_the_head():
    out = R.mark("Study on induction hardening. Front Mater. 2023.", ["author names"])
    assert out.startswith("[author names missing] Study on")


def test_both_ends_can_be_marked_at_once():
    out = R.mark("[7] A study of things. J Test. 2001.",
                 ["author names", "page numbers"])
    assert out.startswith("[7] [author names missing] A study")
    assert out.endswith("2001 [page numbers missing].")


def test_an_entry_with_nothing_missing_is_untouched():
    entry = "[1] Smith J. A study. J Test. 2001; 4(2): 10-19."
    assert R.mark(entry, []) == entry


def test_marking_twice_marks_once():
    paras = ["[7] Study on induction hardening. Front Mater. 2023."]
    once, n1 = R.apply(paras, {0: ["author names"]})
    twice, n2 = R.apply(once, {0: ["author names"]})
    assert n1 == 1 and n2 == 0 and twice == once


def test_the_marker_gets_its_own_highlight(tmp_path):
    """Not yellow — yellow is what every ordinary insertion wears on the author's
    copy, and the team asked for this to read as a hole rather than an edit."""
    source = tmp_path / "in.docx"
    d = docx.Document()
    d.add_paragraph("[17] Study on induction hardening. Front Mater. 2023.")
    d.save(str(source))
    out = tmp_path / "out.docx"
    editor.generate_redline_docx(
        str(source),
        ["[17] [author names missing] Study on induction hardening. "
         "Front Mater. 2023."],
        str(out))
    with zipfile.ZipFile(str(out)) as z:
        xml = z.read("word/document.xml").decode("utf8")
    assert 'w:highlight w:val="cyan"' in xml
    assert "author names missing" in xml
