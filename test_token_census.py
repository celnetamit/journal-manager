"""The net underneath the guards — and the false positives it had to stop reporting.

Each negative case here is a real finding from a real redline, not an invented one:
the first version of this check reported about as much correct copyediting as it did
damage, and a report like that is read once.
"""
import token_census as T


def _found(original, edited):
    return [q["query"].split("`")[1]
            for q in T.missing_tokens(original, edited)]


# --- what it must catch -------------------------------------------------------

def test_a_subscript_marker_that_vanished_is_reported():
    """Job #104, the finding that prompted this: no guard anywhere asked the
    question, so it went through the whole chain untouched."""
    assert _found(["recovery (G_IC,healed/G_IC,pristine) to identify"],
                  ["recovery (GIC,healed/GIC,pristine) to identify"]) == [
        "G_IC,healed", "G_IC,pristine"]


def test_a_value_that_went_with_its_equation_is_reported():
    """Job #100: `K_IC ≈ 0.7 MPa·m^1/2` and `a = 50 nm` left no trace in the file."""
    found = _found(["where K_IC ≈ 0.7 MPa is the toughness and a = 50 nm the flaw"],
                   ["where the toughness and the flaw size are given"])
    assert "0.7 MPa" in found and "50 nm" in found


def test_a_reported_token_is_reported_once():
    """A term used in six paragraphs is one thing to check, not six."""
    original = ["the value of G_IC,healed here"] * 6
    edited = ["the value of GIC,healed here"] * 6
    assert _found(original, edited) == ["G_IC,healed"]


# --- what it must not report --------------------------------------------------

def test_unit_spacing_is_not_a_loss():
    """`1J` -> `1 J` and `150 °C` -> `150°C` were most of the first version's output."""
    assert _found(["an impact above 1J at 150 °C"], ["an impact above 1 J at 150°C"]) == []


def test_the_house_subscript_conversion_is_not_a_loss():
    assert _found(["the H2O and SiO2 content"], ["the H₂O and SiO₂ content"]) == []


def test_the_house_superscript_conversion_is_not_a_loss():
    """Job #68: `R^2` set as `R²` is this pipeline doing its job."""
    assert _found(["an R^2 of 0.98"], ["an R² of 0.98"]) == []


def test_but_a_dropped_superscript_marker_is():
    assert _found(["an R^2 of 0.98"], ["an R2 of 0.98"]) == ["R^2"]


def test_the_invisible_twins_are_one_token():
    assert _found(["particles of 5 μm"], ["particles of 5 µm"]) == []


def test_a_range_collapsed_correctly_is_not_a_loss():
    """`(between 45°C - 48°C)` -> `(45–48°C)`. The number and its unit are still
    together, which is the question worth asking."""
    assert _found(["agar (between 45°C - 48°C) inside"], ["agar (45–48°C) inside"]) == []


def test_an_underscore_inside_an_ordinary_word_is_not_a_symbol():
    """Job #94: the author typed `Digital_Financial`, and opening it up is correct."""
    assert _found(["Cost of Digital_Financial Services"],
                  ["Cost of Digital Financial Services"]) == []


def test_a_figure_label_is_not_sixteen_amperes():
    """Job `92e07cc6`: `Figure 16 A comparison of…` — `A`, `L`, `M` and `t` are out of
    the unit list for this reason."""
    assert _found(["Figure 16 A comparison of curves"],
                  ["Figure 16. A comparison of curves"]) == []


def test_a_doi_suffix_is_not_a_chemical_formula():
    """Job #73: `10.1039/D2RA01131J`, lower-cased by the reference reformatting."""
    assert _found(["RSC Adv. 2022; 12: 14299. 10.1039/D2RA01131J."],
                  ["RSC Adv. 2022;12:14299. 10.1039/d2ra01131j."]) == []


def test_a_link_s_query_string_is_not_a_symbol():
    """Job #93: `cf_chl` and `f_tk` came out of a Cloudflare challenge in a URL that
    was correctly cleaned up."""
    assert _found(
        ["see https://pubs.acs.org/doi/10.1021/x?__cf_chl_f_tk=wFseF4Cbi3 here"],
        ["see https://doi.org/10.1021/x here"]) == []


def test_a_year_is_not_an_indium_compound():
    assert _found(["In 2023 the study ran"], ["In 2023, the study ran"]) == []


def test_text_that_only_moved_is_not_lost():
    """The whole edited manuscript is the haystack, not the matching paragraph."""
    assert _found(["the sample was 50 nm across", "it was then heated"],
                  ["the sample was measured", "at 50 nm it was then heated"]) == []
