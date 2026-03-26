"""Live integration tests for all news scrapers.

These tests hit real external URLs. Run them on-demand to check if sources are
still working correctly:

    uv run pytest tests/test_scrapers_live.py -v
    uv run pytest tests/test_scrapers_live.py -v -k hetq
    uv run pytest tests/test_scrapers_live.py -v -k bbc
"""
import re

import httpx
import pytest

from newspulse.formatting import format_notification
from newspulse.scrapers.base import ScrapedArticle
from newspulse.scrapers.rss import RSS_FEEDS, RssScraper
from newspulse.scrapers.web import ArkaScraper, HetqScraper, MediamaxScraper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_article(article: ScrapedArticle, expected_source: str | None = None) -> None:
    """Assert that a ScrapedArticle has all required fields with valid values."""
    assert isinstance(article.source, str) and article.source, \
        f"source must be a non-empty string, got {article.source!r}"

    if expected_source is not None:
        assert article.source == expected_source, \
            f"expected source={expected_source!r}, got {article.source!r}"

    assert isinstance(article.title, str) and article.title, \
        f"title must be a non-empty string, got {article.title!r}"

    assert isinstance(article.url, str) and article.url.startswith("http"), \
        f"url must start with 'http', got {article.url!r}"

    assert isinstance(article.summary, str), \
        f"summary must be a string, got {type(article.summary)}"
    assert len(article.summary) <= 500, \
        f"summary exceeds 500 chars ({len(article.summary)} chars) for {article.url}"

    assert article.published_at is None or isinstance(article.published_at, str), \
        f"published_at must be str or None, got {type(article.published_at)}"

    assert isinstance(article.content, str), \
        f"content must be a string, got {type(article.content)}"


def validate_notification(msg: str) -> None:
    """Assert the MarkdownV2 notification message has the expected structure."""
    # Bold title present
    assert re.search(r"\*.+\*", msg), "message must have a bold title (*...*)"
    # Source line present
    assert re.search(r"📰 _.+_", msg), "message must have a source line (📰 _..._)"
    # Topic line present
    assert re.search(r"🏷 _Topic: .+_", msg), "message must have a topic line"
    # Read article link present
    assert re.search(r"\[Read article\]\(https?://", msg), \
        "message must have a [Read article](...) link"


# ---------------------------------------------------------------------------
# RSS feed tests — one test per feed so failures are pinpointed
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.parametrize("name,feed_url", RSS_FEEDS, ids=[name for name, _ in RSS_FEEDS])
async def test_rss_feed_returns_articles(http_client: httpx.AsyncClient, name: str, feed_url: str):
    """Each RSS feed must return at least one article with valid structure."""
    scraper = RssScraper(feeds=[(name, feed_url)])
    articles = await scraper.scrape(http_client)

    assert len(articles) > 0, f"{name} ({feed_url}) returned no articles — feed may be broken"

    for article in articles:
        validate_article(article, expected_source=name)


@pytest.mark.live
@pytest.mark.parametrize("name,feed_url", RSS_FEEDS, ids=[name for name, _ in RSS_FEEDS])
async def test_rss_feed_summaries_not_empty(http_client: httpx.AsyncClient, name: str, feed_url: str):
    """RSS articles should have non-empty summaries (feed provides descriptions)."""
    scraper = RssScraper(feeds=[(name, feed_url)])
    articles = await scraper.scrape(http_client)

    if not articles:
        pytest.skip(f"{name} returned no articles")

    # NEWS.am RSS provides no descriptions by design — title-only matching is expected
    if name == "NEWS.am":
        pytest.skip("NEWS.am RSS has no descriptions by design")

    empty_summaries = [a.url for a in articles if not a.summary]
    assert not empty_summaries, \
        f"{name}: {len(empty_summaries)} article(s) with empty summary:\n" + "\n".join(empty_summaries[:5])


# ---------------------------------------------------------------------------
# Web scraper tests
# ---------------------------------------------------------------------------

