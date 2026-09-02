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
        # 1-based, because every place this number is shown to a person is 1-based:
        # the House Style panel (`app.py`) and the editorial report (`pipeline.py`)
        # both render `paragraph + 1`. Leaving this one 0-based meant the same
        # paragraph could be named ¶142 in one line of a report and ¶143 in the next,
        # which reads as a tool that cannot count.
        where = f"¶{self.paragraph + 1}" if self.paragraph is not None else "document"
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
#: The heading rules repeat per heading, and across 1,597 real manuscripts they are by
#: far the larger number: `heading.size` averages 11.2 findings a manuscript and reaches
#: 97 in one, `heading.body-text-as-heading` 118. Each line is true and each is word for
#: word the one above it — a manuscript whose H3s are all in Cambria says so ninety-odd
#: times. `heading.skipped-level` is deliberately absent: it is about one specific place
#: in the hierarchy, and there are never many.
_COLLAPSIBLE = ("table.cell-margin", "table.border", "table.font", "table.size",
                "page.geometry",
                "heading.size", "heading.font", "heading.case", "heading.weight",
                "heading.italic", "heading.alignment", "heading.run-on",
                "heading.body-text-as-heading")


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
        # The one heading message that carries a varying number: "reads as body text
        # (143 characters)". Without normalising it every over-long heading is its own
        # group and nothing folds at all.
        generic_key = re.sub(r"\(\d+ characters\)", "(N characters)", generic_key)
        # The heading level is NOT normalised, on purpose. "H1 is Cambria" and "H3 is
        # Cambria" are two different findings, and folding them would name a level the
        # editor would then not find anything wrong with.
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
        if generic == first.message:
            # Nothing in the message named what repeated — a heading finding reads
            # "H3 is Cambria, house font is Times New Roman" and carries no count at
            # all. Left alone, the collapsed finding would be indistinguishable from a
            # single one and the other sixty-three would simply be gone.
            generic = f"{len(group)} headings: {first.message}"
        out.append(Finding(first.rule, first.severity, first.paragraph, generic,
                           f"first: {first.message}"))
    return out


# --------------------------------------------------- body text and front matter

#: The body-text and front-matter specification, from the annotated JoSEM article.
#: Sizes in points, indents in inches.
BODY_SPEC = {
    "font": HOUSE_FONT, "size_pt": 11.0, "align": "justify",
    "first_line_in": 0.15, "space_after_pt": 11.0,
}
TITLE_SPEC = {"font": "Calibri Light", "size_pt": 20.0, "bold": True, "align": "left"}
AUTHORS_SPEC = {"font": "Garamond", "size_pt": 12.0, "align": "left"}
ABSTRACT_HEADING_SPEC = {"size_pt": 11.0, "bold": True, "italic": True, "align": "center"}
ABSTRACT_BODY_SPEC = {"size_pt": 11.0, "italic": True, "align": "justify"}
KEYWORDS_SPEC = {"size_pt": 11.0, "align": "justify"}
REFERENCE_SPEC = {"size_pt": 11.0, "align": "justify", "hanging_in": -0.25}

#: Indents are typed in inches and stored in EMU, so 0.15" round-trips exactly while
#: 11 pt of space-after can land a tenth away.
INDENT_TOLERANCE_IN = 0.01
SPACING_TOLERANCE_PT = 0.6

#: How much of the body has to disagree before it is worth one finding. Below this it
#: is a stray paragraph, above it the manuscript was written to a different template —
#: and the second is the one an editor can act on in a single pass.
BODY_SHARE_THRESHOLD = 0.30
#: Paragraphs shorter than this are captions, labels and equation lines rather than
#: body text, and none of them follow the body rule.
BODY_MIN_CHARS = 120


