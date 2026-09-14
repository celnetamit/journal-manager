"""What a journal looks like to the recommender.

Before 14 Sep 2026 a journal was its name plus a `topics` list, and 232 of the 274 journals
had exactly one topic — "computer" for all twenty-eight computer titles. Nothing in that
could separate two of them, so the recommendation came down to which name looked more like
the manuscript. These tests pin the shape that replaced it: the journal's own subject areas
and the focus and scope the editors publish.
"""

import editor


JOURNAL = {
    "name": "Current Trends in Information Technology",
    "code": "CTIT",
    "topics": ["Computer/IT"],
    "subject_areas": ["Data Management", "Network Technologies", "Machine Learning"],
    "scope": "Data models and database design: relational, object-oriented, document "
             "and graph data models, schema design and normalisation. " + ("x" * 9000),
}


def test_the_embedding_text_carries_the_areas_and_the_scope():
    text = editor._journal_embed_text(JOURNAL)
    assert "Current Trends in Information Technology" in text
    assert "Network Technologies" in text
    assert "relational, object-oriented" in text


def test_subject_areas_come_before_the_scope_prose():
    """The first tokens weigh most in every embedding model we might use, and the areas
    are the journal's remit in the editors' own words."""
    text = editor._journal_embed_text(JOURNAL)
    assert text.index("Machine Learning") < text.index("Data models")


def test_a_very_long_scope_is_capped():
    """Otherwise a journal that pastes its author guidelines into the field drowns out its
    own subject areas."""
    text = editor._journal_embed_text(JOURNAL)
    assert len(text) < len(JOURNAL["scope"]) + 500
    assert len(text) <= editor.SCOPE_EMBED_CHARS + 500


def test_a_journal_with_nothing_but_a_name_still_embeds():
    assert editor._journal_embed_text({"name": "Journal of Nothing"}) == "Journal of Nothing"


def test_the_matchable_terms_are_areas_then_domain():
    terms = editor._journal_terms(JOURNAL)
    assert terms[0] == "Data Management"
    assert "Computer/IT" in terms


def test_the_scope_prose_is_not_turned_into_match_terms():
    """It is sentences, not a remit: every long scope would match every paper on ordinary
    words, and the journal with the most text would always win."""
    terms = editor._journal_terms(JOURNAL)
    assert not any("relational" in t for t in terms)


def test_two_journals_in_one_domain_are_no_longer_identical():
    """The whole point. Same topic, different areas — different text to the model."""
    other = dict(JOURNAL, name="Journal of Computer Technology & Applications",
                 subject_areas=["Compilers", "Operating Systems"],
                 scope="Systems software: compilers, kernels, schedulers.")
    assert editor._journal_embed_text(JOURNAL) != editor._journal_embed_text(other)
    assert editor._journal_terms(JOURNAL) != editor._journal_terms(other)


def test_a_hit_on_one_area_does_not_score_a_narrow_journal_higher_than_a_broad_one():
    """A journal listing three areas used to get 0.33 for a single weak hit while one
    listing thirty could not reach that however well it matched."""
    narrow = {"name": "Narrow", "subject_areas": ["Machine Learning"], "score": 0.5}
    broad = dict(JOURNAL, score=0.5)
    abstract = "a study of machine learning applied to network technologies"
    assert editor._prescreen_score(broad, abstract) >= editor._prescreen_score(narrow, abstract)
