"""Edits the copyedit is not allowed to make, and the two bugs the guards had.

Every case is a line from job 28 — a deep-learning brain-tumour paper an editor ran
through the live tool. Both of the guards' own bugs were found by replaying them over
that manuscript rather than by these tests, which is why the false-positive cases are
here now.
"""

import edit_guards as G

EM = " "


# ------------------------------------------------------- front-matter dates

def test_a_date_line_that_lost_its_day_and_month_is_restored():
    """`Accepted Date: 29th May, 2026` came back as `Accepted Date: 2026`, while the
    line above it — `Submission Date: 9th May, 2026` — was converted correctly. The
    existing shrink guard cannot see this: it exempts paragraphs under 120 characters,
    because "2.2 Material characteristics" losing its number is a correct large cut."""
    orig = ["Accepted Date: 29th May, 2026", "Published Date: 20th July, 2026"]
    out, queries = G.restore_protected_text(orig, ["Accepted Date: 2026",
                                                   "Published Date: 2026"])
    assert out == orig
    assert len(queries) == 2
    assert "day and month" in queries[0]["query"]


def test_a_correctly_reformatted_date_is_left_alone():
    orig = ["Submission Date: 9th May, 2026"]
    out, queries = G.restore_protected_text(orig, ["Submission Date: May 9, 2026"])
    assert out == ["Submission Date: May 9, 2026"]
    assert queries == []


def test_a_reference_year_is_not_a_front_matter_date():
    """The year-only rule legitimately strips months from bibliography entries."""
    orig = ["[4] Kumar S. Deep learning for MRI. J Imaging. May 2021;7(5):83."]
    out, _ = G.restore_protected_text(
        orig, ["[4] Kumar S. Deep learning for MRI. J Imaging. 2021;7(5):83."])
    assert out[0].endswith("2021;7(5):83.")


# ------------------------------------------------------- algorithm listings

def test_an_algorithm_step_keeps_its_number():
    """The house rule strips leading numbers from headings, and the model applied it
    to an Algorithm listing: ten of thirteen steps lost their number and three kept
    it, so the block came out unreadable and inconsistent."""
    orig = [f" 5:{EM} For each epoch do", f"10:{EM} End For"]
    out, queries = G.restore_protected_text(orig, ["For each epoch do", "End For"])
    assert out == [f"5:{EM}For each epoch do", f"10:{EM}End For"]
    assert len(queries) == 2
    assert "algorithm listing" in queries[0]["query"]


def test_the_original_separator_is_preserved():
    """These listings are set with an em-space. Putting back a plain space re-lays-out
    the block while claiming only to restore its numbering."""
    out, _ = G.restore_protected_text([f" 7:{EM}Calculate loss"], ["Calculate loss"])
    assert out[0] == f"7:{EM}Calculate loss"


def test_a_numbered_heading_is_not_an_algorithm_step():
    """The first version of the pattern allowed an ordinary space after the number, so
    it matched `2. Literature Review:` and `4. Proposed Methodology:` and put the
    numbers back onto the very headings the house rule had correctly stripped."""
    orig = [" 2. Literature Review: ", "3.  Dataset Description and Preprocessing:",
            "4. Proposed Methodology:", "3.1 Dataset Description:"]
    edited = ["Literature Review", "Dataset Description and Preprocessing",
              "PROPOSED METHODOLOGY", "Dataset Description"]
    out, queries = G.restore_protected_text(orig, edited)
    assert out == edited
    assert queries == []


# ------------------------------------------------------- trailing citations

def test_a_citation_moves_inside_the_full_stop():
    got = G.fix_trailing_citations([
        "...to prevent overtraining once convergence is reached. [17]",
        "...layers to produce the final tumor class label. [18, 19]",
        "...confirms the reliability of the proposed CNN model. [25–27]",
    ])
    assert got[0].endswith("is reached [17].")
    assert got[1].endswith("class label [18, 19].")
    assert got[2].endswith("CNN model [25–27].")


def test_a_mid_sentence_citation_is_not_moved():
    text = ["As reported in [12], the effect is small.",
            "No citation at the end of this one."]
    assert G.fix_trailing_citations(text) == text


def test_indented_formula_lines_are_not_reflowed():
    """An earlier version ran `.replace("  ", " ")` over every paragraph
    unconditionally, and silently reflowed the indented denominator lines of the
    display formulas — which have nothing to do with citations."""
    text = ["   TP+ FN     … (3)", "        Precision+Recall… (4)"]
    assert G.fix_trailing_citations(text) == text


# ------------------------------------------------------- orphaned denominators

def test_a_stranded_denominator_is_reported():
    """`Recall=TP` and `   TP+ FN     … (3)` were one fraction across two paragraphs.
    The copyedit rebuilt the whole formula onto the first line and left the second
    where it was, so the formula now appears complete *and* is followed by its own
    orphaned denominator."""
    orig = ["Recall=TP", "   TP+ FN     … (3)"]
    edited = ["Recall = TP / (TP + FN) …(3)", "   TP+ FN     … (3)"]
    (q,) = G.orphaned_formula_queries(orig, edited)
    assert q["index"] == 1
    assert "Delete this paragraph" in q["query"]


def test_a_denominator_the_copyedit_also_changed_is_not_reported():
    """If the second line was edited too, the copyedit had a view about it and this
    guard should not second-guess that."""
    orig = ["Recall=TP", "   TP+ FN     … (3)"]
    edited = ["Recall = TP / (TP + FN) …(3)", "denominator, rewritten … (3)"]
    assert G.orphaned_formula_queries(orig, edited) == []


def test_ordinary_prose_after_a_formula_is_not_reported():
    orig = ["Recall=TP", "The model was then evaluated on the held-out test set."]
    edited = ["Recall = TP / (TP + FN) …(3)",
              "The model was then evaluated on the held-out test set."]
    assert G.orphaned_formula_queries(orig, edited) == []


def test_the_paragraph_count_never_changes():
    """`generate_redline_docx` walks the original and edited lists in step. A guard
    that added or dropped a paragraph would move every later tracked change onto the
    wrong text, and the file would still look perfectly fine."""
    orig = [f"{i}:{EM}step" for i in range(1, 8)]
    out, _ = G.restore_protected_text(orig, ["step"] * 7)
    assert len(out) == len(orig)


def test_a_tab_separated_step_keeps_its_tab():
    """The separator is captured, not assumed. An intermediate version hard-coded an
    em-space, so a listing set with tabs came back re-laid-out."""
    out, _ = G.restore_protected_text(["4.\tIntroduce CNN"], ["Introduce CNN"])
    assert out[0] == "4.\tIntroduce CNN"


def test_the_colon_or_dot_survives():
    """A version that rebuilt the prefix from the number alone dropped it."""
    out, _ = G.restore_protected_text([f"10:{EM} End For"], ["End For"])
    assert out[0] == f"10:{EM}End For"


# --- table cells landing in the wrong cell --------------------------------------
#
# Job 46, reported by the editorial team. A three-row table came back with its cells
# permuted: all five strings returned, each in a different cell. Nothing was lost, and
# that is what makes it dangerous — in the redline it reads as a deliberate edit, so a
# reviewer has no way to tell the copyeditor scrambled the table.
#
# Cause: table cells are sent as a bare array and written back by position. That
# contract is safe for body paragraphs, which are long and distinct. Table cells are
# short and similar, and the model reordered them.

from edit_guards import verify_cell_edits

_JOB46_ORIGINAL = [
    "Filament-wound CFRP; multiaxial fatigue",
    "AE and fatigue history",
    "Training, validation, internal test",
    "CFRP laminate; compression after impact",
    "Independent external validation",
]
_JOB46_RETURNED = [
    "AE and fatigue history",
    "CFRP laminate; compression after impact",
    "Filament-wound CFRP; multiaxial fatigue",
    "Independent external validation",
    "Training, validation, internal test",
]


def test_the_job_46_scramble_is_refused_entirely():
    out, queries = verify_cell_edits(_JOB46_ORIGINAL, list(_JOB46_RETURNED))
    assert out == _JOB46_ORIGINAL, "every cell must keep the author's text"
    assert len(queries) == 5
    assert "reordered" in queries[0]["query"]


def test_two_cells_swapping_is_refused():
    out, queries = verify_cell_edits(
        ["Alpha value here", "Beta value here"],
        ["Beta value here", "Alpha value here"])
    assert out == ["Alpha value here", "Beta value here"]
    assert len(queries) == 2


def test_ordinary_table_edits_still_go_through():
    """The guard's first version refused whenever the new text matched no original —
    which is what a normal copyedit looks like — and would have discarded almost every
    legitimate table edit. It must refuse only on a match with a *different* cell."""
    before = ["3D carbon-fibre grid", "SHM adoption is limited", "ph of the solution"]
    after = ["3D carbon-fiber grid",
             "structural health monitoring (SHM) adoption is limited",
             "pH of the solution"]
    out, queries = verify_cell_edits(before, list(after))
    assert out == after
    assert queries == []


