from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from newspulse.db.repository import Repository

# Language codes: "en" = English, "hy" = Armenian
SOURCE_LANGUAGES: dict[str, str] = {
    "BBC World": "en",
    "Al Jazeera": "en",
    "CivilNet": "hy",
    "1Lurer": "hy",
    "NEWS.am": "hy",
    "Azatutyun": "hy",
    "Hetq": "hy",
    "Mediamax": "hy",
    "Arka.am": "hy",
    "APA": "en",
}

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "hy": "Հայերեն",
}


def get_all_source_names() -> list[str]:
    """Return static (non-Telegram) source names."""
    return list(SOURCE_LANGUAGES.keys())


async def get_all_source_names_with_channels(repo: Repository) -> list[str]:
    """Return static source names plus tg:<username> for every active channel."""
    channels = await repo.get_active_telegram_channels()
    return list(SOURCE_LANGUAGES.keys()) + [f"tg:{ch.username}" for ch in channels]
