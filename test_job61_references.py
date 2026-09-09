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
