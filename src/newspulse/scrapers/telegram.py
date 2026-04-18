import hashlib
import logging
import re

import httpx
from bs4 import BeautifulSoup

from newspulse.db.models import TelegramChannel
from newspulse.scrapers.base import HEADERS, BaseScraper, ScrapedArticle

logger = logging.getLogger(__name__)

_MEDIA_BG_RE = re.compile(r"background-image:url\('([^']+)'\)")


def _content_hash(text: str) -> str:
    chunk = text[:200].lower()
    chunk = re.sub(r"[^\w\s]", "", chunk, flags=re.UNICODE)
    chunk = " ".join(chunk.split())
    return hashlib.sha256(chunk.encode()).hexdigest()


async def fetch_channel_title(username: str, client: httpx.AsyncClient) -> str | None:
    """Fetch the display title for a public Telegram channel.

    Returns None if the channel is private, doesn't exist, or has preview disabled.
    """
    try:
        resp = await client.get(
            f"https://t.me/s/{username}", headers=HEADERS, timeout=15
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        el = soup.select_one(".tgme_channel_info_header_title")
        return el.get_text(strip=True) if el else None
    except Exception:
        return None


def parse_channel_username(text: str) -> str | None:
    """Extract a lowercase channel username from various user input formats.

    Accepts: t.me/foo, https://t.me/foo, @foo, foo
    Returns None for obviously invalid input.
    """
    text = text.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    if text.startswith("@"):
        text = text[1:]
    # Strip query string / fragment
    text = text.split("?")[0].split("#")[0].rstrip("/")
    if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{3,}", text):
        return text.lower()
    return None


class TelegramChannelScraper(BaseScraper):
    def __init__(self, channels: list[TelegramChannel]) -> None:
        self._channels = channels

    async def scrape(self, client: httpx.AsyncClient) -> list[ScrapedArticle]:
        results: list[ScrapedArticle] = []
        for channel in self._channels:
            try:
                articles = await self._scrape_channel(client, channel)
                results.extend(articles)
            except Exception as e:
                logger.error("TelegramScraper: failed to scrape @%s: %s", channel.username, e)
        return results

    async def _scrape_channel(
        self, client: httpx.AsyncClient, channel: TelegramChannel
    ) -> list[ScrapedArticle]:
        resp = await client.get(
            f"https://t.me/s/{channel.username}", headers=HEADERS, timeout=20
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        articles: list[ScrapedArticle] = []
        for wrap in soup.select(".tgme_widget_message_wrap"):
            try:
                article = self._parse_message(wrap, channel)
                if article:
                    articles.append(article)
            except Exception as e:
                logger.debug("TelegramScraper @%s: parse error: %s", channel.username, e)

        logger.info("TelegramScraper: scraped %d posts from @%s", len(articles), channel.username)
        return articles

    def _parse_message(
        self, wrap: BeautifulSoup, channel: TelegramChannel
    ) -> ScrapedArticle | None:
        date_a = wrap.select_one("a.tgme_widget_message_date")
        if not date_a:
            return None
        url = date_a.get("href", "")
        if not url:
            return None

        time_el = date_a.select_one("time[datetime]")
        published_at = time_el["datetime"] if time_el else None

        text_el = wrap.select_one(".tgme_widget_message_text")
        content = text_el.get_text(separator="\n", strip=True) if text_el else ""

        media_url: str | None = None
        photo_el = wrap.select_one(".tgme_widget_message_photo_wrap")
        if photo_el:
            style = photo_el.get("style", "")
            m = _MEDIA_BG_RE.search(style)
            if m:
                media_url = m.group(1)

        forwarded_from: str | None = None
        fwd_el = wrap.select_one(".tgme_widget_message_forwarded_from_name")
        if fwd_el:
            forwarded_from = fwd_el.get_text(strip=True) or None

        if not content and not media_url:
            return None

        if content:
            first_line = content.split("\n")[0][:120]
            title = first_line if first_line else f"@{channel.username}: new post"
        else:
            title = f"@{channel.username}: new post"

        summary = content[:200] if content else ""
        ch = _content_hash(content) if content else None

        return ScrapedArticle(
            source=f"tg:{channel.username}",
            title=title,
            url=url,
            summary=summary,
            published_at=published_at,
            content=content,
            forwarded_from=forwarded_from,
            media_url=media_url,
            content_hash=ch,
        )
