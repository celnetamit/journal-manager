"""Tests for the deterministic keywords-line normalizer (enforce_keywords_format
/ _format_keywords_line): alphabetical order, first-keyword capitalization, the
cased-term safety net, and the guard against mangling a non-keyword sentence."""

from editor import _format_keywords_line, enforce_keywords_format


def test_alphabetical_and_first_capital():
    out = _format_keywords_line(
        "Keywords: Internet of Things, Artificial Intelligence, quality control"
    )
    assert out == "Keywords: Artificial Intelligence, Internet of Things, quality control"


def test_first_letter_capitalized_when_lowercase():
    out = _format_keywords_line("Keywords: zebra, apple")
    assert out == "Keywords: Apple, zebra"


def test_cased_terms_preserved():
    # Intentionally-cased scientific terms must never be force-capitalized.
    assert _format_keywords_line("Keywords: mRNA vaccines, gene therapy") == (
        "Keywords: Gene therapy, mRNA vaccines"
    )
    assert _format_keywords_line("Keywords: pH sensing, biosensors") == (
        "Keywords: Biosensors, pH sensing"
    )
    assert _format_keywords_line("Keywords: iOS apps, mobile health") == (
        "Keywords: iOS apps, mobile health"
    )


def test_single_or_empty_left_untouched():
    assert _format_keywords_line("Keywords: only one") == "Keywords: only one"
    assert _format_keywords_line("Keywords:") == "Keywords:"


def test_non_keyword_sentence_not_mangled():
    # A body sentence that merely starts with "Keyword:" must be left alone.
    prose = "Keyword: this approach works well, scales nicely, and is robust"
    assert _format_keywords_line(prose) == prose

    sentence = "Keyword: the method is fast. It also scales, well, here"
    assert _format_keywords_line(sentence) == sentence


def test_and_joined_list_defers_safely():
    # An "and"-joined keyword list is left to the LLM rather than risk corruption.
    line = "Keywords: machine learning, deep learning, and neural networks"
    assert _format_keywords_line(line) == line


def test_enforce_respects_disabled_rule():
    paras = ["Keywords: b, a"]
    # Rule group not enabled -> untouched.
    assert enforce_keywords_format(paras, enabled_rule_ids=["reference"]) == paras
    # Enabled -> normalized.
    assert enforce_keywords_format(paras, enabled_rule_ids=["keywords"]) == [
        "Keywords: A, b"
    ]
