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
