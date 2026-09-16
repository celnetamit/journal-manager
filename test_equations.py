"""An inline equation survives the copyedit — job #100.

Built as a real `.docx` with real OMML rather than a mock, because every part of this
failed at the XML level: `Paragraph.text` steps over an equation, `Paragraph.clear()`
deletes it, and neither of those is visible from a stub.
"""
import re

import docx
import pytest

import edit_guards as G
from editor import (OBJECT_PLACEHOLDER, generate_redline_docx,
                    paragraph_objects, paragraph_text_with_objects, read_docx)

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"



W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _redline_text(p) -> str:
    """The paragraph as it reads on the page, tracked changes and equations included.

    `paragraph_text_with_objects` walks the direct `w:r` children, which is right for
    the manuscript and wrong for the redline: there the edited words live inside
    `w:ins` and `w:del`, one level down.
    """
    out = []
    for node in p._p.iter():
        if node.tag == f"{{{W}}}t":
            out.append(node.text or "")
        elif node.tag == f"{{{M}}}oMath":
            out.append("[EQ]")
    return "".join(out)


def _add_equation(paragraph, text):
    """An inline OMML equation, as Word writes one."""
    from docx.oxml import parse_xml
    xml = (f'<m:oMath xmlns:m="{M}" '
           f'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<m:r><m:t>{text}</m:t></m:r></m:oMath>')
    paragraph._p.append(parse_xml(xml))


def _manuscript(tmp_path):
    """`where [K_IC ≈ 0.7 MPa] is the fracture toughness of silica, [a = 50 nm] is
    the characteristic flaw size` — job #100's sentence, in miniature."""
    doc = docx.Document()
    doc.add_paragraph("Title of the Paper")
    doc.add_paragraph("Abstract: a short abstract.")
    p = doc.add_paragraph()
    p.add_run("where ")
    _add_equation(p, "K_IC ≈ 0.7 MPa")
    p.add_run(" is the fracture toughness of silica, and ")
    _add_equation(p, "a = 50 nm")
    p.add_run(" is the characteristic flaw size.")
    path = str(tmp_path / "manuscript.docx")
    doc.save(path)
    return path


def test_the_copyedit_is_shown_the_equation_not_a_gap(tmp_path):
    paras = read_docx(_manuscript(tmp_path))
    sentence = [t for t in paras if "fracture toughness" in t][0]
    assert sentence.count(OBJECT_PLACEHOLDER) == 2
    # And no run of blanks where an equation was: that hole is what the model filled
    # with `K_Ic` and `a` on the real job.
    assert not re.search(r"\s{2,}", sentence)


def test_the_equation_survives_a_paragraph_the_copyedit_rewrote(tmp_path):
    path = _manuscript(tmp_path)
    original = read_docx(path)
    edited = [t.replace("where", "Where").replace("silica,", "silica")
              for t in original]
    out = str(tmp_path / "redline.docx")
    generate_redline_docx(path, edited, out)

    doc = docx.Document(out)
    sentence = [p for p in doc.paragraphs
                if "fracture toughness" in paragraph_text_with_objects(p)][0]
    maths = paragraph_objects(sentence)
    assert len(maths) == 2, "the author's equations were dropped by the rewrite"
    assert "0.7 MPa" in "".join(t.text or "" for t in maths[0].iter(f"{{{M}}}t"))
    assert "50 nm" in "".join(t.text or "" for t in maths[1].iter(f"{{{M}}}t"))
    # The placeholder is a working character, not something to ship to the author.
    assert OBJECT_PLACEHOLDER not in doc.element.xml


def test_the_equation_stays_in_the_middle_of_its_sentence(tmp_path):
    path = _manuscript(tmp_path)
    original = read_docx(path)
    edited = [t.replace("where", "Where") for t in original]
    out = str(tmp_path / "redline.docx")
    generate_redline_docx(path, edited, out)

    doc = docx.Document(out)
    p = [p for p in doc.paragraphs if "fracture toughness" in p.text][0]
    rendered = _redline_text(p)
    before, after = rendered.split("[EQ]")[0], rendered.split("[EQ]")[-1]
    assert "here" in before, rendered
    assert "characteristic flaw size" in after, rendered


