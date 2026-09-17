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

import difflib
import re

import token_census as _token_census
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


#: A figure or table caption label, however the author punctuated it — `Table 2:`,
#: `Fig 1:`, `Figure 3.`, `Tab. 4 —`. The number is what matters: it is the anchor every
#: in-text "see Table 2" points at, and the only thing that makes a caption findable.
#: The separator between the word and the number is whatever the author typed. `Fig: 2`
#: is real — job #53 wrote its second figure that way — and a pattern that allowed only
#: `Fig.` or `Fig ` walked straight past the one caption that was actually deleted.
_CAPTION_LABEL = re.compile(
    r"(?i)\b(fig(?:ure)?|tab(?:le)?)\s*[.:\-–—]?\s*(\d+)")

#: A paragraph that *opens* with the label is a caption; one that merely contains it is
#: prose mentioning a caption. The distinction decides whether the label can be put back
#: on its own — on a caption it can, so the copyedit's corrections to the caption's
#: wording survive alongside it.
_CAPTION_OPENER = re.compile(r"(?i)^\s*(fig(?:ure)?|tab(?:le)?)\s*[.:\-–—]?\s*\d+")


def _lost_the_caption_label(before: str, after: str) -> Optional[str]:
    """The caption number that the copyedit dropped, or None.

    Job #53 lost both of its numbered elements to the heading rules, which is a house
    rule doing exactly what it says on text it should never have been given:

    * `Table 2: Comparative Summary Table` -> `Comparative Summary Table`. "Table 2:"
      reads like heading numbering, and rule 2 removes leading numbering from headings.
    * `3.2 Sensor Fusion    Fig: 2 Design of Prototype` -> `Sensor Fusion`. A heading
      and a caption had been typed into one paragraph, and only the heading survived.

    Then the manuscript's own cross-reference check reported "the text refers to Table 2,
    which has no caption" — the tool breaking something and filing a defect against the
    author for it. That is the part worth guarding: a caption label is not decoration,
    and no style rule is worth silently unnumbering a figure.

    Only the *number* is compared. A caption legitimately changes shape under the house
    rules — `Fig 1: actual model` -> `Figure 1. Actual model.` is correct and must not be
    flagged — so this asks the narrow question the author cares about: is Table 2 still
    called Table 2?
    """
    for kind, num in _CAPTION_LABEL.findall(before or ""):
        word = "fig" if kind.lower().startswith("fig") else "tab"
        if not any(k.lower().startswith(word[:3]) and n == num
                   for k, n in _CAPTION_LABEL.findall(after or "")):
            return f"{'Figure' if word == 'fig' else 'Table'} {num}"
    return None


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
                "guard": "restore_protected_text",
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
                "guard": "restore_protected_text",
                "suggestion": restored,
            })
            continue
        lost = _lost_the_caption_label(before, after)
        if lost:
            # A caption stays a caption, and its corrections stay with it.
            #
            # Reverting the whole paragraph put the label back and threw the copyedit
            # away with it — including the spelling and wording fixes inside the caption,
            # which are exactly the corrections an editor wants to see. So where the
            # paragraph is a caption and nothing but a caption, only the label is put
            # back and the edited wording is kept underneath it.
            if _CAPTION_OPENER.match(before) and not _CAPTION_OPENER.match(after):
                label = _CAPTION_OPENER.match(before).group(0).strip()
                restored = f"{label}. {after.lstrip()}" if after.strip() else before
                out.append(restored)
                queries.append({
                    "index": i,
                    "snippet": before[:80],
                    "query": (f"The copyedit removed this caption's label. Every "
                              f"'{lost}' in the text points at that number, so it has "
                              f"been put back; the rest of the copyedit is kept."),
                    "guard": "restore_protected_text",
                    "suggestion": restored,
                })
                continue
            # Otherwise the paragraph held a heading *and* a caption, and there is no
            # safe way to guess where one ends and the other begins — splitting it would
            # be this guard inventing structure while claiming to protect it.
            out.append(before)
            queries.append({
                "index": i,
                "snippet": before[:80],
                "query": (f"The copyedit removed the caption label for {lost}. A "
                          f"caption number is what every '{lost}' in the text points "
                          f"at, so the original has been restored. This paragraph holds "
                          f"both a heading and a caption — please split them into two "
                          f"paragraphs."),
                "guard": "restore_protected_text",
                "suggestion": before,
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
                "guard": "orphaned_formula_queries",
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
            "guard": "verify_cell_edits",
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
#: A comma is part of several real organisation names — "United Nations Educational,
#: Scientific and Cultural Organization" is UNESCO — and excluding it made the match
#: start after the comma, at "Scientific", which spells nothing. Letting it in is safe
#: because the initials still have to spell the abbreviation exactly.
_DEFINITION = re.compile(
    r"([A-Za-z][A-Za-z\-‐-―, ]{3,70}?)\s*\(([A-Z][A-Za-z]{1,7})\)")

#: The same thing written the way a chemist writes it: digits, primes and brackets
#: inside the name itself. `2,2′-(ethylenedioxy)bis(ethylamine) (EDBEA)` cannot match
#: the pattern above at all — and an abbreviation that is never learned is one the
#: first-use rule does nothing about, which is how job #104 came back with a *different
#: molecule* invented as EDBEA's expansion and nothing to say otherwise.
_CHEMICAL_DEFINITION = re.compile(
    r"([A-Za-z0-9][^\s][^;:]{2,80}?)\s*\(([A-Z][A-Za-z0-9]{1,8})\)")

#: What makes a phrase chemical rather than ordinary prose. Without this the
#: letters-in-order test below would learn `the results of the experiment (TRE)`: in a
#: long enough phrase, any few letters appear in order somewhere.
_CHEMICAL_SHAPE = re.compile(r"[0-9()\u2032']")


#: Words an acronym is allowed to skip. "Information and Communication Technology" is
#: ICT, not IACT, and "United Nations Educational, Scientific and Cultural
#: Organization" is UNESCO — the joining words are simply not counted.
_JOINERS = {"and", "of", "for", "the", "in", "on", "to", "with", "a", "an", "&", "at"}


def _initials(phrase: str, skip_joiners: bool = False) -> str:
    words = [w for w in re.split(r"[\s\-‐-―]+", phrase) if w]
    if skip_joiners:
        words = [w for w in words if w.lower().strip(",.") not in _JOINERS] or words
    return "".join(w[0] for w in words)


def _sub_after_first(rx: "re.Pattern[str]", replacement: str, text: str) -> str:
    """Leave the first match where it is; replace every later one."""
    first = rx.search(text)
    if first is None:
        return text
    return text[:first.end()] + rx.sub(replacement, text[first.end():])


def _contracts_to(word: str, abbr: str) -> bool:
    """True when `abbr` is `word` with letters taken out — `dicyclopentadiene` -> DCPD.

    A chemical name is one word, so the initials test can never see it: the initials of
    `dicyclopentadiene` are `d`. That rejection was silent, and it took the whole
    first-use rule with it for exactly the terms a materials paper is made of — DCPD,
    PDMS, THF, DMF. Job #103 re-expanded DCPD twice, eight paragraphs after the author
    had defined it, and nothing could tell it not to.

    Tight on purpose, and the third condition is the one that earns its place. The
    abbreviation must start on the word's own first letter, its letters must appear in
    order, it must be at least three letters, and the word must be at least three times
    its length — a contraction that throws away two thirds of a long technical term.

    Without that ratio, `control (CTRL)` is learned, and then every later "control" in
    the manuscript is replaced by `CTRL`: an ordinary English word, rewritten
    throughout the paper. A chemical name is nothing like that — `dicyclopentadiene`
    is 17 letters for 4, `polydimethylsiloxane` 20 for 4 — and the gap between the two
    is wide enough to stand on. `core (DCPD)` fails earlier still, on the first letter,
    which is the commonest case: the word beside the bracket is very often not the term.
    """
    word, abbr = word.lower(), abbr.lower()
    if len(abbr) < 3 or len(word) < 3 * len(abbr) or not word[:1] == abbr[:1]:
        return False
    it = iter(word)
    return all(letter in it for letter in abbr)


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
        # The window has to allow for the joining words the acronym skips: ICT is three
        # letters over four words, UNESCO six over seven. Without the wider window and
        # the joiner-skipping spelling, neither term was ever learned — so the whole
        # first-use rule was silently doing nothing for exactly the abbreviations job
        # #60 came back with expanded seven and eight times.
        for n in range(len(abbr), min(len(words), len(abbr) * 2 + 2) + 1):
            tail = " ".join(words[-n:])
            if abbr.upper() in (_initials(tail).upper(),
                                _initials(tail, skip_joiners=True).upper()):
                pairs.setdefault(abbr, tail)
                break
        else:
            # One word, contracted rather than initialled: the chemical names.
            last = words[-1] if words else ""
            if _contracts_to(last, abbr):
                pairs.setdefault(abbr, last)

    # A chemist's name for the same thing: `2,2′-(ethylenedioxy)bis(ethylamine)` is
    # EDBEA — ethylene, dioxy, bis, ethyl, amine — with the letters taken in order
    # straight through the punctuation.
    for m in _CHEMICAL_DEFINITION.finditer("\n".join(p or "" for p in paragraphs)):
        phrase, abbr = m.group(1).strip(), m.group(2)
        if abbr in pairs:
            continue
        # Shortest tail first, as with the initials: the name is what sits against the
        # bracket, not the clause that introduces it. `provided by 2,2′-(…)` defines
        # EDBEA as the molecule, and "provided by" is not part of its name.
        tokens = phrase.split()
        for n in range(1, min(len(tokens), 4) + 1):
            tail = " ".join(tokens[-n:])
            if not _CHEMICAL_SHAPE.search(tail):
                continue
            if _contracts_to(re.sub(r"[^A-Za-z]", "", tail), abbr):
                pairs[abbr] = tail
                break
    return pairs


#: The keywords line, which closes the front matter. After it the article proper starts.
_KEYWORDS_LINE = re.compile(r"(?i)^\s*key\s*words?\s*[:.\-–—]")
_ABSTRACT_HEADING = re.compile(r"(?i)^\s*abstract\s*[:.\-–—]?\s*$")


def _body_start(paragraphs: List[str]) -> int:
    """Where the article's body begins — after the abstract and its keywords.

    The abstract is a separate scope from the body, and the journal's own rule says so:
    the abstract carries no abbreviations at all, and the body still spells a term out
    in full at *its* first use, because the two are read apart. An abstract is
    reproduced on its own in indexes and databases, where the body is not there to
    define anything.

    Job #61 shows what happens when the two are treated as one document. The abstract's
    `Information and Communication Technology (ICT)` was counted as the definition, so
    the body's first mention was shortened rather than defined — and the abstract itself
    was reduced to a bare `ICT`. The term ended up spelled out nowhere in the paper.
    """
    for i, p in enumerate(paragraphs):
        if _KEYWORDS_LINE.match((p or "").strip()):
            return i + 1
    for i, p in enumerate(paragraphs):
        if _ABSTRACT_HEADING.match((p or "").strip()):
            # No keywords line: skip the abstract's own paragraphs, which run until the
            # next short heading-like line.
            for j in range(i + 1, min(i + 8, len(paragraphs))):
                t = (paragraphs[j] or "").strip()
                if t and len(t) < 60 and not t.endswith("."):
                    return j
            return min(i + 4, len(paragraphs))
    return 0


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
    pairs = learn_abbreviations(original[:_references_start(original)
                                         if _references_start(original) is not None
                                         else len(original)])
    if not pairs:
        return edited, []

    # The bibliography is out of bounds, in both directions.
    #
    # A reference's title is the identity of somebody else's work, quoted. Job #61 came
    # back with `Recommendation on open educational resources (OER)` shortened to
    # `Recommendation on OER`, and `Are open educational resources (OER) and practices
    # (OEP) effective…` to `Are OER and practices (OEP) effective…` — titles that no
    # longer match the papers they name, so a reader searching for them finds nothing.
    # House style governs how *this* manuscript writes; it does not get to rewrite what
    # another author called their work.
    #
    # It is also excluded as a source: an abbreviation defined only inside a reference
    # title was never this manuscript introducing a term.
    refs_at = _references_start(original)
    body_end = refs_at if refs_at is not None else len(original)
    body_from = _body_start(original)

    out = list(edited)
    queries: List[Dict[str, object]] = []

    for abbr, expansion in pairs.items():
        # Match the expansion however it is hyphenated or spaced, but not when it is
        # already followed by its own bracketed abbreviation.
        body = r"[\s\-‐-―]+".join(
            re.escape(w) for w in expansion.split() if w)
        # The bracket may hold the plural. Job #60 carried "Open Educational Resources
        # (OERs)"; the lookahead only excused "(OER)", so the guard treated the phrase
        # as a stray expansion and replaced it — leaving **"OER (OERs)"**, an acronym
        # followed by its own plural. Anything that reads as this abbreviation in
        # brackets counts as already defined.
        # Square brackets are the same statement. Job #59 ¶96 came back as
        # **`OER [OER]`**: the author had written `Open Educational Resources [OER]`,
        # the lookahead only excused round brackets, so the guard read a defined term
        # as a stray expansion and shortened it in front of its own bracket. The
        # brackets have to match each other — `Resources (OER]` defines nothing.
        _a = rf"{re.escape(abbr)}(?:['’]?s)?"
        defined = rf"(?:\(\s*{_a}\s*\)|\[\s*{_a}\s*\])"
        rx = re.compile(rf"\b{body}\b(?!\s*{defined})", re.I)
        def_rx = re.compile(rf"\b{body}\b\s*{defined}", re.I)
        # An author may define a term the other way round, short form first, and job
        # #68 ¶370 did: `MAPE (mean absolute percentage error)`. Only the expansion
        # was looked for, so the guard read the author's own gloss as a stray
        # expansion and shortened it inside its own brackets — **`MAPE (MAPE)`**,
        # which took the definition out of the paper entirely. This is a definition
        # and it is the author's; it is never rewritten, and it counts as the term
        # having been defined.
        rev_rx = re.compile(
            rf"\b{re.escape(abbr)}(?:['’]?s)?\s*(?:\(\s*{body}\s*\)|\[\s*{body}\s*\])",
            re.I)
        # If the author already defined it, that definition stands and no second one
        # is invented — every stray expansion simply becomes the short form. Adding
        # our own earlier definition would leave the paper defining the same term
        # twice, and would move the author's chosen first mention.
        # The house rule, in Amit's words on 16 Sep 2026: "FIRST-USE EXPANSION: spell out
        # an abbreviation in full at its FIRST occurrence in the body text with the
        # abbreviation in parentheses, then use the abbreviation throughout the rest of
        # the text."
        #
        # So the definition belongs at the first occurrence — wherever the author happened
        # to put theirs. Job #72's introduction said "urea-formaldehyde and
        # melamine-formaldehyde" and the author's own "urea-formaldehyde (UF)" came later,
        # in the methods; the rule wants "(UF)" in the introduction and a bare "UF" in the
        # methods. This used to start from "a definition exists somewhere in the body",
        # which produced the opposite: the introduction was shortened to an abbreviation
        # nothing had defined yet.
        #
        # False, then, and set the moment a definition is passed: what matters is whether
        # one has been seen *so far*, not whether one exists.
        seen_definition = False
        first_index: Optional[int] = None
        already_defined_here = False
        redefined: List[int] = []

        for i in range(body_from, body_end):
            para = out[i]
            if not para:
                continue
            if def_rx.search(para):
                if not already_defined_here and not seen_definition:
                    already_defined_here = True             # the definition we keep
                    seen_definition = True
                    # A paragraph can define the same term twice on its own, and the
                    # branch below only ever looked at *later* paragraphs — so a repeat
                    # sitting beside the definition we keep was a repeat to nobody.
                    # Job #66 opened with two `Information and Communication Technology
                    # (ICT)` in one paragraph and both survived, with the rule reporting
                    # itself as applied. The author's first mention stands; everything
                    # after it in the paragraph is governed like the rest of the paper.
                    kept = _sub_after_first(def_rx, abbr, para)
                else:
                    # A second, third, seventh definition of the same term. Job #60
                    # expanded ICT at seven paragraphs and OER at eight, because this
                    # branch marked the term "seen" and moved on without touching the
                    # repeat — so every redundant definition after the first survived
                    # every pass. The rule is full form once, short form thereafter; the
                    # later ones become the short form, and the author's first mention is
                    # left exactly where it was.
                    kept = def_rx.sub(abbr, para)
                if kept != para:
                    out[i] = kept
                    redefined.append(i)
                    para = kept
                # No `continue`: a bare expansion further down the same paragraph is a
                # stray expansion like any other, and was being skipped for the whole
                # paragraph merely because the paragraph also held the definition. The
                # definition we kept carries its brackets, so `rx`'s lookahead passes
                # over it.
            if not rx.search(para):
                continue

            # The expansion inside the author's own `MAPE (mean absolute percentage
            # error)` is not loose text to be shortened; it is the definition.
            protected = [m.span() for m in rev_rx.finditer(para)]

            def replace(m: "re.Match[str]") -> str:
                nonlocal seen_definition
                if any(a <= m.start() and m.end() <= b for a, b in protected):
                    seen_definition = True
                    return m.group(0)
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
                "guard": "enforce_abbreviation_first_use",
                "suggestion": None,
            })
        if redefined:
            where = ", ".join(str(i + 1) for i in redefined[:6])
            queries.append({
                "index": redefined[0],
                "query": (
                    f"'{expansion}' was spelled out again after it had already been "
                    f"defined (paragraph{'s' if len(redefined) > 1 else ''} {where}). "
                    f"The house rule gives the full form once and '{abbr}' from then "
                    f"on, so the repeats now read '{abbr}'."),
                "guard": "enforce_abbreviation_first_use",
                "suggestion": None,
            })

    return out, queries


