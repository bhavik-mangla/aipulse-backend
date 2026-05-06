# GovNotify India - Complete System Prompt & Project Blueprint

**Version:** 1.0 | **Date:** 2026-04-06
**Target:** Production-grade, extensible government notification platform for India
**Codename:** GovNotify | **License:** Apache 2.0

# 1. PROJECT OVERVIEW

### 1.1 Mission
Build an **extensible, production-grade platform** that ingests official Indian government notifications from dozens of sources, deduplicates and enriches them, stores them in a hybrid database with rich metadata, and delivers **daily plain-language category digests** to millions of users via email, web, WhatsApp, and Telegram.

**The core problem:** Indian citizens miss critical government notifications (jobs, schemes, tax changes, health orders) because information is scattered across hundreds of ".gov.in" sites, gazettes, and PDFs - with no unified, filtered, plain-language daily digest. We solve this at scale.

### 1.2 Two-Phase Roadmap

| Phase | Scope | Timeline |
|-------|-------|----------|
| **V1 - Category Digests** | Users subscribe to predefined categories (Jobs, Schemes, Tax, Agriculture, Education, Health, Legal/Gazette, etc.). System **pre-generates one digest per category per day** (not per user - saves LLM calls). Each item is tagged with region metadata. Users receive a composite of their subscribed categories every morning at **7 AM IST**. Only today's new notices are included. If a category has no new notices, a brief "No updates today" is shown. | MVP: 8-12 weeks |
| **V2 - Deep Personalization Agent** | Full conversational onboarding: agent asks users about age, occupation, region, education, income level, family status, specific interests, preferred languages, and notification timing. Builds a rich semantic profile. Daily matching uses profile embeddings vs. all new documents (not just category filters). Includes HyDE, cross-encoder reranking, and per-user digest generation. Also: interactive Q&A ("What subsidies am I eligible for?"). | +8-12 weeks after v1 |

### 1.3 Key Principles
1. **Extensibility First** - Every component (sources, crawlers, parsers, delivery channels) follows a strict interface/schema. Adding a new source = implementing one class.
2. **Schema-Driven** - All data (raw documents, processed notices, user profiles, notification payloads) conforms to Pydantic models with versioned schemas.
3. **Deduplication at Every Layer** - Content-hash at ingest, MinHash/SimHash for near-duplicates, embedding similarity for semantic dedup.
4. **Hybrid Database** - PostgreSQL for relational data + Qdrant for vector search + Redis for caching/queues.
5. **RAG Best Practices** - Decoupled retrieval & synthesis chunks, hybrid search (dense + sparse + metadata filters), reranking, citation grounding.
6. **Multi-Provider LLM** - LiteLLM router with fallback chain (Gemini -> GPT-4o -> Claude -> local Llama).
7. **LLM Cost Efficiency** - V1 generates digests per category (not per user). With ~17 categories, that's ~17 LLM calls/day regardless of user count. V2 adds per-user personalization.
8. **Observable & Testable** - Structured logging, OpenTelemetry traces, comprehensive test suite, CI/CD.

# 2. ARCHITECTURE

### 2.1 High-Level Architecture

INGESTION LAYER
- RSS/Atom, Web, PDF, API
- Fetcher, Crawler, Scraper, Poller
- Source Interface (ABC): fetch() -> RawDocument[]

PROCESSING PIPELINE
- Dedup Check (hash)
- Parser/Extractor (text, meta)
- Enricher (NER, classify)
- Chunker & Embedder (dense+sparse)

STORAGE LAYER
- PostgreSQL (relational, metadata, users, audit log)
- Qdrant (vectors, hybrid search, payloads)
- Redis (cache, task queues, rate limits, sessions)

INTELLIGENCE LAYER
- RAG Engine (retrieve + rerank)
- Category Digest Generator
- Personalization Engine (semantic profile match, V2)

DELIVERY LAYER
- Email Digest
- Web Feed
- WhatsApp Bot
- Telegram Bot
- Delivery Interface (ABC): send(user, digest) -> DeliveryResult

ORCHESTRATION LAYER
- Celery Beat (scheduler)
- Celery Workers (tasks)
- FastAPI Server (API+Web)

### 2.2 Directory Structure