def test_a_copyedit_that_loses_an_equation_is_refused():
    """The model's own job #100 output: the equations replaced by its guesses."""
    original = ["where ￼ is the fracture toughness of silica, and ￼ is the flaw size"]
    edited = ["where K_Ic is the fracture toughness of silica, and a is the flaw size"]
    out, queries = G.keep_every_equation(original, edited)
    assert out == original
    assert len(queries) == 1 and "equation" in queries[0]["query"]


def test_an_ordinary_edit_beside_an_equation_is_kept():
    original = ["where ￼ is the fracture toughness of silica"]
    edited = ["Where ￼ is the fracture toughness of silica"]
    out, queries = G.keep_every_equation(original, edited)
    assert out == edited and queries == []


def test_the_placeholder_never_reaches_a_reader(tmp_path):
    """It is a working character between the reader and the writer. The JATS goes to
    a typesetter and an indexer, where a stray U+FFFC is a defect in the file."""
    from editor import build_jats_xml, for_display
    xml = build_jats_xml(["A Title", "where ￼ is the toughness of silica."])
    assert OBJECT_PLACEHOLDER not in xml
    assert "[equation]" in xml
    assert for_display("a ￼ b") == "a [equation] b"


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _add_ole_equation(paragraph):
    """An old Word equation: an OLE object inside an ordinary run, which is what
    Equation Editor 3.0 leaves behind and what job #106's nomenclature list is made
    of. `Paragraph.text` steps over it exactly as it does over OMML."""
    from docx.oxml import parse_xml
    paragraph._p.append(parse_xml(
        f'<w:r xmlns:w="{W_NS}" '
        f'xmlns:v="urn:schemas-microsoft-com:vml" '
        f'xmlns:o="urn:schemas-microsoft-com:office:office">'
        f'<w:object><v:shape id="s1" style="width:12pt;height:12pt"/>'
        f'<o:OLEObject Type="Embed" ProgID="Equation.3" ShapeID="s1"/>'
        f'</w:object></w:r>'))


def test_an_ole_equation_in_a_line_of_text_is_shown_to_the_copyedit(tmp_path):
    """#106: the copyedit saw `  Initial concentration of TPH (mg/kg)` and wrote its
    own symbol in — `C0 =`, `C =`, `Q =`, and nothing at all on the next four lines."""
    doc = docx.Document()
    doc.add_paragraph("Title")
    doc.add_paragraph("Abstract: x.")
    p = doc.add_paragraph()
    _add_ole_equation(p)
    p.add_run(" Initial concentration of TPH (mg/kg)")
    path = str(tmp_path / "m.docx")
    doc.save(path)

    line = [t for t in read_docx(path) if "Initial concentration" in t][0]
    assert line.count(OBJECT_PLACEHOLDER) == 1, line


def test_an_ole_equation_comes_back_where_it_stood(tmp_path):
    doc = docx.Document()
    doc.add_paragraph("Title")
    doc.add_paragraph("Abstract: x.")
    p = doc.add_paragraph()
    _add_ole_equation(p)
    p.add_run(" Initial concentration of TPH (mg/kg)")
    path = str(tmp_path / "m.docx")
    doc.save(path)

    original = read_docx(path)
    edited = [t.replace("Initial", "The initial") for t in original]
    out = str(tmp_path / "r.docx")
    generate_redline_docx(path, edited, out)

    doc2 = docx.Document(out)
    # `Paragraph.text` reads the direct runs only, and the edited words are inside
    # `w:ins` — the same measurement trap the redline caught earlier in this file.
    para = [q for q in doc2.paragraphs
            if "initial concentration" in _redline_text(q).lower()][0]
    objects = [o for o in para._p.iter(f"{{{W_NS}}}object")]
    assert objects, "the author's equation object was dropped by the rewrite"
    assert OBJECT_PLACEHOLDER not in doc2.element.xml


def test_a_figure_only_paragraph_still_travels_the_old_way(tmp_path):
    """Job #53's fix must not be undone: a paragraph that is only a picture has no
    text for anything to be invented into, and is carried across by
    `_detachable_graphics`."""
    from editor import _detachable_graphics
    doc = docx.Document()
    p = doc.add_paragraph()
    _add_ole_equation(p)
    leading, trailing = _detachable_graphics(p)
    assert leading or trailing, "an object-only paragraph keeps the old path"