# --- front matter and the bibliography's own numbering --------------------------

#: `[1]`, `1.` or `1)` at the head of a bibliography entry — the entry's number, which
#: the in-text `[1]` points at. Not a heading number, though it looks like one.
#:
#: The bracketed form was missing until job #104, where 12 of 21 entries came back
#: unnumbered and this guard said nothing: the house reference style is Vancouver, the
#: manuscript numbers its bibliography `[1]`, `[2]`, and the pattern only knew `1.` and
#: `1)`. A guard that cannot see the thing it guards reports itself as applied.
_ENTRY_NUMBER = re.compile(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})\s*[.)])\s*")


def _entry_number_of(text: str) -> Optional[Tuple[str, str]]:
    """`(number, marker)` for a bibliography entry, in the author's own punctuation.

    The marker matters: putting `3.` on a list the author numbered `[3]` would make
    this guard the second thing in the file changing their reference style.
    """
    m = _ENTRY_NUMBER.match(text or "")
    if not m:
        return None
    if m.group(1) is not None:
        return m.group(1), f"[{m.group(1)}] "
    return m.group(2), f"{m.group(2)}. "

#: How much of an entry's own wording must survive for it to still be that entry.
#: Below this the bibliography has been re-ordered and its numbers are not ours to
#: restore.
_REF_SAME_ENTRY = 0.4

#: A byline: two or more names each carrying its affiliation digit, as in
#: `Adaikkalam Kumar1*, Ashok kumar Aachimuthu2`. Requiring the digit is what keeps
#: this away from the title and the journal line, where an ordinary copyedit — and a
#: spelling fix like `Compatative` -> `Comparative` — must go through untouched.
_BYLINE_NAME = re.compile(r"[A-Za-z]{2,}\s*\d\s*\*?")

#: An affiliation line whose corresponding-author asterisk comes before its number.
_AFFIL_STAR = re.compile(r"^\s*\*\s*\d")

_ABSTRACT_HEAD = re.compile(r"(?i)^\s*(abstract|summary)\b")


def _front_matter_end(paragraphs: List[str]) -> int:
    for i, p in enumerate(paragraphs):
        if _ABSTRACT_HEAD.match(p or ""):
            return i
    return min(len(paragraphs), 15)


def _words(text: str) -> set:
    return set(re.findall(r"[A-Za-z]{2,}", (text or "").lower()))


