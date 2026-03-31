"""Unit tests for formatting utilities."""
import re

from newspulse.formatting import format_digest, format_digest_parts, format_notification


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


def test_format_digest_parts_splits_large_digest():
    # Create enough articles to exceed 4096 chars in one message
    items = [
        (
            f"Article with a fairly long title number {i}",
            "This is a summary sentence that adds to the length of the message.",
            "BBC World",
            f"https://example.com/article/{i}",
            ["Armenia", "Politics"],
        )
        for i in range(30)
    ]
    parts = format_digest_parts(items)
    assert len(parts) > 1, "Large digest should be split into multiple parts"
    for part in parts:
        assert len(part) <= 4096, f"Part exceeds 4096 chars: {len(part)}"
    assert "Daily Digest" in parts[0]
    assert "continued" in parts[1]


def test_format_digest_parts_small_digest_single_part():
    items = [
        ("Short title", "Brief summary.", "Source", "https://example.com/x", ["topic"]),
    ]
    parts = format_digest_parts(items)
    assert len(parts) == 1
    assert "Short title" in parts[0]


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
