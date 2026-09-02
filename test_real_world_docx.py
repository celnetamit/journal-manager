"""What real manuscripts do that clean test fixtures never do.

Every test here comes from a measured failure on a 400-manuscript sweep of the WordPress
media corpus (`wpimport/media/*.docx`) — law, materials science, agronomy, nursing,
homoeopathy. Before these fixes, 39 of those 400 (9.8%) could not be read at all; after,
3 (0.8%), and all three are files whose embedded images have a corrupt CRC.

The failure mode was never a crash the user saw. `run_pipeline` already catches a
structure-read failure and carries on with the copyedit, so the job finished `done` and
the House Style panel — the flagship feature — was simply absent, under a warning that
read "House-style layout check was skipped: " with nothing after the colon. That is the
shape worth testing: not "does it raise", but "does the check still happen".
"""

import zipfile

import docx
import pytest

import docxmodel as M

#: The minimum `run_pipeline` insists on. Building it here rather than in each test
#: keeps the tests about the failure they describe.
_OPTS = {"user_id": 1, "edit_style": "CMOS", "ref_style": "Vancouver",
         "lang_type": "US English"}


@pytest.fixture
def plain(tmp_path):
    """A document with no lists — so Word writes no numbering part at all."""
    d = docx.Document()
    d.add_paragraph("Introduction")
    d.add_paragraph("The samples were held at constant mass throughout the trial.")
    p = tmp_path / "plain.docx"
    d.save(str(p))
    return str(p)


# --------------------------------------------------------------- no numbering part

def test_a_document_with_no_list_is_still_read(plain, monkeypatch):
    """32 of 400. python-docx raises a bare `NotImplementedError` when a document has
    never contained a list, and the original guard named KeyError/AttributeError/
    ValueError — every exception except the one that actually fires."""
    import docx.parts.document as dp

    def boom(self):
        raise NotImplementedError

    monkeypatch.setattr(dp.DocumentPart, "numbering_part",
                        property(boom), raising=False)

    st = M.read_structure(plain)
    assert len(st.paragraphs) == 2
    assert st.paragraphs[0].text == "Introduction"


def test_no_numbering_means_no_list_marker_not_a_failure(plain, monkeypatch):
    import docx.parts.document as dp
    monkeypatch.setattr(dp.DocumentPart, "numbering_part",
                        property(lambda self: (_ for _ in ()).throw(NotImplementedError)),
                        raising=False)
    st = M.read_structure(plain)
    assert all(not p.listing for p in st.paragraphs)


# ------------------------------------------------------------ fractional font sizes

def test_a_fractional_half_point_size_is_read_not_raised(plain):
    """LibreOffice and Google Docs export `w:sz` values like `26.666666666666668`.
    python-docx's typed accessor does `int(value)` on that and raises, which took the
    whole manuscript down over a single heading."""
    from docx.oxml.ns import qn

    d = docx.Document(plain)
    run = d.paragraphs[0].runs[0] if d.paragraphs[0].runs else d.paragraphs[0].add_run("x")
    rpr = run._r.get_or_add_rPr()
    sz = rpr.makeelement(qn("w:sz"), {qn("w:val"): "26.666666666666668"})
    rpr.append(sz)
    out = plain.replace(".docx", "-frac.docx")
    d.save(out)

    st = M.read_structure(out)
    # 26.666… half-points is 13.3 pt. The point is that it is read at all.
    assert st.paragraphs[0].runs[0].font_size_pt == pytest.approx(13.3, abs=0.1)


def test_an_unreadable_size_falls_back_to_what_the_run_inherits(plain):
    """A `w:sz` nobody can parse means the run states no size of its own, so the
    style and then `w:docDefaults` apply — exactly as if the attribute were absent.
    Returning None here instead would report "no size" for a run that plainly has
    one, and every body-text size check would then fire on it."""
    from docx.oxml.ns import qn

    d = docx.Document(plain)
    run = d.paragraphs[0].runs[0] if d.paragraphs[0].runs else d.paragraphs[0].add_run("x")
    rpr = run._r.get_or_add_rPr()
    rpr.append(rpr.makeelement(qn("w:sz"), {qn("w:val"): "large"}))
    out = plain.replace(".docx", "-bad.docx")
    d.save(out)

    st = M.read_structure(out)          # the point: this does not raise
    assert st.paragraphs[0].runs[0].font_size_pt == 11.0


# ----------------------------------------------------------- irregular merged tables

def test_a_row_whose_grid_does_not_resolve_still_yields_its_cells():
    """`row.cells` walks to the cell above for every vertically merged continuation
    and raises `ValueError: no 'tc' element at grid_offset=N` when the grid does not
    line up — which Word tolerates and writes anyway. 4 of 400."""
    class _Tr:
        tc_lst = ["tc0", "tc1", "tc2"]

    class _Row:
        _tr = _Tr()
        table = object()

        @property
        def cells(self):
            raise ValueError("no `tc` element at grid_offset=4")

    cells = M._row_cells(_Row())
    assert len(cells) == 3


def test_a_healthy_row_is_untouched(tmp_path):
    """The fallback must not become the normal path — it loses merge resolution."""
    d = docx.Document()
    t = d.add_table(rows=1, cols=3)
    for i in range(3):
        t.cell(0, i).text = f"c{i}"
    p = tmp_path / "t.docx"
    d.save(str(p))

    row = docx.Document(str(p)).tables[0].rows[0]
    assert [c.text for c in M._row_cells(row)] == ["c0", "c1", "c2"]


# ------------------------------------------------------------------- damaged files

def test_a_corrupt_docx_is_explained_in_words_an_author_can_act_on(tmp_path):
    """3 of 400 have a bad CRC on an embedded image. The author used to be shown
    "Bad CRC-32 for file 'word/media/image1.png'" — true, and no help at all."""
    import pipeline

    bad = tmp_path / "corrupt.docx"
    bad.write_bytes(b"this is not a zip archive")

    with pytest.raises(ValueError) as exc:
        pipeline.run_pipeline(_OPTS, str(bad), lambda *a, **k: None)

    msg = str(exc.value)
    assert "damaged" in msg
    assert "Save As" in msg
    assert not isinstance(exc.value, zipfile.BadZipFile)


# ------------------------------------------------- the warning that said nothing

def test_a_skipped_house_check_always_gives_a_reason():
    """`str(NotImplementedError())` is "", so the warning read "…skipped: " and the
    editor had no way to tell a bug from a document that genuinely had no layout."""
    import pipeline


    assert pipeline.skip_reason(NotImplementedError()) == "NotImplementedError"
    assert pipeline.skip_reason(zipfile.BadZipFile()) == "BadZipFile"
    # A real message is still preferred over the class name.
    assert pipeline.skip_reason(ValueError("no `tc` element")) == "no `tc` element"
