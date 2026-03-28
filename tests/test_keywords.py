"""Unit tests for keyword matching logic."""
from newspulse.matching.keywords import article_matches_keywords


def test_matches_keyword_in_title():
    assert article_matches_keywords("Armenia peace deal", "", ["Armenia"]) is True


def test_matches_keyword_in_summary():
    assert article_matches_keywords("", "The Armenia peace deal is near", ["Armenia"]) is True


def test_no_match():
    assert article_matches_keywords("Unrelated news", "About weather", ["Armenia"]) is False


def test_case_insensitive():
    assert article_matches_keywords("ARMENIA update", "", ["armenia"]) is True
    assert article_matches_keywords("armenia update", "", ["ARMENIA"]) is True


def test_partial_match():
    """Keywords match as substrings."""
    assert article_matches_keywords("Armenian politics", "", ["Armenian"]) is True


def test_empty_keywords():
    assert article_matches_keywords("Some article", "Some summary", []) is False


def test_empty_text():
    assert article_matches_keywords("", "", ["keyword"]) is False


def test_multiple_keywords_any_match():
    assert article_matches_keywords("Tech news", "", ["politics", "tech"]) is True
