"""Character-level science formatting, tested against what the corpus actually contains.

Every false positive named here was produced by an earlier version of these rules on
real manuscripts, and every true positive is a phrase from the same corpus. The three
detectors that were measured and rejected are described in `science_format`'s own
docstring; what is tested here is the one that survived.
"""

import docxmodel as D
import science_format as S


def _structure(*paras):
    """A structure whose paragraphs carry no run formatting (nothing is italic)."""
    return D.Structure(
        paragraphs=[D.Para(index=i, text=t, style="Normal",
                           runs=[D.Run(text=t)]) for i, t in enumerate(paras)],
        tables=[], sections=[], images=[])


def _italic_structure(text):
    return D.Structure(
        paragraphs=[D.Para(index=0, text=text, style="Normal",
                           runs=[D.Run(text=text, italic=True)])],
        tables=[], sections=[], images=[])


def _rules(findings):
    return [f.rule for f in findings]


# ----------------------------------------------------------------- species italics

def test_a_binomial_that_is_not_italic_is_reported():
    st = _structure("Fresh green bananas (Musa paradisiaca) were collected.",
                    "Pomegranate (Punica granatum) peels were used.")
    msgs = [f.message for f in S.check_species_italic(st)]
    assert any("Musa paradisiaca" in m for m in msgs)
    assert any("Punica granatum" in m for m in msgs)


def test_an_italic_binomial_is_not_reported():
    st = _italic_structure("tested against Escherichia coli at 24 hours.")
    assert S.check_species_italic(st) == []


def test_the_abbreviated_form_is_recognised():
    st = _structure("Activity against E. coli and S. aureus was measured.")
    msgs = " ".join(f.message for f in S.check_species_italic(st))
    assert "E. coli" in msgs and "S. aureus" in msgs


def test_author_initials_are_not_species():
    """The corpus has 255 abbreviation-shaped hits and most are reference lists:
    `Kwan, C., Gribben, D., Ayhan, B.` reads as `C. Gribben`, `D. Ayhan`."""
    st = _structure("Kwan C., Gribben D., Ayhan B., and Plaza A. reported this.",
                    "Smith, S. and Jones, R. and Patel, M. and Rao, D. holders.")
    assert S.check_species_italic(st) == []


def test_a_genus_followed_by_an_english_word_is_not_a_binomial():
    """`Rhizobium strain`, `Aegilops species` and `Triticum and` were 4 of the first
    11 findings this rule produced on the corpus."""
    st = _structure("The Rhizobium strain was isolated from Aegilops species.",
                    "Triticum and Hordeum were both examined.")
    assert S.check_species_italic(st) == []


def test_an_english_phrase_in_parentheses_is_never_a_species():
    """`(Mild walking)`, `(Urdu translation)`, `(Jali windows)` — all real, all from
    the parenthetical detector that was rejected for exactly this."""
    st = _structure("The intervention (Mild walking) was compared.",
                    "The text (Urdu translation) was reviewed.",
                    "The facade (Jali windows) reduced heat gain.")
    assert S.check_species_italic(st) == []


# --------------------------------------------------------------- formula subscripts

def test_formulas_get_unicode_subscripts():
    got = S.enforce_formula_subscripts([
        "Ferric chloride (FeCl3), ethanol and distilled water.",
        "iron oxide (Fe3O4) was prepared with H2SO4 and NaOH.",
    ])
    assert got[0] == "Ferric chloride (FeCl₃), ethanol and distilled water."
    assert got[1] == "iron oxide (Fe₃O₄) was prepared with H₂SO₄ and NaOH."


def test_equipment_models_and_statistics_are_not_formulas():
    """A general `[A-Z][a-z]?\\d` pattern returns 950 hits over the corpus led by
    `D8` (a diffractometer), `M4`, `R2` (an R-squared) and `M0`."""
    text = ["A Bruker D8 gave R2 = 0.98 for the M4 and M0 samples."]
    assert S.enforce_formula_subscripts(text) == text


def test_an_already_subscripted_formula_is_left_alone():
    text = ["Starch–Fe₃O₄ nanoblends exhibited activity."]
    assert S.enforce_formula_subscripts(text) == text


def test_a_formula_inside_a_longer_token_is_not_touched():
    text = ["the CO2RR pathway and H2Oxidation were excluded."]
    assert S.enforce_formula_subscripts(text) == text


def test_formulas_are_fixed_not_reported():
    """`enforce_formula_subscripts` corrects them in the redline, so listing them in
    the House Style panel as well would tell the editor `FeCl3` is wrong beside a
    redline where it already reads `FeCl₃`."""
    st = _structure("Ferric chloride (FeCl3) was used.")
    assert "format.formula-subscript" not in _rules(S.check_all(st))
    # Still available on its own, for tests and for measuring the corpus.
    assert S.check_formula_subscripts(st)


