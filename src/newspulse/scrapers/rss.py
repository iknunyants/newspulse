import asyncio
import logging

import feedparser
import httpx

from newspulse.scrapers.base import HEADERS, BaseScraper, ScrapedArticle, _fetch_article_content

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("CivilNet", "https://www.civilnet.am/feed/"),
    ("1Lurer", "https://www.1lurer.am/hy/rss"),
    ("NEWS.am", "https://news.am/arm/rss/"),
    ("Azatutyun", "https://www.azatutyun.am/api/"),
    ("Hetq", "https://hetq.am/hy/rss"),
    ("Mediamax", "https://mediamax.am/am/index.rss"),
    ("APA", "https://en.apa.az/rss"),
]


class RssScraper(BaseScraper):
    def __init__(self, feeds: list[tuple[str, str]] = RSS_FEEDS) -> None:
        self._feeds = feeds

    async def scrape(self, client: httpx.AsyncClient) -> list[ScrapedArticle]:
        articles: list[ScrapedArticle] = []
        for source_name, feed_url in self._feeds:
            try:
                resp = await client.get(feed_url, headers=HEADERS, timeout=20)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
                for entry in feed.entries:
                    title = entry.get("title", "").strip()
                    url = entry.get("link", "").strip()
                    if not title or not url:
                        continue
                    summary = (entry.get("summary", "") or entry.get("description", "")).strip()
                    # Strip HTML tags from summary if present
                    if "<" in summary:
                        from bs4 import BeautifulSoup

                        summary = BeautifulSoup(summary, "lxml").get_text(separator=" ", strip=True)
                    published_at = None
                    if hasattr(entry, "published"):
                        published_at = entry.published
                    articles.append(
                        ScrapedArticle(
                            source=source_name,
                            title=title,
                            url=url,
                            summary=summary[:500],
                            published_at=published_at,
                            content=summary,
                        )
                    )
            except Exception as e:
                logger.error("RSS feed %s failed: %s", feed_url, e)

        # Fetch full article content for articles with no/short summary (title-only feeds)
        needs_content = [(i, a) for i, a in enumerate(articles) if len(a.summary) < 50]
        if needs_content:
            fetched = await asyncio.gather(
                *[_fetch_article_content(client, a.url) for _, a in needs_content],
                return_exceptions=True,
            )
            for (idx, article), body in zip(needs_content, fetched):
                if isinstance(body, str) and body:
                    article.content = body
                    if not article.summary:
                        article.summary = body[:500]

        return articles
