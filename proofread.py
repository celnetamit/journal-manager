"""The proofreading pass — what is left after the copyedit.

The copyedit prompt opens with *"EDIT CONSERVATIVELY — this is the most important rule"*
and then, four lines earlier, asks the same model to "proofread them strictly". Those two
instructions pull against each other, and one pass told to do both does neither
thoroughly. This is the second pass, with a different job: not to improve the writing —
that was the last pass's business, and it was right to be careful — but to find what is
still *wrong*.

**Mechanical checks run first, and without a model.** A double space is a double space;
asking an LLM costs money, takes seconds, and can be talked out of it. Everything in
`mechanical_findings` is deterministic, exact about where it is, and testable — so it is
the same answer every run, which is the property a proofreader is judged on.

**Nothing here rewrites the manuscript.** A proofreader marks; the editor decides. Each
finding carries the paragraph index, the offending fragment and a concrete `suggestion`
where one can be given, and joins the queries the redline already shows. The alternative —
silently applying a hundred "fixes" — is how a wrong correction reaches print with nobody
having read it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

#: Pairs whose two spellings should not both appear in one manuscript. Neither is
#: wrong; using both is. The house style decides which — this only reports the clash,
#: because a checker that "corrects" -ise to -ize silently re-spells a British author.
SPELLING_PAIRS = [
    ("analyse", "analyze"), ("behaviour", "behavior"), ("catalogue", "catalog"),
    ("centre", "center"), ("colour", "color"), ("characterise", "characterize"),
    ("fibre", "fiber"), ("labelled", "labeled"), ("licence", "license"),
    ("modelling", "modeling"), ("organisation", "organization"),
    ("optimise", "optimize"), ("programme", "program"), ("sulphur", "sulfur"),
    ("utilise", "utilize"),
]

#: Ways the same object gets named in one paper. Mixing them inside a manuscript is a
#: house-style failure rather than an error of fact.
LABEL_VARIANTS = [
    ("Fig.", r"\bFig\.\s*\d"), ("Figure", r"\bFigure\s*\d"),
]

#: Units that take a space between the number and the unit. Excludes % and ° on
#: purpose: both are conventionally set closed up, and flagging them would bury the
#: real findings under hundreds of false ones.
SPACED_UNITS = (
    "kg", "g", "mg", "µg", "ng", "km", "cm", "mm", "nm", "µm", "m", "L", "mL", "µL",
    "mol", "mmol", "µmol", "M", "mM", "µM", "nM", "Hz", "kHz", "MHz", "GHz",
    "Pa", "kPa", "MPa", "GPa", "bar", "psi", "V", "mV", "kV", "A", "mA", "W", "kW",
    "J", "kJ", "min", "h", "s", "ms", "rpm",
)


@dataclass
class ProofFinding:
    rule: str
    severity: str                  # "error" | "warning" | "info"
    paragraph: Optional[int]
    message: str
    fragment: str = ""
    suggestion: Optional[str] = None

    def as_query(self) -> Dict[str, Any]:
        """The shape `generate_redline_docx` and `generate_report` already accept.

        The key is `index`, not `local_index`. `ai_edit_chunk` emits `local_index`
        because it only knows where a paragraph sits inside its own chunk, and
        `process_document_async` translates it. These findings already carry the
        real paragraph number, so they use the translated name — sending
        `local_index` would produce a query object that both consumers silently skip
        (`q.get("index")` is None), and the comment would simply never appear in the
        redline with nothing anywhere saying why.

        A document-wide finding has no paragraph to sit on, so `index` is None and
        it is reported in the editorial report rather than anchored in the file.
        """
        return {
            "index": self.paragraph,
            "snippet": self.fragment,
            "query": self.message,
            "suggestion": self.suggestion,
        }


#: Things that legitimately contain punctuation with no space after it, and would
#: otherwise dominate the report. On the Guanidine paper five of the ten findings were
#: DOIs and on the Nigerian one six of thirty were email addresses — all correct text,
#: all reported as errors, and enough of the list to make an editor stop reading it.
_OPAQUE = re.compile(
    r"""(
        https?://\S+                       # URLs
      | www\.[^\s,;)]+                     # bare www hosts
      | \b[\w.+-]+@[\w-]+\.[\w.-]+          # email addresses
      | \bdoi\s*:\s*10\.\d{4,9}/\S+         # doi:10.xxxx/...
      | \b10\.\d{4,9}/\S+                   # bare DOIs
      | \b(?:ISSN|ISBN|eISSN|pISSN)\s*:?\s*[\dXx-]{8,}   # identifiers
      | \b[\w-]+\.(?:com|org|net|edu|gov|in|ng|io)\b     # bare hostnames
    )""",
    re.I | re.X,
)


def _mask_opaque(text: str) -> str:
    """Replace URLs, emails, DOIs and identifiers with same-length filler.

    Same length on purpose: every finding carries a character offset into the
    paragraph, and a mask that changed the length would report the right problem at
    the wrong place — which is worse than not reporting it, because the editor looks
    where they are sent and finds nothing wrong.
    """
    # Filled with a word character rather than spaces: spaces would create new
    # "space before a full stop" findings at the edges of every masked URL,
    # trading one class of false positive for another.
    return _OPAQUE.sub(lambda m: "x" * len(m.group(0)), text)


def _is_reference_block(text: str) -> bool:
    """References are formatted by their own rules and would drown the report.

    A bibliography entry legitimately contains "1." at the start, initials with no
    space after the full stop, and page ranges with a hyphen. Running the general
    punctuation checks over them produces hundreds of findings that are all correct
    behaviour, and a report nobody finishes reading is a report that missed the two
    that mattered.
    """
    t = text.strip()
    if len(t) < 25:
        return False
    return bool(
        re.match(r"^\[?\d{1,3}[\].]\s", t)
        and re.search(r"\b(19|20)\d{2}\b", t)
    ) or bool(re.search(r"\bdoi\s*[:.]\s*(?:org/)?10\.\d{4}", t, re.I))


def mechanical_findings(paragraphs: List[str]) -> List[ProofFinding]:
    """Everything that can be decided by looking, without a model."""
    out: List[ProofFinding] = []
    joined = " ".join(paragraphs)

    for i, text in enumerate(paragraphs):
        if not text.strip():
            continue
        is_ref = _is_reference_block(text)
        # Checked against the masked copy; quoted back from the real one, which the
        # equal-length mask keeps in step.
        scan = _mask_opaque(text)

        for m in re.finditer(r"\S(  +)\S", scan):
            out.append(ProofFinding(
                "space.double", "warning", i,
                "two or more spaces between words",
                text[max(0, m.start() - 22):m.end() + 22].strip(),
                re.sub(r"  +", " ", m.group(0))))

        if not is_ref:
            for m in re.finditer(r"\s+([,.;:!?])", scan):
                out.append(ProofFinding(
                    "space.before-punctuation", "error", i,
                    f"space before {m.group(1)!r}",
                    text[max(0, m.start() - 22):m.end() + 22].strip(),
                    m.group(1)))

            # A full stop with no space after it, where what follows is a word
            # rather than a decimal or an initial.
            for m in re.finditer(r"(?<![A-Z])([.,;:])([A-Za-z]{2,})", scan):
                frag = text[max(0, m.start() - 22):m.end() + 22].strip()
                out.append(ProofFinding(
                    "space.after-punctuation", "error", i,
                    f"no space after {m.group(1)!r}", frag,
                    f"{m.group(1)} {m.group(2)}"))

        for open_c, close_c, name in (("(", ")", "parenthesis"),
                                      ("[", "]", "bracket")):
            if text.count(open_c) != text.count(close_c):
                out.append(ProofFinding(
                    "punctuation.unbalanced", "error", i,
                    f"unbalanced {name}: {text.count(open_c)} {open_c} "
                    f"and {text.count(close_c)} {close_c}",
                    text[:80]))

        if text.count("“") != text.count("”"):
            out.append(ProofFinding(
                "punctuation.unbalanced-quotes", "warning", i,
                "unbalanced curly quotes", text[:80]))

        if not is_ref:
            # A number range set with a hyphen where an en dash belongs. Restricted
            # to plain digit-hyphen-digit so it does not fire on every chemical name
            # or hyphenated compound in the paper.
            for m in re.finditer(r"(?<![\w-])(\d+)\s*-\s*(\d+)(?![\w-])", scan):
                lo, hi = m.group(1), m.group(2)
                # A real range ascends. `2583-8903` is an ISSN and `2019-2024`
                # written as years is a range, but `250-258` reversed is a typo,
                # not a dash problem — and a four-plus-four pair is an identifier
                # far more often than it is a range.
                if int(lo) >= int(hi) or (len(lo) >= 4 and len(hi) >= 4):
                    continue
                out.append(ProofFinding(
                    "dash.range", "info", i,
                    "number range uses a hyphen; an en dash (–) is conventional",
                    text[max(0, m.start() - 18):m.end() + 18].strip(),
                    f"{m.group(1)}–{m.group(2)}"))

            units = "|".join(sorted(SPACED_UNITS, key=len, reverse=True))
            for m in re.finditer(rf"(?<![\w.])(\d+(?:\.\d+)?)({units})\b", scan):
                out.append(ProofFinding(
                    "unit.spacing", "info", i,
                    f"no space between the number and {m.group(2)!r}",
                    text[max(0, m.start() - 18):m.end() + 18].strip(),
                    f"{m.group(1)} {m.group(2)}"))

        if re.search(r"\bthe\s+the\b|\bof\s+of\b|\band\s+and\b|\bis\s+is\b|\bin\s+in\b",
                     text, re.I):
            m = re.search(r"\b(\w+)\s+\1\b", text, re.I)
            if m:
                out.append(ProofFinding(
                    "word.doubled", "error", i,
                    f"repeated word {m.group(1)!r}",
                    text[max(0, m.start() - 24):m.end() + 24].strip(),
                    m.group(1)))

    out.extend(_consistency_findings(paragraphs, joined))
    return out


def _consistency_findings(paragraphs: List[str], joined: str) -> List[ProofFinding]:
    """Clashes that only exist across the whole manuscript, not in one paragraph."""
    out: List[ProofFinding] = []
    low = joined.lower()

    for british, american in SPELLING_PAIRS:
        b = len(re.findall(rf"\b{british}\w*", low))
        a = len(re.findall(rf"\b{american}\w*", low))
        if b and a:
            keep, drop = (british, american) if b >= a else (american, british)
            out.append(ProofFinding(
                "consistency.spelling", "warning", None,
                f"both {british!r} ({b}x) and {american!r} ({a}x) appear — "
                f"pick one for the whole manuscript",
                suggestion=f"the manuscript mostly uses {keep!r}; "
                           f"change the {drop!r} occurrences to match"))

    counts = {label: len(re.findall(pattern, joined))
              for label, pattern in LABEL_VARIANTS}
    if all(counts.values()):
        keep = max(counts, key=lambda k: counts[k])
        out.append(ProofFinding(
            "consistency.figure-label", "warning", None,
            "figures are called both " + " and ".join(
                f"{k!r} ({v}x)" for k, v in counts.items()),
            suggestion=f"use {keep!r} throughout"))

    out.extend(_cross_reference_findings(paragraphs, joined))
    return out


def _cross_reference_findings(paragraphs: List[str], joined: str) -> List[ProofFinding]:
    """A figure or table referred to in the text but never captioned, or the reverse.

    The captions are found by looking for a paragraph that *starts* with the label,
    which is how a caption is written and how a mention is not.
    """
    out: List[ProofFinding] = []

    for label in ("Figure", "Table"):
        captioned = set()
        caption_at = set()
        for i, text in enumerate(paragraphs):
            m = re.match(rf"(?i)^\s*(?:{label}|{label[:3]}\.)\s*(\d+)", text.strip())
            if m:
                captioned.add(m.group(1))
                caption_at.add(i)

        # Mentions are counted everywhere EXCEPT the captions. A caption reads
        # "Figure 2. Apparatus used", which matches the mention pattern too — so
        # counting it makes every figure its own citation and "captioned but never
        # cited" becomes a check that can never fire. It reported nothing on all
        # three real manuscripts and looked like a clean result.
        elsewhere = " ".join(t for i, t in enumerate(paragraphs) if i not in caption_at)
        mentioned = set(re.findall(rf"(?i)\b(?:{label}|{label[:3]}\.)\s*(\d+)",
                                   elsewhere))
        for n in sorted(mentioned - captioned, key=lambda x: int(x)):
            out.append(ProofFinding(
                f"crossref.{label.lower()}-missing", "error", None,
                f"the text refers to {label} {n}, which has no caption in the manuscript"))
        for n in sorted(captioned - mentioned, key=lambda x: int(x)):
            out.append(ProofFinding(
                f"crossref.{label.lower()}-uncited", "warning", None,
                f"{label} {n} is captioned but never referred to in the text"))
    return out


# --------------------------------------------------------------------- LLM pass

PROOFREAD_PROMPT = """You are a proofreader reading the FINAL, already-copyedited text of a scientific manuscript.

