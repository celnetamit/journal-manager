"""Mechanical findings that were wrong on real manuscripts.

Every case here is a sentence taken from the 400-manuscript sweep of the WordPress
media corpus (`wpimport/media/*.docx`), not an invented one. The rules were tuned on
three homoeopathy and microbiology papers; the corpus is law, materials science,
agronomy, telecommunications and nursing, and each of these fired an "error" a
competent editor would not have raised.

Each false-positive test is paired with a true-positive one. A check narrowed until it
stops finding the thing it exists for is worse than the false positive was.
"""

import proofread as P


def rules(text, rule):
    return [f for f in P.mechanical_findings([text]) if f.rule == rule]


# ----------------------------------------------------------------- dash.range

def test_phone_number_is_not_a_number_range():
    """`Tel: +91-8816867362` suggested dialling `91–8816867362`.

    Both existing guards wave it through: the pair ascends, and only the second half
    is four digits or more.
    """
    assert not rules("Corresponding author, Tel: +91-8816867362 for queries.",
                     "dash.range")


def test_a_page_range_in_prose_is_still_a_dash_finding():
    assert rules("The effect is discussed at length on pages 55-65 of the report.",
                 "dash.range")


def test_reference_page_range_is_left_alone():
    """`Environ Geol 35(1): 55-65` — an author-year entry with no leading number and
    no DOI, which `_is_reference_block` did not recognise. Page ranges inside the
    bibliography were a third of every `dash.range` in the corpus."""
    assert not rules("Correia J, Silva P. Groundwater quality assessment. "
                     "Environ Geol 35(1): 55-65", "dash.range")


def test_prose_is_not_mistaken_for_a_reference():
    """The volume(issue) test must not swallow ordinary sentences, or the general
    checks stop running over the body — which is the whole manuscript."""
    long_prose = (
        "The samples were held at ambient temperature and the resulting spread of "
        "values, which ranged from 20-40 units across the three replicates, is "
        "consistent with earlier work in this area and does not by itself indicate "
        "any systematic error in the measurement procedure adopted here, though it "
        "does suggest that a larger sample would be worth collecting in future."
    )
    assert not P._is_reference_block(long_prose)
    assert rules(long_prose, "dash.range")


# ---------------------------------------------------------------- unit.spacing

def test_a_decade_is_not_a_measurement_in_seconds():
    """`the 1970s and 1980s` was reported as 1970 seconds needing a space."""
    assert not rules("Work in the 1970s and 1980s laid the groundwork for this.",
                     "unit.spacing")


def test_a_model_designation_is_not_a_measurement():
    """`HuanJing-1A` (a satellite) and space group `Fm-3m` are names. A digit and a
    capital hung off a hyphen is a designation, not amperes or metres."""
    assert not rules("Imagery from HuanJing-1A was compared against PRISMA.",
                     "unit.spacing")
    assert not rules("The structure adopts space group Fm-3m at room temperature.",
                     "unit.spacing")


def test_a_real_missing_unit_space_is_still_found():
    assert rules("A 12V DC generator converts the output.", "unit.spacing")
    assert rules("The antenna operates in the 300GHz band.", "unit.spacing")


# ------------------------------------------------- the mask leaking to the user

def test_a_suggestion_never_quotes_the_mask():
    """`_mask_opaque` fills URLs and addresses with `x` of the same length so that
    offsets survive. Suggestions were being quoted out of the masked copy, so a
    paragraph listing e-mail addresses proposed replacing text with a run of `x`.
    """
    text = "Write to the editor.contact@example.com for the full dataset."
    for f in P.mechanical_findings([text]):
        assert "xxxx" not in (f.suggestion or ""), f
        assert "xxxx" not in f.fragment, f


def test_double_space_suggestion_is_the_real_text():
    findings = rules("The result  was significant.", "space.double")
    # The match is one character either side of the run, so the suggestion is the
    # collapsed `t  w` — real characters, not mask filler.
    assert findings and findings[0].suggestion == "t w"


# ------------------------------------------------------------------- collapsing

def _many_double_spaces(n):
    return [f"Sentence {i}  with two spaces in it." for i in range(n)]


def test_repeating_findings_are_capped_but_not_lost():
    """13 double spaces meant 13 Word comments, all saying the same thing, in front
    of the copyeditor's actual queries."""
    raw = P.mechanical_findings(_many_double_spaces(13))
    assert len([f for f in raw if f.rule == "space.double"]) == 13

    collapsed = P.collapse_repeats(raw)
    anchored = [f for f in collapsed
                if f.rule == "space.double" and f.paragraph is not None]
    summary = [f for f in collapsed
               if f.rule == "space.double" and f.paragraph is None]

    assert len(anchored) == P.ANCHOR_LIMIT
    assert len(summary) == 1
    # The 10 that lost their anchor are counted, not silently dropped.
    assert "10" in summary[0].message


def test_a_rule_under_the_limit_is_untouched():
    raw = P.mechanical_findings(_many_double_spaces(2))
    assert P.collapse_repeats(raw) == raw


def test_non_repeating_rules_keep_every_anchor():
    """`word.doubled` says something different each time and is rare. Capping it
    would hide real errors behind a count."""
    paras = [f"The the {w} was measured." for w in
             ("mass", "length", "volume", "density", "charge")]
    collapsed = P.collapse_repeats(P.mechanical_findings(paras))
    doubled = [f for f in collapsed if f.rule == "word.doubled"]
    assert len(doubled) == 5
    assert all(f.paragraph is not None for f in doubled)
