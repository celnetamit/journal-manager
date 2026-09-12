"""Job #62 returned sixteen references for sixteen, four of them the wrong works.

UNESCO's OER Recommendation, its 2026 restatement, Vygotsky & Cole (1978) and Almasri
(2024) left the paper; Seale, Wang, Tlili and Hamilton each appeared twice. Two separate
guards were watching and neither said anything.
"""

from __future__ import annotations

import editor
import edit_guards as G


# The shape of the failure: same count, same number of *distinct strings*, because each
# duplicate came back reformatted differently — one with "et al.", one with its full
# author list.
_BEFORE = [
    "1. Fernandez-Batanero JM. Assistive technology for inclusion. Educ Inf Technol. "
    "2022; 27(3): 4067–4085p.",
    "2. Vygotsky LS, Cole M. Mind in society. Harvard University Press; 1978.",
    "3. Seale J. Doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
    "4. UNESCO I. Recommendation on open educational resources. Legal Instruments. 2019.",
]
_AFTER_SWAPPED = [
    "1. Seale J. It's not all doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
    "2. Fernandez-Batanero JM, Montenegro-Rueda M, et al. Assistive technology. "
    "Educ Inf Technol. 2022; 27(3): 4067–4085p.",
    "3. Seale J. Doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
    "4. Fernandez-Batanero JM. Assistive technology for inclusion. Educ Inf Technol. "
    "2022; 27(3): 4067–4085p.",
]


def test_the_census_counts_works_not_wordings():
    """Two copies of one work, reformatted differently, must not count as two works."""
    assert sorted(editor._bibliography_census(_BEFORE).elements()) == [
        ("fernandez-batanero", "2022"), ("seale", "2023"),
        ("unesco", "2019"), ("vygotsky", "1978")]
    assert editor._bibliography_census(_AFTER_SWAPPED) == {
        ("seale", "2023"): 2, ("fernandez-batanero", "2022"): 2}


def test_the_re_sort_is_rejected_on_a_swap():
    """The verdict `align_global_citations` reaches from the two censuses."""
    before = editor._bibliography_census(_BEFORE)
    after = editor._bibliography_census(_AFTER_SWAPPED)
    assert before and after != before
    assert sorted((before - after).elements()) == [("unesco", "2019"),
                                                   ("vygotsky", "1978")]


def test_a_genuine_reorder_is_still_allowed():
    """Re-sorting into citation order is the point of the pass and must survive.

    Same works, different positions, reformatted — nothing lost, so nothing rejected.
    """
    reordered = [
        "1. Seale J. Doom and gloom. Br J Educ Technol. 2023; 52(4): 1545–1552p.",
        "2. UNESCO I. Recommendation on OER. Legal Instruments. 2019.",
        "3. Fernandez-Batanero JM, et al. Assistive technology. Educ Inf Technol. "
        "2022; 27(3): 4067–4085p.",
        "4. Vygotsky LS, Cole M. Mind in society. Cambridge: Harvard Univ Press; 1978.",
    ]
    assert editor._bibliography_census(reordered) == editor._bibliography_census(
        _BEFORE)


# --- the RRB manuscript: jobs #67, #69 and #70 -----------------------------------
#
# Its reference list carries no numbers of its own — this pass is what numbers it. The
# census detected an entry by "starts with 1." and used the same test to find the
# bibliography, so it found nothing, reported an empty list, and `align_global_citations`
# switched its own gate off. Three runs in a row lost Barman (2025) and the loss was
# left to the end-of-pipeline guard, which restores the list but cannot put the in-text
# numbering back — which is why those reports say the numbering needs a human eye.
#
# Verbatim from job #70's redline, ¶515–¶526.

_RRB = [
    "REFERENCES",
    "",
    "Nayak, D., & Jena, A. B. (2025). Role of Regional Rural Banks in Driving "
    "Socio-Economic Transformation: A Bibliometric Analysis of Northern Odisha. "
    "Questions de Fisioterapia, 54(3), 3628-3641.",
    "Barman, S. R., Paul, S., Sengupta, S., & Sengupta, S. (2025). Role of Regional "
    "Rural Banks in Financial Inclusion in India: An Exploratory Study.",
    "Barot, M. B., & Japee, G. (2021). Indian Rural Banking–Role of Regional Rural "
    "Banks. A Global Journal of Social Sciences, 4(2), 56-59.",
]


def test_an_unnumbered_reference_list_is_still_a_reference_list():
    """The gate was not failing to spot the swap; it was not running."""
    assert editor._bibliography_census(_RRB) == {
        ("nayak", "2025"): 1, ("barman", "2025"): 1, ("barot", "2021"): 1}