```
govnotify/
├── pyproject.toml          # Project metadata, dependencies (uv/pip)
├── requirements.txt        # Pinned dependencies
├── .env.example            # Environment variable template
├── docker-compose.yml      # Full local stack
├── Dockerfile              # App container
├── alembic/                # Database migrations
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
└── src/
    └── govnotify/
        ├── __init__.py
        ├── config.py       # Settings via pydantic-settings
        ├── main.py         # FastAPI app factory
        ├── models/         # Pydantic schemas (the single source of truth)
        │   ├── __init__.py
        │   ├── source.py       # SourceMetadata, RawDocument
        │   ├── document.py     # ProcessedDocument, DocumentChunk
        │   ├── notification.py # Notification, NotificationDigest
        │   ├── user.py         # UserProfile, UserPreferences
        │   └── delivery.py     # DeliveryPayload, DeliveryResult
        ├── sources/        # Data source plugins (extensible)
        │   ├── __init__.py
        │   ├── base.py         # AbstractSource interface
        │   ├── registry.py     # Source plugin registry
        │   ├── rss_source.py   # Generic RSS/Atom fetcher
        │   ├── pib_source.py   # Press Information Bureau
        │   ├── egazette_source.py # Central e-Gazette scraper
        │   ├── rbi_source.py   # RBI circulars
        │   └── data_gov_source.py # data.gov.in API
        ├── crawlers/       # Web crawling infrastructure
        │   ├── __init__.py
        │   ├── base.py         # AbstractCrawler
        │   ├── crawl4ai_crawler.py # Crawl4AI-based crawler
        │   ├── rss_crawler.py  # feedparser-based RSS crawler
        │   └── pdf_crawler.py  # PDF download + extraction
        ├── processing/     # Document processing pipeline
        │   ├── __init__.py
        │   ├── pipeline.py     # Orchestrates processing steps
        │   ├── dedup.py        # Deduplication (hash + MinHash + semantic)
        │   ├── parser.py       # Text extraction (PDF, HTML, text)
        │   ├── enricher.py     # NER, classification, metadata extraction
        │   ├── chunker.py      # Smart chunking (semantic boundaries)
        │   └── embedder.py     # Embedding generation (dense + sparse)
        ├── storage/        # Database abstraction layer
        │   ├── postgres.py     # SQLAlchemy models + repository
        │   ├── qdrant.py       # Qdrant vector store operations
        │   ├── redis_store.py  # Redis cache + queue operations
        │   └── repository.py   # Unified repository interface
        ├── rag/            # RAG engine
        │   ├── retriever.py    # Hybrid retrieval (dense + sparse + filter)
        │   ├── reranker.py     # Cross-encoder reranking
        │   └── engine.py       # RAG pipeline orchestrator
        ├── digests/        # Category digest generation (V1 core)
        │   ├── __init__.py
        │   ├── category_digest.py # Pre-generate one digest per category/day
        │   ├── assembler.py    # Assemble user digest from category digests
        │   └── templates.py    # Digest formatting templates
        ├── delivery/       # Notification delivery plugins (extensible)
        │   ├── __init__.py
        │   ├── base.py         # AbstractDeliveryChannel
        │   ├── registry.py     # Channel plugin registry
        │   ├── email_channel.py # Email via SendGrid/SES
        │   ├── web_channel.py   # WebSocket/SSE for web feed
        │   ├── whatsapp_channel.py # WhatsApp Business API
        │   └── telegram_channel.py # Telegram Bot API
        ├── tasks/          # Celery async tasks
        │   ├── celery_app.py   # Celery configuration
        │   ├── ingest_tasks.py # Scheduled ingestion
        │   ├── process_tasks.py # Processing pipeline tasks
        │   ├── digest_tasks.py # Digest generation + delivery
        │   └── maintenance_tasks.py # Cleanup, reindex, health checks
        ├── api/            # FastAPI routes
        │   ├── __init__.py
        │   ├── deps.py         # Dependency Injection
        │   └── v1/
        │       ├── __init__.py
        │       ├── auth.py         # JWT auth endpoints
        │       ├── users.py        # User profile CRUD
        │       ├── notifications.py # Feed & search endpoints
        │       ├── categories.py   # Category management
        │       ├── chat.py         # V2: Conversational agent
        │       └── admin.py        # Admin/monitoring endpoints
        ├── utils/          # Shared utilities
        │   ├── __init__.py
        │   ├── hashing.py      # Content hashing utilities
        │   ├── text.py         # Text cleaning, language detection
        │   ├── translation.py  # Translation utilities
        │   └── logging.py      # Structured logging setup
        └── tests/          # Comprehensive test suite
            ├── conftest.py     # Shared fixtures
            ├── unit/
            │   ├── test_dedup.py
            │   └── test_models.py
            ├── test_sources/
            │   ├── test_rss_source.py
            │   └── test_pib_source.py
            ├── integration/
            │   ├── test_pipeline.py
            │   ├── test_qdrant.py
            │   └── test_rag_engine.py
            └── e2e/
                ├── test_delivery.py
                ├── test_ingest_to_digest.py
                └── test_api.py
```

