"""Author report ke teen faults, 23 Sep 2026 — aur wo taar jo tooti hui thi.

Ye file jaan-boojh kar `MISSING_RULES` ke naam **hardcode nahi** karti. Bug yahi
tha: module aise rule sunta tha jo koi check banata hi nahi (`figure.cited-but-
missing`), aur wo khamoshi se kabhi fire nahi hota. Isliye yahan rule ka naam
asli check se nikala jaata hai — agar naam kabhi badle, test tootega, chuppi nahi
rahegi.
"""
import author_report
import proofread as P


CITES_A_FIGURE_THAT_IS_NOT_THERE = [
    "A Study of Something",
    "Abstract- This paper reports an experiment on composite beams and their behaviour "
    "under load, with the apparatus described in the following section.",
    "The apparatus is shown in Figure 9, which also gives the loading arrangement used "
    "throughout the tests reported here.",
] + ["Body text that carries the paper along without saying anything of note." for _ in range(25)]


def _rule_names_the_checks_really_emit():
    found = P.mechanical_findings(CITES_A_FIGURE_THAT_IS_NOT_THERE)
    return {f.rule for f in found}


def test_the_checks_do_report_a_cited_figure_with_no_caption():
    """Pehle ye saabit karo ki check khud kaam karta hai."""
    assert "crossref.figure-missing" in _rule_names_the_checks_really_emit()


def test_the_report_listens_for_the_name_the_check_actually_uses():
    """Ye wahi assertion hai jo purane code par laal hoti thi."""
    emitted = _rule_names_the_checks_really_emit()
    assert "crossref.figure-missing" in author_report.MISSING_RULES, (
        "the report listens for %s but the checks emit %s"
        % (sorted(author_report.MISSING_RULES), sorted(emitted)))


def test_a_cited_figure_with_no_caption_reaches_the_author():
    findings = P.mechanical_findings(CITES_A_FIGURE_THAT_IS_NOT_THERE)
    md = author_report.build("paper.docx", findings=findings, queries=[])
    assert "Figure 9" in md, md[:600]


def test_our_own_reference_loss_is_not_the_authors_to_supply():
    """"N reference(s) ... went missing while the bibliography was being reformatted"
    hamari galti hai. Wo us list me nahi aani chahiye jo kehti hai "only you can
    supply them"."""
    ours = {"guard": "verify_reference_block",
            "query": "2 reference(s) the author listed went missing while the "
                     "bibliography was being reformatted. They were put back."}
    theirs = {"guard": "refuse_citations_without_a_reference",
              "query": "Citation [7] has no reference. Please supply it."}
    md = author_report.build("paper.docx", findings=[], queries=[ours, theirs])
    gap_section = md.split("## What is missing")[1].split("##")[0]
    assert "went missing while" not in gap_section, gap_section
    assert "Citation [7] has no reference" in gap_section, gap_section


def test_the_empty_case_does_not_claim_more_than_it_checked():
    md = author_report.build("paper.docx", findings=[], queries=[])
    gap_section = md.split("## What is missing")[1].split("##")[0]
    assert "Our automatic checks" in gap_section, gap_section
    # Purana vaakya bina shart ke "Nothing." kehta tha aur review usi page par
    # uska ulta likh deta tha.
    assert not gap_section.strip().startswith("Nothing."), gap_section
