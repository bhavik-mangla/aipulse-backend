"""
Application configuration via pydantic-settings.
This is the single source of truth for configuration across the app.
All settings are loaded from environment variables (or .env file).
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """GovNotify application settings."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "govnotify"
    app_env: str = Field(default="development", description="development | staging | production")
    app_host: str = "0.0.0.0"
    app_secret_key: str = "change-me-in-production"
    app_debug: bool = True
    app_port: int = 8000

    # --- PostgreSQL ---
    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "govnotify"
    db_user: str = "govnotify"
    db_password: str = "change-me"
    database_url: str = "postgresql+asyncpg://govnotify:change-me@postgres:5432/govnotify"

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"

    # --- LLM ---
    #
    # "gemini" uses the hosted free tier and needs GEMINI_API_KEY.
    # "local" talks to an OpenAI-compatible server on your machine (Ollama,
    # LM Studio, llama.cpp) and needs no key, which is how the pipeline can be
    # run and contributed to without anyone's quota.
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    enable_llm: bool = True

    # Local model settings, used when llm_provider is "local".
    # Default to a small instruction-tuned model rather than a reasoning one.
    # Reasoning models answer a request for JSON with paragraphs of visible
    # deliberation, which costs minutes per article and parses to nothing.
    local_llm_model: str = "llama3.2:3b"
    local_llm_base_url: str = "http://localhost:11434"

    @property
    def use_local_llm(self) -> bool:
        return self.llm_provider.lower() == "local"

    # --- Crawling ---
    crawl_user_agent: str = "GovNotify/1.0 (government notification aggregator)"
    crawl_default_rate_limit_rpm: int = 30
    crawl_respect_robots_txt: bool = True

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.app_env == "development"

    @property
    def is_testing(self) -> bool:
        """Check if running in test environment."""
        return self.app_env == "testing"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the application settings singleton.

    Cached: this is called from request handlers, the ingestion pipeline and
    every processing component, and each uncached call re-read and re-validated
    the environment and .env file. The docstring already claimed it was a
    singleton; now it is one.
    """
    return Settings()