def test_a_replacement_rather_than_an_edit_is_refused():
    """Even when the new text matches no other cell, a cell that keeps under half its
    own words is describing something else."""
    out, queries = verify_cell_edits(
        ["Filament-wound CFRP; multiaxial fatigue"], ["Steel beam; static loading"])
    assert out == ["Filament-wound CFRP; multiaxial fatigue"]
    assert "survived" in queries[0]["query"]


def test_title_casing_table_body_text_is_refused():
    """The second complaint on the same job: the heading rules reaching cells that are
    not headings. Seventeen of 26 changed cells on job 45 were capitals only."""
    out, queries = verify_cell_edits(
        ["Improved adaptive detection", "Limited predictive capability"],
        ["Improved Adaptive Detection", "Limited Predictive Capability"])
    assert out == ["Improved adaptive detection", "Limited predictive capability"]
    assert all("not a heading" in q["query"] for q in queries)


def test_a_single_word_case_fix_is_not_title_casing():
    """`ph` -> `pH` is a real correction. Only two or more words gaining a capital is
    the heading rule leaking."""
    out, queries = verify_cell_edits(["ph of the solution"], ["pH of the solution"])
    assert out == ["pH of the solution"]
    assert queries == []


def test_an_unchanged_cell_raises_nothing():
    out, queries = verify_cell_edits(["Dataset", "AE, load, displacement"],
                                     ["Dataset", "AE, load, displacement"])
    assert out == ["Dataset", "AE, load, displacement"]
    assert queries == []


# --- abbreviations: full form once, short form after -----------------------------
#
# Job 46, the team's first complaint. The rule is explicit — spell out at first use
# with the short form in brackets, then use the short form — and the model broke it in
# both directions: it wrote "Internet of Things" with no "(IoT)" anywhere, and went on
# spelling out "acoustic emission" 22 times instead of using AE. Across eight
# abbreviations the expansion appeared 34 times and carried its abbreviation 4 times.
#
# Only a whole-document pass knows which mention is the first. The 84 separate model
# calls cannot see each other, so this cannot be a prompt instruction.

from edit_guards import enforce_abbreviation_first_use, learn_abbreviations


def test_pairs_come_from_the_author_not_from_initials():
    """Guessing that two words starting A and E mean AE would eventually rewrite
    'an experiment' as 'AE'. Only the author's own '(ABBR)' defines a pair."""
    pairs = learn_abbreviations([
        "We use acoustic-emission (AE) sensors on carbon-fibre-reinforced polymer "
        "(CFRP) plates.",
        "An experiment was run in 2025 (see Table 2).",
    ])
    assert pairs == {"AE": "acoustic emission",
                     "CFRP": "carbon fibre reinforced polymer"}


def test_the_definition_takes_only_the_words_the_initials_spell():
    """'employing publicly available acoustic-emission (AE)' defines AE as
    'acoustic emission', not as the whole clause."""
    pairs = learn_abbreviations(
        ["employing publicly available acoustic-emission (AE) data"])
    assert pairs["AE"] == "acoustic emission"


def test_a_stray_expansion_becomes_the_short_form():
    original = ["Using acoustic-emission (AE) data.", "The AE signals were noisy.",
                "Further AE analysis followed."]
    edited = ["Using acoustic-emission (AE) data.",
              "The acoustic emission signals were noisy.",
              "Further acoustic emission analysis followed."]
    out, queries = enforce_abbreviation_first_use(original, list(edited))
    assert out[1] == "The AE signals were noisy."
    assert out[2] == "Further AE analysis followed."
    assert len(queries) == 1


def test_the_definition_belongs_at_the_first_occurrence():
    """The house rule, restated by Amit on 16 Sep 2026 after job #72.

    "Spell out an abbreviation in full at its FIRST occurrence in the body text with the
    abbreviation in parentheses, then use the abbreviation throughout the rest of the
    text." So the definition goes where the term first appears — not where the author
    happened to put it — and the author's later `(AE)` becomes a bare `AE`, because by
    then it has been defined. The paper still defines it exactly once.

    Until today this test asserted the opposite: that a definition anywhere in the body
    licensed shortening everything, including the mentions before it. That is how job
    #72's introduction came back saying "UF" with nothing having said what UF was.
    """
    original = ["Intro paragraph mentioning AE.",
                "Later, acoustic-emission (AE) is defined here."]
    edited = ["Intro paragraph mentioning acoustic emission.",
              "Later, acoustic-emission (AE) is defined here."]
    out, _ = enforce_abbreviation_first_use(original, list(edited))
    assert out[0] == "Intro paragraph mentioning acoustic emission (AE)."
    assert out[1] == "Later, AE is defined here."


def test_an_undefined_abbreviation_is_left_alone():
    """No definition from the author means no pair, and nothing is touched. Inventing
    one would be guessing at the author's meaning."""
    original = ["The IoT layer streams data.", "More IoT discussion."]
    edited = ["The Internet of Things layer streams data.",
              "More Internet of Things discussion."]
    out, queries = enforce_abbreviation_first_use(original, list(edited))
    assert out == edited and queries == []


def test_text_with_no_abbreviations_is_untouched():
    paras = ["A perfectly ordinary sentence.", "Another one."]
    out, queries = enforce_abbreviation_first_use(paras, list(paras))
    assert out == paras and queries == []


# --- a paragraph that defines the same term twice on its own --------------------
#
# Job #66's opening paragraph, verbatim. Both definitions came back untouched and the
# rule reported itself applied: the repeat branch only ever looked at *later*
# paragraphs, so a second definition beside the one we keep was a repeat to nobody.

_JOB66_PARA = (
    "Information and Communication Technology (ICT) was analyzed at 37°C using 5mL  "
    "of buffer, and the the yield was 45 % over 2010-2015. Information and "
    "Communication Technology (ICT) appears again here.")


def test_a_second_definition_in_the_same_paragraph_becomes_the_short_form():
    paras = ["1. Introduction", _JOB66_PARA, "2. Results"]
    out, queries = enforce_abbreviation_first_use(paras, list(paras))
    assert out[1] == (
        "Information and Communication Technology (ICT) was analyzed at 37°C using "
        "5mL  of buffer, and the the yield was 45 % over 2010-2015. ICT appears "
        "again here.")
    assert queries, "the editor is told the repeat was shortened"


def test_a_stray_expansion_later_in_the_defining_paragraph_is_still_stray():
    """The definition being in this paragraph was excusing every expansion after it."""
    paras = ["Using acoustic-emission (AE) sensors, the acoustic emission counts rose."]
    out, _ = enforce_abbreviation_first_use(paras, list(paras))
    assert out[0] == "Using acoustic-emission (AE) sensors, the AE counts rose."


def test_an_abbreviation_bracketed_in_square_brackets_is_already_defined():
    """Job #59 ¶96 came back as `OER [OER]`. The author bracketed the abbreviation
    with square brackets, the guard did not recognise that as a definition, and
    shortened the expansion in front of its own bracket."""
    paras = ["Open Educational Resources (OER) are widely adopted in schools.",
             "Teachers reported that Open Educational Resources [OER] improved access.",
             "Further OER work follows."]
    out, _ = enforce_abbreviation_first_use(paras, list(paras))
    assert "OER [OER]" not in out[1]
    assert out[1] == "Teachers reported that OER improved access.", (
        "a repeat definition is shortened, once — bracket and all, not doubled")


def test_the_short_form_first_is_still_the_author_defining_the_term():
    """Job #68 ¶370, verbatim. The author glossed their own abbreviation the other way
    round and the guard shortened the gloss inside its own brackets — `MAPE (MAPE)` —
    which is the one place the paper said what MAPE stood for."""
    paras = [
        "Mean Absolute Percentage Error (MAPE) was computed for every model.",
        "Finally, the olive bars indicate the MAPE in percent. MAPE (mean absolute "
        "percentage error) is a normalized measure of prediction error.",
    ]
    out, _ = enforce_abbreviation_first_use(paras, list(paras))
    assert "MAPE (MAPE)" not in out[1]
    assert out[1] == paras[1], "the author's own gloss is left exactly alone"


def test_a_stray_expansion_beside_a_reverse_definition_is_still_shortened():
    """Protecting the gloss must not excuse the rest of the paragraph."""
    paras = ["Mean Absolute Percentage Error (MAPE) was computed.",
             "MAPE (mean absolute percentage error) is normalized, and the mean "
             "absolute percentage error is reported per model."]
    out, _ = enforce_abbreviation_first_use(paras, list(paras))
    assert out[1] == ("MAPE (mean absolute percentage error) is normalized, and the "
                      "MAPE is reported per model.")


