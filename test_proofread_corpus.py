"""Mechanical findings that were wrong on real manuscripts.

Every case here is a sentence taken from the 400-manuscript sweep of the WordPress
media corpus (`wpimport/media/*.docx`), not an invented one. The rules were tuned on
three homoeopathy and microbiology papers; the corpus is law, materials science,
agronomy, telecommunications and nursing, and each of these fired an "error" a
competent editor would not have raised.

Each false-positive test is paired with a true-positive one. A check narrowed until it
stops finding the thing it exists for is worse than the false positive was.
"""

import json

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


# ------------------------------------------------- lists are not broken parentheses

def _unbal(text):
    """The `punctuation.unbalanced` findings for one paragraph."""
    return [f for f in P.mechanical_findings([text])
            if f.rule == "punctuation.unbalanced"]


def test_a_numbered_list_is_not_an_unbalanced_parenthesis():
    """Half of the 1,546 `punctuation.unbalanced` findings over the corpus were this:
    a manuscript labelling its list `A)` `B)` `C)`, reported as "0 ( and 5 )". An
    editor told five times that their list is broken stops reading the report."""
    for text in (
        "The 2d images are A) Interleukin 1 beta; B) Interleukin 6; C) CD33.",
        "e) Applying a bubble-forming solution to the weld.",
        "iv) Promote Clean Energy: invest in solar, wind, and hydro power.",
        "5.2) Physical characteristics recommendations",       # a section number
        "ⅰ) ",                                                  # Unicode roman numeral
    ):
        assert _unbal(text) == [], text


def test_a_label_inside_a_pair_still_closes_it():
    """The obvious fix — strip label-shaped `)` before counting — is wrong: the ` 1)`
    in `(Figure 1)` matches the same shape, so stripping it breaks a balanced pair and
    invents a fault. Nothing is forgiven while something is open to close."""
    assert _unbal("a) Hardware Circuitry (Figure 1)") == []
    assert _unbal("See panel b) of Fig. 2 (Reinforced).") == []


def test_a_genuinely_unclosed_parenthesis_is_still_found():
    """Narrowed, not deleted."""
    assert _unbal("Head cabbage; disease symptom ( pest occurrence, leaf yellowing")
    assert _unbal("Noble, A. (. (2003). Patterns of Indian houses.")
    # A stray closer that is not label-shaped is still a stray closer.
    assert _unbal("the viscosity of solution).")


def test_reversed_parentheses_are_found_now_that_order_is_read():
    """`Front. Cardiovasc. Med. 2016;3)3(:1-14` — one `(` and one `)`, so the old
    character count called this balanced and said nothing. It is a real typo, and it
    is reported only because the text is now walked in order.

    The `)` itself is forgiven — `;3)` is exactly the shape of a list label after a
    semicolon, which is how `1) foo; 2) bar` is written, and the guard cannot tell
    the two apart from the characters alone. It does not need to: the `(` that never
    closes is enough to put the paragraph in front of the editor."""
    (f,) = _unbal("Saklayen MG. Timeline of Hypertension. Med. 2016;3)3(:1-14.")
    assert f.message == "unbalanced parenthesis: 1 ( never closed"


def test_the_message_says_which_way_it_is_unbalanced():
    """"3 ( and 4 )" made the editor count the characters again to find out whether
    one was missing or one was spare."""
    (f,) = _unbal("The samples (held at constant mass were weighed.")
    assert f.message == "unbalanced parenthesis: 1 ( never closed"


def test_mixed_quotes_collapse_like_every_other_repeating_rule():
    """One manuscript in the corpus anchored 78 Word comments and 77 were this rule —
    a document that mixes `"` and `”` throughout. Its message is a constant string, so
    the "message differs each time" exemption never applied to it."""
    paras = [f'The {w} was called “stable" throughout.' for w in
             ("mass", "length", "volume", "density", "charge", "field")]
    raw = P.mechanical_findings(paras)
    assert len([f for f in raw if f.rule == "punctuation.unbalanced-quotes"]) == 6

    collapsed = P.collapse_repeats(raw)
    quotes = [f for f in collapsed if f.rule == "punctuation.unbalanced-quotes"]
    assert len([f for f in quotes if f.paragraph is not None]) == P.ANCHOR_LIMIT
    assert len([f for f in quotes if f.paragraph is None]) == 1


# ------------------------------------------------------ figure and table cross-refs

def test_an_enumerated_mention_cites_every_figure_in_it():
    """`Figures 8 and 9 show…` cites both. The single-number pattern saw neither — it
    required "Figure" exactly, so the plural form matched nothing at all — and figure 9
    was reported as captioned but never cited. 8% of these findings on a 150-manuscript
    sample, every one wrong."""
    assert P._mentioned_numbers("Figure", "Figures 8 and 9 show the result") == {"8", "9"}
    assert P._mentioned_numbers("Table", "Table 3-5 summarise the trials") == {"3", "4", "5"}
    assert P._mentioned_numbers("Figure", "Figs. 1, 2, 3 and 4") == {"1", "2", "3", "4"}


def test_an_enumeration_stops_at_the_first_thing_that_is_not_a_number():
    assert P._mentioned_numbers("Figure", "Figure 3 and Table 4") == {"3"}
    assert P._mentioned_numbers("Table", "Figure 3 and Table 4") == {"4"}


def test_a_percentage_after_a_figure_is_not_another_figure():
    """`Figure 5, 60% of samples` — a figure followed by a statistic. Enumerated
    references sit near each other; 60 is fifty-five away from 5."""
    assert P._mentioned_numbers("Figure", "Figure 5, 60% of samples were viable") == {"5"}
    assert P._mentioned_numbers("Figure", "Figure 3 and 40 participants") == {"3"}