A copyeditor has been over this already and was told to change as little as possible. Your job is different and narrower: find what is still WRONG. You are the last person to read it before it is typeset.

Report ONLY:
- spelling errors, including a wrong word that is spelled correctly ("effect" for "affect", "principle" for "principal")
- grammar and agreement errors that survived
- punctuation that changes or obscures the meaning
- a term, abbreviation or symbol used inconsistently (defined as one thing, later used as another)
- a number, unit or statistic that contradicts another statement in the same text
- an abbreviation used before it is defined

Do NOT report:
- style, tone, flow, word choice, sentence length or anything you would merely prefer
- anything already correct
- formatting, fonts or layout — those are checked elsewhere

You are NOT rewriting the manuscript. For each problem, name it and give the exact corrected fragment. If you are not confident it is an error, leave it out entirely: a proofreader who reports doubts is worse than one who misses one, because the editor stops trusting the list.

Return ONLY a JSON array. Each element:
  {"index": <int, the paragraph number given below>,
   "fragment": "<the exact wrong text, copied verbatim>",
   "problem": "<what is wrong, in one clause>",
   "correction": "<the exact replacement text, or null if it needs the author>"}

Return [] if you find nothing. Do not invent problems to fill the array.

Paragraphs:
{payload}
"""


def llm_findings(paragraphs: List[str], generate, settings: Dict[str, Any],
                 batch_size: int = 25) -> List[ProofFinding]:
    """The judgement half of the pass. `generate(prompt, settings, ...)` is injected
    so this is testable without a network — the same reason the mechanical half comes
    first and stands alone."""
    import json

    out: List[ProofFinding] = []
    numbered: List[Tuple[int, str]] = [
        (i, t) for i, t in enumerate(paragraphs)
        if len(t.strip()) > 40 and not _is_reference_block(t)
    ]

    for start in range(0, len(numbered), batch_size):
        batch = numbered[start:start + batch_size]
        payload = json.dumps([{"index": i, "text": t} for i, t in batch],
                             ensure_ascii=False)
        try:
            raw = generate(PROOFREAD_PROMPT.replace("{payload}", payload),
                           settings=settings, response_mime_type="application/json")
            match = re.search(r"\[.*\]", raw or "", re.DOTALL)
            items = json.loads(match.group(0)) if match else []
        except Exception:                                        # noqa: BLE001
            # One bad batch must not lose the mechanical findings or the other
            # batches. A proofread that returns most of the report beats one that
            # returns none of it.
            continue

        known = {i for i, _ in batch}
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            idx = it.get("index")
            # An index outside the batch means the model invented a location; the
            # finding cannot be shown against a paragraph, so it is dropped rather
            # than attached to the wrong one.
            if idx not in known:
                continue
            problem = (it.get("problem") or "").strip()
            fragment = (it.get("fragment") or "").strip()
            if not problem:
                continue
            # The fragment has to actually be in the paragraph. Without this a
            # paraphrase reaches the editor as a verbatim quotation of their author.
            if fragment and fragment not in paragraphs[idx]:
                continue
            correction = it.get("correction")
            out.append(ProofFinding(
                "proofread.llm", "warning", idx, problem, fragment,
                correction.strip() if isinstance(correction, str) and correction.strip()
                else None))
    return out


def proofread(paragraphs: List[str], generate=None,
              settings: Optional[Dict[str, Any]] = None,
              use_llm: bool = True) -> List[ProofFinding]:
    """Mechanical findings always; the model pass when one is available."""
    findings = mechanical_findings(paragraphs)
    if use_llm and generate is not None:
        findings += llm_findings(paragraphs, generate, settings or {})
    return findings


def summarise(findings: List[ProofFinding]) -> Dict[str, Any]:
    by_rule: Dict[str, int] = {}
    by_sev: Dict[str, int] = {}
    for f in findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    return {"total": len(findings), "by_severity": by_sev, "by_rule": by_rule}
