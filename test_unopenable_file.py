"""Jobs #76, #77 and #78: the same person, the same file, three failures in twenty
minutes, and one message that was wrong for all of them.

`python-docx` raises `PackageNotFoundError` with the identical wording —
`Package not found at '<path>'` — for a file that is not there, for a PDF, for a Word
97 `.doc`, for RTF, for HTML and for a truncated zip. Measured in the running
container, all six. We picked one of those causes and told the author it as fact:
"the file appears to be damaged, open it in Word and use File > Save As".

Job #76 arrived as `completed_Priyanka_Patel_Research_Paper_Formatted (2).docx.pdf`.
No amount of re-saving a PDF in Word produces a `.docx`, so the advice could not work
— and advice that cannot work reads exactly like advice that has not been followed,
which is what the next two attempts look like.
"""

from __future__ import annotations

import zipfile

from pipeline import describe_unopenable


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_a_pdf_is_named_as_a_pdf(tmp_path):
    """Job #76, by its first four bytes."""
    msg = describe_unopenable(_write(tmp_path, "m.docx", b"%PDF-1.7\n%\xe2\xe3\xcf"))
    assert "a PDF" in msg and "Word original" in msg
    assert "Save As" not in msg, (
        "re-saving is the answer for a Word file, and this is not one")


def test_an_old_doc_is_named_as_an_old_doc(tmp_path):
    """The other way a `.docx` that is not one usually arrives."""
    msg = describe_unopenable(
        _write(tmp_path, "m.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64))
    assert "Word 97" in msg


def test_a_missing_file_is_not_called_damaged(tmp_path):
    """`Package not found` really does mean not found sometimes, and re-saving a file
    that never arrived is the one thing that cannot help."""
    msg = describe_unopenable(str(tmp_path / "never_written.docx"))
    assert "did not arrive" in msg
    assert "damaged" not in msg


def test_an_empty_upload_says_so(tmp_path):
    assert "empty" in describe_unopenable(_write(tmp_path, "m.docx", b""))


def test_a_truncated_word_file_is_the_one_that_is_damaged(tmp_path):
    """The original message was written for this case, and it stays for this case."""
    msg = describe_unopenable(_write(tmp_path, "m.docx", b"PK\x03\x04" + b"\x00" * 40))
    assert "damaged" in msg


def test_a_powerpoint_is_not_a_word_document(tmp_path):
    p = tmp_path / "m.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ppt/presentation.xml", "<p/>")
    assert "PowerPoint" in describe_unopenable(str(p))


def test_a_real_docx_that_fails_elsewhere_keeps_the_original_advice(tmp_path):
    """A corrupt embedded image — three of 400 real manuscripts — is a Word document
    whose contents could not be read, and Save As is the right answer for it."""
    p = tmp_path / "m.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    msg = describe_unopenable(str(p))
    assert "Word document" in msg and "Save As" in msg
