import hashlib
import json
from pathlib import Path

import aiosqlite

from newspulse.db.migrations import init_db
from newspulse.db.models import Article, Topic, User


class Repository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @classmethod
    async def create(cls, db_path: Path) -> "Repository":
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    # --- Users ---

    _USER_COLS = (
        "id, telegram_id, created_at, languages_json, sources_json,"
        " digest_mode, digest_hour"
    )

    def _row_to_user(self, row: aiosqlite.Row) -> User:
        return User(
            id=row["id"],
            telegram_id=row["telegram_id"],
            created_at=row["created_at"],
            languages_json=row["languages_json"],
            sources_json=row["sources_json"],
            digest_mode=bool(row["digest_mode"]),
            digest_hour=row["digest_hour"],
        )

    async def get_or_create_user(self, telegram_id: int) -> User:
        async with self._conn.execute(
            f"SELECT {self._USER_COLS} FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
        if row:
            return self._row_to_user(row)
        await self._conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (telegram_id,)
        )
        await self._conn.commit()
        async with self._conn.execute(
            f"SELECT {self._USER_COLS} FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_user(row)

    async def set_user_languages(self, user_id: int, languages: list[str]) -> None:
        await self._conn.execute(
            "UPDATE users SET languages_json = ? WHERE id = ?",
            (json.dumps(languages, ensure_ascii=False), user_id),
        )
        await self._conn.commit()

    async def get_user_languages(self, user_id: int) -> list[str]:
        async with self._conn.execute(
            "SELECT languages_json FROM users WHERE id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return ["en", "hy"]
        return json.loads(row["languages_json"])

    async def set_user_sources(self, user_id: int, sources: list[str] | None) -> None:
        value = None if sources is None else json.dumps(sources, ensure_ascii=False)
        await self._conn.execute(
            "UPDATE users SET sources_json = ? WHERE id = ?",
            (value, user_id),
        )
        await self._conn.commit()

    async def get_user_sources(self, user_id: int) -> list[str] | None:
        async with self._conn.execute(
            "SELECT sources_json FROM users WHERE id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row or row["sources_json"] is None:
            return None  # None means all sources
        return json.loads(row["sources_json"])

    # --- Topics ---

    async def add_topic(self, user_id: int, topic_text: str, keywords: list[str]) -> Topic:
        keywords_json = json.dumps(keywords, ensure_ascii=False)
        await self._conn.execute(
            "INSERT INTO topics (user_id, topic_text, keywords_json) VALUES (?, ?, ?)",
            (user_id, topic_text, keywords_json),
        )
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT id, user_id, topic_text, keywords_json, active, "
            "created_at, paused "
            "FROM topics WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        return Topic(
            id=row["id"],
            user_id=row["user_id"],
            topic_text=row["topic_text"],
            keywords_json=row["keywords_json"],
            active=bool(row["active"]),
            created_at=row["created_at"],
            paused=bool(row["paused"]),
        )

    async def count_active_topics(self, user_id: int) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM topics WHERE user_id = ? AND active = 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        return row[0]

    async def get_active_topics(
        self, user_id: int | None = None, include_paused: bool = False
    ) -> list[Topic]:
        paused_filter = "" if include_paused else " AND paused = 0"
        if user_id is not None:
            query = (
                "SELECT id, user_id, topic_text, keywords_json, active, "
                "created_at, paused "
                f"FROM topics WHERE user_id = ? AND active = 1{paused_filter}"
                " ORDER BY id"
            )
            params = (user_id,)
        else:
            query = (
                "SELECT id, user_id, topic_text, keywords_json, active, "
                "created_at, paused "
                f"FROM topics WHERE active = 1{paused_filter} ORDER BY id"
            )
            params = ()
        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        return [
            Topic(
                id=r["id"],
                user_id=r["user_id"],
                topic_text=r["topic_text"],
                keywords_json=r["keywords_json"],
                active=bool(r["active"]),
                created_at=r["created_at"],
                paused=bool(r["paused"]),
            )
            for r in rows
        ]

    async def deactivate_topic(self, topic_id: int, user_id: int) -> bool:
        result = await self._conn.execute(
            "UPDATE topics SET active = 0 WHERE id = ? AND user_id = ? AND active = 1",
            (topic_id, user_id),
        )
        await self._conn.commit()
        return result.rowcount > 0

    async def reactivate_topics(self, user_id: int) -> int:
        """Reactivate all topics for a user. Returns number reactivated."""
        result = await self._conn.execute(
            "UPDATE topics SET active = 1 WHERE user_id = ? AND active = 0",
            (user_id,),
        )
        await self._conn.commit()
        return result.rowcount

    async def pause_topic(self, topic_id: int, user_id: int) -> bool:
        """Pause an active topic. Returns True if paused."""
        result = await self._conn.execute(
            "UPDATE topics SET paused = 1 "
            "WHERE id = ? AND user_id = ? AND active = 1 AND paused = 0",
            (topic_id, user_id),
        )
        await self._conn.commit()
        return result.rowcount > 0

    async def resume_topic(self, topic_id: int, user_id: int) -> bool:
        """Resume a paused topic. Returns True if resumed."""
        result = await self._conn.execute(
            "UPDATE topics SET paused = 0 "
            "WHERE id = ? AND user_id = ? AND active = 1 AND paused = 1",
            (topic_id, user_id),
        )
        await self._conn.commit()
        return result.rowcount > 0

    async def get_paused_topics(self, user_id: int) -> list[Topic]:
        """Get all paused (but active) topics for a user."""
        async with self._conn.execute(
            "SELECT id, user_id, topic_text, keywords_json, active, created_at "
            "FROM topics WHERE user_id = ? AND active = 1 AND paused = 1 "
            "ORDER BY id",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            Topic(
                id=r["id"], user_id=r["user_id"],
                topic_text=r["topic_text"],
                keywords_json=r["keywords_json"],
                active=bool(r["active"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def deactivate_all_topics(self, user_id: int) -> int:
        """Deactivate all topics for a user. Returns number deactivated."""
        result = await self._conn.execute(
            "UPDATE topics SET active = 0 WHERE user_id = ?",
            (user_id,),
        )
        await self._conn.commit()
        return result.rowcount

    async def get_telegram_id(self, user_id: int) -> int | None:
        """Get telegram_id for an internal user ID."""
        async with self._conn.execute(
            "SELECT telegram_id FROM users WHERE id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return row["telegram_id"] if row else None

    async def get_user_by_id(self, user_id: int) -> User | None:
        """Get a user by internal ID."""
        async with self._conn.execute(
            f"SELECT {self._USER_COLS} FROM users WHERE id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_user(row) if row else None

    # --- Articles ---

    @staticmethod
    def _url_hash(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    async def upsert_article(
        self,
        source: str,
        title: str,
        url: str,
        summary: str,
        published_at: str | None,
        content: str = "",
    ) -> tuple[Article, bool]:
        url_hash = self._url_hash(url)
        async with self._conn.execute(
            "SELECT id, url_hash, source, title, url, summary, published_at, created_at, content "
            "FROM articles WHERE url_hash = ?",
            (url_hash,),
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            return Article(**existing), False

        await self._conn.execute(
            "INSERT INTO articles (url_hash, source, title, url, summary, published_at, content) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (url_hash, source, title, url, summary[:500], published_at, content[:5000]),
        )
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT id, url_hash, source, title, url, summary, published_at, created_at, content "
            "FROM articles WHERE url_hash = ?",
            (url_hash,),
        ) as cur:
            row = await cur.fetchone()
        return Article(**row), True

    async def update_article_summary(self, article_id: int, summary: str) -> None:
        await self._conn.execute(
            "UPDATE articles SET summary = ? WHERE id = ?",
            (summary[:500], article_id),
        )
        await self._conn.commit()

    async def is_article_sent(self, article_id: int, topic_id: int) -> bool:
        async with self._conn.execute(
            "SELECT 1 FROM sent_articles WHERE article_id = ? AND topic_id = ?",
            (article_id, topic_id),
        ) as cur:
            return await cur.fetchone() is not None

    async def mark_article_sent(self, article_id: int, topic_id: int) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO sent_articles (article_id, topic_id) VALUES (?, ?)",
            (article_id, topic_id),
        )
        await self._conn.commit()

    # --- Scrape log ---

    async def get_last_scrape_time(self, source: str) -> str | None:
        async with self._conn.execute(
            "SELECT last_scraped_at FROM scrape_log WHERE source = ?", (source,)
        ) as cur:
            row = await cur.fetchone()
        return row["last_scraped_at"] if row else None

    async def update_scrape_time(self, source: str) -> None:
        await self._conn.execute(
            "INSERT INTO scrape_log (source, last_scraped_at) VALUES (?, datetime('now'))"
            " ON CONFLICT(source) DO UPDATE SET last_scraped_at = datetime('now')",
            (source,),
        )
        await self._conn.commit()

    # --- Stats ---

    async def get_user_stats(
        self, user_id: int, days: int = 7
    ) -> list[tuple[str, int]]:
        """Get per-topic article match counts for a user over the last N days.

        Returns list of (topic_text, count) for active topics.
        """
        async with self._conn.execute(
            "SELECT t.topic_text, COUNT(sa.id) as cnt "
            "FROM topics t "
            "LEFT JOIN sent_articles sa ON sa.topic_id = t.id "
            "  AND sa.sent_at >= datetime('now', ? || ' days') "
            "WHERE t.user_id = ? AND t.active = 1 "
            "GROUP BY t.id ORDER BY cnt DESC",
            (f"-{days}", user_id),
        ) as cur:
            rows = await cur.fetchall()
        return [(r["topic_text"], r["cnt"]) for r in rows]

    async def get_total_articles_count(self, days: int = 7) -> int:
        """Total articles scraped in the last N days."""
        async with self._conn.execute(
            "SELECT COUNT(*) FROM articles "
            "WHERE created_at >= datetime('now', ? || ' days')",
            (f"-{days}",),
        ) as cur:
            row = await cur.fetchone()
        return row[0]

    # --- Feedback ---

    async def save_feedback(
        self, user_id: int, article_id: int, relevant: bool
    ) -> None:
        """Save user feedback on an article's relevance."""
        await self._conn.execute(
            "INSERT INTO article_feedback (user_id, article_id, relevant) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, article_id) DO UPDATE SET relevant = ?",
            (user_id, article_id, int(relevant), int(relevant)),
        )
        await self._conn.commit()

    async def get_feedback_stats(
        self, user_id: int
    ) -> tuple[int, int]:
        """Get (positive, negative) feedback counts for a user."""
        async with self._conn.execute(
            "SELECT "
            "  SUM(CASE WHEN relevant = 1 THEN 1 ELSE 0 END) as pos, "
            "  SUM(CASE WHEN relevant = 0 THEN 1 ELSE 0 END) as neg "
            "FROM article_feedback WHERE user_id = ?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        return (row["pos"] or 0, row["neg"] or 0)

    # --- Digest ---

    async def set_digest_mode(
        self, user_id: int, enabled: bool, hour: int = 9
    ) -> None:
        """Enable or disable digest mode for a user."""
        await self._conn.execute(
            "UPDATE users SET digest_mode = ?, digest_hour = ? WHERE id = ?",
            (int(enabled), hour, user_id),
        )
        await self._conn.commit()

    async def get_users_for_digest(self, current_hour: int) -> list[User]:
        """Get all users with digest_mode=1 whose digest_hour matches current_hour."""
        async with self._conn.execute(
            f"SELECT {self._USER_COLS} FROM users "
            "WHERE digest_mode = 1 AND digest_hour = ?",
            (current_hour,),
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_user(r) for r in rows]

    async def queue_digest_article(
        self, user_id: int, article_id: int, topic_id: int
    ) -> None:
        """Add an article to a user's digest queue."""
        await self._conn.execute(
            "INSERT OR IGNORE INTO digest_queue "
            "(user_id, article_id, topic_id) VALUES (?, ?, ?)",
            (user_id, article_id, topic_id),
        )
        await self._conn.commit()

    async def get_digest_queue(
        self, user_id: int
    ) -> list[tuple[Article, list[Topic]]]:
        """Return pending digest items grouped by article for a user."""
        async with self._conn.execute(
            "SELECT a.id, a.url_hash, a.source, a.title, a.url, a.summary, "
            "  a.published_at, a.created_at, a.content, "
            "  t.id as t_id, t.user_id as t_user_id, t.topic_text, "
            "  t.keywords_json, t.active, t.created_at as t_created, t.paused "
            "FROM digest_queue dq "
            "JOIN articles a ON a.id = dq.article_id "
            "JOIN topics t ON t.id = dq.topic_id "
            "WHERE dq.user_id = ? "
            "ORDER BY a.id, t.id",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()

        grouped: dict[int, tuple[Article, list[Topic]]] = {}
        for r in rows:
            art_id = r["id"]
            if art_id not in grouped:
                grouped[art_id] = (
                    Article(
                        id=r["id"], url_hash=r["url_hash"], source=r["source"],
                        title=r["title"], url=r["url"], summary=r["summary"],
                        published_at=r["published_at"], created_at=r["created_at"],
                        content=r["content"],
                    ),
                    [],
                )
            grouped[art_id][1].append(
                Topic(
                    id=r["t_id"], user_id=r["t_user_id"],
                    topic_text=r["topic_text"],
                    keywords_json=r["keywords_json"],
                    active=bool(r["active"]),
                    created_at=r["t_created"],
                    paused=bool(r["paused"]),
                )
            )
        return list(grouped.values())

    async def clear_digest_queue(self, user_id: int) -> None:
        """Clear all queued digest items for a user after sending."""
        await self._conn.execute(
            "DELETE FROM digest_queue WHERE user_id = ?", (user_id,)
        )
        await self._conn.commit()

    # --- Cleanup ---

    async def delete_old_articles(self, days: int = 30) -> int:
        """Delete articles older than N days and their sent_articles records.

        Returns number of articles deleted.
        """
        # Delete sent_articles referencing old articles first
        await self._conn.execute(
            "DELETE FROM sent_articles WHERE article_id IN ("
            "  SELECT id FROM articles "
            "  WHERE created_at < datetime('now', ? || ' days')"
            ")",
            (f"-{days}",),
        )
        result = await self._conn.execute(
            "DELETE FROM articles "
            "WHERE created_at < datetime('now', ? || ' days')",
            (f"-{days}",),
        )
        await self._conn.commit()
        return result.rowcount
