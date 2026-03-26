import asyncio
import logging

import httpx
from bs4 import BeautifulSoup

from newspulse.scrapers.base import HEADERS, BaseScraper, ScrapedArticle

logger = logging.getLogger(__name__)

_FETCH_SEMAPHORE = asyncio.Semaphore(5)


async def _fetch_article_content(client: httpx.AsyncClient, url: str) -> str:
    """Fetch an article page and extract its main body text."""
    async with _FETCH_SEMAPHORE:
        try:
            resp = await client.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logger.debug("Failed to fetch article content from %s: %s", url, e)
            return ""

    soup = BeautifulSoup(resp.text, "lxml")

    # Try common article content containers in order of preference
    for selector in (
        "article",
        ".article-content",
        ".article-body",
        ".entry-content",
        ".post-content",
        "main",
    ):
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator=" ", strip=True)
            if len(text) > 100:
                return text

    return ""


class HetqScraper(BaseScraper):
    """Scrapes https://hetq.am/en/news — Armenian investigative news site."""

    BASE_URL = "https://hetq.am"
    NEWS_URL = "https://hetq.am/en/news"

    async def scrape(self, client: httpx.AsyncClient) -> list[ScrapedArticle]:
        try:
            resp = await client.get(self.NEWS_URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logger.error("HetqScraper failed to fetch: %s", e)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        stubs: list[tuple[str, str, str | None]] = []  # (url, title, published_at)

        for a in soup.select("a.news-block"):
            href = a.get("href", "")
            if not href:
                continue
            url = href if href.startswith("http") else self.BASE_URL + href

            title_el = a.find(["h1", "h2", "h3", "h4"])
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                img = a.find("img")
                title = img.get("alt", "").strip() if img else ""
            if not title:
                continue

            time_el = a.find("time")
            published_at = time_el.get("datetime") if time_el else None

            stubs.append((url, title, published_at))

        # Fetch article content concurrently
        contents = await asyncio.gather(
            *[_fetch_article_content(client, url) for url, _, _ in stubs]
        )

        articles: list[ScrapedArticle] = []
        for (url, title, published_at), content in zip(stubs, contents):
            articles.append(
                ScrapedArticle(
                    source="Hetq",
                    title=title,
                    url=url,
                    summary=content[:500],
                    published_at=published_at,
                    content=content,
                )
            )

        return articles


class MediamaxScraper(BaseScraper):
    """Scrapes https://mediamax.am/en/news/ — Armenian news site."""

    NEWS_URL = "https://mediamax.am/en/news/"

    async def scrape(self, client: httpx.AsyncClient) -> list[ScrapedArticle]:
        try:
            resp = await client.get(self.NEWS_URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logger.error("MediamaxScraper failed to fetch: %s", e)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        stubs: list[tuple[str, str]] = []  # (url, title)
        seen_urls: set[str] = set()

        for block in soup.select("div.top-photo-block"):
            links = block.find_all("a", href=True)
            title = ""
            url = ""
            for a in links:
                text = a.get_text(strip=True)
                href = a.get("href", "")
                if text and len(text) > 10 and "/en/news/" in href:
                    title = text
                    url = href if href.startswith("http") else "https://mediamax.am" + href
                    break
                elif not text and "/en/news/" in href and not url:
                    url = href if href.startswith("http") else "https://mediamax.am" + href

            if not title or not url or url in seen_urls:
                continue
            seen_urls.add(url)
            stubs.append((url, title))

        # Fetch article content concurrently
        contents = await asyncio.gather(
            *[_fetch_article_content(client, url) for url, _ in stubs]
        )

        articles: list[ScrapedArticle] = []
        for (url, title), content in zip(stubs, contents):
            articles.append(
                ScrapedArticle(
                    source="Mediamax",
                    title=title,
                    url=url,
                    summary=content[:500],
                    published_at=None,
                    content=content,
                )
            )

        return articles


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
        HetqScraper(),
        MediamaxScraper(),
        ArkaScraper(),
    ]
