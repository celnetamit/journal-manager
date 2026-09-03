"""Reference completeness, tuned against real bibliographies over six rounds.

Every false-positive case here was produced by an earlier version of this rule on the
corpus and judged by reading the entry in full. The share of references flagged went
62% → 48% → 37% → 34% → 25% → 21% → 16%, and every single narrowing found the rule
wrong rather than the manuscript.
"""

import reference_check as R


def gaps(text):
    return R.missing_fields(text)


# ------------------------------------------------- entries that are complete

def test_a_page_range_in_the_house_p_style():
    """`1189–224p.` — the house's own suffix. The trailing `\\b` after the digits
    could never match, so every entry in that style was reported as missing pages."""
    assert gaps("Ramakrishna S. Biomedical applications. "
                "Compos Sci Technol. 2001; 61: 1189-224p.") == []


def test_a_single_page_article():
    """How most modern journals number: no range at all."""
    for t in ("Mead, P. S. (1999). Food-related illness. "
              "Emerging infectious diseases, 5(5), 607.",
              "Syed, S. (2021). Bio-organic fertilizer. Minerals, 11(12), 1336.",
              "Le, Xuan-Hien. Application of LSTM. Water 11, no. 7 (2019): 1387."):
        assert gaps(t) == [], t


def test_letter_prefixed_pages():
    """`W597–W600` — web-issue pagination."""
    assert gaps("McWilliam H, Li W, et al. Analysis tool web services. "
                "Nucleic Acids Res. 2024;52(W1):W597-W600.") == []


def test_an_article_number_after_the_volume():
    assert gaps("Mishra, S.; Pandey, A. Heliyon. 2020, 6, e03217.") == []


def test_volume_shapes_that_are_not_parenthesised():
    for t in ("Edris, S. N. 2023. Prevalence of Enterobacterales. Vet. World, 16:403-413.",
              "Lu H., Wang X. Design of composites. Materials. 2015. V. 2. N 3. P. 958-977.",
              "[2] Molisch A. MIMO systems. IEEE Microw. Mag. 2004, 5, pp. 46-56."):
        assert gaps(t) == [], t


def test_author_shapes_real_bibliographies_use():
    """`Rao, YVH` has no dots, `Simões` is not ASCII, `European commission` is not a
    person, `Behrouz Pirouz` is first-name-first. All four were reported as having no
    author at all — 997 findings over the corpus, nearly every one wrong."""
    for t in ("Rao, YVH, Voleti, RS (2009) Performance of diesel engines. Energy Env, 20, 134-140.",
              "Simões, S. (2024). Advanced composites. Materials, 17(23), 5997.",
              "European commission (2024), Corporate sustainability reporting, "
              "retrieved from https://finance.ec.europa.eu/x",
              "Behrouz Pirouz. Improving green roofs. ResearchGate. 2021 Feb."):
        assert "authors" not in gaps(t), t


def test_sources_that_have_no_volume_or_pages_by_nature():
    """Books, standards, theses, conference papers, government and web sources."""
    for t in ("Mounika, G. (2024). Concrete. In E3S Web of Conferences (Vol. 559, 01008).",
              "Ministry of Environment, Cameroon. Environmental Management Plan, 2020.",
              "Singh B. Rarest of Rare. Supreme Court of India, 1980.",
              "Stachowiak G. W. Engineering Tribology. 4th ed. Elsevier, 2013.",
              "Oracle World Wide. Recycling Pyrolysis Plant. 2021. "
              "Retrieved from https://example.org/x"):
        assert "volume/issue" not in gaps(t) and "pages" not in gaps(t), t


# ------------------------------------------------- entries that are genuinely thin

def test_a_truncated_entry_is_still_reported():
    assert gaps('M. Bekoff, "Animal Emotions: Exploring Passionate Natures,"')


def test_a_journal_article_with_no_volume_or_pages_is_reported():
    """Narrowed, not disabled."""
    assert gaps("Gulshan, et al. Hybrid deep learning for diabetic retinopathy. "
                "IEEE Transactions on Biomedical Engineering (2019).")
    assert gaps("Patel, A. (2024). Enhanced hydrogen yields. Biotechnology Advances,")


# ------------------------------------------------- things that are not references

def test_body_text_after_the_references_heading_is_ignored():
    """`find_references` returns everything after the heading, which on a real
    manuscript includes appendices, figure captions and stray prose. Those were being
    reported as missing their authors, year, volume and pages — they are not missing
    them, they are not references."""
    class P:
        def __init__(self, t, i=0):
            self.text, self.index = t, i

    for t in ("β-glucosidase enzymes degrade the residual biomass. This helps maximise "
              "the conversion of cellulose into fermentable sugars for downstream use.",
              "Typical XPS wide scan spectrum of (a) 4A zeolite, (b) pure (MC-g-AAm)/NaAlg, "
              "(c) with 5 wt% 4A zeolite and (d) with 10 wt% 4A zeolite.",
              "Full transparency of methodologies and potential conflicts of interest "
              "have been maintained throughout the entire research process."):
        assert R.check_references([P(t)]) == [], t


def test_a_wrapped_first_line_is_not_judged_alone():
    class P:
        def __init__(self, t, i=0):
            self.text, self.index = t, i

    assert R.check_references(
        [P("Lihong Zheng, Xiangjian He, Bijan Samali, and Laurence")]) == []


def test_a_numbered_bibliography_is_grouped_into_entries():
    class P:
        def __init__(self, t, i=0):
            self.text, self.index = t, i

    paras = [P("[1] Smith J. A study of things. J Test. 2001; 5: 1-9.", 0),
             P("[2] Jones B. Another study.", 1),
             P("with the rest of the entry on this line. J Test. 2002; 6: 10-20.", 2),
             P("[3] Brown C. A third study. J Test. 2003; 7: 21-30.", 3)]
    entries = R.group_entries(paras)
    assert len(entries) == 3
    assert "2002" in entries[1][1]


def test_a_crossref_suggestion_is_offered_when_the_record_matches():
    class P:
        def __init__(self, t, i=0):
            self.text, self.index = t, i

    def fake(_):
        return {"authors": "Smith J", "title": "A study of things",
                "journal": "J Test", "year": "2001", "volume": "5",
                "issue": "2", "pages": "1-9", "doi": "10.1000/xyz"}

    (f,) = R.check_references(
        [P("Smith J. A study of things. J Test. 2001.")], fetch=fake)
    assert "10.1000/xyz" in f.suggestion
    assert "5(2)" in f.suggestion


def test_a_crossref_outage_costs_the_suggestion_not_the_run():
    class P:
        def __init__(self, t, i=0):
            self.text, self.index = t, i

    def boom(_):
        raise RuntimeError("crossref down")

    (f,) = R.check_references([P("Smith J. A study of things. J Test. 2001.")], fetch=boom)
    assert f.suggestion is None
    assert "must supply it" in f.message
