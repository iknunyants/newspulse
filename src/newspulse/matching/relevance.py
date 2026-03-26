import json
import logging

from google import genai
from google.genai import types

from newspulse.config import settings
from newspulse.db.models import Article

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


async def batch_check_relevance(topic_text: str, articles: list[Article]) -> list[Article]:
    """
    Ask Gemini whether each article is relevant to the topic.
    Processes up to 10 articles per API call.
    Returns the relevant articles.
    """
    if not articles:
        return []

    relevant: list[Article] = []
    batch_size = 10
    for i in range(0, len(articles), batch_size):
        relevant.extend(await _check_batch(topic_text, articles[i : i + batch_size]))
    return relevant


async def _check_batch(topic_text: str, articles: list[Article]) -> list[Article]:
    numbered = "\n".join(
        f'{idx + 1}. Title: "{a.title}" | Content: "{(a.content or a.summary)[:500]}"'
        for idx, a in enumerate(articles)
    )
    prompt = (
        f'Topic to monitor: "{topic_text}"\n\n'
        f"For each article below, reply 'yes' if it is relevant to the topic, "
        f"or 'no' if not. Return ONLY a JSON array of 'yes'/'no' strings "
        f"with exactly {len(articles)} elements.\n\n"
        f"{numbered}\n\n"
        f'Example output: ["yes", "no", "yes"]'
    )
    client = _get_client()
    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=64),
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        decisions = json.loads(text)
        if isinstance(decisions, list) and len(decisions) == len(articles):
            return [a for a, d in zip(articles, decisions) if str(d).lower().strip() == "yes"]
    except Exception as e:
        logger.error("Relevance check failed for topic %r: %s", topic_text, e)
        # On error, return all candidates to avoid missing articles
        return articles

    return articles
