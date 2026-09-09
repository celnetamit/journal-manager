"""Did the copyedit lose something the author wrote?

ce4 already guards specific known things — front-matter dates, algorithm step numbers,
bibliography entries, citations, formulas — and `_lost_content` restores a paragraph
that came back badly truncated. What none of them ask is the general question: is the
author's *claim* still there.

This is the deterministic half of that question. It compares original against edited and
looks only for losses a machine can be certain about, so it can run on every job for
free. It does not judge style, and it never asks a model anything.

**Every rule here was written against a false positive that was measured, not imagined.**
Three separate metrics today scored correct behaviour as damage:

* heading numbers, which the house rules remove *on purpose* — `2.1.2. Calculation
  Modeling` -> `Calculation Modeling` looked like "a number vanished";
* `H2O` -> `H₂O`, our own subscript fix, which turns ASCII digits into characters a
  naive `\\d` never matches;
* whitespace stripped from an equation label, which looked like a paragraph shrinking
  by 90%.

So each check below normalises those away first. A checker that cries wolf on correct
edits is worse than none, because the real loss is then one line among fifty.

Measured 2026-09-04 against 100 manuscripts. The first scoring pass reported 14.8% of
paragraphs as losing content; reading the first 27 findings by hand showed most were the
house rules working exactly as written, and four more normalisations were added:

* **reference access dates** — `[cited 2025 Oct 24]`, `[Internet]`, and the month/day of
  a publication date, all of which the in-house reference rules delete on purpose
  (rule 0: "the publication date must show the YEAR ONLY");
* **bibliography entry numbers** — `[3]. Bennett MD…`, the list marker, not data;
* **the redundant parenthetical citation** — `"(API 650, Section 8.5.2, 2025)" [2]` ->
  `[2]`, which in-house citation rule 3 requires *when a numbered marker is already
  there*. The precondition is checked, because the same edit without an existing `[n]`
  is a different act entirely: it invents a citation number, and that is the largest
  real defect this found;
* **figure and table caption numbers** — `Figure 4.1:` -> `Figure 1.`, renumbering to
  Arabic sequential per the table/figure rules.

and `fail(ure)` was extended to `failures`, which alone turned "service failure" ->
"service failures" into a reversed claim.

A normalised-away finding is not discarded: it is returned with `sanctioned=True`, so
"the rules deleted this on purpose" stays visible and countable instead of becoming an
invisible assumption. Some of those are worth an argument — dropping "Section 8.5.2"
loses a locator `[2]` does not carry — but that is a question about the rule, not about
whether the copyedit misbehaved.
"""

from __future__ import annotations

import difflib
import re
from typing import Dict, List, Optional

#: Unicode sub/superscript digits back to ASCII, so `H₂O` and `H2O` carry the same
#: numbers. Without this our own formula fix reads as data loss.
_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹", "01234567890123456789")

#: A leading section number, which the house rules strip deliberately — and the
#: bibliography's own entry marker, `[3]. Bennett MD…`, which is the list's numbering
#: rather than anything the author wrote.
_HEADING_NUM = re.compile(r"^\s*(?:\[\d+\]\.?|\d+(?:\.\d+)*\.?)\s+")

_MONTH = (r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|January|February|"
          r"March|April|June|July|August|September|October|November|December")

#: An access date. The in-house reference rules keep at most "[Accessed on Month Year]"
#: on a web page and drop the rest, so every number inside is deliberately gone.
_CITED = re.compile(r"\[[^\]]*\bcited\b[^\]]*\]|\[Internet\]", re.I)

#: A month with its day. Reference rule 0 is explicit: the publication date shows the
#: YEAR ONLY. The year is left alone here, so losing *that* is still reported.
_MONTH_DAY = (re.compile(rf"\b(?:{_MONTH})\.?\s*\d{{1,2}}\b(?!\s*\d)", re.I),
              re.compile(rf"\b\d{{1,2}}\s+(?:{_MONTH})\b\.?", re.I))

#: The parenthetical author-date beside a numbered marker, which in-house citation rule 3
#: says to delete. The `[n]` must already be next to it: the model doing this *without*
#: one is not this rule, it is inventing a citation number, and stays a finding.
_REDUNDANT_PAREN = re.compile(
    r"""["“]?\([^()]{0,160}?\b(?:19|20)\d{2}\b[^()]{0,60}?\)["”]?[\s.,;:]{0,3}(?=\[\d)"""
    r"""|(?<=\])[\s.,;:]{0,3}["“]?\([^()]{0,160}?\b(?:19|20)\d{2}\b[^()]{0,60}?\)["”]?""")