# 3. CORE SCHEMAS (Pydantic Models)

All data flows through these schemas. They are the **single source of truth** for data shape across the entire system.

### 3.1 Source & Raw Document

```python
from datetime import datetime
from enum import Enum
from typing import Optional
import hashlib
from pydantic import BaseModel, Field, HttpUrl

class SourceType(str, Enum):
    RSS = "rss"
    WEB_SCRAPE = "web_scrape"
    PDF = "pdf"
    API = "api"
    EMAIL = "email"

class SourceConfig(BaseModel):
    """Configuration for a data source. Stored in DB, drives crawling."""
    id: str = Field(description="Unique source identifier, e.g. 'pib_press_releases'")
    name: str = Field(description="Human-readable name")
    source_type: SourceType
    url: HttpUrl = Field(description="Base URL or RSS feed URL")
    schedule_cron: str = Field(default="0 */4 * * *", description="Cron expression for polling")
    enabled: bool = True
    category_tags: list[str] = Field(default_factory=list, description="Default categories for this source")
    region_tags: list[str] = Field(default_factory=list, description="Default regions")
    language: str = Field(default="en", description="Primary language of source content")
    crawler_class: str = Field(description="Fully qualified class name of crawler to use")
    crawler_config: dict = Field(default_factory=dict, description="Crawler-specific configuration")
    headers: dict[str, str] = Field(default_factory=dict)
    rate_limit_rpm: int = Field(default=30, description="Max requests per minute")
    last_fetched_at: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "id": "pib_press_releases",
                "name": "PIB Press Releases",
                "source_type": "rss",
                "url": "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
                "schedule_cron": "0 */2 * * *",
                "category_tags": ["press_release", "central_government"],
                "region_tags": ["national"],
                "language": "en",
                "crawler_class": "govnotify.crawlers.rss_crawler.RSSCrawler"
            }
        }

class RawDocument(BaseModel):
    """Raw document as fetched from a source, before processing."""
    source_id: str
    source_url: HttpUrl
    fetch_url: HttpUrl = Field(description="Actual URL this doc was fetched from")
    title: str
    raw_content: str = Field(description="Raw text/HTML/PDF-text content")
    content_type: str = Field(description="MIME type: text/html, application/pdf, text/plain")
    published_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    language: str = Field(default="en")
    content_hash: str = Field(default="", description="SHA-256 of raw_content for exact dedup")
    metadata: dict = Field(default_factory=dict, description="Source-specific metadata")

    def compute_content_hash(self) -> str:
        self.content_hash = hashlib.sha256(self.raw_content.encode("utf-8")).hexdigest()
        return self.content_hash
```

### 3.2 Processed Document & Chunks

