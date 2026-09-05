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
_ALGORITHM_STEP = re.compile("^\\s*((\\d{1,2})\\s*[:.])([  \t])")

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
    return not re.match(rf"^\s*{m.group(2)}\s*[:.]", after)


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
            m = _ALGORITHM_STEP.match(before)
            # The original's own separator, not a hard-coded one: these
            # listings are set with an em-space or a tab, and putting back the
            # wrong character re-lays-out the algorithm block while claiming
            # only to restore its numbering.
            restored = f"{m.group(1)}{m.group(3)}{after.lstrip()}"
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


# --- table cells: is this edit even for this cell? -----------------------------

#: How much of a cell's own wording must survive for the result to be an edit of it.
#: A copyedit rephrases; it does not replace. Below this, the text belongs elsewhere.
_MIN_CELL_OVERLAP = 0.5

_CELL_NORM = re.compile(r"[^a-z0-9]+")


def _norm_cell(text: str) -> str:
    return _CELL_NORM.sub(" ", (text or "").lower()).strip()


def _is_title_casing(before: str, after: str) -> bool:
    """Did the edit only put capitals on words that were lowercase?

    `pH` corrected from `ph` is a real fix and must pass. `Improved adaptive
    detection` -> `Improved Adaptive Detection` is a heading rule reaching text that
    is not a heading, so two or more words gaining a capital is the signature.
    """
    wb, wa = before.split(), after.split()
    if len(wb) != len(wa):
        return False
    promoted = sum(
        1 for b, a in zip(wb, wa)
        if b != a and b.lower() == a.lower() and b[:1].islower() and a[:1].isupper()
    )
    return promoted >= 2


