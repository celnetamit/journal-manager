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
    """Only the missing works come back, and the reformatting is kept.

    This used to restore the author's whole reference list, and the quality team met
    the result on job #107 as "the references were not touched at all": measured across
    91 redlines, that behaviour was throwing away the reformatting of 24 bibliographies,
    almost always because an entry had been reformatted to lead with a different author
    and was read as lost.
    """
    out, queries = G.verify_reference_block(_ORIGINAL, _edited_with_losses())
    assert any("Vygotsky" in p for p in out)
    assert any("Recommendation on open educational" in p for p in out)
    # The reformatted entries are still reformatted — nothing was thrown away.
    assert any(p.startswith("1. Seale") for p in out)
    assert queries and "Vygotsky" in queries[0]["query"]


def test_the_query_names_both_sides_of_the_swap():
    _out, queries = G.verify_reference_block(_ORIGINAL, _edited_with_losses())
    q = queries[0]["query"]
    assert "went missing" in q
    assert "did not list" in q   # the surplus copy, so it can be deleted in one pass
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


def test_a_reference_reformatted_to_lead_with_another_author_is_not_lost():
    """Job #107's actual cause, and the reason a quarter of all bibliographies were
    being restored unformatted.

    `Evely A. Dead planet, living planet ... C. Nellemann, E. Corcoran, editors. 2010.`
    reformatted to open with the editors is the same work. Under the old identity — the
    first word and the year — it was Evely leaving and Nellemann arriving.
    """
    original = [
        "Text.", "REFERENCES",
        "Evely A. Dead planet, living planet. Biodiversity and ecosystem restoration "
        "for sustainable development. C. Nellemann, E. Corcoran, editors. UNEP; 2010.",
    ]
    edited = [
        "Text.", "REFERENCES",
        "1. Nellemann C, Corcoran E, editors. Dead planet, living planet: biodiversity "
        "and ecosystem restoration for sustainable development. UNEP; 2010.",
    ]
    out, queries = G.verify_reference_block(original, edited)
    assert out == edited and queries == []


def test_an_entry_whose_year_the_reformat_dropped_is_not_lost():
    """`Warrens, M. J. (2014). New interpretations of Cohen's kappa. Journal of
    Mathematics` came back as `Warrens MJ. New interpretations of Cohen's kappa. J
    Math.` — the year is gone, which is a defect, but the reference is on the page."""
    original = ["Text.", "REFERENCES",
                "Warrens, M. J. (2014). New interpretations of Cohen's kappa. "
                "Journal of Mathematics, 2014, 1-3."]
    edited = ["Text.", "REFERENCES",
              "1. Warrens MJ. New interpretations of Cohen's kappa. J Math."]
    out, queries = G.verify_reference_block(original, edited)
    assert out == edited and queries == []


def test_a_table_row_after_the_heading_is_not_a_reference():
    """Two manuscripts carry a table after the References heading. `Local
    strain(SB12)+50kgDAP` is not a work that can go missing."""
    original = ["Text.", "REFERENCES", "Local strain(SB12)+50kgDAP",
                "Smith J. A real reference with a title. J Things. 2020; 1: 2."]
    edited = ["Text.", "REFERENCES", "Local strain (SB-12) + 50 kg DAP",
              "1. Smith J. A real reference with a title. J Things. 2020; 1: 2."]
    _out, queries = G.verify_reference_block(original, edited)
    assert queries == []


def test_a_corrected_surname_is_still_the_same_book():
    original = ["Text.", "REFERENCES",
                "Anathanarayan and Panikers, Textbook of Microbiology 10th edition"]
    edited = ["Text.", "REFERENCES",
              "1. Ananthanarayan, Paniker. Textbook of Microbiology. 10th edition."]
    out, queries = G.verify_reference_block(original, edited)
    assert out == edited and queries == []


def test_running_the_guard_twice_does_not_restore_twice():
    """The pipeline runs this before the re-sort and again at the end. The second run
    has to see what the first one put back — it sits past the original's length, and a
    window cut to the shorter list would have hidden it and appended a second copy."""
    once, _q = G.verify_reference_block(_ORIGINAL, _edited_with_losses())
    twice, queries = G.verify_reference_block(_ORIGINAL, once)
    assert twice == once
    assert queries == []
    assert sum(1 for p in twice if "Vygotsky" in p and p.startswith("Vygotsky")) == 1
