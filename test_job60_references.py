"""Job #60's bibliography lost three works and duplicated three others.

Sixteen references in, sixteen out, every entry well-formed and correctly converted to
Vancouver — and UNESCO's OER Recommendation, its 2026 restatement and Vygotsky & Cole
(1978) were gone, replaced by second copies of Tlili, Seale and Hamilton. Vygotsky is
argued from by name in the body, so the paper cited a source it no longer listed.

The defect lives in the relationship between the list and itself, which is why no
per-entry check could ever have seen it.
"""

from __future__ import annotations

import edit_guards as G

# Shortened but structurally faithful to the manuscript: the same heading with its
# colon, the same first-author/year identities, the same shape of loss.
_ORIGINAL = [
    "The theoretical basis draws on Vygotsky's socio-cultural theory.",
    "References:",
    "Seale J. It's not all doom and gloom: what the pandemic taught us. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
    "UNESCO I. Recommendation on open educational resources (OER). Legal Instruments. 2019 Nov 25.",
    "Vygotsky LS, Cole M. Mind in society: development of higher psychological processes. Harvard University Press; 1978.",
    "Hamilton D, McKechnie J. Immersive virtual reality as a pedagogical tool. J Comput Educ. 2021; 8(1): 1–32p.",
]


def _edited_with_losses():
    """What #60 returned: Vygotsky and UNESCO replaced by copies of their neighbours."""
    return [
        _ORIGINAL[0],
        "REFERENCES",
        "1. Seale J. It's not all doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
        "2. Seale J. It's not all doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
        "3. Hamilton D, McKechnie J. Immersive virtual reality. J Comput Educ. 2021; 8(1): 1–32p.",
        "4. Hamilton D, McKechnie J. Immersive virtual reality. J Comput Educ. 2021; 8(1): 1–32p.",
    ]


def test_the_heading_is_found_even_with_a_colon():
    """`References:` — the pattern demanded an exact `References` and found nothing.

    Both reference guards used that pattern, so on this manuscript neither of them ran
    at all, and the silence looked exactly like having nothing to say.
    """
    assert G._references_start(_ORIGINAL) == 1
    assert G._references_start(["References"]) == 0
    assert G._references_start(["1. References."]) == 0
    assert G._references_start(["The references show a gap in the literature."]) is None


def test_works_that_went_missing_are_restored():
    out, queries = G.verify_reference_block(_ORIGINAL, _edited_with_losses())
    assert any("Vygotsky" in p for p in out)
    assert any("Recommendation on open educational" in p for p in out)
    assert sum(1 for p in out if p.startswith("Seale")) == 1
    assert queries and "Vygotsky (1978)" in queries[0]["query"]


def test_the_query_names_both_sides_of_the_swap():
    _out, queries = G.verify_reference_block(_ORIGINAL, _edited_with_losses())
    q = queries[0]["query"]
    assert "went missing" in q and "appeared more than once" in q
    assert "count" in q          # says why a count would not have caught it


def test_a_correct_vancouver_reformat_is_left_alone():
    """The guard must not punish the reformatting it exists alongside.

    Every entry here is rewritten — numbered, abbreviated, re-punctuated — and not one
    work has gone, so nothing should be restored.
    """
    edited = [
        _ORIGINAL[0],
        "REFERENCES",
        "1. Seale J. It's not all doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
        "2. UNESCO I. Recommendation on open educational resources (OER). Legal Instruments. 2019.",
        "3. Vygotsky LS, Cole M. Mind in society. Cambridge: Harvard University Press; 1978.",
        "4. Hamilton D, McKechnie J. Immersive virtual reality. J Comput Educ. 2021; 8(1): 1–32p.",
    ]
    out, queries = G.verify_reference_block(_ORIGINAL, edited)
    assert queries == []
    assert out == edited          # the reformat survives untouched


def test_a_manuscript_with_no_reference_section_is_untouched():
    paras = ["The findings show a gap.", "Digital pedagogies have grown."]
    out, queries = G.verify_reference_block(paras, list(paras))
    assert queries == [] and out == paras
