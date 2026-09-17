"""What went wrong once, and what stops it happening again.

Amit, 16 Sep 2026: *"Iss platform ce4 ke llm modles ke liye koi lession file ni hai
kya? Taki wo bhi same types ki galtiya naa dohraye?"*

The answer is that a lesson written into the prompt is not a lesson, it is a hope. The
abbreviation rule was in the prompt, in full, and job #72 still shipped `UF` before its
own definition; the same rule was applied three different ways in three adjacent
paragraphs of one manuscript. A model does not remember, and it does not promise.

So ce4's lessons live in code — one deterministic guard per real failure, each with its
own test. This file is the register of them, in the quality team's language rather than
in commit messages: what went wrong, where it was seen, and the exact thing that now
prevents it.

**Every entry is checked.** `test_quality_log.py` imports each `prevented_by` and fails
if the function is not there, and looks up each `proved_by` test by name. An entry
cannot quietly become a claim about code that was renamed or deleted — which is the
only way a register like this is worth reading a year from now.

To add one: fix the defect, write the test, then add the row. In that order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Lesson:
    """One defect, and the code that makes it impossible."""

    #: What the reader saw, in the words someone would report it in.
    went_wrong: str
    #: Where it was found — a job number where there is one, otherwise the manuscript.
    found_in: str
    #: ISO date it was fixed.
    fixed_on: str
    #: `module.function` that now prevents it. Verified to exist.
    prevented_by: str
    #: `test_file.py::test_name` that fails if it comes back. Verified to exist.
    proved_by: str
    #: The sentence a copy editor would want: what the tool does now.
    now: str
    #: What it cost, where that was measured rather than guessed.
    measured: Optional[str] = None


#: Oldest first. The quality team reads this top to bottom to see what is settled.
LESSONS: List[Lesson] = [
    Lesson(
        went_wrong="The copyedit emptied a paragraph, or cut most of it away, and the "
                   "report said nothing.",
        found_in="job #53",
        fixed_on="2026-09-04",
        prevented_by="losscheck.check_document",
        proved_by="test_losscheck.py::test_an_emptied_paragraph_is_caught",
        now="A paragraph that comes back empty, or that lost a negation, is refused: "
            "the author's text is kept and the paragraph carries a query. Its spelling "
            "corrections are salvaged rather than thrown away with it.",
    ),
    Lesson(
        went_wrong="Figures disappeared from the file. `word/media/` still held the "
                   "images; no paragraph pointed at them any more.",
        found_in="job #53",
        fixed_on="2026-09-09",
        prevented_by="editor._detachable_graphics",
        proved_by="test_job53_losses.py::test_copyediting_a_caption_does_not_delete_the_figure",
        now="A picture is lifted out of the paragraph before it is rewritten and put "
            "back afterwards, so copyediting a caption can no longer destroy the "
            "figure it captions.",
        measured="3 of 4 figures lost in one manuscript",
    ),
    Lesson(
        went_wrong="A table or figure caption lost its number — `Table 2: Comparative "
                   "Summary` came back as `Comparative Summary` — and the tool then "
                   "filed a defect against the author for a missing caption.",
        found_in="job #53",
        fixed_on="2026-09-09",
        prevented_by="edit_guards.restore_protected_text",
        proved_by="test_job53_losses.py::test_the_table_label_is_restored_without_losing_the_copyedit",
        now="The caption number is put back. Only the number is compared, so the house "
            "rules may still reshape the caption around it.",
    ),
    Lesson(
        went_wrong="Superscript reference markers were invisible to every check: a "
                   "superscript 45 arrived as `react45` and read like a typo.",
        found_in="job #52",
        fixed_on="2026-09-09",
        prevented_by="editor._render_superscripts",
        proved_by="test_job52_gaps.py::test_a_superscript_reference_becomes_a_citation_marker",
        now="A superscript citation is rendered as `[45, 48]` before the copyedit sees "
            "it. An exponent is not — a run only counts as a citation when what "
            "precedes it is a letter or sentence punctuation.",
    ),
    Lesson(
        went_wrong="A column heading read `CONCETRATION (M)` in the largest type on "
                   "the page and no check had ever looked inside a table.",
        found_in="job #52",
        fixed_on="2026-09-09",
        prevented_by="editor.collect_table_texts_for_proofing",
        proved_by="test_job52_gaps.py::test_a_short_column_heading_is_offered_to_the_proofreader",
        now="Table cells are read by the proofreader and reported on. Cells are still "
            "only *rewritten* when they carry three real words, so a bare number in a "
            "results table can never be 'corrected'.",
    ),
    Lesson(
        went_wrong="An edit meant for one table cell was written into a different one.",
        found_in="portfolio manuscripts",
        fixed_on="2026-09-05",
        prevented_by="edit_guards.verify_cell_edits",
        proved_by="test_edit_guards.py::test_a_replacement_rather_than_an_edit_is_refused",
        now="A returned cell must still be recognisably an edit of the cell it was "
            "asked about, or it is refused and the original stands.",
    ),
    Lesson(
        went_wrong="Author names in the front matter were altered, and the "
                   "bibliography was renumbered under the author's feet.",
        found_in="job #60",
        fixed_on="2026-09-05",
        prevented_by="edit_guards.restore_front_matter_names",
        proved_by="test_edit_guards.py::test_a_byline_may_not_lose_a_given_name",
        now="The names on the title page and the numbering of the reference list are "
            "restored from the author's own file, whatever the model returned.",
    ),
    Lesson(
        went_wrong="References went missing from the bibliography, and others appeared "
                   "twice, while every count looked right.",
        found_in="jobs #60 and #62",
        fixed_on="2026-09-09",
        prevented_by="edit_guards.verify_reference_block",
        proved_by="test_job62_bibliography.py::test_the_census_counts_works_not_wordings",
        now="Entries are identified by first surname and year — something a reformat "
            "cannot change — so two reformatted copies of one work are no longer "
            "counted as two different works. The check also runs again at the very "
            "end, after every later step.",
        measured="3 lost and 3 duplicated in #60; 4 more in #62",
    ),
    Lesson(
        went_wrong="A reference lost the web address the house format requires, and "
                   "still read like a complete entry.",
        found_in="job #61",
        fixed_on="2026-09-15",
        prevented_by="edit_guards.restore_reference_urls",
        proved_by="test_job91_reference_link.py::test_the_link_is_put_back_where_the_entry_points_at_it",
        now="The link is put back into the entry, and only the link — the Vancouver "
            "reformatting around it stands.",
    ),
    Lesson(
        went_wrong="An abbreviation arrived before the sentence that defines it: "
                   "`urea-formaldehyde (UF)` was expanded late, so `UF` appeared first.",
        found_in="job #72",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.enforce_abbreviation_first_use",
        proved_by="test_edit_guards.py::"
                  "test_an_abbreviation_never_arrives_before_its_definition",
        now="The definition is placed at the first occurrence in the body and the "
            "short form is used after it — the house rule, enforced in code rather "
            "than asked for in the prompt.",
    ),
    Lesson(
        went_wrong="The same term was expanded again and again — one manuscript "
                   "carried its expansion 34 times.",
        found_in="job #46",
        fixed_on="2026-09-05",
        prevented_by="edit_guards.learn_abbreviations",
        proved_by="test_edit_guards.py::test_pairs_come_from_the_author_not_from_initials",
        now="Pairs are learned from the author's own definitions and applied across "
            "the whole document. The abstract is a separate scope, by design: it "
            "carries no abbreviations of its own.",
    ),
    Lesson(
        went_wrong="The copyedit wrote its own symbols into a nomenclature list: "
                   "`C0 =`, `C =`, `Q =` on the first three lines and nothing at all "
                   "on the four after them, where the author had defined every symbol "
                   "themselves.",
        found_in="job #106",
        fixed_on="2026-09-17",
        prevented_by="editor._paragraph_pieces",
        proved_by="test_equations.py::"
                  "test_an_ole_equation_in_a_line_of_text_is_shown_to_the_copyedit",
        now="An old Word equation is not OMML — it is an OLE object inside an "
            "ordinary run, and `Paragraph.text` steps over it the same way. Those are "
            "now held by the same placeholder as an equation, so the copyedit sees a "
            "symbol rather than a blank line to fill. A paragraph that is only a "
            "figure keeps the older path, which is what job #53 needed.",
    ),
    Lesson(
        went_wrong="`cfu/g` was written `CFU/g` in one place and left alone in the "
                   "other two.",
        found_in="job #106",
        fixed_on="2026-09-17",
        prevented_by="edit_guards.apply_case_changes_everywhere",
        proved_by="test_edit_guards.py::"
                  "test_a_unit_recased_once_is_recased_everywhere",
        now="A unit recased in one place is recased in all of them, with one query "
            "naming the term. `CFU` being the right form is not the point: a paper "
            "that says both is worse than one consistently wrong, because a reader "
            "cannot tell which is the typo.",
        measured="over 90 redlines: 1 finding, this one. A first version read "
                 "`MATERIALS AND METHODS` -> `Materials and Methods` as a ruling on "
                 "`AND` and rewrote 115 paragraphs; a second learned `al` -> `AL` "
                 "from a re-sorted bibliography and would have written `et AL.`",
    ),
    Lesson(
        went_wrong="A figure caption came back naming different data: `Figure 9: Line "
                   "Waver-Burke Plot for T4 (80g)` became `Figure 9. Lineweaver-Burk "
                   "plot for T5 (100 g)`. The spelling repair is right and wanted; the "
                   "caption silently agreeing with a sentence further down the paper "
                   "is not.",
        found_in="job #106",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.keep_caption_values",
        proved_by="test_edit_guards.py::"
                  "test_a_caption_may_be_reworded_but_not_revalued",
        now="A caption may be re-worded and not re-valued. Which of the two is the "
            "typo — the caption or the body — is a question about the artwork that "
            "nobody reading the manuscript can answer, so the author's values come "
            "back and the query asks. Every other correction to the caption stands.",
        measured="over 90 redlines: 1 finding, this one. The first sweep gave 44, of "
                 "which the false ones were prose opening `Table 6 … shows that`, and "
                 "this pipeline's own `CaSO4` -> `CaSO₄` and `10-5` -> `10⁻⁵`",
    ),
    Lesson(
        went_wrong="The copyedit invented an equation placeholder. The author's "
                   "`KCrd = 36.768x - 0.0006`, an equation typed as ordinary text, was "
                   "delivered as a single `￼` — the working character this pipeline "
                   "uses to hold an equation's place, written into the file.",
        found_in="job #106",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.keep_every_equation",
        proved_by="test_edit_guards.py::"
                  "test_an_equation_placeholder_the_copyedit_invented_is_refused",
        now="The placeholder count is compared in both directions: one the author did "
            "not have is as wrong as one they had and lost, and the paragraph is "
            "restored either way. A placeholder with no equation to become is also "
            "stripped as the file is written, so it can never reach a reader.",
    ),
    Lesson(
        went_wrong="Nothing in ce4 asked the general question. Every guard answers one "
                   "past failure, so a new kind of loss — a subscript marker, in this "
                   "case — walked through the whole chain without touching a check, "
                   "and the quality team was the only thing that caught it.",
        found_in="asked by Amit after job #104",
        fixed_on="2026-09-16",
        prevented_by="token_census.missing_tokens",
        proved_by="test_token_census.py::"
                  "test_a_subscript_marker_that_vanished_is_reported",
        now="Every technical token in the author's manuscript — a quantity with a "
            "unit, a symbol carrying a subscript or superscript, a chemical formula — "
            "is looked for in the copyedited text, and anything missing is queried. It "
            "knows nothing about any particular failure, which is the point: it does "
            "not need to be told which way the next one will come.",
        measured="over all 88 redlines: 20 findings in 6 files, every one of them the "
                 "real G_IC loss. The first version reported 47, about half of them "
                 "correct copyediting — each of those classes is normalised away and "
                 "has its own test",
    ),
    Lesson(
        went_wrong="`(G_IC,healed/G_IC,pristine)` came back as "
                   "`(GIC,healed/GIC,pristine)`, and `(G_(IC,healed))` as "
                   "`(GIC,healed)`.",
        found_in="job #104",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.keep_subscript_markers",
        proved_by="test_edit_guards.py::"
                  "test_a_subscript_marker_the_author_wrote_is_kept",
        now="The underscore is what says those letters are a subscript, and in a "
            "plain-text pipeline it is the only thing carrying it — `GIC` is a "
            "different symbol and a typesetter given it has no way back. Unicode has "
            "no subscript `I` or `C`, so this cannot be converted the way `H₂O` is: "
            "the author's notation is kept and the query asks for Word's own subscript "
            "formatting.",
    ),
    Lesson(
        went_wrong="The copyedit wrote its own definition for `EDBEA` — "
                   "`N,N'-bis(2-aminoethyl)-1,3-benzenedicarboxamide` — which is a "
                   "different molecule from the author's "
                   "`2,2′-(ethylenedioxy)bis(ethylamine)`, already defined eight "
                   "paragraphs earlier.",
        found_in="job #104",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.refuse_invented_expansions",
        proved_by="test_edit_guards.py::"
                  "test_an_expansion_the_author_never_wrote_is_refused",
        now="Chemical detail the copyedit adds is checked against the author's own, "
            "and only the inserted words are removed — the rest of the edit on that "
            "sentence stands. Two things had to change: a chemist's name carries "
            "digits, primes and brackets, so `2,2′-(ethylenedioxy)bis(ethylamine) "
            "(EDBEA)` could not be read as a definition at all and EDBEA was never "
            "learned; and nothing anywhere asked whether an inserted expansion came "
            "from this manuscript. Job #105 is the same guard's second case: `DTDA` "
            "came back as `4,4'-DTDA`, a locant put in front of a short form the "
            "author had written bare — not wrong chemistry, but against the first-use "
            "rule, and with an ASCII apostrophe where the author uses a prime. Where "
            "the manuscript never defines the abbreviation at all, the expansion "
            "stands and is queried instead: nothing in the file can confirm it, and "
            "removing it would throw away the house rule's own first-use requirement.",
        measured="over 89 redlines: 6 removals, all of them the same fabricated "
                 "molecule — three different inventions for EDBEA across five runs of "
                 "one manuscript — and 18 expansions kept with a query",
    ),
    Lesson(
        went_wrong="Twelve of twenty-one bibliography entries came back with no "
                   "number, so every in-text `[3]`, `[4]`, `[6]` pointed at nothing.",
        found_in="job #104",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.restore_reference_numbering",
        proved_by="test_edit_guards.py::"
                  "test_a_vancouver_bracketed_entry_number_is_restored",
        now="The entry number is restored in the author's own punctuation — `[3]` on a "
            "list numbered `[3]`, `3.` on a list numbered `3.`. The guard knew `1.` "
            "and `1)` and not `[1]`, which is what the house Vancouver style looks "
            "like, so it had been silent on every manuscript that numbers its "
            "bibliography that way. It also runs once more at the end, after Crossref "
            "completion rewrites an entry — which is where these numbers went.",
        measured="12 of 21 entries in #104",
    ),
    Lesson(
        went_wrong="`timespace` came back as `time space`. It is the author's term and "
                   "the spelling the literature uses; the copyedit did not recognise "
                   "the word and treated it as a slip.",
        found_in="job #104",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.keep_closed_compounds",
        proved_by="test_edit_guards.py::"
                  "test_a_technical_term_is_not_split_into_two_words",
        now="A word the author wrote closed stays closed, with a query. Two conditions "
            "keep the real corrections going through: both halves must be content "
            "words, so `thatthe` and `inorder` are still opened, and the manuscript "
            "must never write the term open itself — an author who uses both forms has "
            "made no decision to enforce.",
    ),
    Lesson(
        went_wrong="A term the author had already defined was spelled out again — "
                   "`dicyclopentadiene (DCPD)` in the sentence after the Figure 1 "
                   "caption, and again at Figure 3 — with the first-use rule switched "
                   "on and reporting itself as applied.",
        found_in="job #103",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.learn_abbreviations",
        proved_by="test_edit_guards.py::"
                  "test_job_103_stops_re_expanding_after_the_caption",
        now="A chemical name is one word, so its initials are one letter and the pair "
            "was never learned — and an abbreviation the guard has not learned is one "
            "it does nothing about. A contraction is now recognised as well: the "
            "letters in order, starting on the word's own first letter, in a word at "
            "least three times as long. `control (CTRL)` is still refused, because "
            "learning it would put `CTRL` in place of every later 'control'.",
        measured="5 paragraphs in #103 — DCPD four times, DTDA once; PDMS, THF and "
                 "DMF were equally invisible",
    ),
    Lesson(
        went_wrong="A tracked change with nothing to see: `μm` deleted, `µm` inserted. "
                   "The same glyph, a different code point.",
        found_in="job #100",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.follow_the_author_on_invisible_twins",
        proved_by="test_edit_guards.py::"
                  "test_the_author_s_micro_sign_survives_the_copyedit",
        now="The micro sign, the ohm sign, the angstrom and the kelvin are written the "
            "way the author wrote them — across the document where they were "
            "consistent, occurrence by occurrence where they were not. `um` -> `µm` is "
            "a real correction and stays a tracked change.",
        measured="5 invisible changes across 84 redlines",
    ),
    Lesson(
        went_wrong="`log|Z|0.01Hz` came back as `log|Z|₀.₀₁Hz` — the digits shrank, "
                   "the decimal point and the `Hz` did not.",
        found_in="job #73",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.undo_broken_subscripts",
        proved_by="test_edit_guards.py::"
                  "test_a_subscript_spanning_a_decimal_point_comes_back_as_plain_digits",
        now="Unicode has subscript digits and no subscript full stop, so a subscript "
            "that cannot be finished is restored to plain digits with a query asking "
            "for Word's own subscript formatting. `H₂O` and `CO₂` are untouched.",
    ),
    Lesson(
        went_wrong="An equation vanished and the copyedit wrote its own symbols in the "
                   "hole: `where [K_IC ≈ 0.7 MPa·m^1/2] is the fracture toughness` "
                   "became `where K_Ic is the fracture toughness`. Neither `0.7 MPa` "
                   "nor `50 nm` appeared anywhere in the returned file.",
        found_in="job #100",
        fixed_on="2026-09-16",
        prevented_by="edit_guards.keep_every_equation",
        proved_by="test_equations.py::"
                  "test_the_equation_survives_a_paragraph_the_copyedit_rewrote",
        now="Each equation is held as a placeholder from the moment the file is read "
            "until the redline is written, where the original object goes back at "
            "exactly that character. If the count comes back wrong the author's "
            "paragraph is kept whole, with a query.",
        measured="16 invented symbols across 5 manuscripts",
    ),
    Lesson(
        went_wrong="A chunk of the manuscript was never copyedited at all, and read "
                   "exactly like a chunk that needed no changes.",
        found_in="a 70-paragraph manuscript",
        fixed_on="2026-09-05",
        prevented_by="pipeline.run_pipeline",
        proved_by="test_skipped_chunks.py::test_the_orchestrator_names_which_paragraphs_were_missed",
        now="A chunk the model failed on is counted and named in the report. Silence "
            "is no longer allowed to mean success.",
        measured="4 chunks, 20 paragraphs, reported as nothing",
    ),
    Lesson(
        went_wrong="Every paragraph the copyedit touched came back with its character "
                   "formatting flattened — italics, superscripts and subscripts gone.",
        found_in="three manuscripts",
        fixed_on="2026-09-05",
        prevented_by="editor.add_track_change_run",
        proved_by="test_redline.py::test_an_edited_paragraph_keeps_its_superscripts_and_italics",
        now="Each rewritten run carries the original run's formatting, so an italic "
            "species name and a superscript activation marker survive the edit.",
        measured="156, 187 and 96 edited paragraphs with zero formatting left",
    ),
    Lesson(
        went_wrong="The author's hyphenation was quietly closed up, and British "
                   "spelling was Americanised in a manuscript written in British "
                   "English.",
        found_in="portfolio manuscripts",
        fixed_on="2026-09-05",
        prevented_by="edit_guards.preserve_author_hyphenation",
        proved_by="test_edit_guards.py::test_the_authors_hyphen_is_put_back",
        now="The manuscript's own variant is detected and followed, and the author's "
            "hyphens are kept — after the variant pass, so a re-spelling cannot undo "
            "it.",
    ),
    Lesson(
        went_wrong="A date line lost its day and month: `Accepted Date: 29th May, "
                   "2026` came back as `Accepted Date: 2026`.",
        found_in="portfolio manuscripts",
        fixed_on="2026-09-04",
        prevented_by="edit_guards.restore_protected_text",
        proved_by="test_edit_guards.py::test_a_date_line_that_lost_its_day_and_month_is_restored",
        now="The article's own dates are restored in full, with a query.",
    ),
    Lesson(
        went_wrong="Numbered steps in an algorithm listing were stripped of their "
                   "numbers, because the house rule says headings carry none.",
        found_in="portfolio manuscripts",
        fixed_on="2026-09-04",
        prevented_by="edit_guards.restore_protected_text",
        proved_by="test_edit_guards.py::test_an_algorithm_step_keeps_its_number",
        now="A numbered step is recognised by the wide separator Word sets it with, "
            "and its number is put back with the author's own spacing.",
        measured="10 of 13 steps unnumbered, 3 left alone",
    ),

    # --- 17 September 2026, with the quality team on jobs #107 to #113 -------------

    Lesson(
        went_wrong="`(FAO, 2015)` was turned into `[3]` although no FAO reference "
                   "exists, so the citation pointed at Akpe et al. on crude-oil soil.",
        found_in="job #107",
        fixed_on="2026-09-17",
        prevented_by="edit_guards.refuse_citations_without_a_reference",
        proved_by="test_edit_guards.py::"
                  "test_a_number_is_not_minted_for_a_missing_reference",
        now="A number is never minted for a work that is not in the list. The author's "
            "own citation is put back and they are asked for the reference.",
        measured="94 findings over 91 redlines narrowed to 8, each read by hand",
    ),
    Lesson(
        went_wrong="A recasing the copyedit made in the prose (`cfu/g` to `CFU/g`) did "
                   "not reach the table, where the unit is looked up.",
        found_in="jobs #106, #107, #110",
        fixed_on="2026-09-17",
        prevented_by="edit_guards.apply_case_changes_to_cells",
        proved_by="test_edit_guards.py::test_a_recasing_reaches_the_table_cells",
        now="The recasing is learned from the body and applied to body and cells "
            "alike, over every cell with a letter in it.",
        measured="5 of 37 table cells were reaching the guard before",
    ),
    Lesson(
        went_wrong="A reference reformatted to lead with a different author was read "
                   "as lost, and the whole bibliography was restored unformatted.",
        found_in="job #107",
        fixed_on="2026-09-17",
        prevented_by="edit_guards._references_lost",
        proved_by="test_job60_references.py::"
                  "test_a_reference_reformatted_to_lead_with_another_author_is_not_lost",
        now="A work is identified by its years, its names and its uncommon title "
            "words, and only the entries actually missing are restored.",
        measured="24 of 91 bibliographies were being discarded; now 13, all real",
    ),
    Lesson(
        went_wrong="In-text citation numbers shifted by one while the reference list "
                   "stayed in its original order, so every number after the shift "
                   "pointed at a different paper.",
        found_in="job #110",
        fixed_on="2026-09-17",
        prevented_by="edit_guards.keep_citation_numbers_when_the_list_did_not_move",
        proved_by="test_edit_guards.py::"
                  "test_a_number_may_not_move_while_the_list_stands_still",
        now="If the bibliography holds the same works in the same order, no in-text "
            "number may change.",
        measured="6 of 92 manuscripts, one with 65 shifted citations",
    ),
    Lesson(
        went_wrong="Thirteen citations were left as author and year in a Vancouver "
                   "manuscript whose list numbers every one of those works.",
        found_in="job #112",
        fixed_on="2026-09-17",
        prevented_by="edit_guards.number_citations_that_have_a_reference",
        proved_by="test_edit_guards.py::"
                  "test_a_listed_work_cited_by_name_gets_its_number",
        now="The number is added after the author's own citation, but only where the "
            "surname and year match exactly one numbered entry.",
        measured="5 of 92 manuscripts; every inserted number checked by hand",
    ),
    Lesson(
        went_wrong="The hypotheses H2, O2 and O3 were subscripted into hydrogen, "
                   "oxygen and ozone in a paper with no chemistry in it.",
        found_in="job #112",
        fixed_on="2026-09-17",
        prevented_by="science_format.labelled_series",
        proved_by="test_edit_guards.py::test_a_numbered_hypothesis_is_not_hydrogen",
        now="A letter used with two or more numbers, one of which cannot be a formula, "
            "is numbering something — unless the paragraph carries real chemistry.",
        measured="3 of 92 manuscripts, two of them already shipped with the defect",
    ),
    Lesson(
        went_wrong="A manuscript set to follow its own language wrote `fiber` 27 times "
                   "and `fibre` 4, because the copyedit chose where the language pass "
                   "had correctly refused to.",
        found_in="job #109",
        fixed_on="2026-09-17",
        prevented_by="edit_guards.apply_spelling_changes_everywhere",
        proved_by="test_edit_guards.py::"
                  "test_a_respelling_is_carried_through_the_manuscript",
        now="Whatever the copyedit re-spelled is re-spelled everywhere outside the "
            "bibliography, where a title is a quotation.",
        measured="6 of 92 manuscripts, one word each",
    ),
    Lesson(
        went_wrong="Lowercase Greek quantity symbols were not italic, against the "
                   "convention every physical-science house style follows.",
        found_in="job #109",
        fixed_on="2026-09-17",
        prevented_by="greek_italics.apply_to_document",
        proved_by="test_edit_guards.py::"
                  "test_a_lowercase_greek_quantity_is_italic_and_a_capital_is_not",
        now="Lowercase italic, capitals upright, and units (μm, μL, Cu Kα) left alone.",
        measured="45 symbols set over 40 manuscripts, 38 left as units",
    ),
    Lesson(
        went_wrong="The text sent a reader to Table 6 and to Figures 1 to 4 that are "
                   "not in the manuscript, and nothing said so.",
        found_in="Amit, 17 Sep",
        fixed_on="2026-09-17",
        prevented_by="house_layout.check_cited_artwork_exists",
        proved_by="test_edit_guards.py::test_a_table_the_text_points_at_must_exist",
        now="Every table and figure the text refers to is checked against the captions "
            "that exist, including captions inside the table.",
        measured="20 of 91 manuscripts have a gap; four read by hand, all real",
    ),
    Lesson(
        went_wrong="A reference missing its authors was reported only in a margin "
                   "comment, beside an entry that looks complete.",
        found_in="job #113",
        fixed_on="2026-09-17",
        prevented_by="reference_gaps.mark",
        proved_by="test_reference_gaps.py::"
                  "test_missing_authors_are_marked_at_the_head_after_the_number",
        now="The gap is written into the entry where the field belongs, in its own "
            "highlight — authors at the head, volume and pages at the tail.",
    ),
]


def as_rows() -> List[dict]:
    """The register as plain dictionaries, for the screen that renders it."""
    return [
        {
            "What went wrong": lesson.went_wrong,
            "Where": lesson.found_in,
            "Fixed": lesson.fixed_on,
            "What stops it now": lesson.now,
            "Guarded by": lesson.prevented_by,
            "Proved by": lesson.proved_by,
            "Measured": lesson.measured or "",
        }
        for lesson in LESSONS
    ]