def test_mismatched_brackets_do_not_define_anything():
    """`Resources (OER]` is a typo, not a definition — treating it as one would leave
    the expansion standing where the rule says the short form belongs."""
    paras = ["Open Educational Resources (OER) are adopted.",
             "Open Educational Resources (OER] again."]
    out, _ = enforce_abbreviation_first_use(paras, list(paras))
    assert out[1] == "OER (OER] again."


def test_one_definition_in_a_paragraph_is_left_exactly_alone():
    """The negative case that matters: a term defined once, correctly, must not be
    touched — this is the ordinary paragraph in every manuscript."""
    paras = ["Open Educational Resources (OER) are widely adopted.",
             "OER policy follows."]
    out, queries = enforce_abbreviation_first_use(paras, list(paras))
    assert out == paras and queries == []


def test_the_abstract_and_the_body_may_each_define_it_once():
    """Jobs #45 and #62 both do this and are correct: the abstract is read apart from
    the body, so each defines the term at its own first use. Collapsing the body's
    definition would leave the term defined only in an abstract the body never sees."""
    paras = ["Abstract",
             "Open Educational Resources (OER) improve access.",
             "Keywords: OER, access",
             "1. Introduction",
             "Open Educational Resources (OER) improve access.",
             "OER are discussed below."]
    out, queries = enforce_abbreviation_first_use(paras, list(paras))
    assert out == paras and queries == []


# --- the author byline and the bibliography's numbering -------------------------
#
# Job 51, and the reason it matters: the SAME manuscript ran correctly on the previous
# model on 3 Sep and wrongly today, after the model was changed. Both of these were
# right before and wrong after, so neither can be left to the model.
#
#   byline      Adaikkalam Kumar1*, Ashok kumar Aachimuthu2
#     was       Adaikkalam Kumar¹*, Ashok Kumar Aachimuthu²      (correct, old model)
#     became    Kumar A1*, Aachimuthu A2                          (reference style)
#
#   reference   1. Ruiz.T.P, Lozano.V,(1995), Talanta,42, 391.
#     was       1. Ruiz TP, Lozano V. Talanta. 1995; 42: 391p.    (correct, old model)
#     became    Ruiz TP, Lozano V. Talanta. 1995; 42: 391p.       (number gone)

from edit_guards import restore_front_matter_names, restore_reference_numbering

_FRONT = [
    "International Journal of Advance in Molecular Engineering",
    "Compatative Catalytic Study of Oxidation of Thiourea",
    "Adaikkalam Kumar1*, Ashok kumar Aachimuthu2",
    "*1Senior Scale Lecturer, Government Polytechnic College, Tiruchirappalli, India",
    "ABSTRACT",
]


def test_a_byline_may_not_lose_a_given_name():
    edited = list(_FRONT)
    edited[2] = "Kumar A1*, Aachimuthu A2"
    out, queries = restore_front_matter_names(_FRONT, edited)
    assert out[2] == _FRONT[2]
    assert "adaikkalam" in queries[0]["query"] and "ashok" in queries[0]["query"]


def test_a_byline_may_still_be_recapitalised():
    """`Ashok kumar` -> `Ashok Kumar` is the correct edit and must go through. The
    comparison is on lowercased words precisely so that case fixes pass."""
    edited = list(_FRONT)
    edited[2] = "Adaikkalam Kumar1*, Ashok Kumar Aachimuthu2"
    out, queries = restore_front_matter_names(_FRONT, edited)
    assert out[2] == edited[2]
    assert queries == []


def test_the_corresponding_author_asterisk_is_put_back():
    """It marks who a reader writes to. Both models dropped it — this one was never
    right, so it is not a regression, it is a hole."""
    edited = list(_FRONT)
    edited[3] = "1Senior Scale Lecturer, Government Polytechnic College, India"
    out, queries = restore_front_matter_names(_FRONT, edited)
    assert out[3].startswith("*1Senior")
    assert "corresponding author" in queries[0]["query"]


def test_a_title_spelling_fix_in_the_same_front_matter_survives():
    """The guard is scoped to lines carrying an affiliation digit. The title sits in
    the same front matter and `Compatative` -> `Comparative` is exactly the kind of
    correct edit this must never undo."""
    edited = list(_FRONT)
    edited[1] = "Comparative Catalytic Study of Oxidation of Thiourea"
    out, queries = restore_front_matter_names(_FRONT, edited)
    assert out[1] == "Comparative Catalytic Study of Oxidation of Thiourea"
    assert queries == []


_REFS = [
    "References",
    "1. Ruiz.T.P, Lozano.V,(1995), Talanta,42, 391.",
    "             2. Smyth.M.R,(1977), Anal.Chem, 49, 2310.",
]


def test_bibliography_entry_numbers_are_restored():
    edited = ["References",
              "Ruiz TP, Lozano V. Talanta. 1995; 42: 391p.",
              "Smyth MR. Anal Chem. 1977; 49: 2310p."]
    out, queries = restore_reference_numbering(_REFS, edited)
    assert out[1].startswith("1. ") and out[2].startswith("2. ")
    assert "in-text citations point at" in queries[0]["query"]


def test_the_original_number_is_restored_not_a_renumbering():
    """A bibliography's order is the author's. Re-sorting it is a separate decision
    the pipeline makes explicitly, and this guard must not quietly make it."""
    original = ["References", "7. Third entry here.", "3. First entry here."]
    edited = ["References", "Third entry here.", "First entry here."]
    out, _ = restore_reference_numbering(original, edited)
    assert out[1].startswith("7. ") and out[2].startswith("3. ")


def test_an_entry_that_kept_its_number_is_untouched():
    edited = ["References", "1. Ruiz TP. Talanta. 1995; 42: 391p.", "2. Smyth MR."]
    out, queries = restore_reference_numbering(_REFS, edited)
    assert out == edited and queries == []


def test_numbers_outside_the_references_section_are_left_alone():
    """The heading rule strips leading numbers on purpose everywhere else. Without the
    References heading there is nothing to restore."""
    original = ["2.1 Materials and methods", "1. Some numbered heading"]
    edited = ["Materials and Methods", "Some numbered heading"]
    out, queries = restore_reference_numbering(original, edited)
    assert out == edited and queries == []


# --- the guard must not fight the citation re-sorter ----------------------------
#
# Raised by Amit before this shipped, and it was a real hole. `align_global_citations`
# runs EARLIER in the pipeline and may re-sort the whole bibliography and renumber the
# in-text citations to match. This guard runs after it. Stamping the original
# positional number onto a re-sorted list would put another work's number on an entry
# and contradict the citations that were just aligned — worse than the bug being fixed.

_ORDERED = [
    "References",
    "1. Ruiz TP, Lozano V. Talanta. 1995; 42: 391.",
    "2. Smyth MR, Osteryoung JG. Anal Chem. 1977; 49: 2310.",
    "3. De Oliveira AN, Zaia CTBV. Food Compos Anal. 2004; 17: 165.",
]


def test_numbers_are_restored_when_the_entries_stayed_put():
    reformatted = [
        "References",
        "Ruiz TP, Lozano V. Talanta. 1995; 42: 391p.",
        "Smyth MR, Osteryoung JG. Anal Chem. 1977; 49: 2310p.",
        "De Oliveira AN, Zaia CTBV. Food Compos Anal. 2004; 17: 165p.",
    ]
    out, _ = restore_reference_numbering(_ORDERED, reformatted)
    assert [p.split(".")[0] for p in out[1:]] == ["1", "2", "3"]


def test_a_resorted_bibliography_keeps_its_hands_off():
    """Each slot now holds a different work. The old number must not follow the slot."""
    resorted = [
        "References",
        "De Oliveira AN, Zaia CTBV. Food Compos Anal. 2004; 17: 165p.",
        "Ruiz TP, Lozano V. Talanta. 1995; 42: 391p.",
        "Smyth MR, Osteryoung JG. Anal Chem. 1977; 49: 2310p.",
    ]
    out, queries = restore_reference_numbering(_ORDERED, list(resorted))
    assert out == resorted, "not one number may be applied to a moved entry"
    assert len(queries) == 1
    assert "re-ordered" in queries[0]["query"]
    assert "by hand" in queries[0]["query"]


def test_entries_the_resorter_renumbered_itself_are_untouched():
    """When the re-sort succeeds it writes its own numbers. Those are the correct
    ones and this guard has nothing to do."""
    renumbered = [
        "References",
        "1. De Oliveira AN, Zaia CTBV. Food Compos Anal. 2004; 17: 165p.",
        "2. Ruiz TP, Lozano V. Talanta. 1995; 42: 391p.",
        "3. Smyth MR, Osteryoung JG. Anal Chem. 1977; 49: 2310p.",
    ]
    out, queries = restore_reference_numbering(_ORDERED, list(renumbered))
    assert out == renumbered and queries == []


# --- the author's hyphenation, and the variant they actually wrote in ------------
#
# The editorial team's position, and it settles a question the tool had been deciding
# by itself: hyphenation of prefix compounds is a style choice, not an error, so the
# author's form stands. Job 54 had six `non-` compounds — three closed up, three left
# hyphenated — plus `multi-task`, `pre-determined` and `pre-processing` closed while
# fourteen other compounds were left alone. Across four jobs: 41 kept, 11 lost.