def restore_front_matter_names(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """Keep the authors' names as the authors wrote them.

    On job 51 the byline `Adaikkalam Kumar1*, Ashok kumar Aachimuthu2` came back as
    `Kumar A1*, Aachimuthu A2` — surname-first with the given name reduced to an
    initial, which is a *reference* style applied to a byline. The same manuscript on
    the previous model returned `Adaikkalam Kumar¹*, Ashok Kumar Aachimuthu²`, correct.

    The house rule invites this: it says "initial(s) + full surname" and then gives
    "Saniya Jose, Susan Kumar" as its example. Those are different instructions, and a
    prompt cannot be relied on to resolve its own contradiction — so the byline is
    protected here instead.

    Two protections, both narrow:

    * a byline may be recapitalised (`Ashok kumar` -> `Ashok Kumar`) but may not LOSE a
      name. Comparison is on lowercased words, so case fixes pass and a dropped given
      name does not;
    * the corresponding-author asterisk is put back if it went. It marks who a reader
      writes to, and both models dropped it — this one is not a regression, it has been
      wrong all along.

    Deliberately scoped to lines carrying an affiliation digit. The title sits in the
    same front matter, and `Compatative` -> `Comparative` there is exactly the kind of
    correct edit this must never undo.
    """
    out = list(edited)
    queries: List[Dict[str, object]] = []
    end = _front_matter_end(original)

    for i in range(min(end, len(out))):
        before, after = original[i] or "", out[i] or ""
        if not before.strip() or before == after:
            continue

        is_byline = len(_BYLINE_NAME.findall(before)) >= 2
        if is_byline and (_words(before) - _words(after)):
            missing = sorted(_words(before) - _words(after))
            out[i] = before
            queries.append({
                "index": i, "snippet": before[:120],
                "query": (
                    f"The author line lost {', '.join(missing[:4])}. Author names are "
                    f"kept as submitted — only their capitalisation is corrected — so "
                    f"the original line has been restored."),
                "guard": "restore_front_matter_names",
                "suggestion": before,
            })
            continue

        if _AFFIL_STAR.match(before) and not after.lstrip().startswith("*"):
            out[i] = "*" + after.lstrip()
            queries.append({
                "index": i, "snippet": before[:120],
                "query": ("The asterisk marking the corresponding author was removed "
                          "from this affiliation line and has been put back."),
                "guard": "restore_front_matter_names",
                "suggestion": out[i],
            })

    return out, queries


#: The bibliography's heading, however the author punctuated or titled it. The pattern
#: used to be an exact `references?` and job #60 writes `References:` — with the colon,
#: which meant the reference guards found no bibliography at all and silently did
#: nothing on that manuscript, and on every other one whose heading carries a colon.
_REFERENCES_HEAD = re.compile(
    r"(?i)^\s*(?:\d+\.?\s*)?(?:list of\s+)?references?\s*[:.\-–—]?\s*$")


def _references_start(paragraphs: List[str]) -> Optional[int]:
    """Index of the References heading, or None."""
    for i, p in enumerate(paragraphs):
        if _REFERENCES_HEAD.match((p or "").strip()):
            return i
    return None


def restore_reference_numbering(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """Put back the number at the head of each bibliography entry.

    On job 51 every entry lost it: `1. Ruiz.T.P, ... (1995), Talanta, 42, 391.` came
    back as `Ruiz TP, ... Talanta. 1995; 42: 391p.` — the Vancouver reformatting is
    right and the entry number is gone, so the in-text `[1]` now points at nothing. The
    previous model kept the numbers on the same manuscript.

    The cause is a house rule doing its job in the wrong place: headings carry no
    leading number, and a bibliography entry opens with something that looks exactly
    like one. It is not one. It is the target of every citation in the paper.

    Only paragraphs after a `References` heading are considered, so the heading rule
    keeps working everywhere else. The original's own number is restored — never a
    renumbering, because a bibliography's order is the author's and re-sorting it is a
    separate decision the pipeline makes explicitly elsewhere.
    """
    start = _references_start(original)
    if start is None:
        return edited, []

    out = list(edited)
    restored: List[str] = []
    moved = 0
    for i in range(start + 1, min(len(original), len(out))):
        m = _entry_number_of(original[i] or "")
        after = out[i] or ""
        if not m or not after.strip() or _ENTRY_NUMBER.match(after):
            continue

        # Is this still the same entry? `align_global_citations` runs earlier and may
        # re-sort the bibliography, after which paragraph i holds a DIFFERENT work.
        # Stamping the original positional number onto it would be worse than the bug
        # this guard exists to fix: the entry would carry another reference's number
        # and disagree with the in-text citations that were just renumbered to match.
        # Reference entries are full of distinctive surnames and journal names, so a
        # word overlap separates "reformatted in place" from "something else is here".
        words = _words(original[i]) - {"and", "the", "of", "in"}
        if words and len(words & _words(after)) / len(words) < _REF_SAME_ENTRY:
            moved += 1
            continue

        out[i] = f"{m[1]}{after.lstrip()}"
        restored.append(m[0])

    if moved:
        return out, [{
            "index": start + 1,
            "snippet": (out[start + 1] or "")[:120],
            "query": (
                f"{moved} bibliography entries came back unnumbered AND no longer "
                f"match the entry that was in their place, so the list appears to have "
                f"been re-ordered. Numbers were NOT restored for those — putting the "
                f"old number on a different work would be worse. Please check the "
                f"bibliography numbering against the in-text citations by hand."),
            "guard": "restore_reference_numbering",
            "suggestion": None,
        }]

    if not restored:
        return out, []
    return out, [{
        "index": start + 1,
        "snippet": (out[start + 1] or "")[:120],
        "query": (
            f"{len(restored)} bibliography entries came back without their numbers "
            f"({', '.join(restored[:5])}{'…' if len(restored) > 5 else ''}). The "
            f"numbers are what the in-text citations point at, so they have been "
            f"restored from the original."),
        "guard": "restore_reference_numbering",
        "suggestion": None,
    }]


# --- the author's own hyphenation ------------------------------------------------

#: Prefixes that attach to a following word, where both the hyphenated and the closed
#: form are defensible English and the choice is the author's. Measured across four
#: real jobs: 41 such compounds kept their hyphen and 11 lost it — in the same
#: documents, so the manuscript ends up spelling the same construction two ways.
_PREFIXES = (
    "non", "pre", "post", "multi", "sub", "semi", "anti", "inter", "intra",
    "over", "under", "micro", "macro", "nano", "co", "self", "cross", "re",
)

_HYPHENATED = re.compile(
    r"\b(" + "|".join(_PREFIXES) + r")-([A-Za-z]{3,})\b", re.I)


def preserve_author_hyphenation(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """Leave `non-stationary` as `non-stationary` if that is how it was written.

    Job 54: six `non-` compounds, three closed up and three left hyphenated — one
    document, two conventions. The same run also closed `multi-task`,
    `pre-determined` and `pre-processing` while leaving fourteen others alone. There
    is no rule for this anywhere in the pipeline, so the model decides afresh in every
    chunk and cannot be consistent by construction.

    Chicago would close most of these, and `nonstationary` is defensible. But the
    editorial team's position is the right one: hyphenation here is not an error, it
    is a house-or-author choice, and a tool should be silent about things that are not
    wrong. Changing it buys nothing and costs a reviewer's question.

    Applied per paragraph and only to the exact compounds the author used there, so
    it can never invent a hyphen the manuscript never had. Case is taken from the
    edited text, so a compound that legitimately became sentence-initial stays
    capitalised.
    """
    out = list(edited)
    changed: List[str] = []

    for i in range(min(len(original), len(out))):
        before, after = original[i] or "", out[i] or ""
        if not before or not after or before == after:
            continue
        forms = {m.group(0).lower().replace("-", ""): m.group(0)
                 for m in _HYPHENATED.finditer(before)}
        if not forms:
            continue

        def restore(m: "re.Match[str]") -> str:
            author = forms.get(m.group(0).lower())
            if not author:
                return m.group(0)
            # Keep the edited text's capitalisation, not the original's.
            if m.group(0)[:1].isupper():
                author = author[:1].upper() + author[1:]
            changed.append(author)
            return author

        new = re.sub(r"\b(" + "|".join(_PREFIXES) + r")([A-Za-z]{3,})\b",
                     restore, after, flags=re.I)
        if new != after:
            out[i] = new

    if not changed:
        return out, []
    unique = sorted(set(c.lower() for c in changed))
    return out, [{
        "index": 0,
        "snippet": "",
        "query": (
            f"The copyedit closed up {len(unique)} hyphenated compound(s) the author "
            f"had hyphenated ({', '.join(unique[:5])}"
            f"{'…' if len(unique) > 5 else ''}). Hyphenation of these prefixes is a "
            f"style choice rather than an error, so the author's form was kept."),
        "guard": "preserve_author_hyphenation",
        "suggestion": None,
    }]


#: What identifies a bibliography entry across a reformat. The Vancouver conversion
#: rewrites almost everything about an entry — author lists become "et al.", journal
#: titles are abbreviated, dates lose their month — but the first author's surname and
#: the year survive all of it, and together they are specific enough to tell sixteen
#: references apart.
_REF_IDENTITY = re.compile(r"^\s*(?:\[?\d{1,3}[\].)]{0,2}\s*)?([A-Za-zÀ-ÿ'\-]{3,})")


#: Given-name initials at the head of an entry — `H. `, `A. B. `, `K.K. `.
#:
#: An IEEE-style list writes `H. Jamil, M. Faizan, …`, initials first. The identity
#: above starts at the first run of three or more letters and does not scan forward, so
#: every entry in such a list came back with no identity at all — and an identity of
#: None is an entry the census cannot see. On jobs #45 and #68 that was the *whole*
#: bibliography: `verify_reference_block` found nothing to compare and returned
#: silently, the same shape of failure as the `References:` heading job #60 arrived
#: with. A guard that cannot read the list is not a guard that passed it.
#:
#: Vancouver moves the initials behind the surname, so `H. Jamil` and `Jamil H` have to
#: fingerprint alike — which they do once the initials are stepped over. Only a single
#: capital followed by a full stop counts, so `UNESCO I.` and `SRIKANTH, H.` keep their
#: own first word.
_LEADING_INITIALS = re.compile(r"^\s*(?:[A-ZÀ-Þ]\.\s*){1,4}")

_ENTRY_NUMBER_HEAD = re.compile(r"^\s*\[?\d{1,3}[\].)]{0,2}\s*")


def _reference_identity(entry: str) -> Optional[Tuple[str, str]]:
    text = _LEADING_INITIALS.sub("", _ENTRY_NUMBER_HEAD.sub("", entry or ""))
    # Two letters, not three. `Q. Li`, `J. Du` and `X. Xu` are ordinary names in this
    # literature and every one of them was unreadable, which on job #45 left seven
    # entries outside the census — the guard reads the list it is given, not the
    # convenient part of it.
    surname = re.match(r"\s*([A-Za-zÀ-ÿ'\-]{2,})", text)
    year = re.search(r"\b(?:19|20)\d{2}\b", entry or "")
    if not surname or not year:
        return None
    return surname.group(1).lower(), year.group(0)


def verify_reference_block(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """Every work the author listed must still be listed, exactly once.

    Job #60 returned sixteen references for sixteen — and three of the author's were
    gone, replaced by second copies of three others. UNESCO's OER Recommendation, its
    2026 restatement and **Vygotsky & Cole (1978)** left the bibliography; Tlili, Seale
    and Hamilton each appeared twice. Vygotsky is argued from by name in the body, so
    the paper now cited a source it did not list.

    Nothing could see it. The count was unchanged, every individual entry was
    well-formed, and each was correctly converted to Vancouver — the defect existed only
    in the relationship between the list and itself, which no per-entry check can reach.
    The cause is the entries being rewritten in place while the model reorders them:
    where it drops or merges one, a neighbour's content lands in two paragraphs.

    On a mismatch the author's whole reference list is restored. That throws away a
    correct reformat, and it is still the right trade: a beautifully formatted
    bibliography citing the wrong papers is worse than a plain one citing the right
    ones, and this fires only when works have actually gone missing.
    """
    start = _references_start(original)
    if start is None or start + 1 >= min(len(original), len(edited)):
        return edited, []

    def census(paras: List[str]) -> Dict[Tuple[str, str], int]:
        counts: Dict[Tuple[str, str], int] = {}
        for p in paras:
            # Twenty characters, not forty. The length test is only here to keep the
            # heading and stray blank lines out; an identity already needs a surname
            # and a year, which no heading has. At forty it did something else as
            # well: job #91 ¶211 came back as `Unesco.org. 2026. Available from: `
            # — thirty-four characters — and the entry fell out of the *edited*
            # census while staying in the original's, so a work that was still on the
            # page was reported as having gone missing. A guard that loses sight of
            # an entry because the copyedit shortened it is measuring length.
            if len((p or "").strip()) <= 20:
                continue
            ident = _reference_identity(p)
            if ident:
                counts[ident] = counts.get(ident, 0) + 1
        return counts

    # The whole of each list, not a window cut to the shorter one. The cap was there
    # when this compared paragraph against paragraph; with entries matched as a set it
    # only hides things — and it would have hidden this guard's own work: the restored
    # entries are appended past the original's length, so on the second pass they fell
    # outside the window, looked missing again, and would have been appended twice.
    before = census(original[start + 1:])
    after = census(edited[start + 1:])
    if not before:
        return edited, []

    lost, surplus = _references_lost(original[start + 1:], edited[start + 1:])
    if not lost:
        return edited, []

    # Only what is actually missing goes back, and it goes back *as the author wrote
    # it*, at the end of the list. Restoring the whole block was the old behaviour and
    # it was costing far more than it saved: measured across 91 redlines it threw away
    # the reformatting of 24 bibliographies, and in every case examined the "lost"
    # reference was present under a different leading author. The quality team saw the
    # result on job #107 as the references not being touched at all.
    out = list(edited)
    out.extend(lost)

    named = "; ".join(_first_words(text) for text in lost[:5])
    extra = "; ".join(_first_words(text) for text in surplus[:5])
    return out, [{
        "index": start + 1,
        "snippet": lost[0][:200],
        "query": (
            f"{len(lost)} reference(s) the author listed went missing while the "
            f"bibliography was being reformatted — {named}. The entry count was "
            f"unchanged, so a count would not have caught it."
            + (f" In their place the list carries {extra}, which the author did not "
               f"list there — usually a neighbouring entry written twice; please "
               f"delete the surplus copy." if surplus else "")
            + " The missing entries have been put back at the end of the list, exactly "
              "as the author wrote them, and the rest of the reformatting has been "
              "kept. Please place them in order and check the numbering."),
        "guard": "verify_reference_block",
        "suggestion": None,
    }]


#: A link, in the two shapes a bibliography writes one.
_REF_URL = re.compile(r"https?://\S+|\bwww\.\S+", re.I)


def restore_reference_urls(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """A reference that arrived with a link must still have it.

    In-House Reference Rule 3 formats a web source as `Available at URL [Accessed on
    Month Year]`, so the link is a required field — and nothing was checking that it
    survived. Job #61 returned `Unesco.org. 2026. Available from:` with the address
    gone: an entry that still reads like a complete reference, still says where to look,
    and no longer tells anyone where.

    Only the link is restored, not the entry, so the Vancouver reformatting around it
    stands. Restoring the whole entry would throw away correct work to recover one
    field.
    """
    start = _references_start(original)
    if start is None:
        return edited, []

    out = list(edited)
    queries: List[Dict[str, object]] = []
    for i in range(start + 1, min(len(original), len(edited))):
        had = _REF_URL.findall(original[i] or "")
        if not had or _REF_URL.search(out[i] or ""):
            continue
        restored = (out[i] or "").rstrip()
        # Put it back where the entry already points at it, or at the end.
        if re.search(r"(?i)(available\s+(?:from|at|online)\s*:?)\s*$", restored):
            restored = f"{restored} {had[0]}"
        else:
            restored = f"{restored} {had[0]}".strip()
        out[i] = restored
        queries.append({
            "index": i,
            "snippet": (original[i] or "")[:200],
            "query": ("The copyedit dropped this reference's link, which the house "
                      "format for a web source requires. It has been put back — please "
                      "check it sits where the entry wants it."),
            "guard": "restore_reference_urls",
            "suggestion": None,
        })
    return out, queries


#: Characters that are the same character twice over: one glyph, one meaning, two code
#: points. Job #100 came back with `μm` deleted and `µm` inserted — a tracked change
#: the copy editor cannot see, cannot judge, and has to accept or reject anyway. The
#: model does this on its own; nothing in the house rules asks for it.
#:
#: Only signs that are visually identical in a normal manuscript font belong here.
#: Deliberately absent:
#:   * `∆` -> `Δ` (U+2206 -> U+0394), which `enforce_science_symbols` performs on
#:     purpose — folding it back would leave two passes fighting each other;
#:   * lookalikes that are NOT identical (`º` for `°`, `'` for `’`, a hyphen for a
#:     minus sign), because correcting those is real work that must stay visible;
#:   * the space characters, because the spacing passes insert a non-breaking space
#:     deliberately.
INVISIBLE_TWINS: Tuple[Tuple[str, str], ...] = (
    ("µ", "μ"),   # MICRO SIGN / GREEK SMALL LETTER MU
    ("Ω", "Ω"),   # OHM SIGN / GREEK CAPITAL OMEGA
    ("Å", "Å"),   # ANGSTROM SIGN / LATIN CAPITAL A WITH RING ABOVE
    ("K", "K"),   # KELVIN SIGN / LATIN CAPITAL K
)


_ANY_TWIN = re.compile("[" + "".join(a + b for a, b in INVISIBLE_TWINS) + "]")


def _fold_twins(text: str) -> str:
    """The text with each twin written one agreed way. For comparison only — this
    spelling is never what gets written out."""
    for a, b in INVISIBLE_TWINS:
        text = text.replace(a, b)
    return text


def _follow_at_each_occurrence(before: str, after: str) -> Tuple[str, int]:
    """The author's own character back at every site where the copyedit swapped one
    twin for the other and changed nothing else.

    Needed because a manuscript is allowed to be inconsistent — job #93 used the micro
    sign four times and the Greek mu once. There is no document-wide answer there, but
    there is an answer at each occurrence: whichever one the author typed.
    """
    if before == after:
        return after, 0
    out: List[str] = []
    swapped = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, before, after, autojunk=False).get_opcodes():
        if tag == "delete":
            continue
        piece = after[j1:j2]
        if (tag == "replace" and (i2 - i1) == (j2 - j1)
                and _fold_twins(before[i1:i2]) == _fold_twins(piece)):
            out.append(before[i1:i2])
            swapped += sum(1 for x, y in zip(before[i1:i2], piece) if x != y)
        else:
            out.append(piece)
    return "".join(out), swapped


def follow_the_author_on_invisible_twins(
    original: List[str], edited: List[str],
) -> Tuple[List[str], int]:
    """Spell each of the twins above the way the author spelled it.

    Two passes, because there are two different questions. Where the author used one
    form and never the other, that is a decision for the whole document and it is
    applied everywhere — including to text the copyedit added, so a newly written
    `5 µm` is set like the author's own. Where the author used both, there is no
    document-wide answer, so each occurrence is matched against the author's character
    at that same place and put back only if nothing else about it changed.

    A twin the author never used at all is left alone in both passes: `um` -> `µm` is
    the copyedit's own work, it is visible on the page, and it must stay a tracked
    change like any other correction.

    Returns the text and the number of characters put back, which is reported nowhere
    on purpose — a change no reader can see is not worth a query on a copy editor's
    screen.
    """
    joined = "\n".join(p or "" for p in original)
    swaps: Dict[str, str] = {}
    for a, b in INVISIBLE_TWINS:
        used_a, used_b = a in joined, b in joined
        if used_a and not used_b:
            swaps[b] = a
        elif used_b and not used_a:
            swaps[a] = b

    if not swaps and not _ANY_TWIN.search(joined):
        return edited, 0

    out: List[str] = []
    changed = 0
    for i, para in enumerate(edited):
        if not para:
            out.append(para)
            continue
        fixed = para
        for wrong, right in swaps.items():
            if wrong in fixed:
                changed += fixed.count(wrong)
                fixed = fixed.replace(wrong, right)
        # The per-occurrence pass, for the forms the document-wide rule had no answer
        # for. Skipped unless this paragraph and the author's own both carry a twin,
        # so the character diff runs on a handful of paragraphs, not the manuscript.
        was = original[i] if i < len(original) else ""
        if _ANY_TWIN.search(fixed) and _ANY_TWIN.search(was or ""):
            fixed, n = _follow_at_each_occurrence(was, fixed)
            changed += n
        out.append(fixed)
    return out, changed


#: The subscript digits. The house convention sets a chemical subscript with these —
#: `H₂O`, `CO₂` — and that works because a single digit has a subscript form.
_SUBSCRIPT_DIGITS = "₀₁₂₃₄₅₆₇₈₉"
_TO_PLAIN = str.maketrans(_SUBSCRIPT_DIGITS, "0123456789")

#: A subscript that could not be finished. Unicode has subscript digits and no
#: subscript full stop, so a decimal number set this way comes out half-sized:
#: job #73 turned the author's `log|Z|0.01Hz` into `log|Z|₀.₀₁Hz` — the digits shrank,
#: the point and the `Hz` did not. It reads as a typo and it breaks search for the
#: value. Requiring the separator keeps `H₂O` and `CO₂`, which are correct, well clear.
_BROKEN_SUBSCRIPT = re.compile(f"[{_SUBSCRIPT_DIGITS}]+\\s*[.,]\\s*[{_SUBSCRIPT_DIGITS}]+")


def undo_broken_subscripts(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """Plain digits back wherever a subscript was set in characters that do not exist.

    Restores the digits and asks for the real thing: a subscript spanning a decimal
    point has to be Word's own subscript formatting, which this pipeline works in plain
    text and cannot apply. Leaving the half-sized version in would ship a value that
    looks mistyped; taking it out silently would lose the author's notation, so it
    comes back as a query against the paragraph it is in.
    """
    out = list(edited)
    queries: List[Dict[str, object]] = []
    for i, para in enumerate(out):
        if not para or not _BROKEN_SUBSCRIPT.search(para):
            continue
        fixed = _BROKEN_SUBSCRIPT.sub(lambda m: m.group(0).translate(_TO_PLAIN), para)
        if fixed == para:
            continue
        out[i] = fixed
        was = original[i] if i < len(original) else ""
        queries.append({
            "index": i,
            "snippet": fixed[:200],
            "query": ("A subscript here was set with subscript digits, which cannot "
                      "carry the decimal point — it came out half-sized. The plain "
                      "digits have been restored; please apply Word's subscript "
                      "formatting to the value if the notation needs it."),
            "guard": "undo_broken_subscripts",
            "suggestion": None,
        })
        if was and was == fixed:
            queries[-1]["query"] += " (This is the author's own text, put back.)"
    return out, queries


#: The stand-in for an equation or embedded object — U+FFFC, kept in step with
#: `editor.OBJECT_PLACEHOLDER`. Defined here as well rather than imported, because
#: `editor` imports `docx` and these guards are meant to run without it.
OBJECT_PLACEHOLDER = "￼"


def keep_every_equation(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """Every equation the author wrote is still in the paragraph it was written in.

    The placeholder is a character like any other by the time the copyedit sees it, so
    a model is free to drop it, double it, or replace it with its own idea of what the
    equation said. Job #100 is what that costs: `K_IC ≈ 0.7 MPa·m^1/2` and `a = 50 nm`
    became `K_Ic` and `a`, and neither value appears anywhere in the returned file.

    Where the count no longer matches, the author's paragraph is restored whole. A
    partial repair would need to know where the missing equation belonged, and a
    sentence built around an equation is not a sentence that survives a guess.

    The count is compared in **both** directions, which job #106 is the reason for.
    The placeholder is a character the model can see, and having seen it standing for
    equations elsewhere in that manuscript it wrote one of its own: the author's
    `KCrd = 36.768x - 0.0006`, an equation typed as ordinary text, came back as a bare
    `￼`. Nothing stood for it, so nothing could put anything back, and the character
    itself was delivered in the file. A placeholder the author did not have is as
    wrong as one they had and lost.
    """
    out = list(edited)
    queries: List[Dict[str, object]] = []
    for i in range(min(len(original), len(edited))):
        was, now = original[i] or "", out[i] or ""
        expected, got = was.count(OBJECT_PLACEHOLDER), now.count(OBJECT_PLACEHOLDER)
        if expected == got:
            continue
        out[i] = was
        queries.append({
            "index": i,
            "snippet": was.replace(OBJECT_PLACEHOLDER, "[equation]")[:200],
            "query": (("This paragraph contains an equation, and the copyedit did not "
                       "return it intact. ") if expected else
                      ("The copyedit replaced this paragraph with a placeholder for an "
                       "equation that is not in the author's file. ")) +
                     "The author's paragraph has been kept as it was — please edit it "
                     "by hand around the equation.",
            "guard": "keep_every_equation",
            "suggestion": None,
        })
    return out, queries


#: Words that a run-on typo is nearly always made of. `ofthe`, `inorder`, `isnot` —
#: splitting those is a real correction and must go through. A term the author coined
#: joins two content words, which is the case this guard is for.
_FUNCTION_WORDS = frozenset("""
a an the and or nor but if then than that this these those of in on at to for from by
with within without into onto over under is are was were be been being has have had do
does did not no as it its their his her our your my we they he she you i also such can
could may might must shall should will would there here when where which who whom whose
""".split())

#: Long enough to be a term rather than a slip, and both halves long enough to be words.
_MIN_COMPOUND = 7
_MIN_HALF = 3


def _closed_compounds(paragraph: str) -> List[str]:
    return [w for w in re.findall(r"[A-Za-z]{%d,}" % _MIN_COMPOUND, paragraph or "")]


def _splits_of(word: str) -> List[Tuple[str, str]]:
    return [(word[:i], word[i:]) for i in range(_MIN_HALF, len(word) - _MIN_HALF + 1)]


def keep_closed_compounds(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """A word the author wrote closed stays closed.

    `timespace` came back as `time space`. It is the author's term, it is written that
    way in the literature, and nothing in the house rules asks for it to be opened —
    the copyedit simply did not recognise the word and treated it as a slip.

    Two conditions keep this away from the corrections that must go through. Both
    halves must be content words, so `ofthe` -> `of the` and `inorder` -> `in order`
    are untouched; and the manuscript must never write the term open itself, because an
    author who uses both forms has not made the decision this guard would be enforcing.

    Restored with a query rather than in silence: if the word really is a slip, the
    editor is the one who should say so.
    """
    whole = "\n".join(p or "" for p in original).lower()
    out = list(edited)
    queries: List[Dict[str, object]] = []
    for i in range(min(len(original), len(edited))):
        was, now = original[i] or "", out[i] or ""
        if not was or was == now:
            continue
        restored: List[str] = []
        for word in _closed_compounds(was):
            if re.search(rf"(?i)\b{re.escape(word)}\b", now):
                continue                      # the copyedit kept it
            for head, tail in _splits_of(word):
                if head.lower() in _FUNCTION_WORDS or tail.lower() in _FUNCTION_WORDS:
                    continue
                if re.search(rf"(?i)\b{re.escape(head)}\s+{re.escape(tail)}\b", whole):
                    continue                  # the author writes it open too
                opened = re.compile(rf"(?i)\b({re.escape(head)})\s+({re.escape(tail)})\b")
                if not opened.search(now):
                    continue
                now = opened.sub(lambda m: m.group(1) + m.group(2), now)
                restored.append(word)
                break
        if restored:
            out[i] = now
            terms = ", ".join(f"'{w}'" for w in dict.fromkeys(restored))
            queries.append({
                "index": i,
                "snippet": now[:200],
                "query": (f"The copyedit split {terms} into two words. The author "
                          f"writes it closed throughout, so it has been kept closed — "
                          f"please open it only if it is genuinely a slip."),
                "audience": "author",
            "guard": "keep_closed_compounds",
            "suggestion": None,
            })
    return out, queries


#: A chemical locant: `4,4\'-`, `2,2\u2032-`, `1,3-`. Job #105 inserted one in front of
#: a short form the author had written bare — `DTDA` became `4,4\'-DTDA`. The number is
#: not wrong (the author writes `4,4\u2032-dithiodianiline` where they define it) and it is
#: still an edit against the house rule: after first use the short form stands alone.
#: The inserted prime was an ASCII apostrophe where the author uses U+2032, so keeping
#: it would not even have matched their own typography.
_LOCANT = re.compile(r"^\s*\d[\d,'\u2032\u2019]*[-\u2010-\u2015]\s*$")

#: What a locant was put in front of: a short form, in capitals.
_SHORT_FORM = re.compile(r"^[A-Z][A-Za-z0-9]{1,8}\b")


def _same_expansion(mine: Optional[str], theirs: str) -> bool:
    """Whether two spellings are the same expansion written differently.

    Strict equality refused five correct edits for every real one, measured over the
    89 redlines: `carbon-fiber-reinforced polymer` against the author's `carbon fibre
    reinforced polymer`, `Convolutional Neural Networks` against its own singular,
    `The Random Forest` against `Random Forest`, and `square error` where the diff had
    left `root mean ` already in place. None of those is a different thing.

    A fabricated one is not close at all — `N,N\'-bis(2-aminoethyl)-1,3-benzene-
    dicarboxamide` against the author's `2,2\u2032-(ethylenedioxy)bis(ethylamine)` scores
    0.3 and shares no containment, which is the gap this rule sits in.
    """
    if not mine:
        return False
    if mine in theirs or theirs in mine:
        return True
    return difflib.SequenceMatcher(None, mine, theirs).ratio() >= 0.8


def refuse_invented_expansions(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """The copyedit may not invent what an abbreviation stands for.

    Job #104: the author defined `EDBEA` as `2,2′-(ethylenedioxy)bis(ethylamine)` and
    used the short form afterwards. Eight paragraphs later the copyedit wrote its own
    definition into the text — `N,N'-bis(2-aminoethyl)-1,3-benzenedicarboxamide
    (EDBEA)` — which is a **different molecule**. Not a style slip: a fabricated
    chemical name, in a manuscript, reading exactly like the author's own work.

    So the expansion is checked against the author's, and only the inserted words are
    taken out — the rest of the copyedit on that sentence stands. Where the manuscript
    never defined the abbreviation at all there is nothing to check it against, and the
    insertion is refused for the same reason: the words came from somewhere that is not
    this manuscript.
    """
    pairs = {a: re.sub(r"[^A-Za-z]", "", e).lower()
             for a, e in learn_abbreviations(original).items()}
    out = list(edited)
    queries: List[Dict[str, object]] = []
    for i in range(min(len(original), len(edited))):
        before, after = original[i] or "", out[i] or ""
        # No `"(" in after` shortcut: that was written when this guard only knew
        # about expansions, and it made the locant case silent on any sentence with no
        # bracket in it — which is most sentences.
        if not before or before == after:
            continue
        rebuilt: List[str] = []
        refused: List[str] = []
        unverifiable: List[str] = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                None, before, after, autojunk=False).get_opcodes():
            if tag == "delete":
                continue
            seg = after[j1:j2]
            if (tag in ("insert", "replace") and _LOCANT.match(seg)
                    and _SHORT_FORM.match(after[j2:])):
                refused.append(_SHORT_FORM.match(after[j2:]).group(0))
                if tag == "replace":
                    rebuilt.append(before[i1:i2])
                continue
            if tag in ("insert", "replace") and seg.rstrip().endswith("("):
                follows = re.match(r"\s*([A-Z][A-Za-z0-9]{1,8})\)", after[j2:])
                if follows:
                    abbr = follows.group(1)
                    words = re.sub(r"[^A-Za-z]", "", seg).lower()
                    if len(words) > 3 and not _same_expansion(pairs.get(abbr), words):
                        if abbr in pairs:
                            # The manuscript says what it stands for, and this is not
                            # that. Fabrication, and the author's own words settle it.
                            refused.append(abbr)
                            if tag == "replace":
                                rebuilt.append(before[i1:i2])
                            continue
                        # Never defined anywhere in the manuscript. The expansion may
                        # well be right — `thermoplastic starch (TPS)` — and nothing
                        # here can tell. Removing it would throw away the house rule's
                        # own first-use requirement; keeping it silently would ship a
                        # fact from outside the paper. So it stands, and it is asked
                        # about.
                        unverifiable.append(abbr)
            rebuilt.append(seg)
        if unverifiable:
            names = ", ".join(dict.fromkeys(unverifiable))
            queries.append({
                "index": i,
                "snippet": after[:200],
                "query": (f"The copyedit spelled out {names} here. The manuscript does "
                          f"not define it anywhere, so nothing in the file confirms "
                          f"the expansion is the right one — please check it against "
                          f"the author's field before accepting."),
                "audience": "author",
            "guard": "refuse_invented_expansions",
            "suggestion": None,
            })
        if not refused:
            continue
        fixed = "".join(rebuilt)
        for abbr in refused:                 # the closing bracket it left behind
            fixed = re.sub(rf"(?<!\()\b{re.escape(abbr)}\)", abbr, fixed)
        out[i] = fixed
        names = ", ".join(dict.fromkeys(refused))
        queries.append({
            "index": i,
            "snippet": fixed[:200],
            "query": (f"The copyedit added chemical detail to {names} here that the "
                      f"author did not write in this sentence — an expansion, or a "
                      f"locant in front of the short form. It has been removed rather "
                      f"than corrected: after its first use the short form stands "
                      f"alone, and where {names} is defined is the author's decision."),
            "audience": "author",
            "guard": "refuse_invented_expansions",
            "suggestion": None,
        })
    return out, queries


#: A symbol the author marked with a subscript or superscript: `G_IC`, `G_(IC,healed)`,
#: `m^1/2`. In a plain-text pipeline the marker is the only thing carrying that
#: information, so removing it is not a tidy-up — it is the difference between
#: *G*ᵢᴄ and a three-letter symbol called GIC.
#: No `/` in the tail: `G_IC,healed/G_IC,pristine` is two symbols with a solidus
#: between them, and a pattern that swallows the slash restores the first and leaves
#: the second flattened — which is how this was caught.
#: The bracket is matched as a pair or not at all. Optional on each side, the tail of
#: `(G_IC,healed/G_IC,pristine)` matches as `G_IC,pristine)` — and putting that back
#: writes a closing bracket the sentence already had.
_MARKED_SYMBOL = re.compile(
    r"\b[A-Za-z][A-Za-z0-9]*[_^](?:\([A-Za-z0-9,.\-]+\)|[A-Za-z0-9,.\-]+)")


def _flattened(symbol: str) -> str:
    return re.sub(r"[_^()]", "", symbol)


def keep_subscript_markers(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """A subscript the author marked stays marked.

    Job #104 returned `(G_IC,healed/G_IC,pristine)` as `(GIC,healed/GIC,pristine)` and
    `(G_(IC,healed))` as `(GIC,healed)`. It reads like tidying and it is not: the
    underscore is what says the letters are a subscript, and a typesetter given `GIC`
    has no way back to *G*ᴵᶜ.

    Unicode has no subscript `I` or `C`, so this cannot be fixed by converting it the
    way `H₂O` is converted — the same wall the half-sized `₀.₀₁Hz` ran into. The
    author's own notation is kept and the query asks for Word's subscript formatting,
    which is the only thing that can actually carry it.
    """
    out = list(edited)
    queries: List[Dict[str, object]] = []
    for i in range(min(len(original), len(edited))):
        was, now = original[i] or "", out[i] or ""
        if not was or was == now or ("_" not in was and "^" not in was):
            continue
        restored: List[str] = []
        for symbol in dict.fromkeys(_MARKED_SYMBOL.findall(was)):
            if symbol in now:
                continue                      # the copyedit kept the marker
            flat = _flattened(symbol)
            if len(flat) < 3 or flat == symbol or flat not in now:
                continue
            now = now.replace(flat, symbol)
            restored.append(symbol)
        if restored:
            out[i] = now
            names = ", ".join(f"`{s}`" for s in restored)
            queries.append({
                "index": i,
                "snippet": now[:200],
                "query": (f"The copyedit removed the subscript marker from {names}. "
                          f"The author's notation has been kept — please set the "
                          f"subscript with Word's own formatting, which is the only "
                          f"thing that can carry it."),
                "guard": "keep_subscript_markers",
                "suggestion": None,
            })
    return out, queries


#: A figure or table caption, by how it opens. A caption is not prose: it is the label
#: on a piece of data, and the numbers in it identify which data.
#: The number may be `9`, `10.2` or `8.1` — all of it belongs to the label, and a
#: pattern that stopped at `10` left `2 Mean` looking like a value that changed.
_CAPTION_START = re.compile(
    r"(?i)^\s*(fig(?:ure)?|tab(?:le)?|scheme|plate)\s*[.:\-–—]?\s*\d+(?:\.\d+)*")

#: What a sentence about a table does and a caption never does. `Table 6 and Figure 2
#: shows that the quality satisfaction level…` opens exactly like a caption and is
#: prose; measured over 90 redlines, this one word separated the two every time.
_REPORTING_VERB = re.compile(
    r"(?i)\b(shows?|summari[sz]es?|presents?|illustrates?|displays?|lists?|gives?|"
    r"depicts?|compares?|indicates?|reports?|describes?|reveals?|contains?)\b")

#: A caption is a label. Past this length it is a paragraph that begins with one.
_MAX_CAPTION = 300

#: A sample label: `T4`, `S1`, `R2`. Everything else worth comparing in a caption —
#: quantities with units, chemical formulae, marked symbols — is already defined once,
#: in `token_census`, and measured there. Defining "a value" a second time here is how
#: the first sweep came to treat `800 and` and `1 region` as data.
_SAMPLE_LABEL = re.compile(r"\b[A-Za-z]{1,3}[\d₀-₉⁰-⁹]{1,3}\b")

#: Sub- and superscript digits folded to plain ones, both of them. The census keeps
#: superscripts marked on purpose — there a dropped `^` is the defect — but a caption
#: asks a different question, and `10-5 moles/L` set as `10⁻⁵ moles/L` is this
#: pipeline doing its job.
_SCRIPT_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹", "01234567890123456789")


def _caption_values(text: str) -> List[str]:
    body = _CAPTION_START.sub("", text or "")
    return _token_census._tokens_outside_links(body) + _SAMPLE_LABEL.findall(body)


def _value_key(value: str) -> str:
    return re.sub(r"[\s\-\u2010-\u2015\u207b]", "",
                  (value or "").translate(_SCRIPT_DIGITS)).lower()


#: The values inside one. `T4`, `80g`, `0.05 M` — a label or a quantity, not the
#: caption's own number, which `_CAPTION_START` has already consumed.

def keep_caption_values(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """A caption's data may be re-worded but not re-valued.

    Job #106: `Figure 9: Line Waver-Burke Plot for T4 (80g) of Room-Dried of Plantain
    Stem Substrate` came back as `Figure 9. Lineweaver-Burk plot for T5 (100 g) of
    room-dried plantain stem substrate.` The spelling repair is right and wanted. `T4
    (80g)` becoming `T5 (100 g)` is not a copyedit: it is the caption now claiming the
    figure shows a different sample at a different mass, silently, to agree with a
    sentence further down the paper.

    It may even be what the author meant — the body does say T5 — and that is the
    point. Which of the two is the typo is a question about the artwork, and nobody
    reading the manuscript can answer it. The values come back and the query asks.

    Only the values are restored. Every other correction to the caption stands.
    """
    out = list(edited)
    queries: List[Dict[str, object]] = []
    for i in range(min(len(original), len(edited))):
        was, now = original[i] or "", out[i] or ""
        if not was or was == now or not _CAPTION_START.match(was):
            continue
        if len(was) > _MAX_CAPTION or _REPORTING_VERB.search(was):
            continue
        mine, theirs = _caption_values(was), _caption_values(now)
        # `CaSO4` -> `CaSO₄` and `cm-1` -> `cm⁻¹` are this pipeline's own corrections,
        # and were 14 of the first sweep's 44 findings. Folded away here.
        flat = [_value_key(v) for v in theirs]
        lost = [v for v in mine if _value_key(v) not in flat]
        if not lost:
            continue
        # Put each one back where the copyedit's own value stands, so the rewritten
        # caption keeps its wording and only the data returns to the author's.
        _mine_flat = [_value_key(x) for x in mine]
        for value, replacement in zip(lost, [v for v in theirs
                                             if _value_key(v) not in _mine_flat]):
            now = now.replace(replacement, value, 1)
        out[i] = now
        queries.append({
            "index": i,
            "snippet": was[:200],
            "query": (f"The copyedit changed {', '.join(f'`{v}`' for v in lost)} in "
                      f"this caption. A caption's values identify which data the "
                      f"figure shows, so the author's have been put back — if the "
                      f"caption really does disagree with the text, that is a question "
                      f"for the author and the artwork, not a copyedit."),
            "audience": "author",
            "guard": "keep_caption_values",
            "suggestion": None,
        })
    return out, queries


#: A short all-letters token that could be a unit or an abbreviation: `cfu`, `tph`,
#: `bod`. Bounded at six letters — beyond that a run of capitals is a word being
#: shouted, not a unit.
_ABBREVIATION_TOKEN = re.compile(r"^[a-z]{2,6}$")

#: Ordinary words, which a heading recases and a unit does not. Without this the first
#: sweep read `MATERIALS AND METHODS` -> `Materials and Methods` as a decision about
#: the term `AND` and rewrote it through 115 paragraphs of one manuscript.
_ORDINARY_WORDS = frozenset("""
a an the and or nor but if then than that this these those of in on at to for from by
with within into onto over under is are was were be been being has have had do does
did not no as it its their his her our your my we they he she you i also such can
could may might must shall should will would there here when where which who whom
whose all any both each few more most other some only very same so what why how
after before during while about above below between through against among per via
new old two one three used using use data both time case study group level total
al et pp ed eds vol no fig figs tab eq
""".split())


def _is_a_recasing(before: str, after: str) -> bool:
    """`cfu` -> `CFU` yes; `and` -> `AND` no; `Fig` -> `FIG` no."""
    return (before.islower() and after.isupper()
            and before.lower() == after.lower()
            and _ABBREVIATION_TOKEN.match(before) is not None
            and before not in _ORDINARY_WORDS)


def apply_case_changes_everywhere(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """A unit recased in one place is recased in all of them.

    Job #106: the author writes `cfu/g` three times; the copyedit returned `CFU/g`
    once and left the other two alone. `CFU` is the right form and that is not the
    complaint — a manuscript that says `CFU/g` on one page and `cfu/g` on the next is
    worse than one that is consistently wrong, because now a reader cannot tell which
    is the typo.

    Only a whole token whose letters are unchanged, only between all-lower and
    all-caps, and only outside the first word of a sentence: `the` -> `The` at a full
    stop is the copyedit punctuating, not a decision about a term.

    One query per term, naming where it was seen, so the editor knows a change of
    theirs was carried further than they made it.
    """
    # A recasing is learned from the body only. The bibliography is re-sorted and
    # re-formatted wholesale, so paragraph *i* before and paragraph *i* after are
    # routinely two different works — which is how the first sweep learned `al` ->
    # `AL` from an `et al.` on one side and an author's initials on the other, and
    # would have written `et AL.` through eight paragraphs.
    body_end = _references_start(original)
    body_end = len(original) if body_end is None else body_end

    changes: Dict[str, str] = {}
    for was, now in zip(original[:body_end], edited[:body_end]):
        if not was or not now or was == now:
            continue
        # By set membership, not by position: pairing two word lists positionally
        # makes every later word disagree as soon as one is inserted, and the first
        # sweep's `and` -> `AND` came from exactly that.
        mine, theirs = set(re.findall(r"[A-Za-z]+", was)), set(
            re.findall(r"[A-Za-z]+", now))
        for before in mine:
            after = before.upper()
            if (after in theirs and before not in theirs
                    and _is_a_recasing(before, after)):
                changes.setdefault(before, after)

    if not changes:
        return edited, []
    return _write_case_changes(edited, changes)


def apply_case_changes_to_cells(
    original: List[str], edited: List[str], cells: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """The same recasing, carried into the table cells.

    Job #107 is job #106's finding again, and it survived a guard written for it: the
    author wrote `cfu/g` three times, ¶37 came back `CFU/g`, and the two in the table —
    `T. Bacteria (cfu/g)`, `HUB (cfu/g)` — stayed as they were. The guard did exactly
    what it was written to do and never saw them, because the pipeline carries body
    paragraphs and table cells as two separate lists.

    A unit is not consistent within the prose; it is consistent within the *paper*, and
    a table is where a reader looks the unit up. So the recasing is learned from the
    body, where the sentence makes it unambiguous, and applied to both — the same
    reasoning `collapse_duplicated_symbols` already uses two steps further down.
    """
    body_end = _references_start(original)
    body_end = len(original) if body_end is None else body_end
    changes = _learn_case_changes(original[:body_end], edited[:body_end])
    if not changes or not cells:
        return cells, []
    out, queries = _write_case_changes(cells, changes)
    for query in queries:
        query["guard"] = "apply_case_changes_to_cells"
        query["query"] = query["query"].replace("elsewhere.", "in the table.")
    return out, queries


def _learn_case_changes(original: List[str], edited: List[str]) -> Dict[str, str]:
    changes: Dict[str, str] = {}
    for was, now in zip(original, edited):
        if not was or not now or was == now:
            continue
        mine, theirs = set(re.findall(r"[A-Za-z]+", was)), set(
            re.findall(r"[A-Za-z]+", now))
        for before in mine:
            after = before.upper()
            if (after in theirs and before not in theirs
                    and _is_a_recasing(before, after)):
                changes.setdefault(before, after)
    return changes


def _write_case_changes(
    edited: List[str], changes: Dict[str, str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    out = list(edited)
    queries: List[Dict[str, object]] = []
    for before, after in changes.items():
        # Never the first word of a sentence, where a capital means something else.
        pattern = re.compile(rf"(?<![.!?]\s)(?<!^)\b{re.escape(before)}\b")
        touched = 0
        for i, para in enumerate(out):
            if not para or before not in para:
                continue
            fixed, n = pattern.subn(after, para)
            if n:
                out[i] = fixed
                touched += n
        if touched:
            queries.append({
                "index": next((i for i, p in enumerate(out) if after in (p or "")), 0),
                "snippet": after,
                "query": (f"The copyedit wrote `{before}` as `{after}` in one place "
                          f"and left it as it was elsewhere. It has been made "
                          f"consistent throughout ({touched} more). If `{before}` was "
                          f"right, the change can be rejected everywhere at once."),
                "guard": "apply_case_changes_everywhere",
                "suggestion": None,
            })
    return out, queries


#: An author-date citation as authors actually write them, in the two shapes that
#: matter: wholly parenthetical — `(FAO, 2015)`, `(Smith et al., 2020)`, `(Nellemann &
#: Corcoran, 2010)` — and narrative, where the name is in the sentence and only the year
#: is bracketed: `Haller (2017)`.
_PARENTHETICAL_CITE = re.compile(
    r"\((?P<body>[A-Z][A-Za-zÀ-ÿ'’\-\.]*(?:[^()]{0,80}?))[,;]?\s*"
    r"(?P<year>(?:19|20)\d{2}[a-z]?)\)")
_NARRATIVE_CITE = re.compile(
    r"(?P<body>[A-Z][A-Za-zÀ-ÿ'’\-]+(?:\s+(?:et\s+al\.?|and|&)\s+[A-Z][A-Za-zÀ-ÿ'’\-]+)?)"
    r"\s*\((?P<year>(?:19|20)\d{2}[a-z]?)\)")

#: Words that sit in front of a year and are not anybody's name. Every one of these
#: was a false finding on the corpus: `Survey (2025)`, `Data (2024)`, `Needs (1943)`,
#: and eight month names from dates the pass had reformatted.
_NOT_A_SURNAME = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "survey", "data", "report", "table", "figure", "fig", "eq", "equation",
    "needs", "since", "during", "between", "from", "until", "the", "this", "these",
    "accessed", "retrieved", "published", "vol", "volume", "issue", "no", "pp",
    "note", "source", "adapted", "based", "see", "cf", "eg", "ie", "www", "https",
}

#: A bracketed number, which is what the citation pass turns those into.
_BRACKETED_NUMBER = re.compile(r"\[\s*\d{1,3}(?:\s*[,;–—-]\s*\d{1,3})*\s*\]")


def _cited_identity(body: str, year: str) -> Optional[Tuple[str, str]]:
    """`(surname, year)` for an in-text citation, matching `_reference_identity`."""
    first = re.match(r"\s*([A-Za-zÀ-ÿ'’\-]{2,})", body or "")
    if not first:
        return None
    return first.group(1).lower().replace("’", "'"), year[:4]


def _first_year(body: str) -> Optional[str]:
    m = re.search(r"\b(?:19|20)\d{2}\b", body or "")
    return m.group(0) if m else None


def _cited_as_written(body: str) -> str:
    """The name as the author typed it. `FAO` is not `Fao`, and a query that renames
    the source makes the author look for something they never wrote."""
    first = re.match(r"\s*([A-Za-zÀ-ÿ'’\-]{2,})", body or "")
    return first.group(1) if first else (body or "").strip()


def _citation_slots(text: str) -> List[Tuple]:
    """Every citation in a paragraph, in order: `(start, end, kind, identity)`.

    Overlaps are resolved by preferring the longer match, because `Haller (2017)` and
    `(2017)` both match and only the first names the work.
    """
    found: List[Tuple] = []
    for pattern, kind in ((_NARRATIVE_CITE, "author-date"),
                          (_PARENTHETICAL_CITE, "author-date")):
        for m in pattern.finditer(text or ""):
            # `(Baumeister, 1995; Deci, 2000; Leary, 2009; Maslow, 1954)` is four
            # citations in one pair of brackets. Read whole, its surname is Baumeister
            # and its year is 1954 — a work nobody cited, reported as missing.
            body = m.group("body")
            head = body.split(";")[0] if ";" in body else body
            identity = _cited_identity(head, m.group("year") if ";" not in body
                                       else _first_year(body) or m.group("year"))
            found.append((m.start(), m.end(), kind, identity,
                          _cited_as_written(head)))
    for m in _BRACKETED_NUMBER.finditer(text or ""):
        found.append((m.start(), m.end(), "number", None, ""))

    found.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: List[Tuple] = []
    for slot in found:
        if kept and slot[0] < kept[-1][1]:
            continue
        kept.append(slot)
    return kept


def _is_listed(surname: str, listed: set) -> bool:
    """Whether the bibliography carries this name, allowing for how it was typed.

    A prefix match either way, from four characters: two entries in the corpus are
    keyed `Mittala, A. K., & Pandeyb, M.` — the author's own typing — and the paper
    cites them as Mittal and Pandey. The reference is plainly there, and telling the
    author it is missing would send them looking for a page they are already on.
    """
    if surname in listed:
        return True
    if len(surname) < 4:
        return False
    return any(name.startswith(surname) or surname.startswith(name)
               for name in listed if len(name) >= 4)


def _names_near(text: str, position: int, surname: str, listed: set) -> bool:
    """Whether this citation names anybody the bibliography lists.

    A narrative citation can carry its whole author list in the sentence — `as per
    A. Boardman, Greenberg, Vining, & Weimer (2001)` — and the name the year sits
    beside is the *last* of them. Boardman is the one in the bibliography, so reading
    only Weimer reports a reference that is there. Everything capitalised in the
    sixty characters before the citation is considered.
    """
    if _is_listed(surname, listed):
        return True
    window = text[max(0, position - 60):position + 1]
    return any(_is_listed(name.lower().replace("’", "'"), listed)
               for name in re.findall(r"[A-Z][A-Za-zÀ-ÿ'’\-]{2,}", window))


def refuse_citations_without_a_reference(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """A citation number is a pointer. It may not be minted for a work that is not there.

    Job #107, ¶18: the author wrote `...plays a foundational role in sustaining life
    (FAO, 2015).` and the citation pass returned `...sustaining life [3].` There is no
    FAO entry anywhere in the nineteen references — so `[3]` now points at Akpe et al.,
    *Bacterial degradation of petroleum hydrocarbons in crude oil polluted soil amended
    with cassava peels*, which has nothing to do with global food production.

    That is not a formatting slip. It is a false attribution, printed, in a paper that
    will be cited itself. And it is invisible to every check that came before: the
    number is well formed, the bibliography is intact, the count of citations is
    unchanged. Only the *relationship* between the citation and the list is wrong.

    The quality team's rule, which is the right one: **until the reference exists, no
    number is given.** The author's own `(FAO, 2015)` is put back and a query goes to
    them asking where the reference is. The paper then says exactly what its author
    said, and the one person who can supply the missing entry is asked for it.

    Paired by position within the paragraph rather than by matching text, because the
    same sentence was copyedited at the same time. Where the count of citations differs
    between the two versions, nothing is rewritten and the query is raised on its own —
    a guard that guesses which number replaced which name would eventually put a name
    back in the wrong place, which is the defect it exists to prevent.
    """
    start = _references_start(original)
    if start is None:
        return edited, []

    # Every surname the bibliography carries, anywhere in any entry — and *only* the
    # surname, not the surname-and-year. Measured on 91 redlines, the pair was wrong in
    # four different ways at once: the year in `(Baumeister, 1995; Deci, 2000; Maslow,
    # 1954)` belongs to Maslow; `Carton et al., 2008` is listed under 2010; the entry
    # for `Virani (2022)` carries no year at all; and a reformat can move which author
    # an entry opens with. Every one of those is a reference that *is there*.
    #
    # So the claim this guard makes is the narrow one it can actually prove: there is no
    # reference for this name at all. A citation to a different work by the same author
    # passes, and that is the right trade — a false "your reference is missing" sends an
    # author looking for something that is on the page in front of them.
    listed = set()
    for entry in original[start + 1:] + edited[start + 1:]:
        for name in re.findall(r"[A-Za-zÀ-ÿ'’\-]{3,}", entry or ""):
            listed.add(name.lower().replace("’", "'"))
    if not listed:
        # No readable bibliography: this guard has nothing to check against, and
        # restoring citations on that basis would be worse than leaving them.
        return edited, []

    out = list(edited)
    queries: List[Dict[str, object]] = []
    seen: set = set()

    for i in range(min(start, len(edited))):
        was, now = original[i] or "", out[i] or ""
        if not was or not now:
            continue
        before_slots = _citation_slots(was)
        unlisted = [s for s in before_slots
                    if s[2] == "author-date" and s[3]
                    and s[3][0] not in _NOT_A_SURNAME
                    and not _names_near(was, s[0], s[3][0], listed)]
        if not unlisted:
            continue

        after_slots = _citation_slots(now)
        if len(after_slots) != len(before_slots):
            # The copyedit added or removed a citation here. Pairing by position would
            # be pairing the wrong things, and a guard that puts a name back in the
            # wrong place is the defect it exists to prevent.
            continue

        # Only the ones that actually *became a number*. An author-date the copyedit
        # left alone has minted no pointer and broken nothing — flagging it would bury
        # the real finding under every uncited name in the manuscript.
        minted = [(slot, target) for slot, target in zip(before_slots, after_slots)
                  if slot in unlisted and target[2] == "number"]
        if not minted:
            continue

        restored = 0
        for slot, target in sorted(minted, key=lambda pair: -pair[1][0]):
            now = now[:target[0]] + was[slot[0]:slot[1]] + now[target[1]:]
            restored += 1
        out[i] = now

        for (_, _, _, identity, written), _target in minted:
            if identity in seen:
                continue
            seen.add(identity)
            _, year = identity
            surname = written or identity[0].title()
            queries.append({
                "index": i,
                "snippet": f"{surname} ({year})",
                "query": (
                    f"`{surname} ({year})` is cited here but there is no "
                    f"reference for it in the list. "
                    + ("The author's own citation has been kept as it was: a number "
                       "cannot be given until the reference exists, or it would point "
                       "at a different work. "
                       if restored else
                       "The citation has been left alone. ")
                    + "Please supply the reference, or remove the citation."),
                "guard": "refuse_citations_without_a_reference",
                "suggestion": None,
            })
    return out, queries


#: Words that appear in half the bibliographies ever written and say nothing about
#: which work an entry is.
_REF_STOPWORDS = {
    "journal", "international", "research", "science", "sciences", "studies",
    "review", "reviews", "analysis", "study", "using", "based", "available",
    "press", "university", "publishing", "volume", "issue", "pages", "edition",
    "https", "http", "www", "doi", "org", "accessed", "retrieved", "proceedings",
    "conference", "report", "technology", "engineering", "management", "effect",
    "effects", "development", "application", "applications",
}


def _first_words(entry: str, words: int = 6) -> str:
    """Enough of an entry to recognise it in a query, without quoting the whole thing."""
    parts = (entry or "").split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def _reference_shape(entry: str) -> Optional[Dict[str, object]]:
    """What an entry is *about*, in a form that survives being reformatted.

    `_reference_identity` — the first token and a year — is not that, and the corpus
    says so plainly. Across 91 redlines it reported a reference as lost in 24 of them,
    and the losses read: `Akio (1973)` replaced by `Nakajima (1973)`, `Yalemtesfa
    (2017)` by `Guade (2017)`, `Csa (2020)` by `Central (2020)`. Those are Akio
    Nakajima, Yalemtesfa Guade and the Central Statistical Agency — one work each,
    reformatted so that a different word comes first. Every one of those manuscripts had
    its whole bibliography restored unformatted as a result.

    So a work is identified by what does not move: the years it names, every name-like
    token in it, and the uncommon words of its title.
    """
    text = (entry or "").strip()
    if len(text) <= 20:
        return None
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", text))
    names = {w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ'’\-]{3,}", text)}
    title = {w for w in names if len(w) >= 5 and w not in _REF_STOPWORDS}
    # A year is the usual anchor but it cannot be required. `Warrens, M. J. (2014). New
    # interpretations of Cohen's kappa. Journal of Mathematics` came back as `Warrens MJ.
    # New interpretations of Cohen's kappa. J Math.` — the reformat dropped the year, so
    # the new entry had no shape at all and the reference sitting on the page was
    # reported as having gone missing. A yearless entry is a defect for another guard to
    # report; it is not a lost reference.
    # A yearless paragraph has to look like a reference before it is treated as one.
    # `Local strain(SB12)+50kgDAP` sits after the References heading in two manuscripts
    # — it is a table row — and reporting it as a lost reference is how a guard ends up
    # ignored.
    if not years and (len(title) < 3 or len(text.split()) < 6):
        return None
    return {"years": years, "names": names, "title": title, "text": text}


def _reads_the_same(a: str, b: str, bar: float = 0.6) -> bool:
    """Whether two entries are recognisably the same string of words.

    Only reached for entries with no year on one side, where there is nothing else
    solid to compare. `difflib` rather than a token test because the difference there
    is usually inside a word — a corrected surname — which no set of tokens can see.
    """
    import difflib
    def flat(text):
        return re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    return difflib.SequenceMatcher(None, flat(a), flat(b)).ratio() >= bar


def _same_work(a: Dict[str, object], b: Dict[str, object]) -> bool:
    """Whether two entries are the same work, allowing for any reformat we perform."""
    shared_title = a["title"] & b["title"]
    if a["years"] and b["years"] and not (a["years"] & b["years"]):
        # Different years is usually a different work — but the pass does correct a
        # wrong year from the catalogue, so a title that plainly matches still counts.
        if len(shared_title) < 3:
            return False
    elif not (a["years"] and b["years"]):
        # One side has no year, so the words have to carry the match on their own.
        # Two shared title words plus a plainly similar entry is enough: `Anathanarayan
        # and Panikers, Textbook of Microbiology 10th edition` became `Ananthanarayan,
        # Paniker. Textbook of Microbiology. 10th edition.` — the pass corrected the
        # spelling of the name, which is the right edit and left only `textbook` and
        # `microbiology` in common.
        if len(shared_title) >= 3:
            return True
        if len(shared_title) >= 2 and _reads_the_same(str(a["text"]), str(b["text"])):
            return True
        return False
    if not (a["title"] | b["title"]):
        return bool(a["names"] & b["names"])
    overlap = len(shared_title) / max(1, min(len(a["title"]), len(b["title"])))
    # Either the title is recognisably the same work, or enough of the names are. The
    # two together are what make this survive an entry that was abbreviated to `et al.`
    # *and* re-led with a different author.
    return overlap >= 0.5 or len(shared_title) >= 4 or len(a["names"] & b["names"]) >= 3


def _match_score(a: Dict[str, object], b: Dict[str, object]) -> int:
    """How strongly two entries look like the same work. 0 means not at all.

    Whether they are the same work is `_same_work`'s decision and only its decision:
    this once had its own year test in front, which scored a pair of *identical*
    yearless entries at zero and reported a reference that had not been touched as
    lost. Two answers to one question is one answer too many.
    """
    if not _same_work(a, b):
        return 0
    return len(a["title"] & b["title"]) * 3 + len(a["names"] & b["names"]) + (
        2 if a["years"] & b["years"] else 0)


def _references_lost(
    before: List[str], after: List[str],
) -> Tuple[List[str], List[str]]:
    """`(the author's entries nothing accounts for, new entries nothing asked for)`.

    The second half matters as much as the first. When a work goes missing it is almost
    always because a neighbour was written twice, and naming the surplus entry is what
    lets an editor put the list right in one pass instead of two.

    Best-match first, not first-match-wins. Taking the first candidate in order lost
    `Gibson-Beverly, G., & Schwartz, J. P. (2008)` on a real manuscript: an earlier
    entry sharing its year and one author name reached it first and consumed it, and
    the entry — sitting in the new list, correctly reformatted, three lines up — was
    reported as gone. Pairs are made strongest-first so a weak match cannot take a
    partner that a strong one needs.

    One-to-one, so a genuine duplication — job #60's Tlili appearing twice while
    Vygotsky left — still shows up as a loss.
    """
    shapes_before = [s for s in (_reference_shape(p) for p in before) if s]
    shapes_after = [s for s in (_reference_shape(p) for p in after) if s]

    pairs = []
    for i, want in enumerate(shapes_before):
        for j, have in enumerate(shapes_after):
            score = _match_score(want, have)
            if score:
                pairs.append((score, i, j))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))

    matched_before, matched_after = set(), set()
    for _score, i, j in pairs:
        if i in matched_before or j in matched_after:
            continue
        matched_before.add(i)
        matched_after.add(j)

    lost = [str(shape["text"]) for i, shape in enumerate(shapes_before)
            if i not in matched_before]
    unaccounted = [str(shape["text"]) for j, shape in enumerate(shapes_after)
                   if j not in matched_after]
    return lost, unaccounted


def _variant_pairs() -> Dict[str, str]:
    """Every word this house knows as a spelling variant, both ways round."""
    from science_format import _UK_TO_US, _US_TO_UK
    pairs = dict(_UK_TO_US)
    pairs.update(_US_TO_UK)
    return pairs


def _learn_spelling_changes(original: List[str], edited: List[str]) -> Dict[str, str]:
    """The re-spellings the copyedit itself made, and only those.

    Validated against the house's own variant list, so this can never turn into
    "replace any word the copyedit replaced". `fibre` → `fiber` is learned; `showed`
    → `demonstrated` is not a spelling variant and is none of this guard's business.
    """
    variants = _variant_pairs()
    changes: Dict[str, str] = {}
    for was, now in zip(original, edited):
        if not was or not now or was == now:
            continue
        mine = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", was)}
        theirs = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", now)}
        for word in mine - theirs:
            target = variants.get(word)
            if target and target in theirs:
                changes.setdefault(word, target)
    return changes


def _write_spelling_changes(
    paragraphs: List[str], changes: Dict[str, str], where: str,
) -> Tuple[List[str], List[Dict[str, object]]]:
    from science_format import _match_case

    out = list(paragraphs)
    queries: List[Dict[str, object]] = []
    for before, after in changes.items():
        pattern = re.compile(rf"\b{re.escape(before)}\b", re.I)
        touched = 0
        for i, para in enumerate(out):
            if not para:
                continue
            fixed, n = pattern.subn(lambda m: _match_case(m.group(0), after), para)
            if n:
                out[i] = fixed
                touched += n
        if touched:
            queries.append({
                "index": next((i for i, p in enumerate(out) if p and after in p.lower()),
                              0),
                "snippet": after,
                "query": (f"The copyedit spelled `{before}` as `{after}` in one place "
                          f"and left it as it was {where}. It has been made consistent "
                          f"throughout ({touched} more). One manuscript cannot hold "
                          f"both spellings; if `{before}` was right, the change can be "
                          f"rejected everywhere at once."),
                "guard": "apply_spelling_changes_everywhere",
                "suggestion": None,
            })
    return out, queries


def apply_spelling_changes_everywhere(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """A word re-spelled in one place is re-spelled in all of them.

    Job #109 was set to *Auto — follow the manuscript*, and the manuscript does not
    follow one: 44 UK-only spellings against 62 US-only. So `enforce_language_variant`
    correctly refused to choose, said so, and did nothing — and the copyedit went ahead
    and chose anyway, in fourteen paragraphs out of seventeen. The paper came back with
    `fiber` twenty-seven times and `fibre` four, which is worse than either spelling
    consistently: a reader cannot tell which is the typo.

    So the decision is the copyedit's and the consistency is this guard's. Whatever it
    re-spelled, it re-spells everywhere — no variant is chosen here, and a change the
    editor rejects is rejected in one place and gone from all of them.

    **The bibliography is never touched.** A reference title is a quotation of a
    published work: `Optimizing the selection of natural fibre reinforcement` is the
    title of somebody else's paper, and re-spelling it makes the reference wrong. That
    is why one of #109's four survivors — ¶449 — was right to survive.
    """
    body_end = _references_start(original)
    body_end = len(original) if body_end is None else body_end
    changes = _learn_spelling_changes(original[:body_end], edited[:body_end])
    if not changes:
        return edited, []
    fixed, queries = _write_spelling_changes(edited[:body_end], changes, "elsewhere")
    return fixed + list(edited[body_end:]), queries


def apply_spelling_changes_to_cells(
    original: List[str], edited: List[str], cells: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """And into the table, for the same reason the recasing goes there."""
    body_end = _references_start(original)
    body_end = len(original) if body_end is None else body_end
    changes = _learn_spelling_changes(original[:body_end], edited[:body_end])
    if not changes or not cells:
        return cells, []
    out, queries = _write_spelling_changes(cells, changes, "in the table")
    for query in queries:
        query["guard"] = "apply_spelling_changes_to_cells"
    return out, queries


_BRACKET_GROUP = re.compile(r"\[\s*(\d{1,3}(?:\s*[,;]\s*\d{1,3}|\s*[–—-]\s*\d{1,3})*)\s*\]")


def _bracket_numbers(text: str) -> List[List[str]]:
    """The numbers inside each bracketed citation, in order."""
    return [re.findall(r"\d{1,3}", m.group(1)) for m in _BRACKET_GROUP.finditer(text or "")]


def _list_order_unchanged(original: List[str], edited: List[str], start: int) -> bool:
    """Whether the bibliography holds the same works in the same order.

    This is the whole question. If the list was re-sorted, renumbering the text is the
    point of the exercise; if it was not, every changed number is a changed pointer.
    """
    before = [s for s in (_reference_shape(p) for p in original[start + 1:]) if s]
    after = [s for s in (_reference_shape(p) for p in edited[start + 1:]) if s]
    if not before or len(before) != len(after):
        return False
    return all(_same_work(a, b) for a, b in zip(before, after))


def keep_citation_numbers_when_the_list_did_not_move(
    original: List[str], edited: List[str],
) -> Tuple[List[str], List[Dict[str, object]]]:
    """A reference's number is the author's until the list itself is re-ordered.

    Job #110, and it is the same defect as job #107 one step further on. The author
    cited `(FAO, 2015)`, which has no reference; the numbering pass counted it as a
    work anyway and gave it a place in the sequence, so every citation after it moved
    up by one — the author's `[3]` came back as `[4]`, `[4]` as `[5]`, `[5-6]` as
    `[6, 7]`. The bibliography did not move: all nineteen entries were in the order the
    author wrote them, with `3.` still Akpe and `4.` still Ali. So `[4]` in the text now
    points at Ali where the author pointed at Akpe.

    Restoring the FAO citation, which #107's guard does, is not enough on its own —
    that fixes the sentence and leaves the shift. This is the other half.

    The rule is decidable rather than clever: if the bibliography holds the same works
    in the same order it started in, no in-text number may change. When the list *is*
    genuinely re-sorted — which is what the pass is for — the numbers are expected to
    change and nothing here interferes.

    Punctuation is not a number. `[7-9]` → `[7–9]` is the house's en dash and is left
    alone; this restores the author's *numbers*, and the citation-formatting rules that
    run after it put the house punctuation back on.
    """
    start = _references_start(original)
    if start is None or not _list_order_unchanged(original, edited, start):
        return edited, []

    out = list(edited)
    moved: List[Tuple[int, str, str]] = []
    for i in range(min(start, len(out))):
        was, now = original[i] or "", out[i] or ""
        if not was or not now:
            continue
        before_groups = list(_BRACKET_GROUP.finditer(was))
        after_groups = list(_BRACKET_GROUP.finditer(now))
        if not before_groups or len(before_groups) != len(after_groups):
            continue
        changed = [(b, a) for b, a in zip(before_groups, after_groups)
                   if _bracket_numbers(b.group(0)) != _bracket_numbers(a.group(0))]
        if not changed:
            continue
        for b, a in sorted(changed, key=lambda pair: -pair[1].start()):
            moved.append((i, a.group(0), b.group(0)))
            now = now[:a.start()] + b.group(0) + now[a.end():]
        out[i] = now

    if not moved:
        return out, []

    shown = "; ".join(f"{was} → {now}" for _i, was, now in moved[:5])
    return out, [{
        "index": moved[0][0],
        "snippet": moved[0][1],
        "query": (
            f"{len(moved)} citation number(s) had moved while the reference list stayed "
            f"in the order the author wrote it — {shown}. A number that moves while the "
            f"list does not is a citation pointing at a different paper, so the author's "
            f"numbers have been put back. This usually means the numbering pass counted "
            f"a citation that has no reference; that query is beside it."),
        "guard": "keep_citation_numbers_when_the_list_did_not_move",
        "suggestion": None,
    }]
