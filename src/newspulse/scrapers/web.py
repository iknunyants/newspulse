import asyncio
import logging

import httpx
from bs4 import BeautifulSoup

from newspulse.scrapers.base import (
    _FETCH_SEMAPHORE,  # noqa: F401 — re-exported for tests/scripts
    HEADERS,
    BaseScraper,
    ScrapedArticle,
    _fetch_article_content,
)

logger = logging.getLogger(__name__)


class ArkaScraper(BaseScraper):
    """Scrapes https://arka.am/am/news/ — Armenian financial/economic news agency."""

    BASE_URL = "https://arka.am"
    NEWS_URL = "https://arka.am/am/news/"

    async def scrape(self, client: httpx.AsyncClient) -> list[ScrapedArticle]:
        try:
            resp = await client.get(self.NEWS_URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logger.error("ArkaScraper failed to fetch: %s", e)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        stubs: list[tuple[str, str, str, str | None]] = []
        seen_urls: set[str] = set()

        for item in soup.select("div.news-item"):
            title_link = item.select_one("a.news-item-title")
            if not title_link:
                continue
            href = title_link.get("href", "")
            if not href:
                continue
            url = href if href.startswith("http") else self.BASE_URL + href
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title_el = title_link.select_one("h2.page-subheader")
            title = title_el.get_text(strip=True) if title_el else title_link.get_text(strip=True)
            if not title:
                continue

            preview_el = item.select_one("a.news-item-preview")
            summary = preview_el.get_text(strip=True) if preview_el else ""

            date_el = item.select_one("span.news-date-time")
            published_at = date_el.get_text(strip=True) if date_el else None

            stubs.append((url, title, summary, published_at))

        contents = await asyncio.gather(
            *[_fetch_article_content(client, url) for url, _, _, _ in stubs]
        )

        articles: list[ScrapedArticle] = []
        for (url, title, summary, published_at), content in zip(stubs, contents):
            articles.append(
                ScrapedArticle(
                    source="Arka.am",
                    title=title,
                    url=url,
                    summary=(summary or content)[:500],
                    published_at=published_at,
                    content=content,
                )
            )
        return articles


def get_all_scrapers() -> list[BaseScraper]:
    from newspulse.scrapers.rss import RssScraper
    return [
        RssScraper(),
        ArkaScraper(),
    ]
