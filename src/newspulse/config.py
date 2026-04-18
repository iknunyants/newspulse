from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    gemini_api_key: str
    database_path: Path = Path("data/newspulse.db")
    scrape_interval_minutes: int = 15
    log_level: str = "INFO"
    max_topics_per_user: int = 10
    gemini_model: str = "gemini-3.1-flash-lite-preview"
    gemini_model_keywords: str = "gemini-3-flash-preview"
    max_channels_per_user: int = 10
    telegram_dedup_window_minutes: int = 360

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
