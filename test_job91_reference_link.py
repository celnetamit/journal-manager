"""Job #91 ¶211 was delivered as `Unesco.org. 2026. Available from: `.

The address is gone — the identical symptom job #61 had, six days after it was written
down as fixed. Nothing in the report mentioned it: the work was still listed, so the
bibliography census was satisfied, and `restore_reference_urls` sits in the middle of
the chain where a later step can undo it.

Both entries here are verbatim from job #91's redline, where the URL survives in the
tracked deletion and the delivered text does not have it.
"""

from __future__ import annotations

import edit_guards as G
from redline_loss_check import links_lost

_URL = "https://unesdoc.unesco.org/ark:/48223/pf0000098427"
_ORIGINAL = f"Unesco.org. 2026. Available from: {_URL}"
_DELIVERED = "Unesco.org. 2026. Available from: "

_LIST = [
    "References",
    "UNESCO I. Recommendation on open educational resources (OER). Legal "
    "Instruments. 2019 Nov 25.",
    _ORIGINAL,
    "Vygotsky LS, Cole M. Mind in society: Development of higher psychological "
    "processes. Harvard university press; 1978.",
]


def test_the_link_is_put_back_where_the_entry_points_at_it():
    edited = list(_LIST)
    edited[2] = _DELIVERED
    out, queries = G.restore_reference_urls(_LIST, edited)
    assert out[2] == f"Unesco.org. 2026. Available from: {_URL}"
    assert queries, "the editor is told the link had gone"


def test_a_shortened_entry_is_not_a_work_that_went_missing():
    """The delivered text is thirty-four characters. At the old forty-character floor
    the entry dropped out of the edited census while staying in the original's, so the
    guard reported UNESCO (2026) as missing and restored a bibliography that still had
    every work in it."""
    edited = list(_LIST)
    edited[2] = _DELIVERED
    _out, queries = G.verify_reference_block(_LIST, edited)
    assert not queries, "no work went missing — only the link did"


def test_a_real_swap_is_still_caught_at_the_shorter_floor():
    """The negative case for the floor: lowering it must not blind the guard."""
    edited = list(_LIST)
    edited[3] = _LIST[1]                       # Vygotsky replaced by a second UNESCO
    out, queries = G.verify_reference_block(_LIST, edited)
    assert queries and "Vygotsky" in queries[0]["query"]
    assert any("Vygotsky" in p for p in out)


def test_the_daily_check_reports_a_lost_link():
    """It reported nothing on job #91: the work was listed, so the census passed."""
    assert links_lost(_LIST, [_LIST[0], _LIST[1], _DELIVERED, _LIST[3]]) == [
        "¶3: Unesco.org. 2026. Available from:"]
    assert links_lost(_LIST, list(_LIST)) == []


def test_the_pipeline_asks_for_the_link_where_nothing_can_follow():
    """The guard restores correctly when handed job #91's own paragraphs, and the list
    still had the link when it finished — so a later step removes it. Until that step
    is named, the question is asked again immediately before the redline."""
    src = open("pipeline.py").read()
    before_redline = src[:src.index('progress(0.68, "Generating redline')]
    assert before_redline.count("restore_reference_urls(") == 2
