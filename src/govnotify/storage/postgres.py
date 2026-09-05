"""
SQLAlchemy ORM models and database session management.
Maps to the PostgreSQL schema defined in §9.1 of the system prompt.
Uses async SQLAlchemy with asyncpg driver.
"""
from __future__ import annotations

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
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
    country = Column(String(10), default="world", index=True)
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
    # Retained so translations produced before Hindi was archived are not
    # destroyed; nothing writes to it now. See archive/hindi-localisation.
    summary_hindi = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)
    image_search_query = Column(Text, nullable=True)
    categories = Column(JSONB, default=list)
    primary_category = Column(String(50), nullable=True, index=True)
    regions = Column(JSONB, default=list)
    departments = Column(JSONB, default=list)
    impact_tier = Column(String(50), default="Medium", index=True)
    # Feed scope this document belongs to: world, in, us. Null for documents
    # ingested before scopes existed, which are excluded from country feeds.
    country = Column(String(10), nullable=True, index=True)
    # Whether this story justifies interrupting a reader. Deliberately rare:
    # notifications that are usually ignored teach people to ignore all of them.
    notification_worthy = Column(Boolean, default=False, nullable=False, index=True)
    affected_audience = Column(JSONB, default=list)
    entities = Column(JSONB, default=dict)
    notification_number = Column(String(255), nullable=True)
    ingested_at = Column(
        DateTime(timezone=True), default=get_utc_now, index=True
    )
    # When the outlet published the story, as opposed to when we ingested it.
    # Nullable: documents stored before this was captured have no value, and
    # readers fall back to ingested_at.
    published_at = Column(DateTime(timezone=True), nullable=True, index=True)
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
        # Every feed request filters on is_duplicate and orders by ingested_at
        # descending; this covers that access path directly.
        # Every feed request filters on country and is_duplicate, then orders
        # by ingested_at descending.
        Index(
            "idx_documents_feed",
            "country",
            "is_duplicate",
            ingested_at.desc(),
        ),
        # Near-duplicate lookups load a recent window by simhash.
        Index("idx_documents_simhash", "simhash"),
    )


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
        
        engine_kwargs = {
            "pool_pre_ping": True,
            "echo": settings.app_debug,
        }
        
        # In serverless environments (like Vercel), NullPool prevents connection exhaustion
        if settings.is_production:
            engine_kwargs["poolclass"] = NullPool
            
        _engine = create_async_engine(
            settings.database_url,
            **engine_kwargs
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