```python
from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl

class NoticeCategory(str, Enum):
    JOBS = "jobs"
    SCHEMES = "schemes"
    TAX = "tax"
    AGRICULTURE = "agriculture"
    EDUCATION = "education"
    HEALTH = "health"
    LEGAL = "legal"
    GAZETTE = "gazette"
    FINANCE = "finance"
    INFRASTRUCTURE = "infrastructure"
    ENVIRONMENT = "environment"
    DEFENSE = "defense"
    LOCAL_GOVERNANCE = "local_governance"
    WOMEN_CHILD = "women_child"
    TECHNOLOGY = "technology"
    SOCIAL_WELFARE = "social_welfare"
    OTHER = "other"

class ProcessedDocument(BaseModel):
    """A fully processed, enriched government notice."""
    id: str = Field(description="UUID")
    source_id: str
    source_url: HttpUrl
    title: str
    clean_text: str = Field(description="Cleaned, normalized text content")
    summary: str = Field(default="", description="AI-generated plain-language summary")
    summary_hindi: str = Field(default="", description="Hindi translation of summary")
    
    # Classification
    categories: list[NoticeCategory] = Field(default_factory=list)
    primary_category: NoticeCategory = NoticeCategory.OTHER
    regions: list[str] = Field(default_factory=list, description="Relevant states/regions")
    departments: list[str] = Field(default_factory=list, description="Issuing departments")
    
    # Extracted entities
    entities: dict[str, list[str]] = Field(
        default_factory=dict,
        description="NER results: {persons: [], organizations: [], dates: [], amounts: [], schemes: []}"
    )
    
    # Metadata
    notification_number: Optional[str] = None
    effective_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    published_at: Optional[datetime] = None
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    language: str = Field(default="en")
    
    # Dedup
    content_hash: str
    simhash: Optional[str] = None
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None
    
    # Quality
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Processing confidence")

class DocumentChunk(BaseModel):
    """A chunk of a processed document, optimized for retrieval."""
    id: str
    document_id: str
    chunk_index: int
    text: str = Field(description="Chunk text content")
    summary_context: str = Field(default="", description="Parent document summary for context")
    
    # Embeddings stored in Qdrant, not in this model
    dense_embedding: Optional[list[float]] = Field(default=None, exclude=True)
    sparse_embedding: Optional[dict] = Field(default=None, exclude=True) # {indices: [], values: []}
    
    # Metadata for filtering in Qdrant
    categories: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    source_id: str = ""
    published_at: Optional[datetime] = None
    language: str = "en"
```

### 3.3 User & Preferences

```python
class DeliveryChannel(str, Enum):
    EMAIL = "email"
    WEB = "web"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"

class DigestFrequency(str, Enum):
    REALTIME = "realtime"
    DAILY = "daily"
    WEEKLY = "weekly"

class UserPreferences(BaseModel):
    """User notification preferences (V1: category-based)."""
    categories: list[NoticeCategory] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list, description="States/regions of interest")
    language: str = Field(default="en", description="Preferred language for summaries")
    delivery_channels: list[DeliveryChannel] = Field(default=[DeliveryChannel.WEB])
    digest_frequency: DigestFrequency = DigestFrequency.DAILY
    max_items_per_digest: int = Field(default=20, ge=1, le=100)

class UserProfile(BaseModel):
    """Full user profile."""
    id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    name: Optional[str] = None
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    
    # V2: Natural language profile for semantic matching
    profile_description: str = Field(default="", description="Free-text profile for V2 agent matching")
    profile_embedding: Optional[list[float]] = Field(default=None, exclude=True)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active_at: Optional[datetime] = None
    is_active: bool = True
```

### 3.4 Notification & Delivery

```python
class NotificationItem(BaseModel):
    """A single notification item in a digest."""
    document_id: str
    title: str
    summary: str
    category: NoticeCategory
    source_name: str
    source_url: HttpUrl
    published_at: Optional[datetime] = None
    regions: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    relevance_score: float = Field(default=0.0)

class CategoryDigest(BaseModel):
    """
    Pre-generated digest for ONE category for ONE day.
    Generated once per category per day (~17 LLM calls total, not per-user).
    Cached in Redis and PostgreSQL.
    """
    id: str
    category: NoticeCategory
    date: str = Field(description="YYYY-MM-DD date this digest covers")
    items: list[NotificationItem] = Field(default_factory=list)
    summary_text: str = Field(default="", description="LLM-generated category summary")
    summary_hindi: str = Field(default="", description="Hindi translation of summary")
    item_count: int = 0
    has_updates: bool = Field(default=True, description="False if no notices for this category today")
    no_update_message: str = Field(
        default="No new updates in this category today. We'll keep watching!",
        description="Shown when has_updates=False"
    )
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: str = Field(default="", description="Which LLM generated this")
    llm_cost_usd: float = Field(default=0.0, description="Cost of LLM call for tracking")

class UserDigest(BaseModel):
    """
    A user's daily digest, assembled from pre-generated CategoryDigests.
    No additional LLM calls needed - just combines the user's subscribed categories.
    """
    id: str
    user_id: str
    category_sections: list[CategoryDigest] = Field(
        default_factory=list,
        description="One section per subscribed category, in user's preference order"
    )
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    date: str = Field(description="YYYY-MM-DD")
    total_items: int = 0
    delivery_channel: DeliveryChannel

class DeliveryResult(BaseModel):
    """Result of attempting to deliver a notification."""
    digest_id: str
    user_id: str
    channel: DeliveryChannel
    success: bool
    delivered_at: Optional[datetime] = None
    error_message: Optional[str] = None
    external_id: Optional[str] = Field(default=None, description="ID from external service (SendGrid, Telegram, etc.)")
```

