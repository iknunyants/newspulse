"""Check all news sources and print sample scraped content.

Shows one formatted Telegram notification + raw fields for each scraper,
so you can visually verify that parsing is working correctly.

Usage:
    uv run python scripts/check_sources.py
    uv run python scripts/check_sources.py --samples 3
    uv run python scripts/check_sources.py --source hetq
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap

import httpx

sys.path.insert(0, "src")

from newspulse.formatting import format_notification
from newspulse.scrapers.base import ScrapedArticle
from newspulse.scrapers.rss import RSS_FEEDS, RssScraper
from newspulse.scrapers.web import _FETCH_SEMAPHORE, ArkaScraper  # noqa: F401

# ANSI colours
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _header(text: str) -> str:
    bar = "─" * 70
    return f"\n{_BOLD}{bar}\n  {text}\n{bar}{_RESET}"


def _field(label: str, value: str, indent: int = 4) -> str:
    prefix = " " * indent
    wrapped = textwrap.fill(value, width=100, subsequent_indent=prefix + "  ")
    return f"{prefix}{_DIM}{label:<14}{_RESET}{wrapped}"


def _print_article(article: ScrapedArticle, index: int, show_notification: bool = True) -> None:
    status_parts = []
    if not article.title:
        status_parts.append(f"{_RED}MISSING title{_RESET}")
    if not article.url or not article.url.startswith("http"):
        status_parts.append(f"{_RED}INVALID url{_RESET}")
    if not article.summary:
        status_parts.append(f"{_YELLOW}empty summary{_RESET}")
    if not article.content:
        status_parts.append(f"{_YELLOW}empty content{_RESET}")
    if not article.published_at:
        status_parts.append(f"{_DIM}no date{_RESET}")

    flags = f"  [{', '.join(status_parts)}]" if status_parts else f"  [{_GREEN}OK{_RESET}]"
    print(f"\n  {_BOLD}Article {index}{_RESET}{flags}")
    print(_field("title:", article.title or "(empty)"))
    print(_field("url:", article.url or "(empty)"))
    print(_field("published_at:", str(article.published_at) if article.published_at else "(none)"))
    print(_field("summary:", (article.summary[:200] + "…") if len(article.summary) > 200 else article.summary or "(empty)"))
    content_preview = article.content[:200] + "…" if len(article.content) > 200 else article.content
    print(_field("content:", content_preview or "(empty)"))

    if show_notification and article.title and article.url:
        msg = format_notification(
            title=article.title,
            content=article.content or article.summary,
            source=article.source,
            url=article.url,
            topic_text="example topic",
        )
        print(f"\n    {_CYAN}── Telegram notification ──{_RESET}")
        for line in msg.splitlines():
            print(f"    {line}")


def _summarise(source: str, articles: list[ScrapedArticle], error: str | None) -> None:
    if error:
        print(f"  {_RED}ERROR:{_RESET} {error}")
        return
    total = len(articles)
    no_summary = sum(1 for a in articles if not a.summary)
    no_content = sum(1 for a in articles if not a.content)
    no_date = sum(1 for a in articles if not a.published_at)
    print(f"  {_GREEN}✓{_RESET} {total} articles scraped", end="")
    issues = []
    if no_summary:
        issues.append(f"{_YELLOW}{no_summary} without summary{_RESET}")
    if no_content:
        issues.append(f"{_YELLOW}{no_content} without content{_RESET}")
    if no_date:
        issues.append(f"{_DIM}{no_date} without date{_RESET}")
    if issues:
        print("  |  " + ",  ".join(issues), end="")
    print()


async def run(n_samples: int, filter_source: str | None) -> None:
    # Build scraper list: one entry per RSS feed + web scrapers
    scrapers: list[tuple[str, object]] = []
    for name, url in RSS_FEEDS:
        scrapers.append((name, RssScraper(feeds=[(name, url)])))
    scrapers.append(("Arka.am", ArkaScraper()))

    if filter_source:
        scrapers = [(n, s) for n, s in scrapers if filter_source.lower() in n.lower()]
        if not scrapers:
            print(f"{_RED}No scraper matches --source {filter_source!r}{_RESET}")
            print(f"Available: {', '.join(n for n, _ in [*[(n, None) for n, _ in RSS_FEEDS], ('Arka.am', None)])}")
            return

    results: dict[str, list[ScrapedArticle] | str] = {}

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        tasks = {name: scraper.scrape(client) for name, scraper in scrapers}
        for name, coro in tasks.items():
            try:
                results[name] = await coro
            except Exception as e:
                results[name] = str(e)

    print(f"\n{_BOLD}NewsPulse — Source Check{_RESET}")
    print(f"Showing up to {n_samples} sample article(s) per source\n")

    for name, _ in scrapers:
        result = results[name]
        print(_header(name))
        if isinstance(result, str):
            _summarise(name, [], error=result)
            continue
        _summarise(name, result, error=None)
        for i, article in enumerate(result[:n_samples], 1):
            _print_article(article, index=i, show_notification=(i == 1))

    print(f"\n{_DIM}Done.{_RESET}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check NewsPulse scrapers and show sample output")
    parser.add_argument("--samples", type=int, default=2, metavar="N",
                        help="Number of sample articles to show per source (default: 2)")
    parser.add_argument("--source", metavar="NAME",
                        help="Only check sources whose name contains this string (case-insensitive)")
    args = parser.parse_args()

    asyncio.run(run(n_samples=args.samples, filter_source=args.source))


if __name__ == "__main__":
    main()
