import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    CONGRESS_API_KEY: str
    DATABASE_URL: str

    # OpenRouter (OpenAI-compatible) settings for the AI processing pipeline.
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_MODEL: str = "anthropic/claude-sonnet-4.5"

    # Allow reading from a .env file relative to the project root
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
