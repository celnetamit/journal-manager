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


# ------------------------------------------- formulas beyond the curated sixty

def test_a_formula_outside_the_list_is_still_subscripted():
    """A manuscript on the catalytic oxidation of thiourea is made of the formulas the
    curated list does not have. Its reaction scheme came through untouched and nothing
    said so."""
    got = S.enforce_all_formula_subscripts([
        "Thiourea (NH2CSNH2) was oxidised with K2S2O8 in H2SO4.",
        "Cr (IV)+ H  N2CSNH2Cr (III) + H  N2CH   N2SSCNH2NH2",
    ])
    assert got[0] == "Thiourea (NH₂CSNH₂) was oxidised with K₂S₂O₈ in H₂SO₄."
    assert "N₂CSNH₂" in got[1]


def test_equipment_and_statistics_survive_the_general_parser():
    """Why the general pattern was rejected the first time: over the corpus it
    returned 950 hits led by `D8`, `M4`, `R2` and `M0`. None of `D`, `M` or `R` is an
    element symbol, so insisting every symbol be real throws all four out."""
    text = ["A Bruker D8 gave R2 = 0.98 for the M4 and M0 samples over I2C."]
    assert S.enforce_all_formula_subscripts(text) == text


def test_the_confusables_the_corpus_named():
    """Every one of these parses cleanly as element symbols and none is chemistry.
    `OV2640` is a camera sensor, `BF00581071` a reference number, `SCF70` a specimen
    code, `SSW1` another, `B12` the vitamin, `V11NU02` a part number."""
    for token in ("OV2640", "BF00581071", "SCF70", "SSW1", "SSW2", "B12", "K3",
                  "V11NU02", "PI3K", "V2I", "HV3", "T2", "CD4"):
        assert not S.parses_as_formula(token), token


def test_real_formulas_of_every_shape():
    for token in ("H2O", "CO2", "FeCl3", "Fe3O4", "C6H12O6", "NH2CONH2", "K2S2O8",
                  "Ti6Al4V", "MgAl2O4", "CH3COOH", "N2", "O2", "I2"):
        assert S.parses_as_formula(token), token


def test_an_already_subscripted_formula_is_untouched_by_the_general_parser():
    text = ["Starch–Fe₃O₄ nanoblends and H₂O were used."]
    assert S.enforce_all_formula_subscripts(text) == text


# ------------------------------------------ symbols no model gets right

def test_the_increment_sign_becomes_a_greek_delta():
    """`∆` is U+2206 INCREMENT, a mathematical operator; the thermodynamic quantity
    is `Δ`, U+0394. They look identical and typeset differently.

    A three-model comparison on the same paragraph settled that no model choice fixes
    this: gemini-2.5-pro corrected `∆s`→`∆S` and left the increment sign,
    claude-sonnet-4.5 corrected the sign and left `Δs` lowercase, gemini-2.5-flash did
    neither — and all three had written `ΔS#` correctly one paragraph earlier."""
    got = S.enforce_science_symbols(
        ["(∆H#) = 41.49 kJ/mol, (∆s#) = -51.754 J/mol K, (∆G#) = 51.68 kJ/mol."])
    assert got[0] == ("(ΔH#) = 41.49 kJ/mol, (ΔS#) = -51.754 J/mol K, "
                      "(ΔG#) = 51.68 kJ/mol.")


def test_the_quantity_after_a_delta_takes_its_capital():
    got = S.enforce_science_symbols(["(ΔH#) is small and (Δs#) is more negative."])
    assert got[0] == "(ΔH#) is small and (ΔS#) is more negative."


def test_an_ordinary_lowercase_delta_term_is_left_alone():
    """Only where the letter is unambiguously a thermodynamic quantity — right after
    a delta and right before the activation marker or a closing bracket. `Δs` meaning
    "a small change in s" keeps its lower case."""
    text = ["a small change Δs in the signal was noted over Δt seconds"]
    assert S.enforce_science_symbols(text) == text


def test_the_double_dagger_form_is_handled_too():
    got = S.enforce_science_symbols(["(∆s‡) and (∆g‡) were derived."])
    assert got[0] == "(ΔS‡) and (ΔG‡) were derived."


# --- SI unit capitalisation ----------------------------------------------------

import pytest


@pytest.mark.parametrize("before, after", [
    ("Enthalpy was 42 KJ per mole.", "Enthalpy was 42 kJ per mole."),
    ("A 5 KG sample.", "A 5 kg sample."),
    ("Pellets pressed at 200 Mpa.", "Pellets pressed at 200 MPa."),
    ("45.06 MPA in an asymmetric case", "45.06 MPa in an asymmetric case"),
    ("sampling frequency of 700 HZ", "sampling frequency of 700 Hz"),
    ("avance neo 500Mhz with solvent", "avance neo 500MHz with solvent"),
    ("at a frequency of 50 KHz", "at a frequency of 50 kHz"),
    ("emisión de CO2 de 59.4Kg y", "emisión de CO2 de 59.4kg y"),
])
def test_unambiguous_unit_case_is_corrected(before, after):
    assert S.enforce_unit_case([before]) == [after]


@pytest.mark.parametrize("text", [
    "a torque of 4.2 Nm was applied",      # newton-metre, NOT nanometre
    "10 Mg of soil was collected",         # megagram, NOT milligram
    "a reservoir of 25 ML",                # megalitre, NOT millilitre
    "a distance of 3 Mm",                  # megametre, NOT millimetre
])
def test_ambiguous_units_are_never_rewritten(text):
    """Every one of these is a valid SI symbol. 'Correcting' it changes the quantity
    by a factor of a billion, and the result looks plausible enough that nothing
    downstream would ever query it."""
    assert S.enforce_unit_case([text]) == [text]


def test_only_corrects_in_a_measurement_context():
    """Without the preceding number, `KG` is an initialism and `Hz` is a surname."""
    for text in ("The KG index is unrelated.", "Reported by Hz and colleagues.",
                 "the KJV translation"):
        assert S.enforce_unit_case([text]) == [text]


def test_already_correct_text_is_untouched():
    text = "run at 100 kJ, 50 Hz and 2.4 GHz"
    assert S.enforce_unit_case([text]) == [text]


def test_empty_and_none_paragraphs_survive():
    assert S.enforce_unit_case(["", None, "5 KJ"]) == ["", None, "5 kJ"]