def verify_cell_edits(
    originals: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """Accept a table cell's edit only if it is plausibly an edit *of that cell*.

    Table cells are sent to the model as a bare array and written back by position.
    That contract holds for body paragraphs, which are long and distinct. It does not
    hold for table cells: they are short, similar, and on job 46 the model returned a
    three-row table's cells **in a different order**. The five strings all came back —
    none was lost — but each landed in the wrong cell, and in the redline that reads as
    a deliberate edit rather than as corruption. A reviewer has no way to tell.

    So position is no longer trusted on its own. Three refusals, each aimed at a
    failure that was observed rather than imagined:

    * the text now sitting here is, word for word, some *other* cell's text — the
      permutation signature, and by itself enough to reject the cell;
    * too little of this cell's own wording survived. A copyedit rephrases a cell; one
      that keeps under half of its words is describing something else;
    * the only change is capital letters on two or more words — the heading rules
      reaching table body text, which was the second complaint on the same job.

    A refused cell keeps the author's text and raises a query. Silently keeping it
    would hide that the model is returning unusable output for tables, which is a
    thing the editor needs to know.
    """
    normed = [_norm_cell(o) for o in originals]
    positions: Dict[str, List[int]] = {}
    for i, n in enumerate(normed):
        positions.setdefault(n, []).append(i)

    out: List[str] = []
    queries: List[Dict[str, object]] = []

    def refuse(index: int, why: str) -> None:
        out.append(originals[index])
        queries.append({
            "index": index,
            "query": f"The copyedit for this cell was not applied: {why} The "
                     f"author's text was kept.",
            "suggestion": None,
        })

    for i, (before, after) in enumerate(zip(originals, edited)):
        if not after or after.strip() == (before or "").strip():
            out.append(before)
            continue

        n_after, n_before = _norm_cell(after), normed[i]

        # Only when it matches ANOTHER cell. Matching nothing is what a normal
        # copyedit looks like; the first version refused on that and would have
        # thrown away almost every legitimate table edit.
        if n_after != n_before and n_after in positions and i not in positions[n_after]:
            refuse(i, "it returned the contents of a different cell in the same "
                      "table, so the cells had been reordered.")
            continue

        words_before = set(n_before.split())
        kept = len(words_before & set(n_after.split()))
        if words_before and kept / len(words_before) < _MIN_CELL_OVERLAP:
            refuse(i, f"only {kept} of its {len(words_before)} words survived, which "
                      f"is a replacement rather than a copyedit.")
            continue

        if _is_title_casing(before.strip(), after.strip()):
            refuse(i, "it only added capital letters. Table body text is not a "
                      "heading and keeps the author's sentence case.")
            continue

        out.append(after)

    return out, queries


# --- abbreviations: full form once, short form after ----------------------------

#: `Expansion (ABBR)` as the author themselves wrote it. Learning the pair from the
#: author's own definition is the whole safety argument: guessing that two words
#: starting A and E mean `AE` would eventually rewrite "an experiment" as "AE".
_DEFINITION = re.compile(
    r"([A-Za-z][A-Za-z\-‐-― ]{3,70}?)\s*\(([A-Z][A-Za-z]{1,7})\)")


def _initials(phrase: str) -> str:
    return "".join(w[0] for w in re.split(r"[\s\-‐-―]+", phrase) if w)


def learn_abbreviations(paragraphs: List[str]) -> Dict[str, str]:
    """`{ABBR: expansion}` for every pair the author defined in their own text.

    The initials must actually spell the abbreviation, so `(Fig. 2)` and `(2025)`
    and an aside in brackets are all rejected. Where an author defines the same
    abbreviation twice, the first definition wins — that is the one at first use.
    """
    pairs: Dict[str, str] = {}
    for m in _DEFINITION.finditer("\n".join(p or "" for p in paragraphs)):
        phrase, abbr = m.group(1).strip(), m.group(2)
        words = re.split(r"[\s\-‐-―]+", phrase)
        # Try the shortest tail of the phrase whose initials spell the abbreviation:
        # "employing publicly available acoustic-emission (AE)" defines "AE" as
        # "acoustic-emission", not as the whole clause.
        for n in range(len(abbr), min(len(words), len(abbr) + 3) + 1):
            tail = words[-n:]
            if _initials(" ".join(tail)).upper() == abbr.upper():
                pairs.setdefault(abbr, " ".join(tail))
                break
    return pairs


def enforce_abbreviation_first_use(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """Full form with the short form in brackets once, the short form thereafter.

    The in-house rule says exactly this, and on job 46 the model broke it in both
    directions at once: it expanded `IoT` to "Internet of Things" without ever writing
    "(IoT)", and it went on spelling out "acoustic emission" sixteen times instead of
    using `AE` after the first. Across eight abbreviations the expansion appeared 34
    times and carried its abbreviation 4 times.

    A rule this mechanical should not depend on a model remembering it across 84
    separate calls, none of which can see what the others did. Only the whole document
    knows which occurrence is the first, so only a pass over the whole document can
    enforce it.

    Pairs come from `learn_abbreviations`, i.e. from the author's own definitions —
    never inferred from initials alone.
    """
    pairs = learn_abbreviations(original)
    if not pairs:
        return edited, []

    out = list(edited)
    queries: List[Dict[str, object]] = []

    for abbr, expansion in pairs.items():
        # Match the expansion however it is hyphenated or spaced, but not when it is
        # already followed by its own bracketed abbreviation.
        body = r"[\s\-‐-―]+".join(
            re.escape(w) for w in expansion.split() if w)
        rx = re.compile(rf"\b{body}\b(?!\s*\({re.escape(abbr)}\))", re.I)
        # If the author already defined it, that definition stands and no second one
        # is invented — every stray expansion simply becomes the short form. Adding
        # our own earlier definition would leave the paper defining the same term
        # twice, and would move the author's chosen first mention.
        seen_definition = bool(re.search(
            rf"\b{body}\b\s*\(\s*{re.escape(abbr)}\s*\)",
            "\n".join(p or "" for p in original), re.I))
        first_index: Optional[int] = None

        for i, para in enumerate(out):
            if not para:
                continue
            if re.search(rf"\b{body}\b\s*\(\s*{re.escape(abbr)}\s*\)", para, re.I):
                seen_definition = True                      # already defined here
                continue
            if not rx.search(para):
                continue

            def replace(m: "re.Match[str]") -> str:
                nonlocal seen_definition
                if not seen_definition:
                    seen_definition = True
                    return f"{m.group(0)} ({abbr})"
                return abbr

            new = rx.sub(replace, para)
            if new != para:
                out[i] = new
                if first_index is None:
                    first_index = i

        if first_index is not None:
            queries.append({
                "index": first_index,
                "query": (
                    f"'{expansion}' was spelled out where the author had used "
                    f"'{abbr}'. The house rule gives the full form once, with "
                    f"'({abbr})' after it, and the short form from then on — that has "
                    f"been restored across the document. Please confirm the first "
                    f"mention is where you want the definition."),
                "suggestion": None,
            })

    return out, queries
