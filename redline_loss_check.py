"""Did the copyedit lose any of the author's work? Ask the redline itself.

    python redline_loss_check.py /data/outbound/user_7_70_redline.docx

Run against the file the tool produced, not against the pipeline's own report. Every
loss found on 9 September was found this way and none of them came from the tests,
which were green throughout.

A redline carries both versions: `w:del` holds what was there, `w:ins` holds what was
put in its place. So the original can be reconstructed from the output alone, and the
two compared on the three things that have actually gone missing before.

**References** are compared as works, never as a count. Four references left job #62
and the count was sixteen both times; the identity is the first author's surname and
the year, which survives the Vancouver reformat when the wording does not. This uses
`edit_guards._reference_identity` on purpose — the daily check should measure exactly
what the guard measures, or the two disagree and neither can be trusted.

**Figures** are compared as media files against the relationships that point at them.
An image left in `word/media/` with nothing referencing it is a figure some paragraph
used to hold; `python-docx`'s `clear()` deleted three that way on job #53. Every part
of the package is searched, not just `word/document.xml` — a bullet glyph lives in
`word/numbering.xml` and a logo in `word/header1.xml`, and counting those as orphans
reports a deleted figure in a file that never had one.

**Caption labels** are compared by kind and number, normalised. `Fig.1a.` becoming
`Figure 1a.` is the copyedit doing its job; treating the two spellings as different
labels reported eight deleted captions in job #68, all of them present.
"""

from __future__ import annotations

import re
import sys
import zipfile
from collections import Counter
from typing import Dict, List, Tuple

from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def paragraphs(path: str, side: str) -> List[str]:
    """`side='edited'` for the text as it stands, `'original'` for the author's."""
    root = etree.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    out: List[str] = []
    for p in root.iter(W + "p"):
        buf: List[str] = []
        for node in p.iter(W + "t", W + "delText"):
            ancestors = {a.tag for a in node.iterancestors()}
            if side == "edited" and (W + "del") in ancestors:
                continue
            if side == "original" and (W + "ins") in ancestors:
                continue
            buf.append(node.text or "")
        out.append("".join(buf))
    return out


def _entries(paras: List[str]) -> List[str]:
    from edit_guards import _references_start

    start = _references_start(paras)
    if start is None:
        return []
    return [p for p in paras[start + 1:] if len((p or "").strip()) > 40]


def reference_census(paras: List[str]) -> "Counter[Tuple[str, str]]":
    from edit_guards import _reference_identity

    counts: "Counter[Tuple[str, str]]" = Counter()
    for entry in _entries(paras):
        ident = _reference_identity(entry)
        if ident:
            counts[ident] += 1
    return counts


def orphan_media(path: str) -> List[str]:
    """Media files no part of the document points at — i.e. deleted figures."""
    z = zipfile.ZipFile(path)
    media = {n for n in z.namelist() if n.startswith("word/media/")}
    referenced: set = set()
    for name in z.namelist():
        if not name.endswith(".rels"):
            continue
        base = name.rsplit("_rels/", 1)[0]
        try:
            rels = etree.fromstring(z.read(name))
        except etree.XMLSyntaxError:
            continue
        for rel in rels:
            target = (rel.get("Target") or "").split("/")[-1]
            if f"{base}media/{target}" in media:
                referenced.add(f"{base}media/{target}")
            elif f"word/media/{target}" in media:
                referenced.add(f"word/media/{target}")
    return sorted(media - referenced)


_KIND = {"fig": "figure", "figure": "figure", "table": "table", "scheme": "scheme",
         "eq": "equation", "equation": "equation"}
_CAPTION = re.compile(
    r"^\s*(fig|figure|table|scheme|eq|equation)\.?\s*[:\-–]?\s*(\d+)", re.I)


def caption_labels(paras: List[str]) -> "Counter[Tuple[str, str]]":
    found: "Counter[Tuple[str, str]]" = Counter()
    for text in paras:
        m = _CAPTION.match(text or "")
        if m:
            found[(_KIND[m.group(1).lower()], m.group(2))] += 1
    return found


def check(path: str) -> Dict[str, object]:
    before, after = paragraphs(path, "original"), paragraphs(path, "edited")
    refs_before, refs_after = reference_census(before), reference_census(after)
    caps_before, caps_after = caption_labels(before), caption_labels(after)
    return {
        "file": path,
        "entries": (len(_entries(before)), sum(refs_before.values())),
        "references_lost": sorted((refs_before - refs_after).elements()),
        "references_duplicated": sorted((refs_after - refs_before).elements()),
        "figures_orphaned": orphan_media(path),
        "captions_lost": sorted((caps_before - caps_after).elements()),
    }


def main(paths: List[str]) -> int:
    clean = True
    for path in paths:
        r = check(path)
        readable, counted = r["entries"]
        print(f"=== {path}")
        print(f"  references : {counted} of {readable} entries readable")
        for key in ("references_lost", "references_duplicated", "figures_orphaned",
                    "captions_lost"):
            if r[key]:
                clean = False
                print(f"  {key:<22}: {r[key]}")
        if readable and counted < readable:
            print(f"  note: {readable - counted} entr(y/ies) carry no year and are "
                  f"outside the census")
    print("nothing lost" if clean else "SOMETHING WAS LOST — read the file")
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