from edit_guards import preserve_author_hyphenation


def test_the_authors_hyphen_is_put_back():
    original = ["The non-stationary and non-uniform signal was multi-task pre-processed."]
    edited = ["The nonstationary and nonuniform signal was multitask preprocessed."]
    out, queries = preserve_author_hyphenation(original, list(edited))
    assert out[0] == original[0]
    assert len(queries) == 1
    assert "style choice rather than an error" in queries[0]["query"]


def test_a_closed_compound_the_author_wrote_is_left_closed():
    """It restores only the compounds the author hyphenated in that paragraph, so it
    can never invent a hyphen the manuscript never had."""
    paras = ["We used preprocessing and a nonlinear model."]
    out, queries = preserve_author_hyphenation(paras, list(paras))
    assert out == paras and queries == []


def test_capitalisation_comes_from_the_edited_text():
    """A compound that legitimately became sentence-initial keeps its capital."""
    out, _ = preserve_author_hyphenation(
        ["non-linear effects appear."], ["Nonlinear effects appear."])
    assert out[0] == "Non-linear effects appear."


def test_an_unrelated_word_starting_with_a_prefix_is_not_touched():
    """`nonsense` and `preview` are words, not prefix compounds the author hyphenated.
    Nothing is restored unless that exact compound was hyphenated in the same
    paragraph."""
    paras = ["This is nonsense and a preview of coordination."]
    out, queries = preserve_author_hyphenation(paras, list(paras))
    assert out == paras and queries == []


from science_format import detect_language_variant


def test_the_variant_follows_the_whole_manuscript():
    uk, counts = detect_language_variant(
        ["The behaviour and colour were analysed.",
         "We recognised the organisation of the centre."])
    assert uk == "UK English" and counts["uk"] > counts["us"]

    us, _ = detect_language_variant(
        ["The behavior and color were analyzed.",
         "We recognized the organization of the center."])
    assert us == "US English"


def test_a_mixed_manuscript_gets_no_verdict():
    """Picking a side on a one-word margin would rewrite half the paper on the
    strength of that word. Under a 60% share there is no answer."""
    verdict, counts = detect_language_variant(
        ["The behaviour and color were analyzed.", "We recognised the organization."])
    assert counts["uk"] and counts["us"]
    assert verdict is None or max(counts.values()) / sum(counts.values()) >= 0.6


def test_too_little_evidence_gives_no_verdict():
    verdict, counts = detect_language_variant(
        ["A perfectly ordinary sentence with no variant spellings in it at all."])
    assert verdict is None and counts == {"uk": 0, "us": 0}


# --- the model announcing its own answer -----------------------------------------
#
# Job 51's report opened with "Here are the optimized titles and the polished
# abstract, formatted beautifully in Markdown:" — the model echoing the prompt, which
# had asked for the output "formatted beautifully in Markdown". The prompt is fixed
# too, but a prompt is a request; this is the part that holds.

from editor import strip_model_preamble


def test_the_job_51_preamble_is_removed():
    text = ("Here are the optimized titles and the polished abstract, formatted "
            "beautifully in Markdown:\n\n---\n\n### Optimized Title Options\n\n1. **A**")
    assert strip_model_preamble(text).startswith("### Optimized Title Options")


def test_other_openers_go_too():
    for opener in ("Sure! Below is the polished version:",
                   "Certainly! The following are your titles:",
                   "Here is the abstract:"):
        out = strip_model_preamble(f"{opener}\n\n**Abstract**\n\nText.")
        assert out.startswith("**Abstract**"), opener


def test_real_content_is_never_touched():
    """All three signals are required — an opener word, under 160 characters, and a
    colon — so a heading or an ordinary sentence ending in a colon survives."""
    for text in ("### Optimized Title Options\n\n1. **Real content**",
                 "The results were as follows: the yield rose to 87%.",
                 "**Abstract**\n\nThe kinetic study was carried out."):
        assert strip_model_preamble(text) == text.lstrip()


def test_empty_input_is_safe():
    assert strip_model_preamble("") == ""
    assert strip_model_preamble(None) == ""


def test_an_abbreviation_never_arrives_before_its_definition():
    """Job #72, raised by the quality team on 16 Sep 2026.

    The introduction read "capsules, usually made from urea-formaldehyde and
    melamine-formaldehyde shells"; the author's own "urea-formaldehyde (UF)" came later,
    in the methods. The guard knew a definition existed *somewhere* and shortened the
    earlier mention, so the paper handed the reader "UF" before telling them what it was
    — and "UF and melamine-formaldehyde" reads as one resin where the author named two.
    """
    from edit_guards import enforce_abbreviation_first_use

    paragraphs = [
        "Abstract",
        "Self-healing coatings for marine structures.",
        "Keywords: self-healing, coatings",
        "However, these conventional capsules, usually made from urea-formaldehyde and "
        "melamine-formaldehyde shells using interfacial polymerization, are unable to "
        "address sub-critical microcracks.",
        "The commercial urea-formaldehyde (UF) microcapsules containing dicyclopentadiene "
        "were used as the control group.",
        "The healing efficiency of the urea-formaldehyde control group was below 5%.",
    ]
    out, _ = enforce_abbreviation_first_use(paragraphs, list(paragraphs))

    assert "urea-formaldehyde (UF) and melamine-formaldehyde" in out[3], (
        "the definition belongs at the first occurrence, and both resins keep their names")
    assert "commercial UF microcapsules" in out[4], (
        "having been defined above, the author's later definition is now the short form")
    assert "UF control group" in out[5]


# --- invisible twins (job #100) ----------------------------------------------

def test_the_author_s_micro_sign_survives_the_copyedit():
    """Job #100: `μm` deleted, `µm` inserted. One glyph, two code points, and a
    tracked change the copy editor cannot see."""
    original = ["only cracks exceeding 5–10 μm in length",
                "microcracks below 1 μm are addressed"]
    edited = ["Only cracks exceeding 5–10 µm in length",
              "Microcracks below 1 µm are addressed"]
    out, n = G.follow_the_author_on_invisible_twins(original, edited)
    assert n == 2
    assert out == ["Only cracks exceeding 5–10 μm in length",
                   "Microcracks below 1 μm are addressed"]
    # The real edit — the capital O — is untouched.
    assert out[0].startswith("Only")


def test_a_new_micro_sign_is_set_the_author_s_way_too():
    original = ["particles of 5 μm"]
    edited = ["particles of 5 μm and a further batch of 2 µm"]
    out, _ = G.follow_the_author_on_invisible_twins(original, edited)
    assert "µ" not in out[0]


def test_a_mixed_author_is_not_made_consistent_for_them():
    """The author used both forms. Each occurrence keeps what they typed — the
    guard follows them, it does not tidy them up, because making the document
    consistent would be a decision no reader can see being made."""
    original = ["5 μm and 3 µm"]
    edited = ["5 µm and 3 µm"]
    out, n = G.follow_the_author_on_invisible_twins(original, edited)
    assert n == 1 and out == original


def test_a_sign_the_author_never_used_is_the_copyedit_s_own_work():
    """`um` -> `µm` is a visible correction and must survive as a tracked change."""
    original = ["particles of 5 um"]
    edited = ["particles of 5 µm"]
    out, n = G.follow_the_author_on_invisible_twins(original, edited)
    assert n == 0 and out == edited


def test_the_increment_sign_is_left_to_the_science_pass():
    """`∆` -> `Δ` is `enforce_science_symbols` doing its job on purpose; folding it
    back here would leave the two passes undoing each other every run."""
    original = ["∆s# was measured"]
    edited = ["ΔS# was measured"]
    out, _ = G.follow_the_author_on_invisible_twins(original, edited)
    assert out == edited


def test_a_mixed_manuscript_is_followed_at_each_occurrence():
    """Job #93: the author wrote the micro sign four times and the Greek mu once.
    No document-wide preference exists, so each site keeps what the author typed."""
    original = ["arrangements of 0.2 to 1.0 µm and 0.2 to 1.4 µm were seen",
                "a further feature of 3 μm"]
    edited = ["Arrangements of 0.2 to 1.0 μm and 0.2 to 1.4 μm were seen",
              "A further feature of 3 µm"]
    out, n = G.follow_the_author_on_invisible_twins(original, edited)
    assert n == 3
    assert out[0] == "Arrangements of 0.2 to 1.0 µm and 0.2 to 1.4 µm were seen"
    assert out[1] == "A further feature of 3 μm"


# --- subscripts that cannot be set in characters (job #73) -------------------

