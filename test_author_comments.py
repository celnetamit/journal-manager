"""Whose question is it? On the author's copy, Word has to say so.

The quality team, 17 Sep 2026: the author's redline carries only the author's queries,
and every one of them was still signed `AI Editor`. To an author that reads as somebody
else's note they have been copied on, which is exactly the wrong signal for the one set
of questions only they can answer.
"""

from __future__ import annotations

import zipfile

import docx
import editor


def _redline(tmp_path, audience, text="The sample was heated to 40 and held."):
    source = tmp_path / "in.docx"
    d = docx.Document()
    d.add_paragraph(text)
    d.save(str(source))
    out = tmp_path / f"out-{audience or 'internal'}.docx"
    editor.generate_redline_docx(
        str(source), [text], str(out),
        queries=[{"index": 0, "query": "40 what — °C?", "guard": "x",
                  "audience": "author", "suggestion": None}],
        audience=audience)
    with zipfile.ZipFile(str(out)) as z:
        return z.read("word/comments.xml").decode("utf8")


def test_the_authors_copy_names_the_author(tmp_path):
    xml = _redline(tmp_path, "author")
    assert "Query to Author" in xml
    assert "AI Editor" not in xml
    assert "Author: 40 what" in xml


def test_the_internal_copy_is_unchanged(tmp_path):
    xml = _redline(tmp_path, None)
    assert "AI Editor" in xml
    assert "Query to Author" not in xml
