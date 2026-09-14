"""Application configuration loaded from environment variables / .env file."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    All values are read from the process environment or a `.env` file
    located in the current working directory (see `.env.example`).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram ---
    BOT_TOKEN: str = Field(..., description="Telegram bot token from @BotFather")

    # --- OpenAI ---
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key")
    OPENAI_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Model used for subject/work-type classification and PDF generation",
    )

    # --- Target group ---
    TARGET_GROUP_ID: int = Field(
        ..., description="Telegram group (forum) chat id where PDFs are posted. Negative number."
    )

    # --- Cache ---
    MAX_CACHE_SIZE_MB: float = Field(
        default=50.0, description="Maximum per-user cache size, in megabytes"
    )
    TEMP_DIR: Path = Field(
        default=Path("./tmp"), description="Directory used to store cached user files"
    )

    # --- Misc ---
    LOG_LEVEL: str = Field(default="INFO", description="Python logging level")
    OPENAI_TIMEOUT_SECONDS: float = Field(
        default=180.0, description="Timeout for OpenAI API calls (PDF generation can be slow)"
    )

    def ensure_dirs(self) -> None:
        """Create the temp directory tree if it does not exist yet."""
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