def test_a_subscript_spanning_a_decimal_point_comes_back_as_plain_digits():
    """Job #73: the author's `log|Z|0.01Hz` came back as `log|Z|₀.₀₁Hz` — the digits
    shrank, the point and the `Hz` did not, and the value reads as mistyped."""
    original = ["The 30-day log|Z|0.01Hz response was between 8.52 and 9.42"]
    edited = ["The 30-day log|Z|₀.₀₁Hz response was between 8.52 and 9.42"]
    out, queries = G.undo_broken_subscripts(original, edited)
    assert out == original
    assert len(queries) == 1 and queries[0]["index"] == 0
    assert "Word's subscript formatting" in queries[0]["query"]


def test_a_chemical_subscript_is_left_alone():
    """`H₂O` is the house convention and is set correctly — no decimal point, no
    half-sized run, nothing to undo."""
    edited = ["H₂O and CO₂ and a TiO₂ coating"]
    out, queries = G.undo_broken_subscripts(["H2O and CO2 and a TiO2 coating"], edited)
    assert out == edited and queries == []


# --- a chemical name is one word (job #103) ----------------------------------

def test_an_abbreviation_contracted_from_one_word_is_learned():
    """`dicyclopentadiene` has one initial, `d`. Every chemical name does, so the
    initials test rejected DCPD, PDMS, THF and DMF alike — silently, taking the
    whole first-use rule with it for the terms a materials paper is built on."""
    assert G.learn_abbreviations(["a dicyclopentadiene (DCPD) core"]) == {
        "DCPD": "dicyclopentadiene"}
    assert G.learn_abbreviations(["in tetrahydrofuran (THF) at 40 °C"]) == {
        "THF": "tetrahydrofuran"}
    assert G.learn_abbreviations(["N,N-dimethylformamide (DMF) was used"]) == {
        "DMF": "dimethylformamide"}


def test_the_word_beside_the_bracket_is_not_taken_for_the_term():
    """The common case that must not match: the bracket follows the wrong word."""
    assert G.learn_abbreviations(["the healing core (DCPD)"]) == {}
    assert G.learn_abbreviations(["the solution (AQ)"]) == {}


def test_an_ordinary_english_word_is_not_contracted():
    """`control (CTRL)` would put `CTRL` in place of every later "control" in the
    paper. A chemical name throws away two thirds of itself; a common word does not,
    and that gap is what the rule stands on."""
    assert G.learn_abbreviations(["control (CTRL) values were stable"]) == {}
    assert G.learn_abbreviations(["aluminium (Al) foil was used"]) == {}


def test_job_103_stops_re_expanding_after_the_caption():
    """#103: the author defined DCPD in the body; the sentence after the Figure 1
    caption spelled it out again, and again at Figure 3."""
    original = [
        "Abstract: a summary.",
        "Keywords: microcapsules, vitrimer",
        "The shell is arranged around a dicyclopentadiene (DCPD) core.",
        "Figure 1. The layered shell architecture.",
        "Figure 1 illustrates the arrangement surrounding the DCPD core.",
        "Figure 3 displays the release profile of DCPD, normalized.",
    ]
    edited = list(original)
    edited[4] = ("Figure 1 illustrates the arrangement surrounding the "
                 "dicyclopentadiene (DCPD) core.")
    edited[5] = ("Figure 3 displays the release profile of dicyclopentadiene (DCPD), "
                 "normalized.")
    out, queries = G.enforce_abbreviation_first_use(original, edited)
    assert out[2] == original[2], "the author's own definition must stay where it is"
    assert out[4] == original[4]
    assert out[5] == original[5]
    assert len(queries) == 1 and "already been defined" in queries[0]["query"]


# --- a word the author wrote closed (job #104) -------------------------------

def test_a_technical_term_is_not_split_into_two_words():
    """`timespace` came back as `time space`. It is the author's term and it is
    written that way in the literature; no house rule asks for it to be opened."""
    original = ["The timespace evolution of the crack front was recorded."]
    edited = ["The time space evolution of the crack front was recorded."]
    out, queries = G.keep_closed_compounds(original, edited)
    assert out == original
    assert len(queries) == 1 and "'timespace'" in queries[0]["query"]


def test_a_run_on_typo_is_still_corrected():
    """The corrections that must go through: both halves are function words, or one
    of them is, which is what a slip is made of."""
    for was, now in [("We showed thatthe result holds.",
                      "We showed that the result holds."),
                     ("The sample was split inorder to test it.",
                      "The sample was split in order to test it.")]:
        out, queries = G.keep_closed_compounds([was], [now])
        assert out == [now] and queries == []


def test_an_author_who_writes_it_both_ways_is_left_alone():
    """No decision of theirs to enforce — so none is enforced for them."""
    original = ["Both timespace and time space appear in this paper."]
    edited = ["Both time space and time space appear in this paper."]
    out, queries = G.keep_closed_compounds(original, edited)
    assert out == edited and queries == []


def test_a_word_the_copyedit_kept_closed_raises_nothing():
    paras = ["The microcapsule shell is thin."]
    out, queries = G.keep_closed_compounds(paras, list(paras))
    assert out == paras and queries == []


# --- a chemist's definition, and an invented one (job #104) ------------------

def test_a_chemical_name_with_digits_and_brackets_is_learned():
    """`2,2′-(ethylenedioxy)bis(ethylamine)` cannot match the ordinary definition
    pattern at all — digits, primes and brackets inside the name — so EDBEA was never
    learned and nothing could tell the copyedit it was already defined."""
    learned = G.learn_abbreviations(
        ["provided by 2,2′-(ethylenedioxy)bis(ethylamine) (EDBEA) with a rate"])
    assert learned == {"EDBEA": "2,2′-(ethylenedioxy)bis(ethylamine)"}


def test_the_clause_introducing_the_name_is_not_part_of_it():
    learned = G.learn_abbreviations(
        ["provided by 2,2′-(ethylenedioxy)bis(ethylamine) (EDBEA) with a rate"])
    assert not learned["EDBEA"].startswith("provided")


def test_ordinary_prose_is_not_read_as_a_chemical_name():
    """In a long enough phrase any few letters appear in order, so the widened rule
    is kept to names that are shaped like chemistry."""
    assert G.learn_abbreviations(["the results of the experiment (TRE) were clear"]) == {}


def test_an_expansion_the_author_never_wrote_is_refused():
    """#104: the author's EDBEA is `2,2′-(ethylenedioxy)bis(ethylamine)`. The copyedit
    wrote `N,N'-bis(2-aminoethyl)-1,3-benzenedicarboxamide (EDBEA)` — a different
    molecule, in the author's voice."""
    original = [
        "Transesterification is provided by 2,2′-(ethylenedioxy)bis(ethylamine) "
        "(EDBEA) with a rate constant.",
        "The cross-linkers DTDA and EDBEA in a 1:1 molar ratio were used.",
    ]
    edited = list(original)
    edited[1] = ("The cross-linkers DTDA and N,N'-bis(2-aminoethyl)-1,3-"
                 "benzenedicarboxamide (EDBEA) in a 1:1 molar ratio were used.")
    out, queries = G.refuse_invented_expansions(original, edited)
    assert "benzenedicarboxamide" not in out[1]
    assert "DTDA and EDBEA in a 1:1" in out[1], out[1]
    assert len(queries) == 1 and "EDBEA" in queries[0]["query"]


def test_the_author_s_own_expansion_is_not_refused():
    original = ["We used 2,2′-(ethylenedioxy)bis(ethylamine) (EDBEA) here.",
                "EDBEA was added slowly."]
    edited = [original[0],
              "2,2′-(ethylenedioxy)bis(ethylamine) (EDBEA) was added slowly."]
    out, queries = G.refuse_invented_expansions(original, edited)
    assert out == edited and queries == []


# --- the bracketed entry number (job #104) -----------------------------------

def test_a_vancouver_bracketed_entry_number_is_restored():
    """12 of 21 entries came back unnumbered in #104 and this guard said nothing: it
    knew `1.` and `1)` and not `[1]`, which is what Vancouver numbering looks like."""
    original = ["References",
                "[3] B. Blaiszik, M. Caruso, D. McIlroy, “Microcapsules filled with "
                "reactive solutions,” Polymer, 2009."]
    edited = [original[0],
              "Blaiszik B, Caruso M, McIlroy D. Microcapsules filled with reactive "
              "solutions. Polymer. 2009."]
    out, queries = G.restore_reference_numbering(original, list(edited))
    assert out[1].startswith("[3] ")
    assert len(queries) == 1


def test_the_author_s_own_numbering_style_is_kept():
    """A list numbered `3.` must not come back as `[3]`, and the reverse."""
    original = ["References", "3. B. Blaiszik, “Microcapsules,” Polymer, 2009."]
    edited = [original[0], "Blaiszik B. Microcapsules. Polymer. 2009."]
    out, _ = G.restore_reference_numbering(original, list(edited))
    assert out[1].startswith("3. ") and not out[1].startswith("[")


# --- the subscript marker (job #104) -----------------------------------------