# ------------------------------------------------------------ sub/superscript markers

def test_a_variable_with_the_qualifier_on_the_line_is_reported():
    st = _structure("exhibited an absorption maximum (λmax) at 204 nm.")
    assert "format.subscript" in _rules(S.check_subscript_markers(st))


def test_names_and_ordinary_words_are_not_variables():
    """Requiring three qualifier letters still matched `Amin` — a person's name, and
    a common one in these manuscripts — plus `Jobs` and `Teff`, which is a grain."""
    st = _structure("Amin et al. reported this.",
                    "Jobs were scheduled overnight.",
                    "Teff (Eragrostis tef) is a staple grain.")
    assert S.check_subscript_markers(st) == []


def test_a_negative_exponent_on_a_unit_is_reported():
    st = _structure("The band appeared at 1650 cm-1 in the spectrum.",
                    "Yield reached 2.4 t ha-1 in the treated plots.")
    assert _rules(S.check_subscript_markers(st)).count("format.superscript") == 2


def test_a_hyphenated_label_is_not_an_exponent():
    """`Fig-3`, `Vol-1`, `HFS-3` and `of -1` all matched the first pattern, which
    allowed any one-to-four letters before the hyphen."""
    st = _structure("As shown in Fig-3 and Vol-1 of the HFS-3 series.")
    assert S.check_subscript_markers(st) == []


def test_a_genus_with_a_plant_part_is_not_a_binomial():
    """A second pass over the corpus turned up `Jatropha oil`, `Jatropha seeds` and
    `Rhizobium inoculants` — 9 of 87 findings, all the same shape."""
    st = _structure("Jatropha oil and Jatropha seeds were pressed.",
                    "Rhizobium inoculants raised the yield.",
                    "Fusarium resistant lines were selected.")
    assert S.check_species_italic(st) == []


def test_a_latin_epithet_ending_in_ans_survives_the_english_filter():
    """`-ant` is an English ending and `-ans` is not: `Caenorhabditis elegans` and
    `Thiobacillus denitrificans` are real species."""
    st = _structure("Assays used Caenorhabditis elegans as the model organism.")
    msgs = " ".join(f.message for f in S.check_species_italic(st))
    assert "Caenorhabditis elegans" in msgs


# ------------------------------------------------------------- language variant

def test_the_configured_variant_is_applied_throughout():
    """On a real job set to US English the copyedit converted `analysing` to
    `analyzing` and left all five occurrences of `behaviour` — one document, both
    variants, which is what the editorial team reported."""
    got = S.enforce_language_variant(
        ["The behaviour of the coloured fibre was analysed at the centre."],
        "US English")
    assert got[0] == "The behavior of the colored fiber was analyzed at the center."


def test_it_works_the_other_way_too():
    got = S.enforce_language_variant(
        ["The behavior of the colored fiber was analyzed."], "British English")
    assert got[0] == "The behaviour of the coloured fibre was analysed."


def test_analyses_is_the_plural_of_analysis_in_both_variants():
    """`analyses` is the plural noun in US English too — "the analyses showed" is
    correct — and mapping it to `analyzes` turns a noun into a verb."""
    got = S.enforce_language_variant(["The analyses showed a clear trend."],
                                     "US English")
    assert got[0] == "The analyses showed a clear trend."


def test_capitalisation_survives():
    got = S.enforce_language_variant(["Behaviour was modelled. COLOUR mattered."],
                                     "US English")
    assert got[0] == "Behavior was modeled. COLOR mattered."


def test_nothing_happens_without_a_variant():
    text = ["The behaviour of the colour was analysed."]
    assert S.enforce_language_variant(text, "") == text
    assert S.enforce_language_variant(text, "Indian English") == text


def test_a_genus_with_a_compound_class_is_not_a_binomial():
    """A pharmacognosy review produced `Solanum steroid` — the genus followed by the
    compound class it yields, the same shape as the plant-part nouns."""
    st = _structure("Solanum steroid alkaloids were isolated from the fruit.")
    assert S.check_species_italic(st) == []


def test_solanaceae_genera_are_known():
    """`Datura stramonium` and `Atropa belladonna` sat beside `Solanum tuberosum` in
    one paragraph of a real review and only the Solanum was recognised."""
    st = _structure("Compared with Solanum tuberosum, Capsicum annuum, "
                    "Atropa belladonna and Datura stramonium samples.")
    got = {f.suggestion for f in S.check_species_italic(st)}
    assert got == {"Solanum tuberosum", "Capsicum annuum",
                   "Atropa belladonna", "Datura stramonium"}
