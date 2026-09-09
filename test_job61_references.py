"""Job #61: reference titles rewritten, and an entry with no title at all.

Both are about the bibliography being somebody else's text. House style governs how
this manuscript writes; it does not govern what another author called their work.
"""

from __future__ import annotations

import edit_guards as G
import reference_check as R


# ------------------------------------------ the abbreviation rule stops at References


_DOC = [
    "Open Educational Resources (OER) are free to use.",
    "Platforms promoting Open Educational Resources reduce cost.",
    "References:",
    "UNESCO I. Recommendation on open educational resources (OER). Legal Instruments. 2019 Nov 25.",
    "Tlili A, et al. Are open educational resources (OER) and practices (OEP) effective "
    "in improving learning. Educ Technol Res Dev. 2023; 71(1): 1–25p.",
]


def test_a_reference_title_is_not_shortened():
    """`Recommendation on open educational resources (OER)` -> `Recommendation on OER`.

    A title is the identity of a published work. Shortened, it names no paper anyone
    can find — and job #61 did it to two entries.
    """
    out, _q = G.enforce_abbreviation_first_use(_DOC, list(_DOC))
    assert out[3] == _DOC[3]
    assert out[4] == _DOC[4]


def test_the_body_is_still_shortened():
    """The rule must keep working everywhere it should — this is not a retreat."""
    out, _q = G.enforce_abbreviation_first_use(_DOC, list(_DOC))
    assert out[1] == "Platforms promoting OER reduce cost."


def test_an_abbreviation_defined_only_in_a_reference_is_not_learned():
    """A term introduced inside somebody else's title is not this paper defining it."""
    doc = ["The study examined learning platforms.",
           "References:",
           "Tlili A. Are open educational resources (OER) effective. "
           "Educ Technol Res Dev. 2023; 71(1): 1–25p.",
           "Wang X. Platforms promoting open educational resources. "
           "Comput Educ. 2022; 60(2): 30–44p."]
    out, _q = G.enforce_abbreviation_first_use(doc, list(doc))
    assert out == doc


# ---------------------------------------------------- a reference with no title at all


def test_an_entry_with_no_title_is_reported():
    """`Unesco.org. 2026. Available from: <url>` — a source, a year and a link."""
    assert R.missing_descriptive_fields(
        "Unesco.org. 2026. Available from: https://unesdoc.unesco.org/ark:/48223/pf0000098427"
    ) == ["title"]


def test_entries_that_do_have_titles_are_left_alone():
    """The four this was wrong about before it was cut back.

    Reading its findings by hand is what caught them: `The UDL Guidelines` and
    `Recommendation on Open Educational Resources (OER)` are titles, and `Legal
    Instruments` is a source, so the journal and publisher arms were removed rather
    than tuned.
    """
    for entry in (
        "CAST, Inc. The UDL Guidelines. CAST_UDL. 2020. Available from: https://udlguidelines.cast.org/",
        "Recommendation on Open Educational Resources (OER). Unesco.org. 2026. "
        "Available from: https://www.unesco.org/en/legal-affairs/x",
        "UNESCO I. Recommendation on open educational resources (OER). Legal Instruments. 2019 Nov 25.",
        "Seale J. Doom and gloom lessons. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
    ):
        assert R.missing_descriptive_fields(entry) == [], entry


# ------------------------------- the abstract and the body are two independent scopes

_SCOPED = [
    "Next-Generation Digital Pedagogies for Inclusive Education",
    "Abstract",
    "The advent of next-generation digital pedagogies has revolutionized inclusive "
    "education by harnessing cutting-edge Information and Communication Technology "
    "(ICT) solutions.",
    "Keywords: digital pedagogy, ICT tools, inclusivity",
    "INTRODUCTION",
    "The transformative potential of Information and Communication Technology aligns "
    "with Sustainable Development Goal 4.",
    "Recent studies emphasize the growing role of Information and Communication "
    "Technology in schools.",
]


