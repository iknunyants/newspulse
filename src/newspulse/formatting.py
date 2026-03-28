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


def format_digest(
    items: list[tuple[str, str, str, str, list[str]]],
) -> str:
    """Build a MarkdownV2 daily digest message.

    Each item is (title, summary, source, url, topic_texts).
    Groups articles with a numbered list.
    """
    header = "📰 *Your Daily Digest*\n"
    lines: list[str] = [header]
    for i, (title, summary, source, url, topic_texts) in enumerate(items, 1):
        short = extract_summary(summary, max_sentences=1)
        topics_str = escape_md(", ".join(topic_texts))
        entry = (
            f"*{i}\\. {escape_md(title)}*\n"
            f"{escape_md(short)}\n"
            f"📰 _{escape_md(source)}_ · 🏷 _{topics_str}_\n"
            f"[Read]({escape_url(url)})"
        )
        lines.append(entry)
    return "\n\n".join(lines)
