from dataclasses import dataclass


@dataclass
class User:
    id: int
    telegram_id: int
    created_at: str


@dataclass
class Topic:
    id: int
    user_id: int
    topic_text: str
    keywords_json: str
    active: bool
    created_at: str


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
