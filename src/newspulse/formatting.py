"""Message formatting utilities for Telegram MarkdownV2 notifications."""
from __future__ import annotations

import re

_MD_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return "".join(f"\\{c}" if c in _MD_SPECIAL else c for c in text)


def escape_url(url: str) -> str:
    """Escape characters that must be escaped inside a MarkdownV2 link URL."""
    return url.replace("\\", "\\\\").replace(")", "\\)")


def extract_summary(text: str, max_sentences: int = 2) -> str:
    """Extract up to max_sentences sentences from text.

    Returns an empty string if text is empty.
    """
    text = text.strip()
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chosen = sentences[:max_sentences]
    result = " ".join(chosen).strip()
    # Ensure it ends with punctuation
    if result and result[-1] not in ".!?":
        result += "."
    return result


def format_notification(
    title: str,
    content: str,
    source: str,
    url: str,
    topic_texts: list[str],
) -> str:
    """Build a MarkdownV2 Telegram notification message.

    Structure:
        *Title*

        Summary sentence one. Summary sentence two.

        📰 _Source_
        🏷 _Topic: topic text_   (or Topics: a, b  when multiple match)

        [Read article](url)
    """
    parts: list[str] = [f"*{escape_md(title)}*"]

    summary = extract_summary(content)
    if summary:
        parts.append(escape_md(summary))

    label = "Topics" if len(topic_texts) > 1 else "Topic"
    topics_str = escape_md(", ".join(topic_texts))
    parts.append(
        f"📰 _{escape_md(source)}_\n"
        f"🏷 _{label}: {topics_str}_"
    )

    parts.append(f"[Read article]({escape_url(url)})")

    return "\n\n".join(parts)


def format_digest_parts(
    items: list[tuple[str, str, str, str, list[str]]],
    max_len: int = 4096,
) -> list[str]:
    """Build MarkdownV2 digest messages split to stay under Telegram's character limit.

    Each item is (title, summary, source, url, topic_texts).
    Returns a list of message strings, each under max_len characters.
    """
    parts: list[str] = []
    header = "📰 *Your Daily Digest*\n"
    current_entries: list[str] = []
    current_header = header
    current_len = len(header)
    article_index = 1

    for title, summary, source, url, topic_texts in items:
        short = extract_summary(summary, max_sentences=1)
        topics_str = escape_md(", ".join(topic_texts))
        entry = (
            f"*{article_index}\\. {escape_md(title)}*\n"
            f"{escape_md(short)}\n"
            f"📰 _{escape_md(source)}_ · 🏷 _{topics_str}_\n"
            f"[Read]({escape_url(url)})"
        )
        # "\n\n" separator between entries
        needed = len(entry) + (2 if current_entries else 0)
        if current_entries and current_len + needed > max_len:
            parts.append(current_header + "\n\n".join(current_entries))
            current_header = "📰 *Your Daily Digest \\_\\(continued\\)_*\n"
            current_entries = []
            current_len = len(current_header)
        current_entries.append(entry)
        current_len += needed
        article_index += 1

    if current_entries:
        parts.append(current_header + "\n\n".join(current_entries))
    elif not parts:
        # Empty digest — return just the header
        parts.append(header)

    return parts


def format_digest(
    items: list[tuple[str, str, str, str, list[str]]],
) -> str:
    """Build a MarkdownV2 daily digest message.

    Each item is (title, summary, source, url, topic_texts).
    Returns the first message part (use format_digest_parts for multi-part digests).
    """
    return format_digest_parts(items)[0]
