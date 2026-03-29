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
    """Return all source names in definition order."""
    return list(SOURCE_LANGUAGES.keys())
