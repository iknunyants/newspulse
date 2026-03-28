"""Unit tests for formatting utilities."""
import re

from newspulse.formatting import format_digest, format_notification


def test_format_digest_basic():
    items = [
        ("Article One", "First sentence. Second.", "BBC World",
         "https://example.com/1", ["Armenia"]),
        ("Article Two", "Another summary.", "Al Jazeera",
         "https://example.com/2", ["Politics", "Economy"]),
    ]
    msg = format_digest(items)
    assert "Daily Digest" in msg
    assert "Article One" in msg
    assert "Article Two" in msg
    assert "BBC World" in msg
    assert "example.com/1" in msg
    assert "example.com/2" in msg


def test_format_digest_numbered():
    items = [
        ("Title A", "Summary.", "Source", "https://example.com/a", ["topic"]),
        ("Title B", "Summary.", "Source", "https://example.com/b", ["topic"]),
    ]
    msg = format_digest(items)
    assert "1\\." in msg
    assert "2\\." in msg


def test_format_digest_empty():
    msg = format_digest([])
    assert "Daily Digest" in msg


def test_format_notification_structure():
    msg = format_notification(
        title="Test Article",
        content="First sentence. Second sentence.",
        source="BBC World",
        url="https://example.com/article",
        topic_texts=["Armenia"],
    )
    assert re.search(r"\*.+\*", msg)
    assert "BBC World" in msg
    assert "Armenia" in msg
    assert "Read article" in msg