# 4. DATA SOURCES - V1 TARGETS

### 4.1 Confirmed Sources for V1

| Source ID | Name | Type | URL / Feed | Categories | Frequency |
|-----------|------|------|------------|------------|-----------|
| egazette_central | Central e-Gazette | Web Scrape | https://egazette.gov.in/ | gazette, legal, bills_acts | Every 6h |
| pib_press_releases | PIB Press Releases | RSS | https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3 | press_release, central_govt | Every 2h |
| egazette_extraordinary | e-Gazette Extraordinary | Web Scrape | https://egazette.gov.in/ (Category=1) | gazette, legal, bills_acts | Every 4h |
| data_gov_in | data.gov.in Datasets | API/RSS | https://data.gov.in/backend/dms/v1/rss.xml | various | Daily |
| rbi_circulars | RBI Circulars | Web Scrape | https://rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx | finance, banking | Every 6h |
| rbi_press_releases | RBI Press Releases | Web Scrape | https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx | finance, banking | Every 6h |
| income_tax | Income Tax Notifications | Web Scrape | https://incometaxindia.gov.in/Pages/communications/notifications.aspx | tax, finance | Every 12h |
| ugc_notifications | UGC Notifications | Web Scrape | https://www.ugc.gov.in/Notification | education | Every 12h |
| nta_exams | NTA Exam Notices | Web Scrape | https://nta.ac.in/ | education, jobs | Every 6h |
| upsc_notifications | UPSC Notifications | Web Scrape | https://upsc.gov.in/ | jobs, education | Every 12h |
| pmkisan | PM-KISAN Updates | Web Scrape | https://pmkisan.gov.in/ | agriculture, schemes | Daily |
| ssc_updates | SSC Updates | Web Scrape | https://ssc.gov.in/ | jobs | Every 12h |

### 4.2 Source Response Validation
Before integrating any source, run:
1. **Check accessibility** - Can we reach the URL? What status code?
2. **Analyze response format** - HTML structure, RSS format, PDF links
3. **Identify pagination** - How to get historical/older items
4. **Find anti-bot measures** - CAPTCHAs, rate limits, IP blocks
5. **Map fields** - Where is title, date, content, department?
6. **Check for existing RSS/API** - Always prefer structured feeds over scraping
7. **Measure update frequency** - How often does content change?

### 4.3 Source Interface Contract

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator
from datetime import datetime