def find_front_matter(structure: Structure) -> Dict[str, Any]:
    """Locate the title, authors, abstract and keywords, or say nothing.

    Heuristic and deliberately timid: it only names a part when the manuscript makes
    it obvious. A confident guess here would report the abstract's formatting against
    a paragraph that is not the abstract, and every one of those findings would look
    exactly like a real one.
    """
    found: Dict[str, Any] = {}
    body = [p for p in structure.body_paragraphs() if _visible(p.text)]
    if not body:
        return found

    for i, p in enumerate(body[:40]):
        text = _visible(p.text)
        low = text.lower().rstrip(":")
        if "abstract" not in found and low == "abstract":
            found["abstract_heading"] = p
            if i + 1 < len(body):
                found["abstract_body"] = body[i + 1]
            found["abstract"] = True
        # `Abstract— This study examines...` — the heading run on with the text. The
        # abstract is present and is not formatted the way the house asks. Recorded
        # separately so the finding can say that, instead of "no abstract was found",
        # which sends an editor looking for something that is on the page.
        elif ("abstract" not in found
              and re.match(r"(?i)^abstract\s*[—–:-]", text) and len(text) > 60):
            found["abstract_runon"] = p
            found["abstract_body"] = p
            found["abstract"] = True
        if "keywords" not in found and low.startswith("keywords"):
            found["keywords"] = p

    # The title is the first paragraph only when nothing above it looks like one.
    first = body[0]
    if len(_visible(first.text)) < 200 and first.outline_level is None:
        found["title"] = first
        if len(body) > 1 and len(_visible(body[1].text)) < 200:
            found["authors"] = body[1]
    return found


def find_references(structure: Structure) -> List[Para]:
    """Everything after a REFERENCES heading. Empty when there is no such heading."""
    body = structure.body_paragraphs()
    start = None
    for p in body:
        if re.fullmatch(r"(?i)\s*references\s*", _visible(p.text)):
            start = p.index
            break
    if start is None:
        return []
    return [p for p in body if p.index > start and _visible(p.text)]


def check_body_text(structure: Structure) -> List[Finding]:
    """The body against 11 pt Times New Roman, justified, 0.15" first line.

    Reported as a share rather than per paragraph. A manuscript written to the wrong
    template has every paragraph wrong, and three hundred identical findings is not
    three hundred pieces of information — it is one, told badly.
    """
    out: List[Finding] = []
    refs = {p.index for p in find_references(structure)}
    front = find_front_matter(structure)
    skip = {p.index for p in front.values() if isinstance(p, Para)}

    body = [p for p in structure.body_paragraphs()
            if len(_visible(p.text)) >= BODY_MIN_CHARS
            and p.outline_level is None
            and not p.listing
            and p.index not in refs
            and p.index not in skip]
    if not body:
        return out

    total = len(body)

    def report(rule, predicate, message, severity="warning"):
        bad = [p for p in body if predicate(p)]
        if len(bad) / total >= BODY_SHARE_THRESHOLD:
            out.append(Finding(
                rule, severity, bad[0].index,
                f"{len(bad)} of {total} body paragraphs {message}",
                _visible(bad[0].text)[:70]))

    report("body.font",
           lambda p: p.dominant_font and p.dominant_font != BODY_SPEC["font"],
           f"are not {BODY_SPEC['font']}")
    report("body.size",
           lambda p: (p.dominant_size_pt is not None
                      and abs(p.dominant_size_pt - BODY_SPEC["size_pt"]) > 0.01),
           f"are not {BODY_SPEC['size_pt']} pt")
    report("body.alignment",
           lambda p: p.alignment is not None and p.alignment != BODY_SPEC["align"],
           f"are not {BODY_SPEC['align']}-aligned")
    report("body.first-line-indent",
           lambda p: (p.first_line_in is None
                      or abs(p.first_line_in - BODY_SPEC["first_line_in"]) > INDENT_TOLERANCE_IN),
           f'do not have the {BODY_SPEC["first_line_in"]}" first-line indent',
           severity="info")
    return out


