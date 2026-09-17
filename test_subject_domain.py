"""Which field a manuscript is in, and how much to trust the answer."""

from __future__ import annotations

import subject_domain as S


def test_the_portfolios_own_topics_map_somewhere():
    assert S.domain_of_topic("Mechanical Engineering") == "engineering"
    assert S.domain_of_topic("Energy") == "engineering"
    assert S.domain_of_topic("Law") == "law"
    assert S.domain_of_topic("Nursing") == "medical & health"
    assert S.domain_of_topic("Computer/IT") == "computer & IT"


def test_chemical_engineering_is_engineering_and_analytical_chemistry_is_not():
    """Shortest-match put every chemical engineering journal under chemistry."""
    assert S.domain_of_topic("Chemical Engineering") == "engineering"
    assert S.domain_of_topic("Analytical Chemistry") == "chemistry"


def test_three_journals_that_agree_are_reported_as_agreeing():
    found = S.detect([{"topics": ["Mechanical Engineering"]},
                      {"topics": ["Energy"]},
                      {"topics": ["Material Science"]}])
    assert found["domain"] == "engineering" and found["agreed"] == 3
    assert "all 3 recommended journals agree" in S.as_sentence(found)


def test_a_split_is_reported_as_a_split():
    """A single confident word would not tell an editor how much to trust it."""
    found = S.detect([{"topics": ["Chemistry"]},
                      {"topics": ["Chemistry"]},
                      {"topics": ["Life Sciences"]}])
    sentence = S.as_sentence(found)
    assert found["domain"] == "chemistry" and found["agreed"] == 2
    assert "2 of 3" in sentence and "life sciences" in sentence


def test_an_unknown_topic_is_skipped_rather_than_forced():
    assert S.domain_of_topic("Multidisciplinary") is None
    assert S.detect([{"topics": ["Multidisciplinary"]}]) is None


def test_no_recommendation_means_no_claim():
    assert S.detect([]) is None
    assert S.as_sentence(None) == ""
