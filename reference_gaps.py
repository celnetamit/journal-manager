"""Mark a reference's missing field where the field belongs.

Amit, 17 Sep 2026, relaying the quality team: *"if the value/data is missing — like ref
7 author missing — to isko reference me hi `[author missing]` ka query lagana chahiye,
alag colour me highlight kar ke, author ke position par, taki ye visualisation sahi ho
jaye."*

The check that finds these has been running for weeks and it says what it found in a
comment: *"This reference is missing author names."* The comment is right and it is in
the wrong place — it sits in the margin, beside an entry that looks complete. A reader
scanning twenty-five references sees twenty-five complete-looking entries and a column
of grey balloons, and nothing on the page says **where** the hole is.

So the gap is written into the entry, at the position the missing field would occupy:

    [15] Lopez-Garcia RD, Medina-Juárez I. Effect of quenching… 2022.
    [17] **[author names missing]** Study on induction hardening performance…

Authors go at the head, after the entry number — that is where Vancouver puts them, and
an entry that opens with the title is exactly the entry whose authors are gone.
Everything else goes at the tail, which is where a volume, an issue and a page range
live. Nothing is invented and nothing is moved: a bracketed note is added and it is a
tracked insertion, so it is rejected in one click and it cannot be mistaken for the
author's own words.

The marker carries its own highlight colour, set in `editor`, so it is not the yellow
that every other insertion wears.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

#: The opening `[15]` or `15.` of a numbered entry. The marker goes *after* it, so the
#: numbering stays where a reader looks for it.
_ENTRY_NUMBER = re.compile(r"^\s*(?:\[\s*\d{1,3}\s*\]|\d{1,3}[.)])\s*")

#: Which gaps belong at the front of an entry. Everything else belongs at the end.
_AT_THE_FRONT = ("author",)

#: How each gap is named to a reader. The check's own words are terse and plural-aware
#: already; this only fixes what a person should see in the middle of a sentence.
MARKER = "[{what} missing]"


def _split(gaps: Iterable[str]) -> Tuple[List[str], List[str]]:
    front, back = [], []
    for gap in gaps:
        text = str(gap).strip()
        if not text:
            continue
        (front if any(word in text.lower() for word in _AT_THE_FRONT) else back
         ).append(text)
    return front, back


def mark(entry: str, gaps: Iterable[str]) -> str:
    """The entry with a bracketed note where each missing field belongs."""
    front, back = _split(gaps)
    if not front and not back:
        return entry
    text = entry or ""
    if front:
        head = _ENTRY_NUMBER.match(text)
        at = head.end() if head else 0
        note = MARKER.format(what=", ".join(front))
        text = f"{text[:at]}{note} {text[at:].lstrip()}"
    if back:
        note = MARKER.format(what=", ".join(back))
        text = text.rstrip()
        # Before the full stop rather than after it, so the entry still ends the way a
        # reference ends.
        if text.endswith("."):
            text = f"{text[:-1]} {note}."
        else:
            text = f"{text} {note}"
    return text


def apply(paragraphs: List[str], gaps_by_index: Dict[int, List[str]]) -> Tuple[List[str], int]:
    """Mark every entry that has a gap. Returns the paragraphs and how many were marked."""
    out = list(paragraphs)
    marked = 0
    for index, gaps in (gaps_by_index or {}).items():
        if not (isinstance(index, int) and 0 <= index < len(out)):
            continue
        before = out[index] or ""
        if not before.strip() or "missing]" in before:
            continue
        after = mark(before, gaps)
        if after != before:
            out[index] = after
            marked += 1
    return out, marked