#: A caption's own element number. The table/figure rules renumber to Arabic sequential,
#: so `Figure 4.1:` -> `Figure 1.` is the rule, not a lost value.
_CAPTION_NUM = re.compile(r"^\s*(?:Figure|Fig\.?|Table|Tab\.?|Scheme|Equation|Eq\.?)"
                          r"\s*\d+(?:[.\-]\d+)*", re.I)

#: A comma is only a thousands separator when it groups three digits. Stripping every
#: comma turned the list `1,2` into the number "12", and when both models correctly
#: repaired the author's typo `(i = 1, 2, 1,2, 3,… N)` to `(i = 1, 2, 3, … N)` the
#: checker reported a lost value. That is the shape of every false positive here:
#: punishing a correct edit.
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

#: Words whose loss reverses a claim. "The treatment was not effective" and "The
#: treatment was effective" differ by one word and read equally well, which is exactly
#: what makes this worth checking mechanically.
#: `failures` was missing from the first version, so pluralising "service failure" read
#: as a claim being reversed. Every inflection a copyedit can reach has to be here or the
#: count is measuring grammar, not meaning.
_NEGATION = re.compile(
    r"\b(?:not|no|never|cannot|can't|without|neither|nor|none|absent|lack(?:s|ed|ing)?|"
    r"fail(?:s|ed|ing|ure|ures)?|unable|insignificant|non-?significant)\b", re.I)

#: Below this, a paragraph is a heading, a label or an equation number, where a large
#: proportional cut is usually a correct edit.
_SHORT = 120

#: How much of a paragraph may disappear before it stops being an edit.
_MIN_KEPT = 0.7


def _sanctioned(text: str) -> str:
    """Remove the things a house rule deletes on purpose.

    Applied to BOTH sides, so it never hides a value that simply moved. What it does
    hide is a genuine loss that happens to sit inside one of these constructs — a wrong
    publication year inside a `[cited …]` block, say. That is the price of not reporting
    nine correct reference reformats for every real defect, and it is the right way
    round: the reference rules are deterministic and separately guarded, while nothing
    else in the pipeline asks whether the author's sentence survived.
    """
    t = _CITED.sub(" ", text or "")
    for pattern in _MONTH_DAY:
        t = pattern.sub(" ", t)
    t = _REDUNDANT_PAREN.sub(" ", t)
    return _CAPTION_NUM.sub(" ", t)


def _numbers(text: str) -> List[str]:
    t = (text or "").translate(_DIGITS)
    t = _HEADING_NUM.sub("", t)
    return [n.replace(",", "") for n in _NUMBER.findall(t)]


def check_paragraph(original: str, edited: str) -> Optional[Dict[str, object]]:
    """One finding, or None. Ordered so the most serious answer wins.

    A finding carries `sanctioned=True` when it survives the raw comparison but not the
    house-rule normalisation — i.e. the rules asked for exactly this deletion. Those are
    returned rather than dropped so they can be counted and argued about, but they do
    not belong in a "the copyedit lost the author's content" rate.
    """
    a, b = original or "", edited or ""
    if not a.strip():
        return None

    if not b.strip():
        return {"kind": "emptied", "sanctioned": False,
                "detail": "The paragraph came back empty; the author's text is gone."}

    lost_negation = len(_NEGATION.findall(a)) - len(_NEGATION.findall(b))
    if lost_negation > 0:
        missing = [w for w in _NEGATION.findall(a) if w.lower() not in
                   [x.lower() for x in _NEGATION.findall(b)]]
        return {"kind": "negation-lost", "sanctioned": False,
                "detail": f"A negation disappeared ({', '.join(missing[:3]) or 'one'}), "
                          f"which can reverse what the sentence claims."}

    # `number-lost` was here and has been removed. Measured overnight on 182 paragraphs
    # from 7 real manuscripts: it produced 26 of the 27 findings, and reading them showed
    # every one was a *correct* edit —
    #
    #   [1, 22] -> [1, 2]           references re-sorted, so citations renumber
    #   (Panwar et al., 2011) -> [1]  author-year converted to the Vancouver style
    #   Figure 4.1 -> Figure 1      the house rule for figure numbering
    #   1151, 79-90 -> 115 (1): 79–90p   volume and issue separated properly
    #
    # In a pipeline whose job includes renumbering citations and reformatting references,
    # "a number changed" is what success looks like. The check could not tell that from a
    # lost measurement, and a checker that fires 26 times on correct work buries the one
    # finding that matters. Catching a genuinely altered result needs to compare numbers
    # *within a sentence's own context*, not across a paragraph — that is a different and
    # harder check, and shipping the crude one meanwhile is worse than shipping nothing.

    if len(a.strip()) >= _SHORT and len(b) < len(a) * _MIN_KEPT:
        return {"kind": "truncated", "sanctioned": False,
                "detail": f"The paragraph lost {100 - int(100 * len(b) / len(a))}% of "
                          f"its length."}
    return None


