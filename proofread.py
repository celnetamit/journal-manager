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

#: What the proofreader assumes when the job does not say. The copyedit has always
#: been told the variant; the proofreading prompt never was, so on a British paper it
#: reported "centre" as a spelling error and proposed "center" — silently re-spelling
#: an author, which is the one thing this module's own docstring says not to do.
DEFAULT_LANG = "US English"


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
    # `[1]. Bennett M. D.` — a bracketed number *and* a full stop. The original
    # `[\].]` matched one or the other and then demanded whitespace, so every entry
    # in a `[n].` bibliography fell through to the general checks.
    if bool(
        re.match(r"^\[?\d{1,3}[\].]{1,2}\s", t)
        and re.search(r"\b(19|20)\d{2}\b", t)
    ) or bool(re.search(r"\bdoi\s*[:.]\s*(?:org/)?10\.\d{4}", t, re.I)):
        return True

    # An author-year entry — `Correia J. Environ Geol 35(1): 55-65` — carries no
    # leading number and often no DOI, so the tests above missed all of them and the
    # general checks ran over the whole bibliography: page ranges alone accounted for
    # a third of `dash.range` across the corpus. A volume(issue) followed by a page
    # range, or an explicit `pp.`, is citation notation and appears in body prose
    # essentially never, so it can carry the decision on its own.
    if len(t) > 400:
        return False                     # a long paragraph is prose, not an entry
    return bool(
        # `35(1): 55-65`, and also `7(1).3-11` — some houses separate the issue from
        # the page range with a full stop, which `[:,]?` alone rejected.
        re.search(r"\b\d{1,4}\s*\(\s*\d{1,4}[a-z]?\s*\)\s*[:.,]?\s*\d{1,5}\s*[-–—]\s*\d{1,5}", t)
        or re.search(r"\bpp?\.?\s*\d{1,5}\s*[-–—]\s*\d{1,5}", t)
        # Vancouver with no parenthesised issue at all — `Handb Clin Neurol. 2018;
        # 147:93-102`. The `year;volume:pages` run is citation notation; prose does
        # not put a semicolon between a year and a colon-led page range.
        or re.search(r"\b(?:19|20)\d{2}\s*;\s*\d{1,4}\s*"
                     r"(?:\(\s*[\w\s./-]{1,15}\s*\))?\s*[:.,]\s*\d{1,5}\s*[-–—]\s*\d{1,5}", t)
    )


def _is_not_a_measurement(text: str, m: "re.Match") -> bool:
    """True when a digit-then-unit match is a name, not a quantity.

    The unit list has to contain the single letters — `5 V`, `8 M`, `100 W` are all
    real — and those are also how equipment models, material grades and space groups
    are written. Over 400 manuscripts the wrong ones all fell into two shapes:

    * a decade: `the 1970s and 1980s` read as 1970 seconds;
    * a designation hung off a hyphen: `HuanJing-1A`, space group `Fm-3m`.

    Narrowed to those two rather than dropping the single-letter units, which would
    stop the check finding `12V DC` and `8Hz` — the cases it exists for.
    """
    number, unit = m.group(1), m.group(2)
    if unit == "s" and re.fullmatch(r"(1[5-9]|20)\d{2}", number):
        return True                      # 1800s, 1970s — a decade, not seconds
    before = text[:m.start()]
    return bool(re.search(r"[A-Za-z]-$", before))     # -1A, Fm-3m


#: A list label — a short token then `)`, with nothing but the start of the text or a
#: separator in front of it. Manuscripts number their lists `a)`, `1)`, `iii)`, `A)`,
#: and that closing parenthesis has no opening one by design.
#: `5.2)` and `10.10.2.)` are section numbers, `ⅰ)` is the Unicode roman numeral rather
#: than a latin `i` — all three are labels the plain `\d{1,2}` shape did not cover.
_LIST_LABEL = re.compile(
    r"(?:(?<=^)|(?<=[\s;,\t]))"
    r"(?:\d{1,3}(?:\.\d{1,3})*\.?|[A-Za-z]|[ivxlcIVXLC]{1,4}|[Ⅰ-ⅿ]{1,4})\)$")


