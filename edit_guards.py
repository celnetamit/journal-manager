"""Edits the copyedit is not allowed to make, undone deterministically.

The copyedit is a model, and on a real manuscript it applied the same rule to three
adjacent lines three different ways. These guards do not try to make it consistent —
they compare the original paragraph with the edited one and put back the part that
must not have gone. Each one is a specific, measured failure, not a general suspicion:

* **Front-matter dates lost their day and month.** `Accepted Date: 29th May, 2026`
  came back as `Accepted Date: 2026` — and `Submission Date: 9th May, 2026` on the
  line above came back correctly as `May 9, 2026`. The existing shrink guard cannot
  see this: it exempts paragraphs under 120 characters, because "2.2 Material
  characteristics" losing its number is a *correct* large cut on a short line.

* **Algorithm step numbers were stripped.** The house rule says headings carry no
  leading number, and the model applied it to the steps of an Algorithm listing:
  `5:  For each epoch do` became `For each epoch do`. Ten of thirteen steps lost
  their number and three kept it, so the listing came out unreadable *and*
  inconsistent.

* **A citation at the end of a paragraph sat outside the full stop.** `... once
  convergence is reached. [17]` — the stop belongs after the marker.

The fourth failure in the same manuscript cannot be fixed here and is reported
instead: see `orphaned_formula_queries`.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

#: A journal front-matter date line. These carry the article's own dates, not a
#: reference's, and the day and month are the point of them.
_FRONT_DATE = re.compile(
    r"^\s*(submission|submitted|received|accepted|revised|published|available)\s*"
    r"(date|online)?\s*[:\-–]", re.I)

_MONTH = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)

#: A numbered step in an algorithm or pseudocode listing: `4:` or `4.` followed by an
#: em-space or tab, which is how Word sets these. Requiring the wide separator keeps
#: it away from ordinary numbered headings. The class must NOT contain an ordinary
#: space — a first version did and it matched `2. Literature Review:` and `4. Proposed
#: Methodology:`, putting numbers back onto the headings the house rule had just
#: correctly stripped. Caught by replaying the guard over the real manuscript.
_ALGORITHM_STEP = re.compile("^\\s*(\\d{1,2})\\s*[:.]([\u2003\u2002\t])")

#: A paragraph that ends with a numbered citation and no terminal punctuation.
_TRAILING_CITATION = re.compile(
    r"(?P<stop>[.!?])\s*(?P<cite>\[\d+(?:\s*[,\-–—]\s*\d+)*\])\s*$")


def _lost_the_date(before: str, after: str) -> bool:
    """True when a front-matter date line came back without its month."""
    return bool(_FRONT_DATE.match(before)
                and _MONTH.search(before) and not _MONTH.search(after))


def _lost_the_step_number(before: str, after: str) -> bool:
    """True when an algorithm step came back without its number."""
    m = _ALGORITHM_STEP.match(before)
    if not m:
        return False
    return not re.match(rf"^\s*{m.group(1)}\s*[:.]", after)


def restore_protected_text(originals: List[str], edited: List[str]) -> Tuple[
        List[str], List[Dict[str, object]]]:
    """Put back what the copyedit removed but must not have.

    Returns the corrected paragraphs and one query per restoration, so the editor is
    told that an edit was rejected rather than the disagreement happening in silence.
    A guard that quietly overrules the copyedit is the same failure as a copyedit that
    quietly overrules the author.
    """
    out: List[str] = []
    queries: List[Dict[str, object]] = []
    for i, (before, after) in enumerate(zip(originals, edited)):
        if not before or not after or before == after:
            out.append(after)
            continue
        if _lost_the_date(before, after):
            out.append(before)
            queries.append({
                "index": i,
                "snippet": before[:80],
                "query": ("The copyedit removed the day and month from this date "
                          "line; the article's own dates are kept in full, so the "
                          "original has been restored."),
                "suggestion": before,
            })
            continue
        if _lost_the_step_number(before, after):
            number = _ALGORITHM_STEP.match(before).group(1)
            restored = f"{number}: {after.lstrip()}"
            out.append(restored)
            queries.append({
                "index": i,
                "snippet": before[:80],
                "query": ("This is a numbered step in an algorithm listing, not a "
                          "heading — its number has been put back."),
                "suggestion": restored,
            })
            continue
        out.append(after)
    # A shorter `edited` would silently truncate the manuscript; zip stops at the
    # shorter list, so anything beyond it is carried through untouched.
    out.extend(edited[len(out):])
    return out, queries


def fix_trailing_citations(paras: List[str]) -> List[str]:
    """`... is reached. [17]` -> `... is reached [17].`

    The marker belongs inside the sentence it supports, and a paragraph that ends on
    a bracket has no terminal punctuation at all. Only touched when the citation is
    the very last thing in the paragraph, so a mid-sentence marker is never moved.
    """
    def fix(p: str) -> str:
        # The collapse is applied only to what the substitution produced. An earlier
        # version ran `.replace("  ", " ")` over every paragraph unconditionally and
        # silently reflowed the indented denominator lines of the display formulas,
        # which have nothing to do with citations.
        new = _TRAILING_CITATION.sub(
            lambda m: f" {m.group('cite')}{m.group('stop')}", p)
        return re.sub(r" {2,}(\[\d)", r" \1", new) if new != p else p

    return [fix(p) if p else p for p in paras]


#: The numerator line of a two-line fraction, after the copyedit has rebuilt the whole
#: formula onto it: it now contains a division and an equation number.
_REBUILT_FORMULA = re.compile(r"=.*/.*…?\s*\(?\d+\)?\s*$")
#: What is left on the line below — a denominator and the equation number, no verb,
#: no sentence.
_ORPHAN_DENOMINATOR = re.compile(r"^[\s ]*[A-Za-z0-9+\-×*/() ]{2,40}…?\s*\(\d+\)\s*$")


def orphaned_formula_queries(originals: List[str],
                             edited: List[str]) -> List[Dict[str, object]]:
    """Denominator lines the copyedit made redundant but could not remove.

    On a real manuscript `Recall=TP` and the line below it, `   TP+ FN     … (3)`,
    were a fraction split across two paragraphs. The copyedit correctly rebuilt the
    whole thing onto the first line — `Recall = TP / (TP + FN) …(3)` — and left the
    second exactly where it was, so the formula now appears complete *and* is
    followed by its own orphaned denominator.

    This cannot be fixed here. The redline is built by walking the original and the
    edited paragraphs in step, so the two lists must stay the same length; deleting a
    paragraph would move every later tracked change onto the wrong text. The editor
    is told instead.
    """
    queries: List[Dict[str, object]] = []
    for i in range(len(edited) - 1):
        rebuilt, nxt_before, nxt_after = edited[i], originals[i + 1], edited[i + 1]
        if not rebuilt or not nxt_after:
            continue
        if (_REBUILT_FORMULA.search(rebuilt.strip())
                and nxt_before == nxt_after
                and _ORPHAN_DENOMINATOR.match(nxt_after)):
            queries.append({
                "index": i + 1,
                "snippet": nxt_after[:80],
                "query": ("The formula above has been rebuilt onto one line, which "
                          "leaves this denominator stranded. Delete this paragraph."),
                "suggestion": "",
            })
    return queries
