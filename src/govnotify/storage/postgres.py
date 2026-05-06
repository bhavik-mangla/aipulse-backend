"""
SQLAlchemy ORM models and database session management.
Maps to the PostgreSQL schema defined in §9.1 of the system prompt.
Uses async SQLAlchemy with asyncpg driver.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from govnotify.config import get_settings
from govnotify.utils.time import get_utc_now


# --- Base ---

class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""
    pass


# --- ORM Models ---

class SourceORM(Base):
    """Data source configuration table."""
    __tablename__ = "sources"

    id = Column(String(100), primary_key=True)
    name = Column(String(255), nullable=False)
    source_type = Column(String(50), nullable=False)
    url = Column(Text, nullable=False)
    schedule_cron = Column(String(50), default="0 4 * * *")
    enabled = Column(Boolean, default=True)
    region_tags = Column(JSONB, default=list)
    category_tags = Column(JSONB, default=list)
    language = Column(String(20), default="en")
    crawler_class = Column(String(255), nullable=False)
    crawler_config = Column(JSONB, default=dict)
    headers = Column(JSONB, default=dict)
    rate_limit_rpm = Column(Integer, default=30)
    last_fetched_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=get_utc_now
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=get_utc_now,
        onupdate=get_utc_now,
    )

    # Relationships
    documents = relationship("DocumentORM", back_populates="source")
    ingest_logs = relationship("IngestLogORM", back_populates="source")


class DocumentORM(Base):
    """Processed document table."""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    source_id = Column(
        String(100), ForeignKey("sources.id"), nullable=False, index=True
    )
    source_url = Column(Text, nullable=False)
    fetch_url = Column(Text, nullable=True)
    title = Column(Text, nullable=False)
    clean_text = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    summary_hindi = Column(Text, nullable=True)
    categories = Column(JSONB, default=list)
    primary_category = Column(String(50), nullable=True, index=True)
    regions = Column(JSONB, default=list)
    departments = Column(JSONB, default=list)
    impact_tier = Column(String(50), default="Medium", index=True)
    affected_audience = Column(JSONB, default=list)
    entities = Column(JSONB, default=dict)
    notification_number = Column(String(255), nullable=True)
    ingested_at = Column(
        DateTime(timezone=True), default=get_utc_now, index=True
    )
    language = Column(String(10), default="en")
    content_hash = Column(String(64), nullable=False, index=True)
    simhash = Column(String(64), nullable=True)
    is_duplicate = Column(Boolean, default=False)
    duplicate_of = Column(UUID(as_uuid=False), ForeignKey("documents.id"), nullable=True)
    confidence_score = Column(Float, default=0.0)

    # Relationships
    source = relationship("SourceORM", back_populates="documents")

    __table_args__ = (
        Index("idx_documents_categories", "categories", postgresql_using="gin"),
        Index("idx_documents_regions", "regions", postgresql_using="gin"),
    )


class UserORM(Base):
    """User account table."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    email = Column(String(255), unique=True, nullable=True)
    phone = Column(String(20), nullable=True)
    telegram_chat_id = Column(String(50), nullable=True)
    name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=True)
    preferences = Column(JSONB, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(
        DateTime(timezone=True), default=get_utc_now
    )
    last_active_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    digests = relationship("DigestORM", back_populates="user")


class CategoryDigestORM(Base):
    """Pre-generated per-category per-day digest table."""
    __tablename__ = "category_digests"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    category = Column(String(50), nullable=False, index=True)
    date = Column(String(10), nullable=False, index=True)
    items = Column(JSONB, default=list)
    summary_text = Column(Text, default="")
    summary_hindi = Column(Text, default="")
    item_count = Column(Integer, default=0)
    has_updates = Column(Boolean, default=True)
    generated_at = Column(
        DateTime(timezone=True), default=get_utc_now
    )
    llm_model_used = Column(String(100), default="")
    llm_cost_usd = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint("category", "date", name="uq_category_date"),
    )


class DigestORM(Base):
    """User digest delivery record table."""
    __tablename__ = "digests"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    category_sections = Column(JSONB, default=list)
    delivery_channel = Column(String(50), nullable=True)
    date = Column(String(10), nullable=False)
    generated_at = Column(
        DateTime(timezone=True), default=get_utc_now
    )
    total_items = Column(Integer, default=0)
    delivered = Column(Boolean, default=False)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationships
    user = relationship("UserORM", back_populates="digests")


class IngestLogORM(Base):
    """Ingestion run audit log table."""
    __tablename__ = "ingest_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(100), ForeignKey("sources.id"), nullable=False)
    status = Column(String(50))  # success, error, partial, running
    items_fetched = Column(Integer, default=0)
    items_new = Column(Integer, default=0)
    items_duplicate = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    error_details = Column(JSONB, default=list)
    duration_ms = Column(Integer, default=0)
    started_at = Column(
        DateTime(timezone=True), default=get_utc_now
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=get_utc_now
    )

    # Relationships
    source = relationship("SourceORM", back_populates="ingest_logs")


# --- Database Session Management ---

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            echo=settings.app_debug,
        )
    return _engine


def get_session_factory(engine):
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory
