import json
import logging
from typing import TYPE_CHECKING

from google.genai import types

from newspulse.config import settings
from newspulse.db.models import Article
from newspulse.gemini_client import get_client

if TYPE_CHECKING:
    from newspulse.db.models import Topic

logger = logging.getLogger(__name__)


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
    client = get_client()
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


async def batch_check_multi_topic_relevance(
    article: Article, topics: list["Topic"]
) -> list["Topic"]:
    """Check one article against multiple topics in a single LLM call.

    Returns the subset of topics the article is relevant to.
    Falls back to returning all topics on error (fail-open).
    """
    if not topics:
        return []
    if len(topics) == 1:
        results = await batch_check_relevance(topics[0].topic_text, [article])
        return topics if results else []

    numbered = "\n".join(
        f'{i + 1}. "{t.topic_text}"' for i, t in enumerate(topics)
    )
    snippet = (article.content or article.summary)[:500]
    article_text = f'Title: "{article.title}" | Content: "{snippet}"'
    prompt = (
        f"Article: {article_text}\n\n"
        f"For each topic below, reply 'yes' if the article is relevant to it, "
        f"or 'no' if not. Return ONLY a JSON array of 'yes'/'no' strings "
        f"with exactly {len(topics)} elements.\n\n"
        f"{numbered}\n\n"
        f'Example output: ["yes", "no", "yes"]'
    )
    client = get_client()
    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=len(topics) * 8,
            ),
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        decisions = json.loads(text)
        if isinstance(decisions, list) and len(decisions) == len(topics):
            return [
                t for t, d in zip(topics, decisions)
                if str(d).lower().strip() == "yes"
            ]
    except Exception as e:
        logger.error(
            "Multi-topic relevance check failed for article %r: %s",
            article.title, e,
        )
    # Fail-open: return all topics
    return topics
