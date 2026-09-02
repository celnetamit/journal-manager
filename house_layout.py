"""The STM Journals house specification, as something a manuscript can be checked against.

The spec Amit supplied covers two different things and only one of them is a property of
an author's manuscript:

* **Heading hierarchy, listing markers and artwork size** are in the submitted `.docx`.
  They are what this module checks.
* **Page furniture** — the header strip's CMYK colour, the 0.5 pt rule 10.83" from the
  bottom, the short-title verso header — belongs to the typeset journal page, which is
  produced downstream. An author's file never contains it, so checking for it would
  report every manuscript ever submitted as broken. Page size and margins are the one
  overlap, and they are checked because a manuscript really does carry them.

Every finding names the paragraph index, so the editor can be shown the actual line
rather than a count. Nothing here rewrites anything: a house rule that silently
retypesets an author's heading is how a wrong "fix" reaches print unnoticed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from docxmodel import Structure, Para

HOUSE_FONT = "Times New Roman"
HOUSE_SIZE_PT = 11.0

#: level (1-based) -> what the house asks of it.
#: `bold`/`italic` None means the spec does not say. `run_on` marks the two levels that
#: are not standalone paragraphs at all.
HEADING_SPEC: Dict[int, Dict[str, Any]] = {
    1: {"case": "upper",    "bold": True,  "italic": None,  "align": "left"},
    2: {"case": "title",    "bold": True,  "italic": None,  "align": "left"},
    3: {"case": "title",    "bold": True,  "italic": True,  "align": "left"},
    4: {"case": "title",    "bold": False, "italic": True,  "align": "left"},
    5: {"case": "sentence", "bold": False, "italic": True,  "align": None,
        "run_on": True, "separator": ":"},
    6: {"case": "sentence", "bold": False, "italic": False, "align": None,
        "run_on": True, "separator": ":"},
}

BULLET_CODES = ("B1", "B2", "B3", "B4")
NUMBER_CODES = ("N1", "N2", "N3")

MAX_ARTWORK_IN = (9.0, 6.0)

PAGE_SPEC = {
    "width_in": 8.27, "height_in": 11.69,
    "left_in": 1.0, "right_in": 1.0, "top_in": 0.6, "bottom_in": 0.5,
}
#: Word rounds A4 to 8.268" x 11.693", and a margin typed as 0.6" can land a
#: thousandth away. Anything inside this is the spec, not a deviation — a checker
#: that reports 8.268 as "not 8.27" is one nobody reads twice.
PAGE_TOLERANCE_IN = 0.02

#: Words a title-case heading may leave lowercase. Not exhaustive by design: the
#: check below only *warns* on title case, because English title case is a matter of
#: house preference and an editor is better at it than a word list.
SMALL_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor",
    "of", "on", "onto", "or", "over", "per", "the", "to", "up", "via", "vs", "with",
}


@dataclass
class Finding:
    """One deviation from the house spec."""
    rule: str
    severity: str            # "error" | "warning" | "info"
    paragraph: Optional[int]
    message: str
    detail: str = ""

    def __str__(self) -> str:
        where = f"¶{self.paragraph}" if self.paragraph is not None else "document"
        return f"[{self.severity}] {where} {self.rule}: {self.message}"


def _visible(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _letters(text: str) -> str:
    return "".join(c for c in text if c.isalpha())


def case_of(text: str) -> str:
    """`upper`, `sentence`, `title`, or `mixed`.

    Judged on letters only, so trailing numerals and punctuation do not decide it, and
    a heading with no letters at all is `unknown` rather than silently `upper` — an
    empty string is uppercase by Python's reckoning and that would pass every H1.
    """
    letters = _letters(text)
    if not letters:
        return "unknown"
    if letters.isupper():
        return "upper"

    words = [w for w in re.split(r"[\s/–—-]+", _visible(text)) if _letters(w)]
    if not words:
        return "unknown"

    def cap(w):
        ls = _letters(w)
        return bool(ls) and ls[0].isupper()

    if len(words) == 1:
        return "sentence" if cap(words[0]) else "mixed"

    rest = words[1:]
    capped = [w for w in rest if cap(w)]
    lower = [w for w in rest if not cap(w)]

    if cap(words[0]) and not capped:
        return "sentence"
    # Title case: everything capitalised except the small words that convention
    # leaves down.
    if cap(words[0]) and all(_letters(w).lower() in SMALL_WORDS for w in lower):
        return "title"
    return "mixed"


def check_headings(structure: Structure) -> List[Finding]:
    out: List[Finding] = []
    headings = [p for p in structure.headings() if _visible(p.text)]

    for p in headings:
        level = (p.outline_level or 0) + 1
        spec = HEADING_SPEC.get(level)
        if not spec:
            continue

        # A "heading" longer than this is a body paragraph wearing a heading style.
        # Reported first and on its own, because every other check on it would be
        # noise about a paragraph that should not be a heading at all — and it is the
        # single most common real defect: the Guanidine manuscript has sixteen.
        if len(_visible(p.text)) > 90:
            out.append(Finding(
                "heading.body-text-as-heading", "error", p.index,
                f"styled {p.style!r} but reads as body text ({len(_visible(p.text))} characters)",
                _visible(p.text)[:80] + "…"))
            continue

        if spec.get("run_on"):
            # H5 and H6 run on with the text and end in a colon; a standalone
            # paragraph carrying that level is already not what the spec describes.
            if not _visible(p.text).endswith(spec["separator"]):
                out.append(Finding(
                    "heading.run-on", "warning", p.index,
                    f"H{level} should run on with the text and end in "
                    f"{spec['separator']!r}", _visible(p.text)[:60]))

        want_case = spec["case"]
        got_case = case_of(p.text)
        if got_case != "unknown" and got_case != want_case:
            sev = "error" if want_case == "upper" else "warning"
            out.append(Finding(
                "heading.case", sev, p.index,
                f"H{level} should be {want_case} case, reads as {got_case}",
                _visible(p.text)[:60]))

        font = p.dominant_font
        if font and font != HOUSE_FONT:
            out.append(Finding("heading.font", "error", p.index,
                               f"H{level} is {font}, house font is {HOUSE_FONT}",
                               _visible(p.text)[:60]))

        size = p.dominant_size_pt
        if size is not None and abs(size - HOUSE_SIZE_PT) > 0.01:
            out.append(Finding("heading.size", "error", p.index,
                               f"H{level} is {size} pt, house size is {HOUSE_SIZE_PT} pt",
                               _visible(p.text)[:60]))

        # `is_bold` is None when nothing in the file says either way, which is not the
        # same as "not bold" — reporting it as a deviation would flag every heading
        # that inherits its weight from a correctly-configured style.
        if spec["bold"] is not None and p.is_bold is not None and p.is_bold != spec["bold"]:
            out.append(Finding(
                "heading.weight", "error", p.index,
                f"H{level} should be {'bold' if spec['bold'] else 'not bold'}",
                _visible(p.text)[:60]))

        if spec["italic"] is not None and p.is_italic is not None and p.is_italic != spec["italic"]:
            out.append(Finding(
                "heading.italic", "error", p.index,
                f"H{level} should be {'italic' if spec['italic'] else 'not italic'}",
                _visible(p.text)[:60]))

        if spec.get("align") and p.alignment and p.alignment != spec["align"]:
            out.append(Finding("heading.alignment", "warning", p.index,
                               f"H{level} is {p.alignment}-aligned, house is {spec['align']}",
                               _visible(p.text)[:60]))

    out.extend(_check_hierarchy(headings))
    return out


def _check_hierarchy(headings: List[Para]) -> List[Finding]:
    """Levels must not be skipped: an H1 followed by an H3 has no H2 to belong to."""
    out: List[Finding] = []
    previous: Optional[int] = None
    for p in headings:
        level = (p.outline_level or 0) + 1
        if previous is not None and level > previous + 1:
            out.append(Finding(
                "heading.skipped-level", "warning", p.index,
                f"H{previous} is followed by H{level} — H{previous + 1} is missing",
                _visible(p.text)[:60]))
        previous = level
    return out


def check_listings(structure: Structure) -> List[Finding]:
    """Bullets must be one of B1-B4 and numbers one of N1-N3, with a dot."""
    out: List[Finding] = []
    reported = set()

    for p in structure.paragraphs:
        L = p.listing
        if not L:
            continue
        key = (L.get("num_id"), L.get("level"))
        if key in reported:
            continue                       # one finding per list, not per bullet
        reported.add(key)

        kind = L.get("kind")
        code = L.get("house_code")

        if kind == "bullet" and code not in BULLET_CODES:
            out.append(Finding(
                "listing.bullet", "warning", p.index,
                f"bullet {L.get('glyph')!r} is not one of the house marks "
                f"(B1 ● B2 ○ B3 ■ B4 □)", _visible(p.text)[:60]))
        elif kind == "number":
            if code not in NUMBER_CODES:
                out.append(Finding(
                    "listing.number", "warning", p.index,
                    f"numbering {L.get('num_fmt')!r} is not one of the house formats "
                    f"(N1 1. N2 i. N3 a.)", _visible(p.text)[:60]))
            elif not L.get("dot_suffix"):
                out.append(Finding(
                    "listing.number-separator", "warning", p.index,
                    f"{code} should end in a dot; the list prints "
                    f"{L.get('lvl_text')!r}", _visible(p.text)[:60]))
    return out


def check_artwork(structure: Structure) -> List[Finding]:
    max_w, max_h = MAX_ARTWORK_IN
    out = []
    for img in structure.images:
        if img.width_in > max_w + 0.01 or img.height_in > max_h + 0.01:
            out.append(Finding(
                "artwork.size", "error", None,
                f"image {img.index + 1} is {img.width_in}\" x {img.height_in}\", "
                f"over the {max_w}\" x {max_h}\" maximum"))
    return out


def check_page(structure: Structure) -> List[Finding]:
    """Page size and margins — the only part of the layout spec a manuscript carries."""
    out: List[Finding] = []
    tol = PAGE_TOLERANCE_IN
    for i, s in enumerate(structure.sections):
        checks = [
            ("page width", s.page_width_in, PAGE_SPEC["width_in"]),
            ("page height", s.page_height_in, PAGE_SPEC["height_in"]),
            ("left margin", s.left_margin_in, PAGE_SPEC["left_in"]),
            ("right margin", s.right_margin_in, PAGE_SPEC["right_in"]),
            ("top margin", s.top_margin_in, PAGE_SPEC["top_in"]),
            ("bottom margin", s.bottom_margin_in, PAGE_SPEC["bottom_in"]),
        ]
        for label, got, want in checks:
            if got is None:
                continue
            if abs(got - want) > tol:
                out.append(Finding(
                    "page.geometry", "warning", None,
                    f"section {i + 1}: {label} is {got}\", house is {want}\""))
    return out


def check_tables(structure: Structure) -> List[Finding]:
    """Every table needs a caption, and the text needs to refer to it.

    Only possible at all now that tables are read: the previous reader skipped table
    cells entirely, so 11.3% of the Guanidine manuscript was never looked at by
    anything.
    """
    out: List[Finding] = []
    body = {p.index: p for p in structure.paragraphs}
    all_text = " ".join(p.text for p in structure.paragraphs).lower()

    for t in structure.tables:
        above = body.get(t.after_paragraph)
        caption = _visible(above.text) if above else ""
        if not re.match(r"(?i)^table\s*\d", caption):
            out.append(Finding(
                "table.caption", "warning", t.after_paragraph if above else None,
                f"table {t.index + 1} has no 'Table N' caption immediately above it",
                caption[:60] or "(nothing above it)"))
            continue
        m = re.match(r"(?i)^table\s*(\d+)", caption)
        if m:
            n = m.group(1)
            # A caption alone is not enough: a table nothing refers to is a table the
            # reader meets with no idea why it is there.
            if not re.search(rf"table\s*{n}\b", all_text.replace(caption.lower(), "", 1)):
                out.append(Finding(
                    "table.not-cited", "warning", t.after_paragraph,
                    f"Table {n} is captioned but never referred to in the text"))
    return out


#: The table specification. Sizes in points, margins in inches.
TABLE_SPEC = {
    "caption_size_pt": 11.0,        # "Table 3. Frequency and percentage…"
    "number_size_pt": 9.0,          # the "Table 3." label itself, bold
    "body_size_pt": 9.0,
    "font": HOUSE_FONT,
    "border_style": "single",
    "border_size_pt": 0.5,
    "margin_top_in": 0.02, "margin_bottom_in": 0.02,
    "margin_left_in": 0.04, "margin_right_in": 0.04,
    "note_size_pt": 9.0,
}
#: Cell margins are typed in inches and stored in twentieths of a point, so 0.04"
#: round-trips as 0.04 but 0.02" can land a thousandth away. Half a hundredth of an
#: inch is below what anyone can see on a page.
MARGIN_TOLERANCE_IN = 0.005

#: Paragraphs under a table that carry their own 9 pt rule.
NOTE_PREFIXES = ("note:", "note ", "abbreviation", "abbreviations", "source:")


def check_table_format(structure: Structure) -> List[Finding]:
    """Tables against the house table specification.

    Reported per table rather than per cell. A 7x8 table whose body font is wrong is
    one decision an editor makes once; fifty-six findings saying the same thing is a
    report that hides its other contents.
    """
    out: List[Finding] = []
    body = {p.index: p for p in structure.paragraphs if not p.in_table}

    for t in structure.tables:
        label = f"table {t.index + 1}"
        f = t.fmt

        if f.border_style is None:
            out.append(Finding(
                "table.border", "info", None,
                f"{label} states no borders of its own (style {f.style!r}); "
                f"house is a single solid {TABLE_SPEC['border_size_pt']} pt line"))
        else:
            if f.border_style != TABLE_SPEC["border_style"]:
                out.append(Finding("table.border", "warning", None,
                                   f"{label} border is {f.border_style!r}, "
                                   f"house is {TABLE_SPEC['border_style']!r}"))
            if (f.border_size_pt is not None
                    and abs(f.border_size_pt - TABLE_SPEC["border_size_pt"]) > 0.01):
                out.append(Finding("table.border", "warning", None,
                                   f"{label} border is {f.border_size_pt} pt, "
                                   f"house is {TABLE_SPEC['border_size_pt']} pt"))

        for edge, attr in (("top", "margin_top_in"), ("bottom", "margin_bottom_in"),
                           ("left", "margin_left_in"), ("right", "margin_right_in")):
            got = getattr(f, attr)
            want = TABLE_SPEC[attr]
            if got is not None and abs(got - want) > MARGIN_TOLERANCE_IN:
                out.append(Finding("table.cell-margin", "info", None,
                                   f"{label} {edge} cell margin is {got}\", "
                                   f"house is {want}\""))

        out.extend(_check_table_cells(t, label))
        out.extend(_check_table_caption(t, label, body))
        out.extend(_check_table_notes(t, label, body))
    return out


def _check_table_cells(t, label: str) -> List[Finding]:
    """Column heads bold, body text plain, everything 9 pt Times New Roman."""
    out: List[Finding] = []
    if not t.grid:
        return out

    wrong_font, wrong_size, unbold_head = set(), set(), 0
    for ri, row in enumerate(t.grid):
        for cell in row:
            for p in cell.paragraphs:
                if not p.text.strip():
                    continue
                if p.dominant_font and p.dominant_font != TABLE_SPEC["font"]:
                    wrong_font.add(p.dominant_font)
                size = p.dominant_size_pt
                if size is not None and abs(size - TABLE_SPEC["body_size_pt"]) > 0.01:
                    wrong_size.add(size)
                # Only the first row: a subhead row is bold italic and legitimate,
                # and rows below the head are meant to be plain.
                if ri == 0 and p.is_bold is False:
                    unbold_head += 1

    if wrong_font:
        out.append(Finding("table.font", "warning", None,
                           f"{label} uses {', '.join(sorted(wrong_font))}, "
                           f"house table font is {TABLE_SPEC['font']}"))
    if wrong_size:
        sizes = ", ".join(f"{s} pt" for s in sorted(wrong_size))
        out.append(Finding("table.size", "warning", None,
                           f"{label} has text at {sizes}, "
                           f"house table size is {TABLE_SPEC['body_size_pt']} pt"))
    if unbold_head:
        out.append(Finding("table.column-head", "warning", None,
                           f"{label} has {unbold_head} column head cell(s) not in bold"))
    return out


def _check_table_caption(t, label: str, body: Dict[int, Para]) -> List[Finding]:
    """`Table N.` bold at 9 pt, the caption itself 11 pt normal, above the table."""
    out: List[Finding] = []
    above = body.get(t.after_paragraph)
    if above is None or not re.match(r"(?i)^\s*table\s*\d", _visible(above.text)):
        return out                     # `check_tables` already reports the absence

    size = above.dominant_size_pt
    if size is not None and abs(size - TABLE_SPEC["caption_size_pt"]) > 0.01:
        out.append(Finding("table.caption-size", "warning", above.index,
                           f"{label} caption is {size} pt, house is "
                           f"{TABLE_SPEC['caption_size_pt']} pt",
                           _visible(above.text)[:60]))

    if above.dominant_font and above.dominant_font != TABLE_SPEC["font"]:
        out.append(Finding("table.caption-font", "warning", above.index,
                           f"{label} caption is {above.dominant_font}, house is "
                           f"{TABLE_SPEC['font']}", _visible(above.text)[:60]))

    # "Table 3." is bold and the sentence after it is not, so the caption paragraph
    # must contain both. A caption that is bold throughout, or nowhere, is wrong in
    # a way a per-paragraph bold check cannot see — it has to look run by run.
    weights = {bool(r.bold) for r in above.runs if r.text.strip()}
    if len(weights) == 1:
        out.append(Finding(
            "table.caption-weight", "info", above.index,
            f"{label} caption is "
            f"{'entirely bold' if weights == {True} else 'not bold anywhere'}; "
            f"house sets the 'Table N.' label bold and the caption text normal",
            _visible(above.text)[:60]))
    return out


def _check_table_notes(t, label: str, body: Dict[int, Para]) -> List[Finding]:
    """Note, Abbreviation and Source lines under a table are 9 pt."""
    out: List[Finding] = []
    # The note sits after the table, so it is the first body paragraph whose index is
    # greater than the one the table follows.
    following = sorted(i for i in body if i > t.after_paragraph)
    for idx in following[:3]:
        p = body[idx]
        text = _visible(p.text).lower()
        if not any(text.startswith(prefix) for prefix in NOTE_PREFIXES):
            continue
        size = p.dominant_size_pt
        if size is not None and abs(size - TABLE_SPEC["note_size_pt"]) > 0.01:
            out.append(Finding("table.note-size", "info", p.index,
                               f"{label} note line is {size} pt, house is "
                               f"{TABLE_SPEC['note_size_pt']} pt",
                               _visible(p.text)[:60]))
    return out


#: Rules where the same deviation repeating across tables is one decision, not many.
#: Twelve tables with the same wrong cell margin produced 34 findings on the Guanidine
#: paper — enough to bury the four that were about something else.
_COLLAPSIBLE = ("table.cell-margin", "table.border", "table.font", "table.size",
                "page.geometry")


def collapse_repeats(findings: List[Finding]) -> List[Finding]:
    """Fold identical deviations that differ only in which table they are about.

    Keyed on the message with the table number removed, so "table 1 left cell margin
    is 0.03" and "table 7 left cell margin is 0.03" become one line that names the
    count. The first table is still named, so there is somewhere to go and look.
    """
    out: List[Finding] = []
    groups: Dict[str, List[Finding]] = {}
    order: List[Any] = []

    for f in findings:
        if f.rule not in _COLLAPSIBLE:
            order.append(f)
            continue
        # Section number normalised alongside the table number: a manuscript with
        # five sections reported the same four wrong margins twenty times.
        generic_key = re.sub(r"\btable \d+\b", "table N", f.message)
        generic_key = re.sub(r"\bsection \d+\b", "section N", generic_key)
        key = f.rule + "|" + generic_key
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f)

    for item in order:
        if isinstance(item, Finding):
            out.append(item)
            continue
        group = groups[item]
        first = group[0]
        if len(group) == 1:
            out.append(first)
            continue
        generic = re.sub(r"\btable \d+\b", f"{len(group)} tables", first.message, count=1)
        generic = re.sub(r"\bsection \d+\b", f"{len(group)} sections", generic, count=1)
        out.append(Finding(first.rule, first.severity, first.paragraph, generic,
                           f"first: {first.message}"))
    return out


def check_all(structure: Structure) -> List[Finding]:
    return collapse_repeats(
        check_headings(structure) + check_listings(structure)
        + check_artwork(structure) + check_page(structure)
        + check_tables(structure) + check_table_format(structure))


def summarise(findings: List[Finding]) -> Dict[str, Any]:
    by_rule: Dict[str, int] = {}
    by_sev: Dict[str, int] = {}
    for f in findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    return {"total": len(findings), "by_severity": by_sev, "by_rule": by_rule}