def test_the_rrb_swap_is_rejected_where_it_happens():
    """Barman leaves, a second Barot arrives, the entry count never moves."""
    swapped = list(_RRB)
    swapped[3] = ("2. Barot MB, Japee G. Indian rural banking: role of regional rural "
                  "banks. Glob J Soc Sci. 2021; 4(2): 56–59p.")
    before = editor._bibliography_census(_RRB)
    after = editor._bibliography_census(swapped)
    assert sum(before.values()) == sum(after.values()), "a swap keeps the size"
    assert after != before
    assert sorted((before - after).elements()) == [("barman", "2025")]


def test_an_initials_first_reference_is_readable():
    """Jobs #45 and #68 write IEEE style, initials before the surname. The identity
    started at the first run of letters and did not scan past `H.`, so every entry in
    both bibliographies fingerprinted as nothing — 38 and 36 entries the census could
    not see, which is `verify_reference_block` returning silently on the whole list.

    Both entries are verbatim from job #68's redline.
    """
    ieee = ('H. Jamil, M. Faizan, M. Adeel, T. Jesionowski, G. Boczkaj, and A. '
            'Balčiūnaitė, “Recent advances in polymer nanocomposites,” Molecules, '
            'vol. 29, no. 6, p. 1267, 2024.')
    assert G._reference_identity(ieee) == ("jamil", "2024")
    # and the Vancouver form of the same work has to fingerprint alike, because the
    # reformat moves the initials behind the surname
    assert G._reference_identity(
        "1. Jamil H, Faizan M, Adeel M, et al. Recent advances in polymer "
        "nanocomposites. Molecules. 2024; 29(6): 1267p.") == ("jamil", "2024")


def test_a_two_letter_surname_is_a_surname():
    """Job #45 ¶531. `Q. Li` was one of seven entries the census dropped for being
    too short to be a name."""
    assert G._reference_identity(
        'Q. Li, Z. Liu, D. Ji, et al., “A data-driven framework for real-time failure '
        'prediction,” Thin-Walled Structures, vol. 222, 2026.') == ("li", "2026")


def test_a_name_that_is_not_an_initial_keeps_its_own_first_word():
    """Only a single capital and a stop is an initial — an all-caps surname and an
    organisation are not, and must not be stepped over."""
    assert G._reference_identity(
        "UNESCO I. Recommendation on open educational resources. Legal Instruments. "
        "2019.") == ("unesco", "2019")
    assert G._reference_identity(
        "SRIKANTH, H. (2016). PERFORMANCE AND IMPACT OF REGIONAL RURAL BANKS–A CASE "
        "STUDY OF KARNATAKA VIKAS GRAMEENA BANK.") == ("srikanth", "2016")


def test_an_entry_with_no_year_is_still_no_identity():
    """Job #70 ¶524, which carries no year anywhere. Guessing one would invent a work;
    the entry stays outside the census, as it always has."""
    assert G._reference_identity(
        "VIRANI, D. V. A STUDY ON THE ANALYSIS OF FINANCIAL PERFORMANCE WITH "
        "REFERENCE TO REGIONAL RURAL BANKS (RRBS). MULTIDISCIPLINARY RESEARCH "
        "VOLUME-2, 51. Page 51") is None


def test_the_rrb_list_renumbered_in_place_is_not_a_swap():
    """Numbering the list is exactly what this pass is for and must survive it."""
    numbered = [_RRB[0], _RRB[1]] + [
        f"{n}. {p}" for n, p in enumerate(_RRB[2:], start=1)]
    assert editor._bibliography_census(numbered) == editor._bibliography_census(_RRB)


def test_the_block_guard_catches_the_same_swap():
    """The second line of defence, now asked again at the end of the chain.

    Job #62's loss was not present when the guard ran in the middle of the pipeline and
    was there by the time the redline was written — so the question is asked once more
    where nothing can follow it.
    """
    out, queries = G.verify_reference_block(
        ["References:"] + _BEFORE, ["REFERENCES"] + _AFTER_SWAPPED)
    assert queries, "a swap must be reported"
    assert "Vygotsky" in queries[0]["query"]
    assert any("Vygotsky" in p for p in out)      # the author's list is back


def test_the_pipeline_asks_again_before_writing_the_redline():
    """A guard in the middle of a long chain leaves every later step unguarded."""
    src = open("pipeline.py").read()
    before_redline = src[:src.index('progress(0.68, "Generating redline')]
    assert before_redline.count("verify_reference_block(") == 2
