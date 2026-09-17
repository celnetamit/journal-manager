"""One short page for the author: what is missing, and what a reviewer would say.

Amit, 17 Sep 2026: *"kya hum ek authors report bhi bana sakte hai, jisme missing
elements and short me technical review bhi mil jaye author ke liye?"*

The author already gets a redline carrying only their own queries. What they do not get
is the thing they most need before they resubmit: a page that says **what is not in the
manuscript at all**. A tracked change can only be made where there is text; a missing
Table 6 leaves nothing to track, so the one defect an author can actually fix on their
own is the one nothing has been telling them about.

Three parts, in the order an author will use them:

1. **What is missing** — entirely from checks that read the file, never from a model.
   The Abstract, the Keywords, a table or figure the text sends a reader to, a work
   cited with no reference. Each one names the thing and says nothing else.
2. **What the reviewer says** — the peer review that is already produced, cut to the
   parts addressed to the author: what the paper is, what is wrong, what is minor, and
   the recommendation. The referee framing and the reviewer's confidence are the
   editor's business and stay out.
3. **What was changed** — one line pointing at the redline, because a report that does
   not say where the edits are sends the author looking for a second file.

**Short on purpose.** The quality team's own reason for the author's redline was that
the full one is too much to read. A five-page report would repeat that mistake in a new
file.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

#: Findings that mean *something is not here*, as opposed to something being formatted
#: the wrong way. Only these reach the author: a hanging indent is the production team's
#: job and an absent Abstract is the author's.
MISSING_RULES = {
    "front.abstract-missing": "The Abstract is missing.",
    "front.keywords-missing": "There is no Keywords line.",
    "table.cited-but-missing": None,      # the finding's own message is the sentence
    "figure.cited-but-missing": None,
    "table.caption": None,
}

#: The order an author will use them in: the parts of the paper first, then the works
#: they cite, then the artwork. Not the order the checks happen to run in.
ORDER = ("front.abstract-missing", "front.keywords-missing",
         "table.cited-but-missing", "figure.cited-but-missing", "table.caption")

#: One sentence instead of N identical ones.
COLLAPSE = {
    "table.caption": "{n} tables have no 'Table N' caption above them.",
}

#: Guards whose query is a gap in the manuscript rather than an edit to review.
MISSING_GUARDS = {
    "refuse_citations_without_a_reference",
    "verify_reference_block",
}

#: The review sections an author is meant to act on. `Confidence` and the referee's
#: self-assessment are for whoever decides the paper, not for the person revising it.
AUTHOR_SECTIONS = ("Summary", "Major Concerns", "Minor Issues", "Recommendation")

_HEADING = re.compile(r"^#{1,6}\s*(.+?)\s*$")


def _review_sections(markdown: str) -> Dict[str, str]:
    """The review split by its headings. Tolerant of a model that renames one."""
    sections: Dict[str, str] = {}
    current: Optional[str] = None
    lines: List[str] = []
    for line in (markdown or "").splitlines():
        m = _HEADING.match(line)
        if m:
            if current:
                sections[current] = "\n".join(lines).strip()
            current, lines = m.group(1).strip(), []
        elif current:
            lines.append(line)
    if current:
        sections[current] = "\n".join(lines).strip()
    return sections


def _matching_section(sections: Dict[str, str], wanted: str) -> str:
    for name, body in sections.items():
        if name.lower().strip() == wanted.lower():
            return body
    for name, body in sections.items():          # "Major Concerns / Weaknesses"
        if wanted.lower() in name.lower():
            return body
    return ""


def missing_elements(findings, queries) -> List[str]:
    """Every "this is not in the manuscript" we know of, as plain sentences.

    Deduplicated, because the same gap can be reported by a layout check and by a guard
    — and an author reading the same sentence twice concludes the report is padding.
    """
    by_rule: Dict[str, List[str]] = {}
    for finding in findings or []:
        rule = getattr(finding, "rule", "")
        if rule not in MISSING_RULES:
            continue
        sentence = MISSING_RULES[rule] or getattr(finding, "message", "")
        if sentence:
            by_rule.setdefault(rule, []).append(sentence[:1].upper() + sentence[1:])

    out: List[str] = []
    for rule in ORDER:
        sentences = by_rule.get(rule)
        if not sentences:
            continue
        # Collapsed where one fault repeats. A manuscript with six uncaptioned tables
        # produced six identical lines, which is how a nine-line list buries the one
        # line that says the Abstract is not there.
        if rule in COLLAPSE and len(sentences) > 1:
            out.append(COLLAPSE[rule].format(n=len(sentences)))
        else:
            out.extend(sentences)

    for query in queries or []:
        if query.get("guard") in MISSING_GUARDS:
            text = str(query.get("query") or "")
            # The first sentence is the finding; the rest is what was done about it.
            out.append(text.split(". ")[0].strip() + ".")

    seen: set = set()
    unique = []
    for sentence in out:
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(sentence)
    return unique


def build(
    filename: str,
    findings: Optional[List[Any]] = None,
    queries: Optional[List[Dict[str, Any]]] = None,
    ai_review_md: str = "",
    recommended_journal: str = "",
    subject: str = "",
) -> str:
    """The report, as the limited Markdown `markdown_to_docx` renders."""
    gaps = missing_elements(findings, queries)
    sections = _review_sections(ai_review_md)

    out = ["# Report for the Author", ""]
    out.append(f"**Manuscript:** {filename}")
    if subject:
        out.append("")
        out.append(f"**{subject}**")
    out.append("")

    out.append("## What is missing")
    out.append("")
    if gaps:
        out.append("These are things the manuscript does not contain. They cannot be "
                   "fixed by editing — only you can supply them.")
        out.append("")
        for sentence in gaps:
            out.append(f"- {sentence}")
    else:
        out.append("Nothing. Every section, table and figure the text refers to is "
                   "present, and every work cited has a reference.")
    out.append("")

    out.append("## Technical review")
    out.append("")
    wrote_any = False
    for name in AUTHOR_SECTIONS:
        body = _matching_section(sections, name)
        if not body:
            continue
        wrote_any = True
        out.append(f"**{name}**")
        out.append("")
        out.append(body)
        out.append("")
    if not wrote_any:
        out.append("_No review was produced for this manuscript._")
        out.append("")

    if recommended_journal:
        out.append(f"**Suggested journal:** {recommended_journal}")
        out.append("")

    out.append("## What was changed")
    out.append("")
    out.append("The copyediting is in your tracked-changes file, with every insertion "
               "highlighted. Each change is yours to accept or reject in Word — the "
               "final decision on your own manuscript is yours. Questions that only "
               "you can answer are comments beside the text, signed **Query to "
               "Author**; in Word they are listed together under Review → Comments.")
    out.append("")
    return "\n".join(out)