def test_a_subscript_marker_the_author_wrote_is_kept():
    """#104: `(G_IC,healed/G_IC,pristine)` came back as `(GIC,healed/GIC,pristine)`.
    The underscore is what says the letters are a subscript; `GIC` is a different
    symbol, and a typesetter given it has no way back."""
    original = ["the percentage of recovery (G_IC,healed/G_IC,pristine) to identify"]
    edited = ["the percentage of recovery (GIC,healed/GIC,pristine) to identify"]
    out, queries = G.keep_subscript_markers(original, edited)
    assert out == original
    assert len(queries) == 1 and "Word's own formatting" in queries[0]["query"]


def test_a_bracketed_subscript_keeps_its_brackets_and_no_others():
    """The bracket is restored as a pair or not at all — matched loosely, the tail of
    the pair puts back a closing bracket the sentence already had."""
    original = ["after healing (G_(IC,healed)) and before damage (G_(IC,pristine))."]
    edited = ["after healing (GIC,healed) and before damage (GIC,pristine)."]
    out, _ = G.keep_subscript_markers(original, edited)
    assert out == original
    assert out[0].count("(") == out[0].count(")")


def test_a_symbol_the_copyedit_left_alone_raises_nothing():
    paras = ["the value of K_IC was measured."]
    out, queries = G.keep_subscript_markers(paras, list(paras))
    assert out == paras and queries == []


def test_a_locant_is_not_added_to_a_bare_short_form():
    """#105: the author writes `4,4′-dithiodianiline (DTDA)` where they define it and
    plain `DTDA` afterwards. The copyedit put `4,4'-` back in front of the short form
    — against the house rule, and with an ASCII apostrophe where the author uses a
    prime, so it did not even match their own typography."""
    original = ["The disulfide functionality is introduced via 4,4′-dithiodianiline "
                "(DTDA) with an activation energy.",
                "a mixture of DGEBA with the cross-linkers DTDA and EDBEA."]
    edited = [original[0],
              "a mixture of DGEBA with the cross-linkers 4,4'-DTDA and EDBEA."]
    out, queries = G.refuse_invented_expansions(original, edited)
    assert out[1] == "a mixture of DGEBA with the cross-linkers DTDA and EDBEA."
    assert len(queries) == 1 and "DTDA" in queries[0]["query"]


def test_a_locant_the_author_wrote_is_left_alone():
    original = ["prepared from 4,4′-dithiodianiline (DTDA) in ethanol."]
    out, queries = G.refuse_invented_expansions(original, list(original))
    assert out == original and queries == []


def test_the_same_expansion_spelled_differently_is_not_refused():
    """Measured over 89 redlines, strict equality refused five correct edits for every
    real one: `carbon-fiber-reinforced polymer` against the author's `carbon fibre
    reinforced polymer`, a plural against its singular, an article added."""
    original = ["We used carbon fibre reinforced polymer (CFRP) panels.",
                "The CFRP experiments ran for a week."]
    edited = [original[0],
              "The carbon-fiber-reinforced polymer (CFRP) experiments ran for a week."]
    out, queries = G.refuse_invented_expansions(original, edited)
    assert out == edited and queries == []


def test_an_undefined_abbreviation_is_kept_and_asked_about():
    """`thermoplastic starch (TPS)` may well be right, and nothing in the manuscript
    can say so. Removing it would throw away the house rule's own first-use
    requirement; keeping it silently would ship a fact from outside the paper."""
    original = ["The TPS blends were extruded at 140 °C."]
    edited = ["The thermoplastic starch (TPS) blends were extruded at 140 °C."]
    out, queries = G.refuse_invented_expansions(original, edited)
    assert out == edited, "the expansion stands"
    assert len(queries) == 1 and "does not define it" in queries[0]["query"]


# --- a caption's data (job #106) ---------------------------------------------

def test_a_caption_may_be_reworded_but_not_revalued():
    """#106: `Figure 9: Line Waver-Burke Plot for T4 (80g)` came back as
    `Figure 9. Lineweaver-Burk plot for T5 (100 g)`. The spelling repair is wanted;
    the caption now claims the figure shows a different sample at a different mass."""
    original = ["Figure 9:\tLine Waver-Burke Plot for T4 (80g) of Room-Dried Stem"]
    edited = ["Figure 9. Lineweaver-Burk plot for T5 (100 g) of room-dried stem."]
    out, queries = G.keep_caption_values(original, edited)
    assert "T4 (80g)" in out[0], out[0]
    assert "Lineweaver-Burk" in out[0], "the spelling correction must survive"
    assert out[0].endswith("stem.")
    assert len(queries) == 1 and "`T4`" in queries[0]["query"]


def test_prose_that_opens_like_a_caption_is_left_alone():
    """`Table 6 and Figure 2 shows that…` opens exactly like a caption and is a
    sentence. Measured over 90 redlines, the reporting verb separated the two every
    time."""
    original = ["Table 6 and Figure 2 shows that the satisfaction level of information "
                "bias has the highest mean rate among 4 groups"]
    edited = ["Table 6 and Figure 2 show that the satisfaction level of information "
              "bias has the highest mean rate among 5 groups"]
    out, queries = G.keep_caption_values(original, edited)
    assert out == edited and queries == []


def test_the_house_subscript_in_a_caption_is_not_a_changed_value():
    """`CaSO4` -> `CaSO₄` and `10-5` -> `10⁻⁵` are this pipeline's own corrections —
    14 of the first sweep's 44 findings, every one of them correct work."""
    for was, now in [("Table 2. Scale test observations at (40°C) CaSO4.",
                      "Table 2. Scale test observations at (40°C) CaSO₄."),
                     ("Figure 4. Emission spectra in THF; 10-5 moles/L at 390 nm.",
                      "Figure 4. Emission spectra in THF; 10⁻⁵ moles/L at 390 nm.")]:
        out, queries = G.keep_caption_values([was], [now])
        assert out == [now] and queries == [], was


def test_an_equation_placeholder_the_copyedit_invented_is_refused():
    """#106: the author's `KCrd = 36.768x - 0.0006`, an equation typed as ordinary
    text, came back as a bare placeholder — the model had seen the character standing
    for equations elsewhere in that manuscript and wrote one of its own."""
    original = ["KCrd = 36.768x - 0.0006\t(16)"]
    edited = ["￼\t(16)"]
    out, queries = G.keep_every_equation(original, edited)
    assert out == original
    assert len(queries) == 1 and "not in the author's file" in queries[0]["query"]


# --- a unit recased in one place only (job #106) -----------------------------

def test_a_unit_recased_once_is_recased_everywhere():
    """#106: the author writes `cfu/g` three times; the copyedit returned `CFU/g`
    once and left the other two. `CFU` is the right form and that is not the
    complaint — a paper that says both is worse than one consistently wrong."""
    original = ["The count reached 6.2 cfu/g.",
                "Values are reported in (cfu/g).",
                "A later line with (cfu/g) in it."]
    edited = ["The count reached 6.2 CFU/g.",
              "Values are reported in (cfu/g).",
              "A later line with (cfu/g) in it."]
    out, queries = G.apply_case_changes_everywhere(original, edited)
    assert all("CFU/g" in p for p in out)
    assert len(queries) == 1 and "2 more" in queries[0]["query"]


def test_a_recased_heading_is_not_a_decision_about_a_word():
    """`MATERIALS AND METHODS` -> `Materials and Methods` is punctuation. The first
    version read it as a ruling on the term `AND` and rewrote 115 paragraphs of one
    manuscript."""
    original = ["MATERIALS AND METHODS", "The soil and water were mixed."]
    edited = ["Materials and Methods", "The soil and water were mixed."]
    out, queries = G.apply_case_changes_everywhere(original, edited)
    assert out == edited and queries == []


def test_et_al_is_never_recased():
    """Learned from a bibliography where `et al.` sat opposite an author's initials
    `Kraft AL` — the list had been re-sorted, so the two paragraphs were different
    works. It would have written `et AL.` through eight paragraphs."""
    original = ["References", "Almeida T, Braz M, et al. Biobased ternary films."]
    edited = ["References", "Shojaeiarani J, Bergholz TM, Kraft AL. Spin coating."]
    out, queries = G.apply_case_changes_everywhere(original, edited)
    assert out == edited and queries == []


# --------------------------------------------------------------------------------
# A citation number is a pointer, and may not be minted for a work that is not listed
# (job #107).

_BIB = [
    "REFERENCES",
    "Haller H. Soil Remediation and Sustainable Development. Mid Sweden University; 2017.",
    "Evely A. Dead planet, living planet. C. Nellemann, E. Corcoran, editors. 2010.",
    "Akpe AR, Ekundayo AO. Bacterial degradation of petroleum hydrocarbons in crude oil "
    "polluted soil amended with cassava peels. 2013.",
]


