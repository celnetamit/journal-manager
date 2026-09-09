"""The three things the team found in job #59, each with the text that showed them.

Every case here is quoted from *Ms. Harmeet's Review formatting.docx* as the pipeline
actually rendered it, not invented — a consistency rule written against imagined text
tends to fire on real text for the wrong reason.
"""

from __future__ import annotations

import proofread as P

# Paragraphs 153-163 of job #59, in order. "OER" is used in three headings and a table,
# then expanded at 159 and expanded AGAIN at 163.
OER_DOC = [
    "Evaluation of OER Quality",
    "Lack of consistent frameworks for evaluating and curating OER materials",
    "By integrating adaptive learning technologies, collaborative learning platforms, "
    "and open educational resources (OER), we have drawn valuable conclusions.",
    "OER and Global Accessibility: Open Educational Resources (OER) provide free, "
    "customizable learning materials.",
]

# Four references from the same list: three abbreviated, one spelled out.
REF_DOC = [
    "1. Seale J. It's not all doom and gloom: what the pandemic taught us. "
    "Br J Educ Technol. 2021; 52(4): 1545–1552p.",
    "4. Mikropoulos TA, Iatraki G. Digital technology supports science education for "
    "students with disabilities: a systematic review. Educ Inf Technol. 2023; 28(4): 3911–3935p.",
    "7. Topping KJ, Douglas W. Effectiveness of online and blended learning from "
    "schools: a systematic review. Rev Educ. 2022; 10(2): e3353.",
    "17. Downes S, Siemens G. Connectivism: a learning theory of the digital age. "
    "International Journal of Instructional Technology and Distance Learning. 2005; 2(1): 3–10p.",
]


def rules(findings):
    return {f.rule for f in findings}


def test_acronym_used_before_it_is_defined():
    found = P._acronym_findings(OER_DOC)
    hit = [f for f in found if f.rule == "acronym.used_before_definition"]
    assert hit, "OER is used in the heading before it is expanded"
    assert hit[0].paragraph == 0                 # flagged at its FIRST use, not later
    assert "paragraph 3" in hit[0].message       # and it names where the definition is


def test_acronym_expanded_twice():
    hit = [f for f in P._acronym_findings(OER_DOC) if f.rule == "acronym.defined_twice"]
    assert hit and hit[0].paragraph == 3
    assert "3 and 4" in hit[0].message


def test_a_parenthesis_that_is_not_a_definition_is_ignored():
    """"the model (SEM)" does not define SEM, and flagging it would be noise.

    The initials of the words before the bracket have to spell the acronym; without
    that check every parenthetical capital in the manuscript becomes a "definition".
    """
    assert P._acronym_findings(["The model (SEM) was fitted.", "SEM again."]) == []


def test_reference_list_mixing_abbreviated_and_full_journal_names():
    hit = [f for f in P._reference_style_findings(REF_DOC)
           if f.rule == "reference.journal_abbreviation"]
    assert len(hit) == 1, "only the odd one out should be flagged"
    assert hit[0].paragraph == 3
    assert "International Journal of Instructional Technology" in hit[0].fragment
    assert "abbreviated" in hit[0].message


def test_a_consistently_abbreviated_list_is_not_flagged():
    """The rule is consistency, not a preference for either convention."""
    assert P._reference_style_findings(REF_DOC[:3]) == []


def test_too_few_references_to_call_it_a_convention():
    """Two entries are not a house style; flagging them would be an opinion."""
    assert P._reference_style_findings(REF_DOC[2:]) == []


# The ILO case Amit asked about: an organisation name introduced once and never
# shortened afterwards. The rule is the same as for any abbreviation — but an
# abbreviation nobody uses a second time has only cost the reader a bracket.

def test_an_abbreviation_introduced_once_and_never_used_is_flagged():
    doc = [
        "Employment patterns were reviewed across three regions.",
        "The International Labour Organization (ILO) reports a widening gap in "
        "access to vocational training.",
        "That gap is largest in rural districts.",
    ]
    hits = [f for f in P._acronym_findings(doc) if f.rule == "acronym.defined_but_unused"]
    assert len(hits) == 1 and hits[0].paragraph == 1
    assert "International Labour Organization" in hits[0].suggestion


def test_an_abbreviation_that_is_used_again_is_not_flagged():
    """The normal, correct case: define once, then use the short form."""
    doc = [
        "The International Labour Organization (ILO) reports a widening gap.",
        "The ILO recommends expanding vocational programmes.",
        "ILO figures for 2024 show the same pattern.",
    ]
    assert [f for f in P._acronym_findings(doc)
            if f.rule == "acronym.defined_but_unused"] == []


# ------------------------------------------------ the abstract carries no short forms

def test_an_abbreviation_left_in_the_abstract_is_reported():
    """Job #53 expanded PID in the abstract's first paragraph and left it in the third.

    The house rule is that an abstract carries no abbreviations at all — it is read on
    its own, away from the paper that defines its terms — and the model applied it to
    one paragraph of one abstract but not the next.
    """
    doc = [
        "Abstract",
        "The system combines electromagnetic and disc braking for safety.",
        "The system merges ultrasonic and infrared sensors, and a PID controller "
        "distributes the braking force.",
        "Keywords: braking, sensors",
        "A proportional-integral-derivative (PID) control algorithm analyzes inputs.",
    ]
    hits = [f for f in P._abstract_abbreviation_findings(doc)
            if f.rule == "abstract.abbreviation"]
    assert len(hits) == 1 and hits[0].paragraph == 2
    assert "PID" in hits[0].message


def test_a_hyphenated_expansion_still_defines_its_acronym():
    """`proportional-integral-derivative (PID)` is one whitespace token.

    Splitting on spaces alone gave the initials "P", so PID was not recognised as
    defined anywhere — and every check that starts from "what does this paper define"
    walked past it, including the abstract one above.
    """
    defs, phrases = P._definitions_in(
        ["A proportional-integral-derivative (PID) control algorithm analyzes inputs."])
    assert "PID" in defs
    assert phrases["PID"] == "proportional-integral-derivative"


def test_an_oxidation_state_is_not_an_abbreviation():
    """`Cr(VI)` fills job #52's abstract and is not a short form of anything."""
    doc = ["Abstract",
           "The oxidation of thiourea by Cr(VI) was followed at pH 2.44.",
           "Keywords: thiourea"]
    assert P._abstract_abbreviation_findings(doc) == []
