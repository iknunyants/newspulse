import asyncio
import datetime
import json
import logging

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, TelegramError

from newspulse.db.models import Article, Topic
from newspulse.db.repository import Repository
from newspulse.formatting import format_digest, format_notification
from newspulse.matching.keywords import article_matches_keywords
from newspulse.matching.relevance import batch_check_multi_topic_relevance
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
    feedback_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("👍", callback_data=f"fb:1:{article.id}"),
        InlineKeyboardButton("👎", callback_data=f"fb:0:{article.id}"),
    ]])
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=False,
            reply_markup=feedback_kb,
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

        async with repo.batch():
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

    # Build per-user preferences (fetched once per user)
    user_languages: dict[int, list[str]] = {}
    user_sources: dict[int, list[str] | None] = {}
    user_digest: dict[int, bool] = {}
    user_telegram: dict[int, int] = {}
    for topic in topics:
        uid = topic.user_id
        if uid not in user_languages:
            user_languages[uid] = await repo.get_user_languages(uid)
        if uid not in user_sources:
            user_sources[uid] = await repo.get_user_sources(uid)
        if uid not in user_digest:
            u = await repo.get_user_by_id(uid)
            user_digest[uid] = u.digest_mode if u else False
            user_telegram[uid] = u.telegram_id if u else 0

    # 4. Match articles to topics using article-first batching to minimize LLM calls.
    #
    #    First pass (keyword): for each article, collect candidate topics per user.
    #    Second pass (LLM): one call per (user, article) pair instead of per topic.
    #
    # article_candidates: {article_id: {user_id: [topics]}}
    article_candidates: dict[int, dict[int, list[Topic]]] = {}

    for topic in topics:
        user_langs = user_languages.get(topic.user_id, ["en", "hy"])
        user_srcs = user_sources.get(topic.user_id)
        allowed = set(user_srcs) if user_srcs is not None else None
        keywords = json.loads(topic.keywords_json)

        for article in new_articles:
            if SOURCE_LANGUAGES.get(article.source, "en") not in user_langs:
                continue
            if allowed is not None and article.source not in allowed:
                continue
            if not article_matches_keywords(article.title, article.summary, keywords):
                continue
            article_candidates.setdefault(article.id, {}).setdefault(
                topic.user_id, []
            ).append(topic)

    # pending: {(user_id, article_id): (telegram_id, article, [matching topics])}
    pending: dict[tuple[int, int], tuple[int, Article, list[Topic]]] = {}

    # Build article lookup for fast access
    article_by_id: dict[int, Article] = {a.id: a for a in new_articles}

    for article_id, user_topics in article_candidates.items():
        article = article_by_id[article_id]
        for user_id, candidate_topics in user_topics.items():
            telegram_id = user_telegram.get(user_id, 0)
            if not telegram_id:
                continue

            logger.debug(
                "Article %r: %d candidate topics for user %d, running LLM check...",
                article.title, len(candidate_topics), user_id,
            )

            relevant_topics = await batch_check_multi_topic_relevance(
                article, candidate_topics
            )
            if not relevant_topics:
                continue

            logger.info(
                "Article %r: %d/%d topics relevant for user %d.",
                article.title, len(relevant_topics), len(candidate_topics), user_id,
            )

            # Generate summary once per article (not per topic)
            if article.content and len(article.content) > 100 and not article.summary:
                summaries = await batch_generate_summaries(
                    [(article.title, article.content)]
                )
                if summaries and summaries[0]:
                    article.summary = summaries[0]
                    await repo.update_article_summary(article.id, summaries[0])

            key = (user_id, article_id)
            if key not in pending:
                pending[key] = (telegram_id, article, [])
            pending[key][2].extend(relevant_topics)

    # 5. Send one notification per (user, article), listing all matching topics.
    #    Digest-mode users get articles queued instead of sent immediately.
    #    mark_article_sent calls are batched to reduce commit overhead.
    user_blocked: dict[int, bool] = {}

    async with repo.batch():
        for (user_id, _article_id), (telegram_id, article, matched_topics) in pending.items():
            if user_blocked.get(user_id):
                continue

            unsent_topics = [
                t for t in matched_topics
                if not await repo.is_article_sent(article.id, t.id)
            ]
            if not unsent_topics:
                continue

            if user_digest.get(user_id):
                # Queue for digest delivery — mark sent to prevent re-queueing next cycle
                for t in unsent_topics:
                    await repo.queue_digest_article(user_id, article.id, t.id)
                    await repo.mark_article_sent(article.id, t.id)
                continue

            success = await _send_notification(bot, telegram_id, unsent_topics, article)

            if not success:
                user_blocked[user_id] = True
                await repo.deactivate_all_topics(user_id)
                continue

            for t in unsent_topics:
                await repo.mark_article_sent(article.id, t.id)

    # 6. Clean up old articles (older than 30 days)
    deleted = await repo.delete_old_articles(days=30)
    if deleted:
        logger.info("Cleaned up %d old articles.", deleted)


async def send_digests(repo: Repository, bot: Bot) -> None:
    """Send queued digest articles to users whose digest_hour matches the current UTC hour."""
    current_hour = datetime.datetime.utcnow().hour
    users = await repo.get_users_for_digest(current_hour)
    if not users:
        return

    logger.info("Sending digests for hour %d UTC (%d users).", current_hour, len(users))

    for user in users:
        items = await repo.get_digest_queue(user.id)
        if not items:
            continue

        # Build digest payload: (title, summary, source, url, topic_texts)
        payload = [
            (
                article.title,
                article.summary or article.content,
                article.source,
                article.url,
                [t.topic_text for t in topics],
            )
            for article, topics in items
        ]

        text = format_digest(payload)
        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            await repo.clear_digest_queue(user.id)
            logger.info(
                "Sent digest to user %d (%d articles).",
                user.telegram_id, len(items),
            )
        except Forbidden:
            logger.warning("Digest: user %d blocked the bot.", user.telegram_id)
            await repo.deactivate_all_topics(user.id)
        except TelegramError as e:
            logger.error("Digest: failed to send to %d: %s", user.telegram_id, e)


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
    scheduler.add_job(
        send_digests,
        trigger=IntervalTrigger(hours=1),
        args=[repo, bot],
        id="digest_job",
        replace_existing=True,
        misfire_grace_time=300,
    )
    return scheduler
