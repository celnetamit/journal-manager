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
    assert editor._bibliography_census(_BEFORE) == (4, 4)
    assert editor._bibliography_census(_AFTER_SWAPPED) == (4, 2)


def test_the_re_sort_is_rejected_on_a_swap():
    """The verdict `align_global_citations` reaches from those two numbers."""
    b_n, b_d = editor._bibliography_census(_BEFORE)
    a_n, a_d = editor._bibliography_census(_AFTER_SWAPPED)
    assert b_n and (a_n != b_n or a_d != b_d)


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
    b_n, b_d = editor._bibliography_census(_BEFORE)
    a_n, a_d = editor._bibliography_census(reordered)
    assert (a_n, a_d) == (b_n, b_d)


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