class AbstractSource(ABC):
    """Base interface for all data sources. Implement this to add a new source."""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier for this source."""
        pass

    @property
    @abstractmethod
    def source_config(self) -> SourceConfig:
        """Configuration for this source."""
        pass

    @abstractmethod
    async def fetch(self, since: datetime | None = None) -> AsyncIterator[RawDocument]:
        """
        Fetch new documents from this source.
        Args:
            since: Only fetch documents published after this datetime.
        Yields:
            RawDocument instances.
        Raises:
            SourceFetchError: If the source is unreachable or returns errors.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if this source is accessible and responding correctly."""
        pass

    async def validate_response(self, response: RawDocument) -> bool:
        """Validate that a fetched document meets minimum quality standards."""
        if not response.title or len(response.title) < 5:
            return False
        if not response.raw_content or len(response.raw_content) < 50:
            return False
        return True
```

# 5. CRAWLING & INGESTION

### 5.1 Crawler Architecture
We use **Crawl4AI** (63k GitHub stars, LLM-friendly output, anti-bot detection, async) as the primary web crawling engine, with **feedparser** for RSS and **pdfplumber** for PDFs.

```python
class AbstractCrawler(ABC):
    """Base crawler interface."""
    @abstractmethod
    async def crawl(self, url: str, config: dict) -> CrawlResult:
        """Crawl a URL and return structured result."""
        pass

class CrawlResult(BaseModel):
    url: str
    status_code: int
    content: str  # Extracted text/markdown
    content_type: str  # text/html, application/pdf, etc.
    links: list[str] = []  # Discovered links
    metadata: dict = {}  # Page-specific metadata
    raw_html: Optional[str] = None  # Original HTML if needed
    elapsed_s: float = 0.0
```

### 5.2 RSS Crawler (feedparser)
```python
import feedparser

class RSSCrawler(AbstractCrawler):
    async def crawl(self, url: str, config: dict) -> list[CrawlResult]:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries:
            results.append(CrawlResult(
                url=entry.link,
                status_code=200,
                content=entry.get("summary", "") or entry.get("description", ""),
                content_type="text/html",
                metadata={
                    "title": entry.get("title", ""),
                    "published": entry.get("published", ""),
                    "author": entry.get("author", ""),
                    "tags": [t.term for t in entry.get("tags", [])],
                }
            ))
        return results
```

### 5.3 Crawl4AI Web Crawler
```python
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

class Crawl4AICrawler(AbstractCrawler):
    async def crawl(self, url: str, config: dict) -> CrawlResult:
        run_config = CrawlerRunConfig(
            word_count_threshold=50,
            excluded_tags=["nav", "footer", "header", "sidebar"],
            **config
        )
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=run_config)
            return CrawlResult(
                url=url,
                status_code=result.status_code,
                content=result.markdown,  # Clean markdown
                content_type='text/html',
                metadata=result.metadata or {},
                links=result.links.get("internal", []),
                raw_html=result.html,
                elapsed_s=result.elapsed or 0.0,
            )
```

### 5.4 Rate Limiting & Politeness
- **Per-source rate limits** defined in SourceConfig.rate_limit_rpm
- Use `asyncio.Semaphore` + token bucket algorithm
- Respect robots.txt
- Random delay jitter: 1-3 seconds between requests
- Exponential backoff on 429/503 responses (2s -> 4s -> 8s -> 16s, max 5 retries)
- User-Agent: GovNotify/1.0 (government notification aggregator; contact@govnotify.in)

# 6. DEDUPLICATION STRATEGY

### 6.1 Three-Layer Dedup
- **Layer 1: EXACT HASH** (fastest, catches identical content)
  - SHA-256 of normalized raw_content
  - Check against PostgreSQL content_hash index
  - If match -> skip immediately
- **Layer 2: NEAR-DUPLICATE** (catches reformatted/slightly edited versions)
  - MinHash with 128 permutations (via datasketch library)
  - Jaccard similarity threshold: 0.85
  - LSH index for sub-linear lookup
  - If similar -> mark as duplicate, link to original
- **Layer 3: SEMANTIC DEDUP** (catches same news from different sources)
  - Cosine similarity of document embeddings
  - Threshold: 0.92 (very high - only near-identical meaning)
  - Check only within same category + same week window
  - If similar -> mark as duplicate, keep the one from highest-authority source

### 6.2 Implementation
```python
from datasketch import MinHash, MinHashLSH
import hashlib

class DeduplicationEngine:
    def __init__(self, threshold: float = 0.85, num_perm: int = 128):
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)

    def compute_exact_hash(self, text: str) -> str:
        normalized = " ".join(text.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def compute_minhash(self, text: str) -> MinHash:
        m = MinHash(num_perm=self.num_perm)
        words = text.lower().split()
        for i in range(len(words) - 2):
            shingle = " ".join(words[i:i+3])
            m.update(shingle.encode('utf-8'))
        return m

    async def is_duplicate(self, doc: RawDocument) -> tuple[bool, str | None]:
        """Check all three layers. Returns (is_dup, duplicate_of_id)."""
        # Layer 1: Exact hash
        exact_match = await self.db.find_by_content_hash(doc.content_hash)
        if exact_match:
            return True, exact_match.id

        # Layer 2: MinHash LSH
        minhash = self.compute_minhash(doc.raw_content)
        similar_ids = self.lsh.query(minhash)
        if similar_ids:
            return True, similar_ids[0]

        # Register in LSH for future checks
        self.lsh.insert(doc.content_hash, minhash)
        return False, None
```

# 7. PROCESSING PIPELINE

### 7.1 Pipeline Steps (in order)
1. Ingest RawDocument
2. Exact Hash Dedup (Layer 1)
3. Text Cleaning (HTML/PDF -> Plain Text)
4. LLM Classification (Category, Tags, Regions)
5. NER (Entity extraction: departments, dates, schemes)
6. MinHash Dedup (Layer 2)
7. Chunking (Semantic boundaries)
8. Embedding Generation (Dense + Sparse)
9. Semantic Dedup (Layer 3)
10. Store in DB (PG + Qdrant)
