"""The proofreading pass.

Half of these tests are about what the proofreader must **not** say. The first run over
three real manuscripts produced 10, 6 and 30 findings of which most were DOIs, email
addresses and ISSNs reported as punctuation errors — all correct text. A report that is
mostly wrong is not a partly-useful report; it is one the editor stops opening, and then
the two real findings in it are lost too. After masking, the same three files give 3, 2
and 21, and every one is real.
"""

import proofread as P


def rules(findings):
    return sorted(f.rule for f in findings)


# ------------------------------------------------------------------ true positives

def test_double_space_is_found():
    f = P.mechanical_findings(["The result  was significant across the samples."])
    assert "space.double" in rules(f)


def test_space_before_punctuation_is_found():
    f = P.mechanical_findings(["Vastu , the ancient Indian architectural tradition."])
    assert "space.before-punctuation" in rules(f)
    assert f[0].paragraph == 0


def test_missing_space_after_a_full_stop_is_found():
    f = P.mechanical_findings(["The trial ended.Results were then analysed further."])
    assert "space.after-punctuation" in rules(f)


def test_unbalanced_parentheses_are_found():
    f = P.mechanical_findings(
        ["(Dihydroxyphosphaneyl)methyl)-1.3.3-tris(phosphonomethyl)guanidine)"])
    assert "punctuation.unbalanced" in rules(f)


def test_a_repeated_word_is_found():
    f = P.mechanical_findings(["The the sample was heated to constant mass."])
    assert "word.doubled" in rules(f)


def test_mixed_spelling_across_the_manuscript_is_reported_once():
    f = P.mechanical_findings([
        "We analyse the data using standard methods.",
        "The samples were analyzed in triplicate.",
        "Further analyzed results follow.",
    ])
    spelling = [x for x in f if x.rule == "consistency.spelling"]
    assert len(spelling) == 1
    # It says which spelling dominates, so the editor has something to act on
    # rather than only a complaint.
    assert "analyze" in (spelling[0].suggestion or "")


def test_a_figure_referenced_but_never_captioned_is_reported():
    f = P.mechanical_findings([
        "As shown in Figure 4, the yield increases.",
        "Figure 1. The reaction scheme.",
    ])
    assert "crossref.figure-missing" in rules(f)


def test_a_captioned_figure_nobody_cites_is_reported():
    f = P.mechanical_findings([
        "The reaction proceeds cleanly.",
        "Figure 2. Apparatus used.",
    ])
    assert "crossref.figure-uncited" in rules(f)


# ----------------------------------------------------------------- false positives

def test_a_doi_is_not_a_punctuation_error():
    f = P.mechanical_findings(
        ["Smith J. Chemistry of scale. J Pet Sci. 2016;140:1149. "
         "doi:10.1016/j.ajhg.2016.09.015."])
    assert "space.after-punctuation" not in rules(f)


def test_an_email_address_is_not_a_punctuation_error():
    f = P.mechanical_findings(
        ["Corresponding author: aliyu.mohammed@sun.edu.ng for all correspondence."])
    assert "space.after-punctuation" not in rules(f)


def test_a_url_is_not_a_punctuation_error():
    f = P.mechanical_findings(
        ["Further material is available at www.biophilic-design.com for readers."])
    assert "space.after-punctuation" not in rules(f)


def test_an_issn_is_not_a_number_range():
    f = P.mechanical_findings(["Journal of Design, Volume 8, Issue 2, ISSN: 2583-8903"])
    assert "dash.range" not in rules(f)


def test_a_descending_pair_is_not_reported_as_a_range():
    """`2024-2019` is a typo or an identifier; calling it a dash problem sends the
    editor to fix the wrong thing."""
    f = P.mechanical_findings(["The cohort ran from 2024-2019 in the register."])
    assert "dash.range" not in rules(f)


def test_a_real_range_is_still_reported():
    f = P.mechanical_findings(["Samples were held at 20-25 degrees throughout."])
    assert "dash.range" in rules(f)


def test_a_reference_block_is_left_alone():
    f = P.mechanical_findings(
        ["1. Kelland MA. Production Chemicals for the Oil and Gas Industry. "
         "2nd ed. Boca Raton: CRC Press; 2014. p.45-67."])
    assert "space.after-punctuation" not in rules(f)
    assert "dash.range" not in rules(f)


def test_masking_keeps_the_offsets_honest():
    """The mask must not change the length, or a finding points at the wrong place."""
    text = "See https://example.com/a/b for detail , then continue."
    assert len(P._mask_opaque(text)) == len(text)
    f = P.mechanical_findings([text])
    assert "space.before-punctuation" in rules(f)


# ------------------------------------------------------------------------ LLM pass

def _fake_generate(payload_out):
    def generate(prompt, settings=None, response_mime_type=None):
        return payload_out
    return generate


def test_llm_findings_are_kept_when_the_fragment_is_real():
    paras = ["The affect of temperature on yield was measured across the samples."]
    out = P.llm_findings(paras, _fake_generate(
        '[{"index":0,"fragment":"The affect of temperature",'
        '"problem":"\'affect\' should be \'effect\'",'
        '"correction":"The effect of temperature"}]'), {})
    assert len(out) == 1
    assert out[0].suggestion == "The effect of temperature"


def test_a_fragment_the_model_invented_is_dropped():
    """Without this the editor is shown a quotation their author never wrote."""
    paras = ["The effect of temperature on yield was measured across the samples."]
    out = P.llm_findings(paras, _fake_generate(
        '[{"index":0,"fragment":"a sentence that is not in the paper",'
        '"problem":"something","correction":null}]'), {})
    assert out == []


def test_an_index_outside_the_batch_is_dropped():
    paras = ["A sufficiently long paragraph of manuscript text for the batch."]
    out = P.llm_findings(paras, _fake_generate(
        '[{"index":99,"fragment":"","problem":"something"}]'), {})
    assert out == []


def test_a_broken_model_response_loses_nothing_else():
    """A bad batch must not take the mechanical findings down with it."""
    paras = ["The result  was significant across every one of the samples measured."]
    out = P.proofread(paras, generate=_fake_generate("not json at all"), settings={})
    assert "space.double" in rules(out)


def test_findings_convert_to_the_query_shape_the_redline_expects():
    f = P.mechanical_findings(["Vastu , the ancient tradition."])[0]
    q = f.as_query()
    # `index`, not `local_index`: both `generate_redline_docx` and `generate_report`
    # read `q["index"]`, and the wrong key makes the finding vanish without an error.
    assert set(q) == {"index", "snippet", "query", "suggestion"}
    assert q["index"] == 0