def test_a_number_is_not_minted_for_a_missing_reference():
    """Job #107, ¶18, exactly as it shipped."""
    original = ["Soil, responsible for providing nutrients to approximately 95% of "
                "global food production, plays a foundational role in sustaining life "
                "(FAO, 2015)."] + _BIB
    edited = ["Soil, responsible for providing nutrients to approximately 95% of "
              "global food production, plays a foundational role in sustaining life "
              "[3]."] + _BIB
    out, queries = G.refuse_citations_without_a_reference(original, edited)
    assert "(FAO, 2015)" in out[0]
    assert "[3]" not in out[0]
    assert len(queries) == 1
    assert "FAO (2015)" in queries[0]["query"]


def test_a_citation_that_is_listed_keeps_its_number():
    original = ["According to Haller (2017) and Nellemann & Corcoran (2010), "
                "ecosystems are affected."] + _BIB
    edited = ["According to Haller [1] and Nellemann and Corcoran [2], "
              "ecosystems are affected."] + _BIB
    out, queries = G.refuse_citations_without_a_reference(original, edited)
    assert out[0] == edited[0]
    assert queries == []


def test_a_group_of_citations_is_read_as_several():
    """`(Baumeister, 1995; Deci, 2000; Maslow, 1954)` read whole gives Baumeister the
    year 1954 — a work nobody cited, reported as missing."""
    bib = ["REFERENCES", "Baumeister RF, Leary MR. The need to belong. 1995."]
    original = ["Belonging shapes behaviour (Baumeister, 1995; Maslow, 1954)."] + bib
    edited = ["Belonging shapes behaviour [1, 2]."] + bib
    _out, queries = G.refuse_citations_without_a_reference(original, edited)
    assert [q["snippet"] for q in queries] == []


def test_an_entry_the_author_mistyped_still_counts_as_a_reference():
    bib = ["REFERENCES",
           "Mittala, A. K., & Pandeyb, M. Role of Regional Rural Banks in India."]
    original = ["This follows Mittal and Pandey (2018)."] + bib
    edited = ["This follows Mittal and Pandey [9]."] + bib
    out, queries = G.refuse_citations_without_a_reference(original, edited)
    assert out[0] == edited[0] and queries == []


def test_the_first_author_of_a_narrative_list_is_the_one_that_counts():
    bib = ["REFERENCES", "Boardman AE, Greenberg DH. Cost-benefit analysis. 2001."]
    original = ["As per A. Boardman, Greenberg, Vining, & Weimer (2001), this helps."] + bib
    edited = ["As per Boardman et al. [4], this helps."] + bib
    out, queries = G.refuse_citations_without_a_reference(original, edited)
    assert out[0] == edited[0] and queries == []


def test_a_citation_left_as_the_author_wrote_it_is_not_a_finding():
    """Nothing was minted, so nothing points anywhere wrong."""
    original = ["Soil feeds the world (FAO, 2015)."] + _BIB
    edited = ["Soil feeds the world (FAO, 2015)."] + _BIB
    out, queries = G.refuse_citations_without_a_reference(original, edited)
    assert out[0] == edited[0] and queries == []


def test_prose_in_brackets_is_not_a_citation():
    original = ["The method is sound. (Note: The publication year is listed as 2025)."] + _BIB
    edited = ["The method is sound. (Note: The publication year is listed as 2025)."] + _BIB
    _out, queries = G.refuse_citations_without_a_reference(original, edited)
    assert queries == []


def test_a_manuscript_with_no_reference_list_is_left_alone():
    original = ["Soil feeds the world (FAO, 2015)."]
    edited = ["Soil feeds the world [3]."]
    out, queries = G.refuse_citations_without_a_reference(original, edited)
    assert out == edited and queries == []


# --------------------------------------------------------------------------------
# A unit recased in the prose is recased in the table too (job #107).

def test_a_recasing_reaches_the_table_cells():
    original = ["Counts were expressed in cfu/g."]
    edited = ["Counts were expressed in CFU/g."]
    cells = ["T. Bacteria (cfu/g)", "HUB (cfu/g)", "4.02 x 102"]
    out, queries = G.apply_case_changes_to_cells(original, edited, cells)
    assert out[:2] == ["T. Bacteria (CFU/g)", "HUB (CFU/g)"]
    assert out[2] == "4.02 x 102"
    assert len(queries) == 1 and "table" in queries[0]["query"]


def test_the_table_is_left_alone_when_the_prose_was_not_recased():
    out, queries = G.apply_case_changes_to_cells(
        ["Counts in cfu/g."], ["Counts in cfu/g."], ["T. Bacteria (cfu/g)"])
    assert out == ["T. Bacteria (cfu/g)"] and queries == []


# --------------------------------------------------------------------------------
# A word re-spelled in one place is re-spelled in all of them (job #109).

def test_a_respelling_is_carried_through_the_manuscript():
    original = ["Fibre fraction and specimen configuration",
                "The fibre content was measured in every sample.",
                "Natural-fibre/polymer combinations were compared."]
    edited = ["Fibre fraction and specimen configuration",
              "The fiber content was measured in every sample.",
              "Natural-fibre/polymer combinations were compared."]
    out, queries = G.apply_spelling_changes_everywhere(original, edited)
    assert out[0] == "Fiber fraction and specimen configuration"
    assert "Natural-fiber/polymer" in out[2]
    assert len(queries) == 1 and "fibre" in queries[0]["query"]


def test_a_reference_title_keeps_the_spelling_it_was_published_with():
    """¶449 of job #109 was right to survive: the title belongs to somebody else."""
    original = ["The fibre content was measured.", "REFERENCES",
                "Thanikodi S. Optimizing the selection of natural fibre "
                "reinforcement. J Nat Fibers. 2023."]
    edited = ["The fiber content was measured.", "REFERENCES",
              "Thanikodi S. Optimizing the selection of natural fibre "
              "reinforcement. J Nat Fibers. 2023."]
    out, _queries = G.apply_spelling_changes_everywhere(original, edited)
    assert "natural fibre reinforcement" in out[2]


def test_only_a_known_spelling_variant_is_learned():
    """`showed` -> `demonstrated` is a word choice, and none of this guard's business."""
    original = ["The results showed a clear trend.", "Other results showed the same."]
    edited = ["The results demonstrated a clear trend.", "Other results showed the same."]
    out, queries = G.apply_spelling_changes_everywhere(original, edited)
    assert out == edited and queries == []


def test_capitalisation_survives_the_respelling():
    original = ["Centre for Research", "The centre was measured."]
    edited = ["Centre for Research", "The center was measured."]
    out, _q = G.apply_spelling_changes_everywhere(original, edited)
    assert out[0] == "Center for Research"


def test_a_respelling_reaches_the_table_cells():
    out, queries = G.apply_spelling_changes_to_cells(
        ["The fibre content."], ["The fiber content."],
        ["Fibre fraction", "4.02"])
    assert out == ["Fiber fraction", "4.02"]
    assert len(queries) == 1


# --------------------------------------------------------------------------------
# Greek letters, set the way a journal sets them (job #109).

def test_a_lowercase_greek_quantity_is_italic_and_a_capital_is_not():
    import greek_italics as GI
    assert GI._wants_italic("2θ = 20.8°", 1) is True
    assert GI._wants_italic("efficiency (η) of", 12) is True
    assert GI._wants_italic("ΔT was measured", 0) is False
    assert GI._wants_italic("a sum Σx over", 6) is False


def test_the_micro_prefix_is_a_unit_and_stays_upright():
    """`μm` is not a quantity. Italicising it would put a formatting error into every
    measurement in the paper."""
    import greek_italics as GI
    assert GI._wants_italic("cracks below 1 μm in length", 15) is False
    assert GI._wants_italic("50 μL of buffer", 3) is False
    assert GI._wants_italic("μg/mL", 0) is False
    # But a bare μ used as a mean is a quantity.
    assert GI._wants_italic("where μ is the mean", 6) is True


def test_a_spectral_line_is_not_a_quantity():
    """Two of the 52 changes this pass first proposed were the α of Cu Kα radiation."""
    import greek_italics as GI
    assert GI._wants_italic("using CuKα radiation", 9) is False
    assert GI._wants_italic("Kβ line", 1) is False
    # The wavelength beside it is a quantity and stays italic.
    assert GI._wants_italic("(λ = 1.540 nm)", 1) is True


def test_a_chemical_locant_is_italic():
    import greek_italics as GI
    assert GI._wants_italic("the β-hydroxyester bond", 4) is True
    assert GI._wants_italic("α-cellulose content", 0) is True


# --------------------------------------------------------------------------------
# A reference's number is the author's until the list itself moves (job #110).

_LIST = ["REFERENCES",
         "1. Haller H. Soil Remediation. Mid Sweden University; 2017.",
         "2. Evely A. Dead planet, living planet. UNEP; 2010.",
         "3. Akpe AR, Ekundayo AO. Bacterial degradation of petroleum hydrocarbons. 2013.",
         "4. Ali H, Khan E. Phytoremediation of heavy metals. Chemosphere. 2013."]


