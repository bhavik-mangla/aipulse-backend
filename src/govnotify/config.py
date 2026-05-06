"""
Application configuration via pydantic-settings.
This is the single source of truth for configuration across the app.
All settings are loaded from environment variables (or .env file).
"""
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

    # --- Qdrant ---
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_collection: str = "govnotify_chunks"

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # --- LLM API Keys ---
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    enable_llm: bool = True

    # --- Embedding Model ---
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # --- Delivery ---
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "notifications@govnotify.in"
    telegram_bot_token: str = ""
    # Twilio (Legacy/Multi-channel)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    whatsapp_from_number: str = ""
    # WhatsApp Cloud API (Latest/Direct)
    whatsapp_cloud_access_token: str = ""
    whatsapp_cloud_phone_number_id: str = ""
    whatsapp_cloud_business_account_id: str = ""
    whatsapp_cloud_version: str = "v21.0"

    # --- Crawling ---
    crawl_user_agent: str = "GovNotify/1.0 (government notification aggregator)"
    crawl_default_rate_limit_rpm: int = 30
    crawl_respect_robots_txt: bool = True

    # --- RAG ---
    rag_top_k_retrieval: int = 50
    rag_top_k_rerank: int = 10
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 64
    rag_similarity_threshold: float = 0.3

    # --- Auth ---
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

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


def get_settings() -> Settings:
    """Create and return application settings singleton."""
    return Settings()
