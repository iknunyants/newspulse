import logging

import httpx
from bs4 import BeautifulSoup

from newspulse.scrapers.base import HEADERS, BaseScraper, ScrapedArticle

logger = logging.getLogger(__name__)


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
        articles: list[ScrapedArticle] = []

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

            articles.append(
                ScrapedArticle(
                    source="Hetq",
                    title=title,
                    url=url,
                    summary="",
                    published_at=published_at,
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
        articles: list[ScrapedArticle] = []
        seen_urls: set[str] = set()

        for block in soup.select("div.top-photo-block"):
            links = block.find_all("a", href=True)
            # Find the text link (the one with article title text)
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

            articles.append(
                ScrapedArticle(
                    source="Mediamax",
                    title=title,
                    url=url,
                    summary="",
                    published_at=None,
                )
            )

        return articles


def get_all_scrapers() -> list[BaseScraper]:
    from newspulse.scrapers.rss import RssScraper
    return [
        RssScraper(),
        HetqScraper(),
        MediamaxScraper(),
    ]
