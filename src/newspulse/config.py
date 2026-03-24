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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
