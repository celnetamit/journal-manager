"""What a reference is missing, and what Crossref can fill in.

An incomplete reference is the defect an editor cannot fix from the manuscript — the
volume number is simply not on the page — so it is the one that most needs raising
early, while the author is still reachable. Until now the tool checked how references
were *formatted* (`references.size`, `.hanging-indent`, `.numbering`) and never once
looked at whether they were *complete*.

**Nothing here rewrites a reference.** A bibliography entry is the author's claim
about someone else's work; getting it wrong attaches the wrong DOI to the wrong paper
and that error propagates into Crossref, the citation graph and everyone who copies
it. So a missing field becomes a query, and where Crossref has the record with a
confident title match, the complete entry is offered as a *suggestion* the editor
accepts — the same shape the copyedit's own queries use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

#: Fields a Vancouver-style entry is expected to carry, and how to see one.
#: Deliberately loose: the goal is "is there a year at all", not "is the year in the
#: right place", which is what the formatting rules already cover.
_YEAR = re.compile(r"\b(1[89]|20)\d{2}\b")
#: A page range, an eLocator, or a modern article number. `Smart Materials and
#: Structures, 23(3), 033001` has no range at all — 033001 *is* the page.
#: Reading twenty flagged entries in full showed the page test was the single biggest
#: source of wrong findings. Three shapes it did not know:
#:   `Compos Sci Technol. 2001; 61: 1189–224p.` — the house's own `p.` suffix, where
#:      the trailing `\b` after the digits could never match;
#:   `Emerging infectious diseases, 5(5), 607.` — a single-page article, which is how
#:      most modern journals number, with no range at all;
#:   `Water 11, no. 7 (2019): 1387.` and `Minerals, 11(12), 1336.` — the same thing.
_PAGES = re.compile(
    r"(?:pp?\.?\s*)?[A-Za-z]?\d{1,5}\s*[-–—]\s*[A-Za-z]?\d{1,5}p?\b"   # 1189–224p, W597–W600
    r"|\be\d{4,7}\b"                                   # eLocator
    r"|\bpp?\.\s*\d"                                    # pp. 46
    r"|[,:;]\s*0?\d{1,7}\s*p?\s*\.?\s*$")               # `, 607.` `: 1387.` `, 033001`

#: A volume, in the four shapes the corpus actually uses. The first version demanded
#: `12(3)` or `vol. 12` and so reported "missing volume" on 1,307 references that
#: plainly had one: `Sensors and Actuators A: Physical, 1151, 79-90` is volume 115,
#: issue 1 with the parentheses lost in conversion, and `2019;12:45` is Vancouver.
#: The rule was wrong, not the manuscripts.
_VOLUME = re.compile(
    r"\b\d{1,4}\s*\(\s*\d{1,4}[a-z]?\s*\)"     # 12(3)
    r"|\bvol\.?\s*\d+"                            # vol. 12
    r"|;\s*\d{1,4}\s*[:(]"                         # 2019;12:45
    r"|,\s*\d{1,4}\s*,\s*(?:pp?\.\s*)?[A-Za-z]?\d"   # , 115, 79-90 / , 6, e03217
    r"|,\s*\d{1,4}\s*[,:]\s*0?\d{5,7}"           # Journal, 233, 033001
    r"|\b\d{1,4}\s*,?\s*no\.\s*\d"               # Water 11, no. 7
    r"|;\s*\d{1,4}\s*[,:]"                         # 2001; 61: 1189
    r"|,\s*\d{1,4}\s*:\s*\d"                       # Vet. World, 16:403–413
    r"|\bV\.\s*\d+\.?\s*N\s*\d"                  # Materials. 2015. V. 2. N 3.
    r"|\bno\.\s*\d+\s*[,:]",                       # no. 7: 1387
    re.I)
_DOI = re.compile(r"\b10\.\d{4,9}/\S+|doi\s*:", re.I)
_URL = re.compile(r"https?://|www\.", re.I)
#: An author, in any of the shapes real bibliographies use. The first version matched
#: only `Surname AB` and `Surname, A.`, so it reported "missing authors" on
#: `F. J. Dian`, on `Lihong Zheng, Xiangjian He` and on `T.V.N. Rao` — 997 findings
#: over the corpus, nearly all of them wrong.
_AUTHORS = re.compile(
    r"[^\W\d_][^\W\d_]+\s+[A-Z]{1,3}\b"        # Bennett MD, Rao YVH
    r"|[^\W\d_]{2,},\s*[A-Z]{1,3}\.?(?:\s|,|;|$)"   # Wang, R. / Rao, YVH
    r"|(?:[A-Z]\.\s*){1,3}[A-Z][a-z]+"     # F. J. Dian
    r"|[A-Z][a-z]+\s+[A-Z][a-z]+,"          # Lihong Zheng,
    r"|^\s*\[?\d{0,3}\]?\s*[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b"   # Behrouz Pirouz.
    r"|\bet\s+al\b"
    # An organisation authors its own report: `World Health Organisation`, `Oracle
    # World Wide`, `Ministry of ...`. Demanding a personal name reported all of them.
    r"|\b(?:Organi[sz]ation|Ministry|Department|Institute|Council|Commission"
    r"|Agency|Association|Society|Bureau|Board|Authority|Corporation|Foundation)\b",
    # Case-insensitive, because `European commission (2024)` writes it lower case,
    # and the letter classes take accents: `Simões, S.` failed `[A-Z][a-z]+` on the
    # ô and was reported as having no author at all.
    re.I | re.UNICODE)

#: References that are not journal articles and legitimately carry no volume or
#: pages: standards, technical reports, theses, patents, books, conference papers and
#: anything with a URL. Asking those for a volume put a wrong finding on every one.
_NOT_AN_ARTICLE = re.compile(
    r"https?://|www\.|\bavailable\s+(?:from|at|online)\b"
    r"|\bin\s*:\s|\bproc(?:eedings)?\b|\bconf(?:erence)?\b|\bsymposium\b"
    r"|\bstandard\b|\bIEEE\s+Std\b|\bIS\s*\d{3,}|\bISO\s*\d|\bASTM\b"
    r"|\btechnical\s+report\b|\bwhite\s*paper\b|\bthesis\b|\bdissertation\b"
    r"|\bpatent\b|\bpress\b|\bpublish(?:er|ing|ers)\b|\bed(?:s|ition|itors)?\.\s"
    r"|\bSpringer\b|\bElsevier\b|\bWiley\b|\bTaylor\s*&\s*Francis\b"
    r"|\bCRC\b|\bAcademic\s+Press\b|\bISBN\b|\bchapter\b"
    # `\bconf(?:erence)?\b` never matched `Conferences`, and `E3S Web of Conferences`
    # is exactly where a conference paper says so. Same for government and legal
    # sources, which carry neither volume nor pages by nature.
    r"|\bconferences\b|\beBooks?\b|\bworking\s+paper\b"
    r"|\bministry\b|\bdepartment\s+of\b|\bgovernment\b|\bcommission\b"
    r"|\bsupreme\s+court\b|\bhigh\s+court\b|\bact\b|\bbill\b"
    r"|\bResearchGate\b|\barXiv\b|\bpreprint\b|\bbioRxiv\b|\bmedRxiv\b"
    # More shapes the sample turned up: `Retrieved from ...`, `4th Ed.`, and the
    # organisations that author their own reports.
    r"|\bretrieved\s+from\b|\baccessed\b|\bhandbook\b|\bmanual\b"
    r"|\b\d(?:st|nd|rd|th)\s+ed\b|\bWHO\b|\bWorld\s+Health\b|\bUNESCO\b"
    r"|\bUNICEF\b|\bOECD\b|\bFAO\b|\bIPCC\b|\bNITI\b|\bUnited\s+Nations\b", re.I)

#: At least one of these has to be present for a paragraph to be a reference at all.
#: `find_references` returns everything after the REFERENCES heading, which on a real
#: manuscript includes appendices, author biographies and stray body text — and the
#: sample was full of findings like "β-glucosidase enzymes to degrade the residual
#: biomass" reported as missing its authors, year, volume and pages. It is not
#: missing them; it is not a reference.
_CITATION_SIGNAL = re.compile(
    r"\b(1[89]|20)\d{2}\b"          # a year
    r"|10\.\d{4,9}/"                 # a DOI
    r"|https?://|www\."               # a URL
    r"|\bpp?\.\s*\d"                # pp. 46
    r"|\bvol\.?\s*\d"               # vol. 12
    r"|\bet\s+al\b", re.I)

#: A reference short enough that it cannot be a real entry at all.
_MIN_CHARS = 30

#: How many Crossref lookups one manuscript may make.
_MAX_LOOKUPS = 15

#: How a numbered bibliography starts each entry: `[12]`, `12.`, `12)`.
_ENTRY_START = re.compile(r"^\s*\[?\d{1,3}[\].)]")


def group_entries(paragraphs):
    """[(first paragraph, whole entry text)] — one per reference, not per line.

    A reference wraps. `Lihong Zheng, Xiangjian He, Bijan Samali, and Laurence` is a
    complete entry's first line and the year, volume and pages are on the next
    paragraph; checked on its own it looks like it is missing all three. That single
    mistake accounted for most of what this rule reported.

    Grouping needs a marker, and a numbered bibliography gives one: every entry opens
    with `[n]` or `n.`. When no paragraph carries that — an author-year list — there
    is nothing to group on and each paragraph is treated as its own entry, which is
    what such bibliographies actually do with their hanging indents.
    """
    numbered = [p for p in paragraphs if _ENTRY_START.match(p.text or "")]
    if len(numbered) < 3:
        return [(p, (p.text or "").strip()) for p in paragraphs]

    entries, head, parts = [], None, []
    for p in paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue
        if _ENTRY_START.match(text):
            if head is not None:
                entries.append((head, " ".join(parts)))
            head, parts = p, [text]
        elif head is not None:
            parts.append(text)
    if head is not None:
        entries.append((head, " ".join(parts)))
    return entries


@dataclass
class RefFinding:
    """One incomplete reference."""
    rule: str
    severity: str
    paragraph: Optional[int]
    message: str
    detail: str = ""
    suggestion: Optional[str] = None
    missing: List[str] = field(default_factory=list)

    def as_query(self) -> Dict[str, object]:
        """The shape `generate_redline_docx` and the report already accept."""
        return {"index": self.paragraph, "snippet": self.detail,
                "query": self.message, "suggestion": self.suggestion}


def missing_fields(text: str) -> List[str]:
    """Which expected parts of a reference are absent.

    Only a journal article is asked for a volume and a page range. Books, standards,
    theses, patents, conference papers and web sources legitimately have neither, and
    demanding them turned 62% of the corpus's references into findings — a rule that
    fires on two references in three is not a check, it is noise.
    """
    t = text.strip()
    missing = []
    if not _AUTHORS.search(t):
        missing.append("authors")
    if not _YEAR.search(t):
        missing.append("year")
    # Only a journal article is expected to have a volume and page range. Books,
    # standards, theses, patents, conference papers and web sources do not, and
    # demanding them turned 62% of the corpus's references into findings.
    if _NOT_AN_ARTICLE.search(t) or _DOI.search(t):
        return missing
    if not _VOLUME.search(t):
        missing.append("volume/issue")
    if not _PAGES.search(t):
        missing.append("pages")
    return missing


def _crossref_entry(text: str, fetch) -> Optional[str]:
    """A complete reference rebuilt from Crossref, or None.

    `fetch` is injected so this is testable without the network, and so a Crossref
    outage degrades to "no suggestion" rather than to a failed run.
    """
    try:
        rec = fetch(text)
    except Exception:                        # noqa: BLE001 — a suggestion is optional
        return None
    if not rec:
        return None
    authors = rec.get("authors") or ""
    title = rec.get("title") or ""
    journal = rec.get("journal") or ""
    year = rec.get("year") or ""
    vol, issue = rec.get("volume") or "", rec.get("issue") or ""
    pages, doi = rec.get("pages") or "", rec.get("doi") or ""
    if not (title and year):
        return None
    volpart = f"{vol}({issue})" if vol and issue else (vol or "")
    parts = [p for p in (authors, f"{title}.", journal, f"{year};{volpart}"
                         + (f":{pages}" if pages else "")) if p and p.strip(".;:")]
    entry = " ".join(parts).strip()
    if doi:
        entry += f". https://doi.org/{doi}"
    return entry


def check_references(reference_paragraphs, fetch=None) -> List[RefFinding]:
    """A finding per incomplete reference, with a Crossref-built suggestion when one
    can be had.

    `reference_paragraphs` is what `house_layout.find_references` returns — the
    paragraphs after the REFERENCES heading. When a manuscript has no such heading
    that list is empty and this reports nothing, which is right: guessing at where the
    bibliography starts would put reference findings on the body text.
    """
    out: List[RefFinding] = []
    lookups = 0
    for p, text in group_entries(reference_paragraphs):
        if len(text) < _MIN_CHARS:
            continue
        # A short line with no year at all is the first line of a wrapped entry, not
        # an entry — `Lihong Zheng, Xiangjian He, Bijan Samali, and Laurence` is 54
        # characters of author list whose year, volume and pages are on the paragraph
        # below. Grouping catches this in a numbered bibliography, where `[n]` marks
        # each entry; an author-year list offers no such marker, so a fragment is
        # skipped rather than reported as missing everything it obviously carries
        # further down.
        if len(text) < 120 and not _YEAR.search(text):
            continue
        # Not a reference at all — see `_CITATION_SIGNAL`.
        if not _CITATION_SIGNAL.search(text):
            continue
        gaps = missing_fields(text)
        if not gaps:
            continue
        # Each lookup is a network round trip. A median manuscript flags two
        # references and the 90th percentile nine, so the cap almost never bites —
        # but a bibliography of a hundred thin entries would otherwise add minutes to
        # the run. When it does bite, the report says so rather than quietly
        # offering fewer suggestions than it could have.
        suggestion = None
        if fetch and lookups < _MAX_LOOKUPS:
            lookups += 1
            suggestion = _crossref_entry(text, fetch)
        out.append(RefFinding(
            "references.incomplete", "info", p.index,
            "this reference is missing its " + ", ".join(gaps)
            + ("; a complete entry from Crossref is suggested" if suggestion
               else ("; it could not be matched in Crossref, so the author must "
                     "supply it" if fetch and lookups <= _MAX_LOOKUPS
                     else f"; more than {_MAX_LOOKUPS} references were incomplete, "
                          "so Crossref was not consulted for this one")),
            text[:180], suggestion, gaps))
    return out
