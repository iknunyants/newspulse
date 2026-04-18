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
    forwarded_from: str | None = None
    media_url: str | None = None
    content_hash: str | None = None


@dataclass
class TelegramChannel:
    id: int
    username: str
    title: str
    added_by_user_id: int
    active: bool
    created_at: str


@dataclass
class UserChannelMode:
    user_id: int
    channel_id: int
    mode: str  # 'filter' | 'forward_all'