def check_front_matter(structure: Structure) -> List[Finding]:
    out: List[Finding] = []
    front = find_front_matter(structure)

    def check(part: str, spec: Dict[str, Any], rule_prefix: str):
        p = front.get(part)
        if not isinstance(p, Para):
            return
        if "font" in spec and p.dominant_font and p.dominant_font != spec["font"]:
            out.append(Finding(f"{rule_prefix}.font", "warning", p.index,
                               f"{part.replace('_', ' ')} is {p.dominant_font}, "
                               f"house is {spec['font']}", _visible(p.text)[:60]))
        if ("size_pt" in spec and p.dominant_size_pt is not None
                and abs(p.dominant_size_pt - spec["size_pt"]) > 0.01):
            out.append(Finding(f"{rule_prefix}.size", "warning", p.index,
                               f"{part.replace('_', ' ')} is {p.dominant_size_pt} pt, "
                               f"house is {spec['size_pt']} pt", _visible(p.text)[:60]))
        # `is_bold`/`is_italic` are None when the file says nothing, which is not the
        # same as False — reporting it would flag every part that inherits correctly.
        if "bold" in spec and p.is_bold is not None and p.is_bold != spec["bold"]:
            out.append(Finding(f"{rule_prefix}.weight", "warning", p.index,
                               f"{part.replace('_', ' ')} should be "
                               f"{'bold' if spec['bold'] else 'not bold'}",
                               _visible(p.text)[:60]))
        if "italic" in spec and p.is_italic is not None and p.is_italic != spec["italic"]:
            out.append(Finding(f"{rule_prefix}.italic", "warning", p.index,
                               f"{part.replace('_', ' ')} should be "
                               f"{'italic' if spec['italic'] else 'not italic'}",
                               _visible(p.text)[:60]))
        if "align" in spec and p.alignment and p.alignment != spec["align"]:
            out.append(Finding(f"{rule_prefix}.alignment", "info", p.index,
                               f"{part.replace('_', ' ')} is {p.alignment}-aligned, "
                               f"house is {spec['align']}", _visible(p.text)[:60]))

    check("title", TITLE_SPEC, "title")
    check("authors", AUTHORS_SPEC, "authors")
    check("abstract_heading", ABSTRACT_HEADING_SPEC, "abstract-heading")
    check("abstract_body", ABSTRACT_BODY_SPEC, "abstract")
    check("keywords", KEYWORDS_SPEC, "keywords")

    runon = front.get("abstract_runon")
    if isinstance(runon, Para):
        out.append(Finding(
            "front.abstract-runon", "warning", runon.index,
            "the Abstract heading runs on with the abstract text; house sets it as "
            "its own centred, bold, italic line",
            _visible(runon.text)[:70]))
    elif "abstract" not in front:
        out.append(Finding("front.abstract-missing", "warning", None,
                           "no paragraph reading just 'Abstract' was found"))
    if "keywords" not in front:
        out.append(Finding("front.keywords-missing", "warning", None,
                           "no 'Keywords:' line was found"))
    elif not _visible(front["keywords"].text).lower().startswith("keywords:"):
        # Names the separator actually used, so the fix is obvious. Both real
        # manuscripts checked used a dash, and "should use a colon" without saying
        # what is there now reads as a complaint rather than an instruction.
        after = _visible(front["keywords"].text)[len("keywords"):][:3].strip()
        out.append(Finding("front.keywords-colon", "info",
                           front["keywords"].index,
                           f"the keywords line separates with {after[:1]!r}; "
                           f"house is a colon",
                           _visible(front["keywords"].text)[:60]))
    return out


def check_references(structure: Structure) -> List[Finding]:
    """Vancouver: 11 pt, justified, numbered, 0.25" hanging indent."""
    out: List[Finding] = []
    refs = [p for p in find_references(structure)
            if len(_visible(p.text)) > 30]
    if not refs:
        return out

    total = len(refs)
    numbered = sum(1 for p in refs
                   if re.match(r"^\s*\[?\d{1,3}[\].]", _visible(p.text)) or p.listing)
    if numbered / total < 0.5:
        out.append(Finding("references.numbering", "warning", refs[0].index,
                           f"only {numbered} of {total} references are numbered; "
                           f"the house uses a numbered (Vancouver) list",
                           _visible(refs[0].text)[:70]))

    hanging = sum(1 for p in refs
                  if p.first_line_in is not None
                  and abs(p.first_line_in - REFERENCE_SPEC["hanging_in"]) <= INDENT_TOLERANCE_IN)
    if hanging / total < 0.5:
        out.append(Finding("references.hanging-indent", "info", refs[0].index,
                           f'{total - hanging} of {total} references lack the '
                           f'0.25" hanging indent'))

    wrong_size = [p for p in refs
                  if p.dominant_size_pt is not None
                  and abs(p.dominant_size_pt - REFERENCE_SPEC["size_pt"]) > 0.01]
    if len(wrong_size) / total >= BODY_SHARE_THRESHOLD:
        out.append(Finding("references.size", "warning", wrong_size[0].index,
                           f"{len(wrong_size)} of {total} references are not "
                           f"{REFERENCE_SPEC['size_pt']} pt",
                           _visible(wrong_size[0].text)[:70]))
    return out


def check_all(structure: Structure) -> List[Finding]:
    return collapse_repeats(
        check_headings(structure) + check_listings(structure)
        + check_artwork(structure) + check_page(structure)
        + check_tables(structure) + check_table_format(structure)
        + check_body_text(structure) + check_front_matter(structure)
        + check_references(structure))


def summarise(findings: List[Finding]) -> Dict[str, Any]:
    by_rule: Dict[str, int] = {}
    by_sev: Dict[str, int] = {}
    for f in findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    return {"total": len(findings), "by_severity": by_sev, "by_rule": by_rule}
