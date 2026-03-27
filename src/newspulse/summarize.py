"""LLM-based article summary generation using Gemini."""
from __future__ import annotations

import json
import logging

from google.genai import types

from newspulse.config import settings
from newspulse.gemini_client import get_client

logger = logging.getLogger(__name__)

_BATCH_SIZE = 5


async def batch_generate_summaries(articles: list[tuple[str, str]]) -> list[str]:
    """Generate 2-3 sentence summaries for a list of (title, content) pairs.

    Returns a list of summary strings in the same order. Empty string on failure.
    """
    if not articles:
        return []

    results: list[str] = [""] * len(articles)
    for i in range(0, len(articles), _BATCH_SIZE):
        batch = articles[i : i + _BATCH_SIZE]
        summaries = await _summarize_batch(batch)
        for j, s in enumerate(summaries):
            results[i + j] = s
    return results


async def _summarize_batch(articles: list[tuple[str, str]]) -> list[str]:
    numbered = "\n".join(
        f'{idx + 1}. Title: "{title}" | Content: "{content[:1000]}"'
        for idx, (title, content) in enumerate(articles)
    )
    prompt = (
        f"For each article below, write a concise 2-3 sentence summary in the same language "
        f"as the article. Return ONLY a JSON array of strings "
        f"with exactly {len(articles)} elements.\n\n"
        f"{numbered}\n\n"
        f'Example output (2 articles): ["Summary of first article.", "Summary of second article."]'
    )
    client = get_client()
    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=512),
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        summaries = json.loads(text)
        if isinstance(summaries, list) and len(summaries) == len(articles):
            return [str(s).strip() for s in summaries]
    except Exception as e:
        logger.error("Summary generation failed: %s", e)

    return [""] * len(articles)
