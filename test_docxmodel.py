"""The structured reader, and the house-spec checks built on it.

The test that matters most is `test_read_docx_contract_is_unchanged`. `generate_redline_docx`
walks `zip(doc.paragraphs, edited_paragraphs)`, so if the plain list ever gains, loses or
reorders an entry, every track change after that point lands on the wrong paragraph — in a
file that still opens, still looks like a redline, and is wrong. Nothing else in the suite
would catch it.

Fixtures are built here rather than committed: a .docx in the repository is a binary
nobody can review, and these need specific formatting rather than a real manuscript.
"""

import docx
import pytest
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

import docxmodel as M
import house_layout as H


@pytest.fixture
def manuscript(tmp_path):
    """A small paper with one correct heading, one wrong one, and a table."""
    d = docx.Document()

    h1 = d.add_paragraph("INTRODUCTION", style="Heading 1")
    h1.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for r in h1.runs:
        r.bold = True
        r.font.name = "Times New Roman"
        r.font.size = Pt(11)

    d.add_paragraph("Scale inhibition matters. See Table 1.")

    bad = d.add_paragraph("Materials and Methods", style="Heading 1")   # wrong case
    for r in bad.runs:
        r.font.name = "Calibri"                                          # wrong font
        r.font.size = Pt(14)                                             # wrong size

    d.add_paragraph("Table 1. Reagents used.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Reagent"
    t.cell(0, 1).text = "Purity"
    t.cell(1, 0).text = "NaCl"
    t.cell(1, 1).text = "99%"

    path = tmp_path / "m.docx"
    d.save(str(path))
    return str(path)


def test_read_docx_contract_is_unchanged(manuscript):
    """`Structure.texts` must equal `[p.text for p in doc.paragraphs]`, exactly.

    Same length, same order, same strings. The redline writer pairs the two by index
    and has no way to notice a mismatch.
    """
    plain = [p.text for p in docx.Document(manuscript).paragraphs]
    s = M.read_structure(manuscript)

    assert s.texts == plain
    assert len(s.paragraphs) == len(plain)
    for i, text in enumerate(plain):
        assert s.paragraphs[i].index == i
        assert s.paragraphs[i].text == text


def test_table_text_is_read(manuscript):
    """The old reader could not see any of this; 11.3% of a real manuscript sat here."""
    s = M.read_structure(manuscript)
    assert len(s.tables) == 1
    assert s.tables[0].rows == 2 and s.tables[0].cols == 2
    assert "NaCl" in s.tables[0].text
    # …and it is still absent from the plain list, which is what keeps the redline safe.
    assert not any("NaCl" in t for t in s.texts)


def test_a_table_knows_which_paragraph_it_follows(manuscript):
    s = M.read_structure(manuscript)
    above = s.paragraphs[s.tables[0].after_paragraph]
    assert above.text.startswith("Table 1.")


def test_formatting_survives(manuscript):
    s = M.read_structure(manuscript)
    intro = next(p for p in s.paragraphs if p.text == "INTRODUCTION")
    assert intro.is_bold is True
    assert intro.dominant_font == "Times New Roman"
    assert intro.dominant_size_pt == 11.0
    assert intro.outline_level == 0


def test_font_is_resolved_through_the_style(tmp_path):
    """A correctly-formatted heading has no font on the run — it is on the style.

    Reading only the run returns None for every paragraph, which reads as uniformity
    and is a dead measurement: nothing about "Times New Roman, 11 pt" is checkable.
    """
    d = docx.Document()
    style = d.styles["Heading 1"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(11)
    p = d.add_paragraph("METHODS", style="Heading 1")
    assert all(r.font.name is None for r in p.runs)      # nothing on the run itself

    path = tmp_path / "s.docx"
    d.save(str(path))

    para = M.read_structure(str(path)).paragraphs[0]
    assert para.dominant_font == "Times New Roman"
    assert para.dominant_size_pt == 11.0


@pytest.mark.parametrize("text,expected", [
    ("INTRODUCTION", "upper"),
    ("Materials and Methods", "title"),
    ("Results of the compatibility test", "sentence"),
    ("Findings and Analysis", "title"),
    ("mixed Case heading Here", "mixed"),
    ("2025", "unknown"),          # no letters: not silently "upper"
    ("", "unknown"),
])
def test_case_detection(text, expected):
    assert H.case_of(text) == expected


def test_house_checks_find_the_planted_faults(manuscript):
    findings = H.check_all(M.read_structure(manuscript))
    rules = {f.rule for f in findings}
    assert "heading.case" in rules       # "Materials and Methods" is not upper case
    assert "heading.font" in rules       # Calibri
    assert "heading.size" in rules       # 14 pt


def test_a_correct_heading_raises_nothing(manuscript):
    findings = H.check_headings(M.read_structure(manuscript))
    intro = [f for f in findings if f.paragraph == 0]
    assert intro == [], intro


def test_body_text_wearing_a_heading_style_is_caught(tmp_path):
    d = docx.Document()
    d.add_paragraph("A" * 40 + " and then a great deal more text besides, "
                    "which is a paragraph and not a heading at all.", style="Heading 1")
    path = tmp_path / "b.docx"
    d.save(str(path))

    findings = H.check_headings(M.read_structure(str(path)))
    assert [f.rule for f in findings] == ["heading.body-text-as-heading"]


def test_skipped_heading_level_is_reported(tmp_path):
    d = docx.Document()
    d.add_paragraph("INTRODUCTION", style="Heading 1")
    d.add_paragraph("Sub Sub Heading", style="Heading 3")
    path = tmp_path / "h.docx"
    d.save(str(path))

    findings = H.check_headings(M.read_structure(str(path)))
    assert any(f.rule == "heading.skipped-level" for f in findings)


def test_an_uncaptioned_table_is_reported(tmp_path):
    d = docx.Document()
    d.add_paragraph("Some body text with no caption.")
    t = d.add_table(rows=1, cols=1)
    t.cell(0, 0).text = "x"
    path = tmp_path / "t.docx"
    d.save(str(path))

    findings = H.check_tables(M.read_structure(str(path)))
    assert any(f.rule == "table.caption" for f in findings)


def test_oversized_artwork_is_reported(monkeypatch):
    s = M.Structure(paragraphs=[], tables=[], sections=[],
                    images=[M.Image(index=0, width_in=10.0, height_in=7.0)])
    findings = H.check_artwork(s)
    assert len(findings) == 1 and findings[0].rule == "artwork.size"


def test_artwork_at_the_limit_is_fine():
    s = M.Structure(paragraphs=[], tables=[], sections=[],
                    images=[M.Image(index=0, width_in=9.0, height_in=6.0)])
    assert H.check_artwork(s) == []


def test_a4_is_not_reported_as_the_wrong_page_size():
    """Word stores A4 as 8.268 x 11.693. A checker that calls that a deviation from
    8.27 x 11.69 reports every correct manuscript as broken, and stops being read."""
    s = M.Structure(paragraphs=[], tables=[], images=[], sections=[
        M.Section(page_width_in=8.268, page_height_in=11.693,
                  left_margin_in=1.0, right_margin_in=1.0,
                  top_margin_in=0.6, bottom_margin_in=0.5)])
    assert H.check_page(s) == []


def test_wrong_margins_are_reported():
    s = M.Structure(paragraphs=[], tables=[], images=[], sections=[
        M.Section(page_width_in=8.268, page_height_in=11.693,
                  left_margin_in=0.59, right_margin_in=0.59,
                  top_margin_in=0.319, bottom_margin_in=0.194)])
    findings = H.check_page(s)
    assert len(findings) == 4
    assert all(f.rule == "page.geometry" for f in findings)