def test_the_body_defines_the_term_again_at_its_own_first_use():
    """An abstract is read on its own, in indexes and databases, so it defines nothing
    for the body. The body spells the term out at *its* first use and shortens after.
    """
    out, _q = G.enforce_abbreviation_first_use(_SCOPED, list(_SCOPED))
    assert out[5].startswith(
        "The transformative potential of Information and Communication Technology (ICT)")
    assert out[6] == "Recent studies emphasize the growing role of ICT in schools."


def test_the_abstract_is_not_shortened_by_this_guard():
    """Job #61 reduced the abstract's own `Information and Communication Technology
    (ICT)` to a bare `ICT`, and the body's first mention was shortened rather than
    defined — so the term was spelled out nowhere in the paper.
    """
    out, _q = G.enforce_abbreviation_first_use(_SCOPED, list(_SCOPED))
    assert out[2] == _SCOPED[2]


def test_the_body_starts_after_the_keywords_line():
    assert G._body_start(_SCOPED) == 4
    # No keywords line: the abstract's own paragraphs are skipped to the next heading.
    assert G._body_start(["Title", "Abstract", "A long abstract sentence goes here.",
                          "INTRODUCTION", "Body text follows."]) == 3
    assert G._body_start(["Just body text with no front matter at all."]) == 0


# ------------------------------------------------- the house has a convention, not a vote

def test_the_journal_abbreviation_check_points_at_the_house_rule():
    """In-House Reference Rule 2 abbreviates journal names; a vote can contradict it.

    The check used to take the majority as the convention, which reads sensibly until
    you notice that a manuscript arriving with its journal names spelled out — the
    ordinary case, and the whole reason the rule exists — has a spelled-out majority.
    On those it told the editor to undo the house rule.
    """
    import proofread as P

    mostly_full = [
        "1. Downes S. Connectivism. International Journal of Instructional Technology "
        "and Distance Learning. 2005; 2(1): 3–10p.",
        "2. Wang X. Efficacy of adaptive systems. International Journal of Educational "
        "Technology in Higher Education. 2023; 20(1): 5–19p.",
        "3. Hamilton D. Immersive virtual reality. Journal of Computers in Education. "
        "2021; 8(1): 1–32p.",
        "4. Seale J. Doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
    ]
    hits = P._reference_style_findings(mostly_full)
    assert len(hits) == 3                       # the three spelled-out ones
    for f in hits:
        assert "abbreviate" in f.suggestion
        assert "spelled out in full" not in f.suggestion


def test_a_fully_abbreviated_list_says_nothing():
    import proofread as P

    assert P._reference_style_findings([
        "1. Seale J. Doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
        "2. Topping KJ. Blended learning. Rev Educ. 2022; 10(2): 3–19p.",
        "3. Mikropoulos TA. Digital technology. Educ Inf Technol. 2023; 28(4): 39–55p.",
        "4. Meng B. Brake-by-wire survey. IEEE Access. 2020; 8(2): 22–35p.",
    ]) == []


def test_a_reference_that_lost_its_link_gets_it_back():
    """`Unesco.org. 2026. Available from:` with the address gone.

    In-House Reference Rule 3 requires `Available at URL` for a web source, and nothing
    was checking the link survived — an entry that still says where to look and no
    longer says where.
    """
    orig = ["References:",
            "Unesco.org. 2026. Available from: https://unesdoc.unesco.org/ark:/48223/pf0000098427",
            "Seale J. Doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p."]
    edited = ["REFERENCES",
              "1. Unesco.org. 2026. Available from:",
              "2. Seale J. Doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p."]
    out, queries = G.restore_reference_urls(orig, edited)
    assert "https://unesdoc.unesco.org/ark:/48223/pf0000098427" in out[1]
    assert out[1].startswith("1. ")          # the reformatting is kept
    assert len(queries) == 1


def test_nothing_happens_when_no_link_was_lost():
    orig = ["References:",
            "Seale J. Doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p."]
    out, queries = G.restore_reference_urls(orig, list(orig))
    assert queries == [] and out == orig