@pytest.mark.live
async def test_hetq_scraper(http_client: httpx.AsyncClient):
    """HetqScraper must return articles with titles, URLs, and content."""
    scraper = HetqScraper()
    articles = await scraper.scrape(http_client)

    assert len(articles) > 0, "HetqScraper returned no articles — site structure may have changed"

    for article in articles:
        validate_article(article, expected_source="Hetq")

    # Hetq fetches full article content — at least some should have non-empty content
    articles_with_content = [a for a in articles if a.content]
    assert articles_with_content, "HetqScraper: no articles have non-empty content"


@pytest.mark.live
async def test_hetq_scraper_published_dates(http_client: httpx.AsyncClient):
    """Hetq articles should expose publication dates via <time datetime=...>."""
    scraper = HetqScraper()
    articles = await scraper.scrape(http_client)

    if not articles:
        pytest.skip("HetqScraper returned no articles")

    articles_with_date = [a for a in articles if a.published_at]
    assert articles_with_date, \
        "HetqScraper: no articles have published_at — <time datetime> selector may be broken"


@pytest.mark.live
async def test_mediamax_scraper(http_client: httpx.AsyncClient):
    """MediamaxScraper must return articles with titles and URLs."""
    scraper = MediamaxScraper()
    articles = await scraper.scrape(http_client)

    assert len(articles) > 0, "MediamaxScraper returned no articles — site structure may have changed"

    for article in articles:
        validate_article(article, expected_source="Mediamax")

    # Mediamax fetches full article content — at least some should have non-empty content
    articles_with_content = [a for a in articles if a.content]
    assert articles_with_content, "MediamaxScraper: no articles have non-empty content"


@pytest.mark.live
async def test_arka_scraper(http_client: httpx.AsyncClient):
    """ArkaScraper must return Armenian articles with titles, URLs, summaries, and dates."""
    scraper = ArkaScraper()
    articles = await scraper.scrape(http_client)

    assert len(articles) > 0, "ArkaScraper returned no articles — site structure may have changed"

    for article in articles:
        validate_article(article, expected_source="Arka.am")

    articles_with_summary = [a for a in articles if a.summary]
    assert articles_with_summary, "ArkaScraper: no articles have non-empty summary"

    articles_with_date = [a for a in articles if a.published_at]
    assert articles_with_date, "ArkaScraper: no articles have published_at"


# ---------------------------------------------------------------------------
# Notification format tests
# ---------------------------------------------------------------------------

@pytest.mark.live
async def test_notification_format_from_rss(http_client: httpx.AsyncClient):
    """format_notification() output must have the expected MarkdownV2 structure."""
    scraper = RssScraper(feeds=[RSS_FEEDS[0]])  # BBC World
    articles = await scraper.scrape(http_client)

    if not articles:
        pytest.skip("No articles available to test notification format")

    article = articles[0]
    msg = format_notification(
        title=article.title,
        content=article.content or article.summary,
        source=article.source,
        url=article.url,
        topic_text="test topic",
    )
    validate_notification(msg)


@pytest.mark.live
async def test_notification_format_special_characters(http_client: httpx.AsyncClient):
    """format_notification() must not crash or break MarkdownV2 on titles with special chars."""
    article = ScrapedArticle(
        source="Test Source",
        title="Article: 'Hello' & (World) — 50% off! [Updated]",
        url="https://example.com/article-1",
        summary="First sentence. Second sentence with *bold* and _italic_ chars.",
        published_at=None,
        content="First sentence. Second sentence with *bold* and _italic_ chars.",
    )
    msg = format_notification(
        title=article.title,
        content=article.content,
        source=article.source,
        url=article.url,
        topic_text="deals & offers",
    )
    validate_notification(msg)
    # Ensure no unescaped MarkdownV2 special chars outside intended formatting
    # The title should be escaped (no bare * or _ in the title section)
    title_section = msg.split("\n\n")[0]
    # Strip the outer * bold markers, the rest should have no bare *
    inner = title_section[1:-1]
    assert "*" not in inner, f"Unescaped * in title section: {title_section!r}"