def _unbalanced(text: str, open_c: str, close_c: str) -> Optional[tuple]:
    """(unmatched opens, unmatched closes), or None when the text is balanced.

    Counting `text.count("(") != text.count(")")` was 1,546 findings over the corpus
    and more than half of them were numbered lists: "A) Interleukin 1 beta; B)
    Interleukin 6; C) CD33" was reported as "0 ( and 5 )". An editor told five times
    that their list is broken stops reading the report.

    Stripping label-shaped `)` before counting is the obvious fix and it is wrong —
    the ` 1)` inside `(Figure 1)` matches the same shape, so it would break a properly
    balanced pair and invent a fault. So the text is walked instead, and a `)` is only
    forgiven as a label when nothing is open for it to close.
    """
    depth = 0
    stray_closes = 0
    for i, ch in enumerate(text):
        if ch == open_c:
            depth += 1
        elif ch == close_c:
            if depth:
                depth -= 1
            elif close_c == ")" and _LIST_LABEL.search(text[:i + 1]):
                continue                 # `a)`, `1)`, `iii)` — a label, not a pair
            else:
                stray_closes += 1
    return (depth, stray_closes) if depth or stray_closes else None


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
                # Sliced out of `text`, never quoted from `scan`. The mask is
                # equal-length precisely so offsets stay usable, but the characters
                # under it are filler — quoting them puts a run of `xxxxxxxx` in
                # front of the editor as the suggested correction.
                re.sub(r"  +", " ", text[m.start():m.end()])))

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
                # `.` immediately before a masked URL or address matches here, and
                # the word after the stop is then filler. Read the real characters
                # back out of `text` at the same offsets — an email list otherwise
                # suggested `, xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.
                word = text[m.start(2):m.end(2)]
                out.append(ProofFinding(
                    "space.after-punctuation", "error", i,
                    f"no space after {m.group(1)!r}", frag,
                    f"{m.group(1)} {word}"))

        for open_c, close_c, name in (("(", ")", "parenthesis"),
                                      ("[", "]", "bracket")):
            counts = _unbalanced(text, open_c, close_c)
            if counts is not None:
                opens, closes = counts
                # Say which way it is unbalanced. "3 ( and 4 )" made the editor count
                # the characters again to find out whether one was missing or one was
                # spare; the pair that never closed is the thing to go and look at.
                parts = []
                if opens:
                    parts.append(f"{opens} {open_c} never closed")
                if closes:
                    parts.append(f"{closes} {close_c} with nothing open")
                out.append(ProofFinding(
                    "punctuation.unbalanced", "error", i,
                    f"unbalanced {name}: " + ", ".join(parts),
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
                # A phone number, not a range: `Tel: +91-8816867362` ascends and its
                # first half is only two digits, so both guards above wave it through
                # and the report suggests dialling `91–8816867362`. Two signals, either
                # alone enough — a leading `+`, or halves of wildly unequal length.
                if scan[:m.start()].rstrip().endswith("+") or len(hi) - len(lo) >= 3:
                    continue
                out.append(ProofFinding(
                    "dash.range", "info", i,
                    "number range uses a hyphen; an en dash (–) is conventional",
                    text[max(0, m.start() - 18):m.end() + 18].strip(),
                    f"{m.group(1)}–{m.group(2)}"))

            units = "|".join(sorted(SPACED_UNITS, key=len, reverse=True))
            for m in re.finditer(rf"(?<![\w.])(\d+(?:\.\d+)?)({units})\b", scan):
                if _is_not_a_measurement(scan, m):
                    continue
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


#: How far apart the ends of a written range may be before it stops being one. "Figures
#: 2–4" is three figures; "Figure 1-2019" is a year that happens to follow a dash, and
#: expanding it would invent two thousand citations.
_MAX_RANGE = 20


def _mentioned_numbers(label: str, text: str) -> set:
    """Every figure or table number the text refers to, enumerations included.

    A single-number pattern reads "Figures 8 and 9" as a reference to figure 8 alone,
    so figure 9 was reported as captioned but never cited — 8% of these findings across
    a 150-manuscript sample, and every one of them wrong. Ranges (`Table 3-5`) and lists
    (`Figures 5, 6`) are how authors actually write this.

    Continuation numbers are held to two digits: `Figure 1, 2000 samples` must read as
    figure 1, not as figures 1 and 2000.
    """
    out = set()
    # Two digits, and a word boundary after them: "Cancer Facts & Figures 2020" is a
    # reference title, and `\d+` read it as a citation of figure 2020. No manuscript
    # in a 1,597-paper corpus has a hundred figures.
    head = rf"(?i)\b(?:{label}s?|{label[:3]}s?\.)\s*(\d{{1,2}})\b"
    for m in re.finditer(head, text):
        out.add(m.group(1))
        rest = text[m.end():]
        previous = int(m.group(1))
        # Walk the enumeration one link at a time, so it stops at the first thing that
        # is not another number — "Figure 1 and Table 2" ends after figure 1.
        while True:
            link = re.match(r"\s*(,|and|&|to|through|[-–—])\s*(\d{1,2})\b", rest, re.I)
            if not link:
                break
            n = int(link.group(2))
            # An enumeration stays near its neighbours. "Figures 1, 5 and 9" is a real
            # list; "Figure 5, 60% of samples" is a figure followed by a percentage, and
            # without this it read as a reference to figure 60.
            if abs(n - previous) > _MAX_RANGE:
                break
            if link.group(1) in ("-", "–", "—", "to", "through") and previous < n:
                out.update(str(k) for k in range(previous, n + 1))
            else:
                out.add(str(n))
            previous = n
            rest = rest[link.end():]
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
        # Reference entries are excluded alongside the captions. A bibliography is full
        # of titles like "Cancer Facts & Figures 2020" and volume numbers that read as
        # citations of a figure nobody wrote — and a reference list never cites a figure.
        elsewhere = " ".join(t for i, t in enumerate(paragraphs)
                             if i not in caption_at and not _is_reference_block(t))
        mentioned = _mentioned_numbers(label, elsewhere)
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

The manuscript is written in {lang_type}. Spellings belonging to that variant are CORRECT: do not report "centre", "behaviour", "analyse" or "programme" in British English, or "center", "behavior", "analyze" or "program" in American English. Do not report a British/American variant as inconsistent either — whether the manuscript mixes the two is checked separately, over the whole text. You are shown a slice of the manuscript, so you cannot know what the rest of it does: never claim that "the manuscript uses both" anything.

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
- curly quotation marks and apostrophes (’ “ ”). They are correct and the file is going to be typeset; replacing them with ASCII ' and " is damage, not a correction

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
                 batch_size: int = 25,
                 lang_type: str = DEFAULT_LANG) -> List[ProofFinding]:
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
            prompt = (PROOFREAD_PROMPT
                      .replace("{lang_type}", lang_type or DEFAULT_LANG)
                      .replace("{payload}", payload))
            raw = generate(prompt,
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


#: Rules where the same fault recurs mechanically through a manuscript and every
#: occurrence reads identically. Anchoring all of them buries the findings that are
#: about the writing. Rules that fire rarely, or whose message differs each time
#: (`word.doubled`, `punctuation.unbalanced`, the consistency and cross-reference
#: checks), are left alone — they are not the volume problem.
_REPEATING = {
    "space.double", "space.before-punctuation", "space.after-punctuation",
    "dash.range", "unit.spacing",
    # Its message is the constant string "unbalanced curly quotes" — it never
    # differs, so the exemption above was never true of it. One manuscript in the
    # corpus anchored 78 Word comments and 77 were this rule, which is a document
    # that mixes " and ” throughout: one note, not seventy-seven.
    "punctuation.unbalanced-quotes",
}

#: How many of a repeating rule keep their own anchor. Enough to show the editor the
#: shape of the problem and three places to look; the rest are counted, not pinned.
ANCHOR_LIMIT = 3


def collapse_repeats(findings: List[ProofFinding]) -> List[ProofFinding]:
    """Cap each repeating rule's anchored findings, and count the remainder.

    `house_layout.check_all` has ended in its own `collapse_repeats` for a while;
    the proofreading half never had one, and every mechanical finding with a
    paragraph becomes a Word comment. Over 397 real manuscripts that came to 33
    findings each — `space.double` alone averaged 10.9 — so the copyeditor's actual
    queries sat behind a dozen identical notes about spacing.

    Nothing is dropped. What loses its anchor is replaced by one document-level
    finding naming the total, which the editorial report prints; an editor fixing
    whitespace does it with one find-and-replace, not by visiting 30 comments.
    """
    out: List[ProofFinding] = []
    seen: Dict[str, int] = {}
    extra: Dict[str, ProofFinding] = {}

    for f in findings:
        if f.rule not in _REPEATING or f.paragraph is None:
            out.append(f)
            continue
        n = seen[f.rule] = seen.get(f.rule, 0) + 1
        if n <= ANCHOR_LIMIT:
            out.append(f)
        else:
            extra.setdefault(f.rule, f)

    for rule, first in extra.items():
        hidden = seen[rule] - ANCHOR_LIMIT
        out.append(ProofFinding(
            rule, first.severity, None,
            f"{hidden} further occurrence(s) of this beyond the {ANCHOR_LIMIT} marked "
            f"in the text: {first.message}",
            first.fragment))
    return out


def proofread(paragraphs: List[str], generate=None,
              settings: Optional[Dict[str, Any]] = None,
              use_llm: bool = True,
              lang_type: str = DEFAULT_LANG) -> List[ProofFinding]:
    """Mechanical findings always; the model pass when one is available.

    Collapsed here rather than inside `mechanical_findings`, which stays the raw,
    exactly-testable primitive — the same split `house_layout` makes between its
    individual checks and `check_all`.
    """
    findings = collapse_repeats(mechanical_findings(paragraphs))
    if use_llm and generate is not None:
        findings += llm_findings(paragraphs, generate, settings or {},
                                 lang_type=lang_type)
    return findings


def summarise(findings: List[ProofFinding]) -> Dict[str, Any]:
    by_rule: Dict[str, int] = {}
    by_sev: Dict[str, int] = {}
    for f in findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    return {"total": len(findings), "by_severity": by_sev, "by_rule": by_rule}
