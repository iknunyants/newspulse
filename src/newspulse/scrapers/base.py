import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

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


class BaseScraper(ABC):
    @abstractmethod
    async def scrape(self, client: httpx.AsyncClient) -> list[ScrapedArticle]:
        ...
