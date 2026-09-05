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


def test_the_author_s_own_definition_is_never_duplicated():
    """If the author defined it, that definition stands and no second one is invented
    — otherwise the paper defines the same term twice and the author's chosen first
    mention moves."""
    original = ["Intro paragraph mentioning AE.",
                "Later, acoustic-emission (AE) is defined here."]
    edited = ["Intro paragraph mentioning acoustic emission.",
              "Later, acoustic-emission (AE) is defined here."]
    out, _ = enforce_abbreviation_first_use(original, list(edited))
    assert out[0] == "Intro paragraph mentioning AE."
    assert out[1] == edited[1], "the author's definition is left exactly alone"


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
