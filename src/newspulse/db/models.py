from dataclasses import dataclass


@dataclass
class User:
    id: int
    telegram_id: int
    created_at: str
    languages_json: str = '["en","hy"]'
    sources_json: str | None = None
    digest_mode: bool = False
    digest_hour: int = 9  # UTC hour (0-23) for digest delivery


@dataclass
class Topic:
    id: int
    user_id: int
    topic_text: str
    keywords_json: str
    active: bool
    created_at: str
    paused: bool = False
    keywords_updated_at: str | None = None


@dataclass
class Article:
    id: int
    url_hash: str
    source: str
    title: str
    url: str
    summary: str
    published_at: str | None
    created_at: str
    content: str = ""
