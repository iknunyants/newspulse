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

    async def get_or_create_user(self, telegram_id: int) -> User:
        async with self._conn.execute(
            "SELECT id, telegram_id, created_at FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
        if row:
            return User(**row)
        await self._conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (telegram_id,)
        )
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT id, telegram_id, created_at FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
        return User(**row)

    # --- Topics ---

    async def add_topic(self, user_id: int, topic_text: str, keywords: list[str]) -> Topic:
        keywords_json = json.dumps(keywords, ensure_ascii=False)
        await self._conn.execute(
            "INSERT INTO topics (user_id, topic_text, keywords_json) VALUES (?, ?, ?)",
            (user_id, topic_text, keywords_json),
        )
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT id, user_id, topic_text, keywords_json, active, created_at "
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
        )

    async def count_active_topics(self, user_id: int) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM topics WHERE user_id = ? AND active = 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        return row[0]

    async def get_active_topics(self, user_id: int | None = None) -> list[Topic]:
        if user_id is not None:
            query = (
                "SELECT id, user_id, topic_text, keywords_json, active, created_at "
                "FROM topics WHERE user_id = ? AND active = 1 ORDER BY id"
            )
            params = (user_id,)
        else:
            query = (
                "SELECT id, user_id, topic_text, keywords_json, active, created_at "
                "FROM topics WHERE active = 1 ORDER BY id"
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
    ) -> tuple[Article, bool]:
        url_hash = self._url_hash(url)
        async with self._conn.execute(
            "SELECT id, url_hash, source, title, url, summary, published_at, created_at "
            "FROM articles WHERE url_hash = ?",
            (url_hash,),
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            return Article(**existing), False

        await self._conn.execute(
            "INSERT INTO articles (url_hash, source, title, url, summary, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (url_hash, source, title, url, summary[:500], published_at),
        )
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT id, url_hash, source, title, url, summary, published_at, created_at "
            "FROM articles WHERE url_hash = ?",
            (url_hash,),
        ) as cur:
            row = await cur.fetchone()
        return Article(**row), True

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
