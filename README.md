# GovNotify India

**GovNotify** is a production-grade, extensible platform that ingests official Indian government notifications from dozens of sources, deduplicates and enriches them, and delivers daily plain-language category digests to users via email, web, WhatsApp, and Telegram.

## Mission
To ensure Indian citizens never miss critical government notifications (jobs, schemes, tax changes, health orders) by providing a unified, filtered, and simplified daily digest.

## Key Features
- **Multi-Source Ingestion:** RSS, Web Scraping, APIs, and PDF parsing.
- **NLP Pipeline:** AI-powered classification, summarization (English & Hindi), and entity extraction.
- **Smart Deduplication:** Three-layer check (exact, near-duplicate, and semantic).
- **Hybrid Search:** RAG (Retrieval-Augmented Generation) with dense and sparse embeddings.
- **Flexible Delivery:** Daily digests via multiple channels.

## Tech Stack
- **Backend:** FastAPI, Python 3.12
- **Task Queue:** Celery, Redis
- **Databases:** PostgreSQL (Relational), Qdrant (Vector)
- **AI/LLM:** LiteLLM (Gemini, GPT-4o), FastEmbed
- **Crawling:** Crawl4AI, feedparser

## Quick Start
```bash
# Clone the repository
git clone https://github.com/your-repo/govnotify.git
cd govnotify

# Set up environment variables
cp .env.example .env
# Edit .env with your API keys

# Start the stack via Docker
docker-compose up -d
```

## License
Apache 2.0
