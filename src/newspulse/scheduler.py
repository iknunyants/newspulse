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
from newspulse.formatting import format_notification
from newspulse.matching.keywords import article_matches_keywords
from newspulse.matching.relevance import batch_check_relevance
from newspulse.scrapers import SOURCE_LANGUAGES
from newspulse.scrapers.web import get_all_scrapers
from newspulse.summarize import batch_generate_summaries

logger = logging.getLogger(__name__)


async def _send_notification(
    bot: Bot, telegram_id: int, topics: list[Topic], article: Article
) -> bool:
    """Send a single article notification. Returns False if user blocked the bot."""
    text = format_notification(
        title=article.title,
        content=article.summary or article.content,
        source=article.source,
        url=article.url,
        topic_texts=[t.topic_text for t in topics],
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


async def scrape_and_notify(repo: Repository, bot: Bot) -> None:
    logger.info("Starting scrape cycle...")

    # 1. Scrape all sources concurrently
    scrapers = get_all_scrapers()
    transport = httpx.AsyncHTTPTransport(retries=2)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True, timeout=30) as client:
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
                logger.info(
                    "Source %r: first scrape — storing baseline, skipping notifications.", source
                )

        for sa in scraped:
            try:
                article, is_new = await repo.upsert_article(
                    source=sa.source,
                    title=sa.title,
                    url=sa.url,
                    summary=sa.summary,
                    published_at=sa.published_at,
                    content=sa.content,
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

    # Build per-user language and source preferences (fetched once per user)
    user_languages: dict[int, list[str]] = {}
    user_sources: dict[int, list[str] | None] = {}
    for topic in topics:
        if topic.user_id not in user_languages:
            user_languages[topic.user_id] = await repo.get_user_languages(topic.user_id)
        if topic.user_id not in user_sources:
            user_sources[topic.user_id] = await repo.get_user_sources(topic.user_id)

    # 4. Match articles to topics, accumulating per (user, article) to avoid duplicate messages
    # pending: {(user_id, article_id): (telegram_id, article, [matching topics])}
    pending: dict[tuple[int, int], tuple[int, Article, list[Topic]]] = {}

    for topic in topics:
        user_langs = user_languages.get(topic.user_id, ["en", "hy", "ru"])
        lang_filtered = [
            a for a in new_articles
            if SOURCE_LANGUAGES.get(a.source, "en") in user_langs
        ]
        user_srcs = user_sources.get(topic.user_id)
        if user_srcs is not None:
            allowed = set(user_srcs)
            lang_filtered = [a for a in lang_filtered if a.source in allowed]
        keywords = json.loads(topic.keywords_json)
        candidates_scraped = [
            a for a in lang_filtered
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

        # Generate summaries for relevant articles that have content
        articles_with_content = [
            (a, a.content) for a in relevant if a.content and len(a.content) > 100
        ]
        if articles_with_content:
            summaries = await batch_generate_summaries(
                [(a.title, content) for a, content in articles_with_content]
            )
            for (article, _), summary in zip(articles_with_content, summaries):
                if summary:
                    article.summary = summary
                    await repo.update_article_summary(article.id, summary)

        # Get telegram_id for this user (needed for the send step)
        async with repo._conn.execute(
            "SELECT telegram_id FROM users WHERE id = ?", (topic.user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            continue
        telegram_id = row["telegram_id"]

        for article in relevant:
            key = (topic.user_id, article.id)
            if key not in pending:
                pending[key] = (telegram_id, article, [])
            pending[key][2].append(topic)

    # 5. Send one notification per (user, article), listing all matching topics
    user_blocked: dict[int, bool] = {}

    for (user_id, _article_id), (telegram_id, article, matched_topics) in pending.items():
        if user_blocked.get(user_id):
            continue

        unsent_topics = [
            t for t in matched_topics
            if not await repo.is_article_sent(article.id, t.id)
        ]
        if not unsent_topics:
            continue

        success = await _send_notification(bot, telegram_id, unsent_topics, article)

        if not success:
            user_blocked[user_id] = True
            await repo._conn.execute(
                "UPDATE topics SET active = 0 WHERE user_id = ?", (user_id,)
            )
            await repo._conn.commit()
            continue

        for t in unsent_topics:
            await repo.mark_article_sent(article.id, t.id)


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
