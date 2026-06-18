"""Tests for the deterministic 6-author reference trimming pass."""

from editor import enforce_author_limit, _trim_reference_authors


def test_journal_eight_authors_trimmed_to_six():
    ref = ("Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, Brown G, Davis H. "
           "Title of the article. J Sci. 2020;10(2):100-10.")
    out = _trim_reference_authors(ref)
    assert out == ("Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, et al. "
                   "Title of the article. J Sci. 2020;10(2):100-10.")


def test_exactly_six_authors_unchanged():
    ref = ("Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F. "
           "Title. J Sci. 2020;10(2):100-10.")
    assert _trim_reference_authors(ref) == ref


def test_seven_authors_with_leading_number_keeps_prefix():
    ref = ("1. Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, Brown G. "
           "Title. J Sci. 2020.")
    out = _trim_reference_authors(ref)
    assert out == ("1. Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, et al. "
                   "Title. J Sci. 2020.")


def test_bracketed_number_prefix():
    ref = ("[12] Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, Brown G, Davis H. "
           "Title. Nature. 2021.")
    out = _trim_reference_authors(ref)
    assert out.startswith("[12] Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, et al. ")


def test_already_abbreviated_unchanged():
    ref = ("Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, et al. "
           "Title. J Sci. 2020.")
    assert _trim_reference_authors(ref) == ref


def test_body_sentence_not_touched():
    para = ("The results showed a significant improvement across all cohorts, and "
            "further analysis confirmed the trend. We then repeated the experiment.")
    assert _trim_reference_authors(para) == para


def test_in_text_author_date_not_touched():
    para = ("Recent work (Smith A, Jones B, Lee C, Patel D, Garcia E, Kim F, Brown G, "
            "2020) demonstrated the effect. It was robust.")
    assert _trim_reference_authors(para) == para


def test_multiword_surname_eight_authors():
    ref = ("Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, Brown-White G, O'Neil H. "
           "Title. J Med. 2019.")
    out = _trim_reference_authors(ref)
    assert out == ("Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, et al. "
                   "Title. J Med. 2019.")


def test_enforce_respects_disabled_reference_group():
    ref = ("Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, Brown G, Davis H. "
           "Title. J Sci. 2020.")
    # reference group disabled -> no change
    assert enforce_author_limit([ref], enabled_rule_ids=["heading"]) == [ref]
    # reference group enabled -> trimmed
    assert enforce_author_limit([ref], enabled_rule_ids=["reference"])[0] != ref


def test_enforce_preserves_blank_paragraphs():
    paras = ["", "   ", "Smith JA, Jones BR, Lee C, Patel DK, Garcia E, Kim F, Brown G, Davis H. Title. J. 2020."]
    out = enforce_author_limit(paras)
    assert out[0] == "" and out[1] == "   "
    assert "et al." in out[2]
