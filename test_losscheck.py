"""The production loss guard.

Two checks and no more, because a third was written, measured and removed. Over 182
paragraphs from 7 real manuscripts it produced 26 of 27 findings and every one was a
*correct* edit — citations renumbering after a re-sort, author-year converted to
Vancouver, `Figure 4.1` becoming `Figure 1`. In a pipeline whose job includes renumbering
citations, "a number changed" is what success looks like, and a guard that fires 26 times
on correct work hides the one case that is not.

What survived is what was actually observed to go wrong: a paragraph coming back empty
(seen on 4 Sep — a sentence with citation [6] vanished and the job reported no error),
and a negation disappearing, which reverses a claim while reading perfectly.
"""

import losscheck as L


def test_an_emptied_paragraph_is_caught():
    hit = L.check_paragraph("real-time, flagging unusual behavior and preventing "
                            "unauthorized access attempts [6].", "")
    assert hit and hit["kind"] == "emptied"


def test_a_dropped_negation_is_caught():
    hit = L.check_paragraph(
        "The treatment was not effective in reducing tumour size across all cohorts.",
        "The treatment was effective in reducing tumour size across all cohorts.")
    assert hit and hit["kind"] == "negation-lost"


def test_citation_renumbering_is_not_damage():
    """References re-sort, so citation numbers change. That is the pipeline working."""
    assert L.check_paragraph(
        "Chickens matter for food security [1, 22]. Flocks hold 6 to 12 birds [8, 14].",
        "Chickens matter for food security [1, 2]. Flocks hold 6 to 12 birds [3, 4].") is None


def test_vancouver_conversion_is_not_damage():
    assert L.check_paragraph(
        "Initial cost is an obstacle despite long-term savings, and incentives help. "
        "(Panwar et al., 2011)",
        "Initial cost is an obstacle despite long-term savings, and incentives help [1]."
    ) is None


def test_figure_renumbering_is_not_damage():
    assert L.check_paragraph("Figure 4.1: Admin Dashboard page",
                             "Figure 1. Admin dashboard page") is None


def test_a_gutted_paragraph_is_still_caught():
    long_original = ("The reaction proceeded smoothly under mild conditions, giving the "
                     "desired product in good yield after purification by column "
                     "chromatography on silica gel with a gradient eluent.")
    hit = L.check_paragraph(long_original, "The reaction gave the product.")
    assert hit and hit["kind"] == "truncated"


def test_a_heading_may_shrink_freely():
    assert L.check_paragraph("2.2 Material characteristics",
                             "Material Characteristics") is None
