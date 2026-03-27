import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


@dataclass
class ScrapedArticle:
    source: str
    title: str
    url: str
    summary: str
    published_at: str | None
    content: str = ""


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


class BaseScraper(ABC):
    @abstractmethod
    async def scrape(self, client: httpx.AsyncClient) -> list[ScrapedArticle]:
        ...
