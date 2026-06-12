import os
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    CONGRESS_API_KEY: str
    DATABASE_URL: str

    # OpenRouter (OpenAI-compatible) settings for the AI processing pipeline.
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_MODEL: str = Field(
        default="anthropic/claude-sonnet-4.5",
        validation_alias=AliasChoices("LLM_MODEL", "OPENROUTER_MODEL"),
    )

    REDIS_URL: str = "redis://localhost:6379"

    # Auth / JWT
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"

    # Email / SMTP (for verification emails)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # Frontend base URL (used in verification email links)
    FRONTEND_URL: str = "http://localhost:5173"

    # Allow reading from a .env file relative to the project root
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
