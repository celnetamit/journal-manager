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