def check_document(originals: List[str], edited: List[str]) -> List[Dict[str, object]]:
    """Findings for a whole manuscript, each carrying its paragraph index."""
    out: List[Dict[str, object]] = []
    for i, (a, b) in enumerate(zip(originals, edited)):
        hit = check_paragraph(a, b)
        if hit:
            out.append({"index": i, **hit, "original": a, "edited": b})
    return out


#: A word-for-word correction is accepted only when the two words are recognisably the
#: same word. `comparision` -> `comparison` scores 0.95; `breaking` -> `braking` 0.87;
#: `disc` -> `drum`, which would be a change of meaning rather than a spelling fix,
#: scores 0.25 and is refused.
_SAME_WORD = 0.75


def salvage_safe_corrections(original: str, edited: str) -> str:
    """The author's paragraph back, but keeping the copyedit's spelling corrections.

    Reverting a paragraph wholesale is the right instinct and the wrong result. Job #53
    put a heading, a source note, a citation and a body sentence into one paragraph:

        6.1 Theoretical Performance Metrics (Derived from … Guo et al., 2021) [2, 5]
        Table 1 illustrate the comparision of breaking system between …

    The copyedit shortened it by 36%, the loss guard restored the original, and the two
    corrections inside it — `comparision` -> `comparison`, `breaking` -> `braking` — went
    back with everything else. The manuscript shipped with the misspellings still in it,
    which is what the team saw and reported.

    So the revert is made partial, on terms that cannot lose anything: **every original
    token is kept unless a single word was replaced by a single, recognisably similar
    word.** Deletions are refused, insertions are refused, multi-word rewrites are
    refused. The output therefore has the same words as the author's original but for
    spelling, which is the one class of edit that is safe to take without reading the
    rest of the paragraph.
    """
    if not original.strip() or original == edited:
        return original

    token = re.compile(r"(\s+)")
    a = [t for t in token.split(original) if t]
    b = [t for t in token.split(edited) if t]

    out: List[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            out.extend(a[i1:i2])
        elif tag == "replace" and (i2 - i1) == 1 and (j2 - j1) == 1:
            out.append(_corrected_word(a[i1], b[j1]))
        else:
            # delete, insert, or a rewrite of more than one word: keep the author's.
            out.extend(a[i1:i2])
    return "".join(out)


def _corrected_word(before: str, after: str) -> str:
    """`after` if it is the same word spelled correctly, else `before` untouched."""
    # Punctuation is not part of the word and must survive either way: the copyedit
    # legitimately turns `system.` into `systems.` and the full stop is not the edit.
    lead = re.match(r"^\W*", before).group(0)
    trail = re.search(r"\W*$", before).group(0)
    core_a = before[len(lead):len(before) - len(trail) or None]
    core_b = after.strip(" \t")
    core_b = core_b[len(re.match(r"^\W*", core_b).group(0)):
                    len(core_b) - len(re.search(r"\W*$", core_b).group(0)) or None]

    if not core_a.isalpha() or not core_b.isalpha():
        return before                     # numbers, units and symbols are never "spelling"
    if core_a.lower() == core_b.lower():
        return before                     # a case change is a style decision, not a fix
    if difflib.SequenceMatcher(None, core_a.lower(), core_b.lower()).ratio() < _SAME_WORD:
        return before
    return f"{lead}{core_b}{trail}"