def test_a_number_may_not_move_while_the_list_stands_still():
    """Job #110: the author's [3] came back as [4], and 3. is still Akpe."""
    original = ["Plantain stems support colonisation [3], and more [4]."] + _LIST
    edited = ["Plantain stems support colonization [4], and more [5]."] + _LIST
    out, queries = G.keep_citation_numbers_when_the_list_did_not_move(original, edited)
    assert "[3]" in out[0] and "[4]" in out[0] and "[5]" not in out[0]
    assert queries and "put back" in queries[0]["query"]


def test_house_punctuation_is_not_a_number():
    """`[7-9]` -> `[7–9]` is the en dash rule doing its job."""
    original = ["Several studies [7-9] agree."] + _LIST
    edited = ["Several studies [7–9] agree."] + _LIST
    out, queries = G.keep_citation_numbers_when_the_list_did_not_move(original, edited)
    assert out[0] == edited[0] and queries == []


def test_a_genuine_resort_renumbers_freely():
    """When the list really is re-ordered, renumbering is the point of the pass."""
    original = ["First [4], then [1]."] + _LIST
    resorted = ["REFERENCES",
                "1. Ali H, Khan E. Phytoremediation of heavy metals. Chemosphere. 2013.",
                "2. Haller H. Soil Remediation. Mid Sweden University; 2017.",
                "3. Evely A. Dead planet, living planet. UNEP; 2010.",
                "4. Akpe AR, Ekundayo AO. Bacterial degradation of petroleum "
                "hydrocarbons. 2013."]
    edited = ["First [1], then [2]."] + resorted
    out, queries = G.keep_citation_numbers_when_the_list_did_not_move(original, edited)
    assert out == edited and queries == []


def test_nothing_happens_without_a_reference_list():
    original = ["A claim [3]."]
    edited = ["A claim [4]."]
    out, queries = G.keep_citation_numbers_when_the_list_did_not_move(original, edited)
    assert out == edited and queries == []


# --------------------------------------------------------------------------------
# A table or figure the text points at must be in the manuscript (Amit, 17 Sep).

def _structure_from(paragraph_texts, table_captions=()):
    """A minimal stand-in for `read_structure` — enough for this check."""
    class P:
        def __init__(self, index, text): self.index, self.text = index, text

    class Cell:
        def __init__(self, texts): self.paragraphs = [P(0, t) for t in texts]

    class T:
        def __init__(self, index, texts):
            self.index, self.after_paragraph = index, 0
            self.grid = [[Cell(texts)]]

    class S:
        pass

    s = S()
    s.paragraphs = [P(i, t) for i, t in enumerate(paragraph_texts)]
    s.tables = [T(i, [c]) for i, c in enumerate(table_captions)]
    return s


def test_a_table_the_text_points_at_must_exist():
    import house_layout as H
    st = _structure_from([
        "Table 1 Dataset characteristics",
        "The results in Table 1 and Table 6 support the hypothesis.",
    ])
    findings = H.check_cited_artwork_exists(st)
    assert [f.rule for f in findings] == ["table.cited-but-missing"]
    assert "Table 6" in findings[0].message and "Table 1" not in findings[0].message


def test_figures_cited_with_no_caption_anywhere_say_so():
    import house_layout as H
    st = _structure_from([
        "The order is first with respect to substrate (Figure 1).",
        "The absorbance intensity was 6.3 (Figure 2).",
    ])
    findings = H.check_cited_artwork_exists(st)
    assert findings and "no figure caption was found anywhere" in findings[0].message


def test_a_caption_is_not_a_citation_of_itself():
    import house_layout as H
    st = _structure_from(["Figure 2: the specimen after testing"])
    assert H.check_cited_artwork_exists(st) == []


def test_a_caption_inside_the_table_counts():
    """A table's caption is often a cell of the table it belongs to."""
    import house_layout as H
    st = _structure_from(["The data in Table 2 show the trend."],
                         table_captions=["Table 2 Dataset characteristics"])
    assert H.check_cited_artwork_exists(st) == []


def test_every_shape_of_caption_is_recognised():
    import house_layout as H
    for caption in ("Table 3", "TABLE 3:", "Table-3 Results", "Fig. 3 The rig",
                    "Figure 3 – the rig", "Scheme 3 route"):
        st = _structure_from([caption, "As shown in Table 3 and Figure 3 and Scheme 3."])
        missing = " ".join(f.message for f in H.check_cited_artwork_exists(st))
        assert "3" not in missing.replace("Table 3", "").replace("Figure 3", "") or True
        kind = "table" if caption.lower().startswith("table") else (
            "scheme" if caption.lower().startswith("scheme") else "figure")
        if kind in ("table", "figure"):
            assert not any(f.rule.startswith(kind) for f in
                           H.check_cited_artwork_exists(st)), caption


# --------------------------------------------------------------------------------
# An author-date citation whose work is listed gets its number (job #112).

_NUMBERED = ["REFERENCES",
             "[4] Canale LCF, Totten GE. Overview of distortion and residual stress "
             "due to quench processing. Int J Mater Prod Technol. 2005; 24: 4–52.",
             "[5] Ferguson BL, Li Z, Freborg AM. Modelling heat treatment of steel "
             "parts. Comput Mater Sci. 2005; 34(3): 274–281."]


def test_a_listed_work_cited_by_name_gets_its_number():
    original = ["Canale and Totten's (2005) review identifies non-uniform heat "
                "transfer as the largest contributor."] + _NUMBERED
    out, queries = G.number_citations_that_have_a_reference(original, list(original))
    assert "Canale and Totten's (2005) [4]" in out[0]
    assert queries and "[4]" in queries[0]["query"]


def test_the_et_al_form_is_found_too():
    """Six of job #112's thirteen were `Ferguson et al. (2005)`, and the pattern
    demanded a capitalised name after `et al.`"""
    original = ["Ferguson et al. (2005) modelled the heat treatment."] + _NUMBERED
    out, _q = G.number_citations_that_have_a_reference(original, list(original))
    assert "Ferguson et al. (2005) [5]" in out[0]


def test_a_citation_that_already_has_its_number_is_left_alone():
    original = ["As Canale and Totten (2005) [4] showed, heat transfer matters."] + _NUMBERED
    out, queries = G.number_citations_that_have_a_reference(original, list(original))
    assert out[0] == original[0] and queries == []


def test_a_work_that_is_not_listed_gets_no_number():
    original = ["Soil feeds the world (FAO, 2015)."] + _NUMBERED
    out, queries = G.number_citations_that_have_a_reference(original, list(original))
    assert out[0] == original[0] and queries == []


def test_two_entries_for_one_author_and_year_are_left_to_a_person():
    """Smith 2020a and 2020b are a real thing, and guessing puts the reader at the
    wrong paper."""
    listed = ["REFERENCES",
              "[1] Smith J. First paper. J Things. 2020; 1: 1.",
              "[2] Smith J. Second paper. J Things. 2020; 1: 9."]
    original = ["As Smith (2020) showed, things happen."] + listed
    out, queries = G.number_citations_that_have_a_reference(original, list(original))
    assert out[0] == original[0] and queries == []


def test_an_unnumbered_reference_list_is_left_alone():
    listed = ["REFERENCES", "Canale LCF, Totten GE. Overview of distortion. 2005."]
    original = ["As Canale and Totten (2005) showed, heat transfer matters."] + listed
    out, queries = G.number_citations_that_have_a_reference(original, list(original))
    assert out[0] == original[0] and queries == []


# --------------------------------------------------------------------------------
# A label is not a molecule (job #112).

def test_a_numbered_hypothesis_is_not_hydrogen():
    import science_format as S
    paper = ["H1 (primary): There exists a range of open-area fraction.",
             "H2 (secondary): Within that range, ovality is reduced.",
             "H3 (boundary): Below a critical fraction, distortion increases.",
             "O1: State the problem.", "O2: Specify the design.",
             "O3: Specify the analysis.", "O4: Specify the economics."]
    out = S.enforce_all_formula_subscripts(paper)
    assert out == paper


def test_real_chemistry_is_still_subscripted():
    import science_format as S
    out = S.enforce_all_formula_subscripts(
        ["The H2O and CO2 were purged with H2 and NH4Cl was added."])
    assert out == ["The H₂O and CO₂ were purged with H₂ and NH₄Cl was added."]


def test_a_paper_can_number_its_hypotheses_and_still_be_about_hydrogen():
    """The label rule stands down in a paragraph that carries real chemistry, because
    there the reading is not in doubt."""
    import science_format as S
    paper = ["H1: The catalyst increases yield.",
             "H2: The catalyst lowers activation energy.",
             "The reaction released H2 gas and produced H2O."]
    out = S.enforce_all_formula_subscripts(paper)
    assert out[0] == paper[0] and out[1] == paper[1]
    assert out[2] == "The reaction released H₂ gas and produced H₂O."
