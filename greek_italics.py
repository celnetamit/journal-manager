"""Greek letters set the way a journal sets them.

The quality team, job #109: *"Sabhi lower greek character italic and Capital greek
character Roman me honge."* That is the international convention (ISO 80000-2) and it
is what every physical-science house style says: a **quantity** symbol is italic, and a
Greek capital used as an operator or a constant is upright.

**The exception that matters more than the rule.** `μ` in `μm`, `μL`, `μg` is not a
quantity — it is the SI prefix *micro*, and a unit symbol is **always** upright. So is
`Ω` in `10 Ω`, and so is `Δ` in `ΔT`, an operator rather than a variable. Italicising
the micro in `μm` would put a formatting error into every measurement in the paper, and
on this estate that letter already has form: job #100's whole argument was about `µm`.

So the rule is applied to letters standing as symbols and refused everywhere the letter
is doing another job. Measured on the corpus before it was wired in.

**This writes formatting, which is new here, and the reason is worth stating.**
`science_format`'s docstring says plainly that nothing rewrites italics, because a
wrong italic is worse than a missing one and the redline carries tracked *text*
changes, not tracked formatting — an editor cannot reject this the way they reject a
word. It is done anyway because the team asked for it and because the rule is
mechanical: there is no judgement in "a lowercase Greek quantity symbol is italic".
Every change is counted and reported in one query, so nothing happens silently.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from docx.oxml.ns import qn

LOWER_GREEK = set("αβγδεζηθικλμνξοπρστυφχψωϑϕϖϱς")
UPPER_GREEK = set("ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ")

#: Unit symbols the micro prefix attaches to. A letter here after `μ` makes the `μ`
#: part of a unit, and units are upright.
_UNIT_AFTER_MICRO = re.compile(
    r"\s*(?:m|g|s|L|l|A|K|N|J|W|V|F|C|T|H|Pa|mol|cd|Hz|Ω|Sv|Gy|Bq|M|m³|m3|m2|m²)\b")

#: `Ω` and `°` are units wherever a number is what comes before them.
_NUMBER_BEFORE = re.compile(r"[\d\s,.]$")


def _wants_italic(text: str, index: int) -> bool | None:
    """`True`, `False`, or `None` for "this character is not our business".

    Kept as one function with the reasoning beside each case, because every one of
    these is a decision somebody will ask about later.
    """
    char = text[index]
    if char in UPPER_GREEK:
        # Upright, always. Δ is an operator, Σ a sum, Ω an ohm, and a capital used as
        # a quantity (Φ for magnetic flux) is upright in this convention too.
        return False
    if char not in LOWER_GREEK:
        return None

    after = text[index + 1:]
    before = text[:index]

    if char == "μ":
        # The micro prefix: `μm`, `μL`, `10 μg`. A unit, so upright.
        if _UNIT_AFTER_MICRO.match(after):
            return False
    if before[-1:].isalpha() and before[-1:].isupper():
        # `CuKα`, `Kβ`, `Lα` — the designation of a spectral line, not a quantity, and
        # upright by the same convention that italicises the quantities. Found by
        # reading all 52 changes this pass proposed across 40 real manuscripts: two
        # were the α of Cu Kα radiation. A Greek quantity symbol does not run straight
        # on from a capital letter — it stands alone, or after a space, a bracket or a
        # digit.
        return False
    if char in "Ωω" and _NUMBER_BEFORE.search(before or " "):
        # `10 Ω` — resistance, a unit.
        if not after[:1].isalnum():
            return False
    return True


def _italic_of(run) -> bool:
    rpr = run.find(qn("w:rPr"))
    if rpr is None:
        return False
    node = rpr.find(qn("w:i"))
    if node is None:
        return False
    return node.get(qn("w:val")) not in ("0", "false", "none")


def _set_italic(run, italic: bool) -> None:
    rpr = run.find(qn("w:rPr"))
    if rpr is None:
        rpr = run.makeelement(qn("w:rPr"), {})
        run.insert(0, rpr)
    node = rpr.find(qn("w:i"))
    if italic:
        if node is None:
            rpr.append(rpr.makeelement(qn("w:i"), {}))
        else:
            node.attrib.pop(qn("w:val"), None)
    elif node is not None:
        node.set(qn("w:val"), "0")


def _split_run(run, spans: List[Tuple[str, bool | None]]) -> None:
    """Replace one run with several, one per stretch that needs the same italic.

    The run's own properties are copied to each piece, so a superscript stays a
    superscript and a colour stays a colour. Only `w:i` is decided here.
    """
    import copy

    parent = run.getparent()
    at = list(parent).index(run)
    rpr = run.find(qn("w:rPr"))
    made = []
    for text, italic in spans:
        piece = copy.deepcopy(run)
        for child in list(piece):
            if child.tag in (qn("w:t"), qn("w:delText")):
                child.text = text
                child.set(qn("xml:space"), "preserve")
            elif child.tag != qn("w:rPr"):
                piece.remove(child)
        if rpr is None and italic is not None:
            pass
        if italic is not None:
            _set_italic(piece, italic)
        made.append(piece)
    for offset, piece in enumerate(made):
        parent.insert(at + offset, piece)
    parent.remove(run)


def apply_to_document(doc) -> Dict[str, int]:
    """Set every Greek letter the way the convention wants it. Returns a census."""
    counts: Dict[str, int] = {"italicised": 0, "made upright": 0, "left as a unit": 0}

    for run in list(doc.element.body.iter(qn("w:r"))):
        nodes = [n for n in run if n.tag in (qn("w:t"), qn("w:delText"))]
        if len(nodes) != 1:
            continue
        text = nodes[0].text or ""
        if not text or not any(c in LOWER_GREEK or c in UPPER_GREEK for c in text):
            continue

        italic_now = _italic_of(run)
        wanted = [_wants_italic(text, i) for i in range(len(text))]
        if all(w is None for w in wanted):
            continue

        # A letter that is part of a unit is counted so the query can say so; it is
        # the case an editor is most likely to query back.
        counts["left as a unit"] += sum(
            1 for i, w in enumerate(wanted)
            if w is False and text[i] in LOWER_GREEK)

        # What each character should end up as: a decided value, or the run's own
        # setting where this module has no opinion.
        final = [italic_now if w is None else w for w in wanted]
        if all(f == italic_now for f in final):
            continue

        spans: List[Tuple[str, bool | None]] = []
        start = 0
        for i in range(1, len(text) + 1):
            if i < len(text) and final[i] == final[start]:
                continue
            spans.append((text[start:i], final[start]))
            start = i
        for chunk, italic in spans:
            if italic != italic_now:
                changed = sum(1 for c in chunk if c in LOWER_GREEK or c in UPPER_GREEK)
                counts["italicised" if italic else "made upright"] += changed
        _split_run(run, spans)

    return counts


def query_for(counts: Dict[str, int]) -> List[Dict[str, object]]:
    """One query, or none. Formatting is not a tracked change, so if this is not said
    plainly nobody knows it happened."""
    changed = counts.get("italicised", 0) + counts.get("made upright", 0)
    if not changed:
        return []
    parts = []
    if counts.get("italicised"):
        parts.append(f"{counts['italicised']} lowercase Greek symbol(s) set in italic")
    if counts.get("made upright"):
        parts.append(f"{counts['made upright']} capital Greek letter(s) set upright")
    note = ""
    if counts.get("left as a unit"):
        note = (f" {counts['left as a unit']} were left upright because the letter is "
                f"part of a unit (μm, μL, 10 Ω) — a unit symbol is never italic.")
    return [{
        "index": 0,
        "snippet": "Greek symbols",
        "query": ("Greek letters have been set to the usual convention: "
                  + " and ".join(parts) + "." + note
                  + " This is a formatting change, so it does not appear as a tracked "
                    "change — it is listed here instead."),
        "guard": "greek_italics",
        "suggestion": None,
    }]
