import asyncio
import json
import logging

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot
from telegram.error import Forbidden, TelegramError

from newspulse.db.models import Article, Topic
from newspulse.db.repository import Repository
from newspulse.matching.keywords import article_matches_keywords
from newspulse.matching.relevance import batch_check_relevance
from newspulse.scrapers.web import get_all_scrapers

logger = logging.getLogger(__name__)


async def _send_notification(bot: Bot, telegram_id: int, topic: Topic, article: Article) -> bool:
    """Send a single article notification. Returns False if user blocked the bot."""
    text = (
        f"*{_escape_md(article.title)}*\n\n"
        f"{_escape_md(article.summary[:300]) + '...' if article.summary else ''}"
        f"\n\n[Read more]({article.url})"
        f"\n\n_Topic: {_escape_md(topic.topic_text)}_"
    )
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=False,
        )
        return True
    except Forbidden:
        logger.warning("User %d blocked the bot, skipping.", telegram_id)
        return False
    except TelegramError as e:
        logger.error("Failed to send message to %d: %s", telegram_id, e)
        return True  # Don't deactivate topics on generic errors


def _escape_md(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)


async def scrape_and_notify(repo: Repository, bot: Bot) -> None:
    logger.info("Starting scrape cycle...")

    # 1. Scrape all sources concurrently
    scrapers = get_all_scrapers()
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        results = await asyncio.gather(
            *[s.scrape(client) for s in scrapers],
            return_exceptions=True,
        )

    # 2. Store new articles; skip notification for sources being scraped for the first time
    new_articles: list[Article] = []
    for scraper, result in zip(scrapers, results):
        if isinstance(result, Exception):
            logger.error("Scraper %s raised: %s", scraper.__class__.__name__, result)
            continue
        scraped = result
        if not scraped:
            continue

        # Determine sources present in this batch (usually one per scraper)
        sources_in_batch: set[str] = {sa.source for sa in scraped}
        first_scrape_sources: set[str] = set()
        for source in sources_in_batch:
            if await repo.get_last_scrape_time(source) is None:
                first_scrape_sources.add(source)
                logger.info("Source %r: first scrape — storing baseline, skipping notifications.", source)

        for sa in scraped:
            try:
                article, is_new = await repo.upsert_article(
                    source=sa.source,
                    title=sa.title,
                    url=sa.url,
                    summary=sa.summary,
                    published_at=sa.published_at,
                )
                if is_new and sa.source not in first_scrape_sources:
                    new_articles.append(article)
            except Exception as e:
                logger.error("Failed to store article %r: %s", sa.url, e)

        for source in sources_in_batch:
            await repo.update_scrape_time(source)

    logger.info("Scraped %d new articles.", len(new_articles))
    if not new_articles:
        return

    # 3. Get all active topics
    topics = await repo.get_active_topics()
    if not topics:
        return

    # Group topics by user for deactivation tracking
    user_blocked: dict[int, bool] = {}

    for topic in topics:
        keywords = json.loads(topic.keywords_json)
        candidates_scraped = [
            a for a in new_articles
            if article_matches_keywords(a.title, a.summary, keywords)
        ]

        if not candidates_scraped:
            continue

        logger.debug(
            "Topic %r: %d keyword matches, running LLM check...",
            topic.topic_text,
            len(candidates_scraped),
        )

        relevant = await batch_check_relevance(topic.topic_text, candidates_scraped)
        logger.info("Topic %r: %d relevant articles.", topic.topic_text, len(relevant))

        for article in relevant:
            if await repo.is_article_sent(article.id, topic.id):
                continue

            if user_blocked.get(topic.user_id):
                continue

            # Get user's telegram_id
            async with repo._conn.execute(
                "SELECT telegram_id FROM users WHERE id = ?", (topic.user_id,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                continue

            telegram_id = row["telegram_id"]
            success = await _send_notification(bot, telegram_id, topic, article)

            if not success:
                # User blocked the bot — deactivate all their topics
                user_blocked[topic.user_id] = True
                await repo._conn.execute(
                    "UPDATE topics SET active = 0 WHERE user_id = ?", (topic.user_id,)
                )
                await repo._conn.commit()
                break

            await repo.mark_article_sent(article.id, topic.id)


def setup_scheduler(repo: Repository, bot: Bot, interval_minutes: int) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scrape_and_notify,
        trigger=IntervalTrigger(minutes=interval_minutes),
        args=[repo, bot],
        id="scrape_job",
        replace_existing=True,
        misfire_grace_time=300,
    )
    return scheduler
