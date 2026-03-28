import aiosqlite

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

CREATE_TOPICS = """
CREATE TABLE IF NOT EXISTS topics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    topic_text    TEXT NOT NULL,
    keywords_json TEXT NOT NULL DEFAULT '[]',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

CREATE_ARTICLES = """
CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash     TEXT UNIQUE NOT NULL,
    source       TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

CREATE_SENT_ARTICLES = """
CREATE TABLE IF NOT EXISTS sent_articles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES articles(id),
    topic_id   INTEGER NOT NULL REFERENCES topics(id),
    sent_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (article_id, topic_id)
)
"""

CREATE_SCRAPE_LOG = """
CREATE TABLE IF NOT EXISTS scrape_log (
    source         TEXT PRIMARY KEY,
    last_scraped_at TEXT NOT NULL
)
"""


async def init_db(conn: aiosqlite.Connection) -> None:
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute(CREATE_USERS)
    await conn.execute(CREATE_TOPICS)
    await conn.execute(CREATE_ARTICLES)
    await conn.execute(CREATE_SENT_ARTICLES)
    await conn.execute(CREATE_SCRAPE_LOG)
    # Migrations for existing databases
    try:
        await conn.execute("ALTER TABLE articles ADD COLUMN content TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass  # Column already exists
    try:
        default = '["en","hy"]'
        await conn.execute(
            f"ALTER TABLE users ADD COLUMN languages_json TEXT NOT NULL DEFAULT '{default}'"
        )
    except Exception:
        pass  # Column already exists
    try:
        await conn.execute("ALTER TABLE users ADD COLUMN sources_json TEXT DEFAULT NULL")
    except Exception:
        pass  # Column already exists
    try:
        await conn.execute(
            "ALTER TABLE topics ADD COLUMN paused INTEGER NOT NULL DEFAULT 0"
        )
    except Exception:
        pass  # Column already exists
    # Performance indexes
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_topics_user_active "
        "ON topics(user_id, active)",
        "CREATE INDEX IF NOT EXISTS idx_articles_source "
        "ON articles(source)",
        "CREATE INDEX IF NOT EXISTS idx_articles_created "
        "ON articles(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_sent_articles_article "
        "ON sent_articles(article_id)",
        "CREATE INDEX IF NOT EXISTS idx_sent_articles_topic "
        "ON sent_articles(topic_id)",
    ]:
        await conn.execute(idx_sql)
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS article_feedback ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  user_id INTEGER NOT NULL REFERENCES users(id),"
        "  article_id INTEGER NOT NULL REFERENCES articles(id),"
        "  relevant INTEGER NOT NULL,"
        "  created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        "  UNIQUE(user_id, article_id)"
        ")"
    )
    await conn.commit()
