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
    topic_text: str,
) -> str:
    """Build a MarkdownV2 Telegram notification message.

    Structure:
        *Title*

        Summary sentence one. Summary sentence two.

        📰 _Source_
        🏷 _Topic: topic text_

        [Read article](url)
    """
    parts: list[str] = [f"*{escape_md(title)}*"]

    summary = extract_summary(content)
    if summary:
        parts.append(escape_md(summary))

    parts.append(
        f"📰 _{escape_md(source)}_\n"
        f"🏷 _Topic: {escape_md(topic_text)}_"
    )

    parts.append(f"[Read article]({escape_url(url)})")

    return "\n\n".join(parts)
