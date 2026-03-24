import json
import logging

from google import genai
from google.genai import types

from newspulse.config import settings

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


async def generate_keywords(topic_text: str) -> list[str]:
    """Use Gemini to generate search keywords for a topic."""
    prompt = (
        f'Given the news monitoring topic: "{topic_text}"\n\n'
        "Generate a JSON array of 10-20 keywords and short phrases that would appear "
        "in relevant news articles. Include variations, abbreviations, related terms, "
        "and names of key people/places/organizations related to this topic. "
        "Be inclusive — it is better to cast a wide net.\n"
        "Return ONLY a valid JSON array of strings, no explanation."
    )
    client = _get_client()
    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3),
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        keywords = json.loads(text)
        if isinstance(keywords, list):
            return [str(k).strip() for k in keywords if k]
    except Exception as e:
        logger.error("Keyword generation failed for topic %r: %s", topic_text, e)
    # Fallback: split topic into words
    return [w for w in topic_text.split() if len(w) > 2]


def article_matches_keywords(title: str, summary: str, keywords: list[str]) -> bool:
    """Fast case-insensitive keyword pre-filter."""
    text = (title + " " + summary).lower()
    return any(kw.lower() in text for kw in keywords)