def test_a_reference_title_is_not_a_figure_citation():
    """`Cancer Facts & Figures 2020` is a book. `\\d+` read it as figure 2020."""
    assert not P._mentioned_numbers(
        "Figure", "American Cancer Society. Cancer Facts & Figures 2020. Atlanta.")


def test_the_bibliography_does_not_cite_figures():
    paras = [
        "Figure 1. Apparatus used in the trial.",
        "The apparatus is shown in Figure 1.",
        "Bennett M, Leitch I. Nuclear DNA amounts. Ann Bot. 2011;107(3):467-590. "
        "See also Cancer Facts & Figures 12.",
    ]
    missing = [f for f in P._cross_reference_findings(paras, " ".join(paras))
               if f.rule == "crossref.figure-missing"]
    assert not missing, missing


def test_an_uncited_figure_is_still_reported():
    """The rule earns its keep: on real manuscripts the caption was very often the only
    place the figure was named anywhere in the document."""
    paras = ["Figure 1. Apparatus used in the trial.",
             "The samples were held at constant mass throughout."]
    assert [f for f in P._cross_reference_findings(paras, " ".join(paras))
            if f.rule == "crossref.figure-uncited"]


def test_a_figure_referred_to_but_never_captioned_is_still_reported():
    paras = ["Results for both runs appear in Figures 4 and 5.",
             "Figure 4. The first run."]
    missing = [f for f in P._cross_reference_findings(paras, " ".join(paras))
               if f.rule == "crossref.figure-missing"]
    assert len(missing) == 1 and "Figure 5" in missing[0].message


# ------------------------------------------------ the proofreader's language variant

def _prompt_for(lang=None, paras=None):
    """The prompt `llm_findings` actually sends, captured from a fake `generate`."""
    seen = []

    def fake_generate(prompt, settings=None, **kw):
        seen.append(prompt)
        return "[]"

    kwargs = {} if lang is None else {"lang_type": lang}
    P.llm_findings(paras or ["The prototype has a low centre of gravity and is stable "
                             "across the full range of operating speeds tested here."],
                   fake_generate, {}, **kwargs)
    assert seen, "llm_findings sent nothing to the model"
    return seen[0]


def test_the_proofreader_is_told_the_language_variant():
    """It never was. `lang_type` reached the copyedit and stopped there, so on a London
    manuscript the proofreader reported `low centre of gravity` as "this is a spelling
    error" and proposed `center` — silently re-spelling a British author, which is the
    one thing this module's docstring says not to do."""
    assert "UK English" in _prompt_for("UK English")
    assert "US English" in _prompt_for("US English")


def test_the_prompt_has_no_placeholder_left_in_it():
    """A `{lang_type}` reaching the model as a literal would be worse than no variant
    at all — it reads as an instruction the model has to guess at."""
    for lang in ("UK English", "US English", "", None):
        assert "{lang_type}" not in _prompt_for(lang)
        assert "{payload}" not in _prompt_for(lang)


def test_an_unset_variant_still_names_one():
    assert P.DEFAULT_LANG in _prompt_for("")


def test_proofread_passes_the_variant_down():
    seen = []

    def fake_generate(prompt, settings=None, **kw):
        seen.append(prompt)
        return "[]"

    P.proofread(["The organisation analysed the samples and recorded the behaviour "
                 "of every specimen across the whole of the observation period."],
                generate=fake_generate, settings={}, lang_type="UK English")
    assert seen and "UK English" in seen[0]


# ------------------------------- claims about a manuscript the model has not been shown

def _batch_returning(items, paragraphs):
    """Run `llm_findings` against a fixed model response."""
    return P.llm_findings(paragraphs, lambda *a, **k: json.dumps(items), {})


_DEFINED_EARLY = (
    ["Artificial Intelligence (AI) and Machine Learning (ML) have emerged as "
     "transformative forces across the whole of the pharmaceutical industry."]
    + ["Filler text that is long enough to be sent to the model for review." for _ in range(5)]
    + ["ML models were trained on the dataset described in the section above."]
)


def test_an_abbreviation_defined_outside_the_batch_is_not_undefined():
    """`llm_findings` sends 25 paragraphs at a time. Measured on a real manuscript:
    `Machine Learning (ML)` is defined in paragraph 8 and the model reported ML as
    "used without being defined" at paragraph 232 — a claim about a document it was
    never shown. The whole text is right here, so the claim is checkable."""
    findings = _batch_returning(
        [{"index": 6, "fragment": "ML models",
          "problem": "the abbreviation ML is used without being defined"}],
        _DEFINED_EARLY)
    assert findings == []


def test_an_abbreviation_never_expanded_is_still_reported():
    """Narrowed, not deleted: only a bracketed introduction earlier counts, so an
    abbreviation that appears and is never expanded survives."""
    findings = _batch_returning(
        [{"index": 6, "fragment": "ML models",
          "problem": "the abbreviation QRS is not defined anywhere in the manuscript"}],
        _DEFINED_EARLY)
    assert len(findings) == 1


def test_a_consistency_claim_is_not_a_definition_claim():
    """"'IoT' was used previously, but 'IOT' is used here" is a good finding — both
    spellings are inside the model's own batch. It must not be filtered."""
    findings = _batch_returning(
        [{"index": 6, "fragment": "ML models",
          "problem": "'IoT' was used previously, but 'IOT' is used here"}],
        _DEFINED_EARLY)
    assert len(findings) == 1
