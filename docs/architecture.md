# Architecture

The whole system runs on free tiers and has no server to administer. That
constraint shapes most of the design decisions below.

```
      GitHub Actions (cron)                    Vercel                Mobile app
┌──────────────────────────────┐        ┌────────────────┐        ┌────────────┐
│ migrate → sync sources →     │        │  FastAPI       │        │ Capacitor  │
│ ingest                       │───────▶│  /api/v1/...   │◀───────│  WebView   │
│                              │  write │                │  JSON  │            │
│ RSS → extract → summarize →  │        └────────┬───────┘        └────────────┘
│ dedupe → store               │                 │
└──────────────┬───────────────┘                 │
               │                                 │
               ▼                                 ▼
          ┌─────────────────────────────────────────┐
          │            PostgreSQL                    │
          │   sources · documents · ingest_log       │
          └─────────────────────────────────────────┘
```

## Ingestion

`scripts/run_github_ingestion.py`, run by `.github/workflows/ingest.yml`.

The workflow ticks every 30 minutes, but each source carries its own cron
window and is only picked up when due. Sources are staggered across four
windows every two hours, because a top-stories feed publishes a few dozen items
a day and re-reading it more often gains nothing while costing LLM calls.

Per source:

1. **Read the feed** (`crawlers/robust_news_crawler.py`). Uses `curl_cffi` to
   impersonate a real browser, since several outlets reject plain HTTP clients.
2. **Filter duplicates before extraction**, so a story we already have costs no
   page fetch at all.
3. **Extract article text**, five articles concurrently behind a semaphore,
   capped at 25 articles per feed per run. Both limits exist because extraction
   was previously serial and unbounded: one feed returning 200 items meant 200
   fetches and 200 LLM calls in a single run.
4. **Summarize** (`processing/enricher.py`) into a structured JSON card:
   quick take, key details, topic, significance, and an entity to search for an
   image.
5. **Resolve an image** (`processing/image_resolver.py`): the article's own
   `og:image` first, then Wikipedia, then image search, then a bundled logo.
6. **Deduplicate** (`processing/dedup.py`) and store.

## Deduplication

The interesting part. Several outlets carry the same story, and a reader who
sees it four times stops trusting the feed.

One engine is shared across all sources in a run and seeded from a seven-day
window of already-stored documents, so detection spans runs rather than being
rebuilt and thrown away per source.

Four layers, cheapest first:

| Layer | Catches |
|---|---|
| Exact content hash | The identical article seen again |
| Title + source in Postgres | A re-publish under the same headline |
| SimHash, Hamming ≤ 7 | Near-identical bodies — one wire story syndicated to several outlets |
| Title token overlap, Jaccard ≥ 0.35 | The same event written up independently |

Both similarity layers are **indexed rather than scanned**: SimHash by banding
(two hashes within distance 7 must share one of eight 8-bit bands, by the
pigeonhole principle), titles by an inverted token index. Lookup cost stays
roughly flat as sources are added.

The thresholds were measured, not chosen. Across 28,680 title pairs from the
live feed, every pair scoring 0.30 or above was a genuine duplicate and no
false positive appeared in that range. For bodies, a syndicated copy measured a
distance of 7 while an independent rewrite of the same event measured 30.

What this does **not** catch is genuinely independent long-form on the same
topic. That needs semantic similarity, which is not implemented.

## API

FastAPI on Vercel serverless (`api/index.py` → `src/govnotify/main.py`).

- `GET /api/v1/feed/latest` — the feed, scoped by `country`, filtered by
  `categories`, `source_id`, `date`, `impact_level`
- `GET /api/v1/feed/search` — same filters plus `q`
- `GET /api/v1/feed/{id}` — one document in full
- `GET /api/v1/config/metadata` — regions, topics, tiers
- `GET /api/v1/config/sources` — outlets, optionally for one region

Responses carry `Cache-Control` so Vercel's edge absorbs most traffic. Pass
`include_total=false` to skip the count query when you are not paginating.

## Feed scopes

Every document belongs to a scope: `world`, `in` or `us`. This is what a reader
picks in the app.

It also quietly does a second job. The project began as an Indian government
notification aggregator; those documents are still in the database with a NULL
country. Every feed query filters on country, so they match no scope and are
invisible in the app without a single row having been deleted.

## Storage

PostgreSQL, three tables:

- **`sources`** — the ingestion work list. Not read from code at runtime:
  `scripts/sync_sources.py` reconciles the registry in code into this table,
  and retired sources are disabled rather than deleted, because documents carry
  a foreign key to their source.
- **`documents`** — articles, summaries and dedup hashes.
- **`ingest_log`** — one row per source per run, for debugging.

## LLM access

`processing/llm_router.py`, via litellm.

Two providers. `gemini` spreads calls across every configured key and falls
back down a chain of models as each is rate limited. `local` talks to an
OpenAI-compatible server on your own machine, needs no key, and is what makes
the pipeline runnable by anyone who clones the repository.

The free Gemini tier is the binding constraint on the whole project. It is why
there are twelve sources rather than fifty, why schedules are staggered, why
article text is truncated to 8,000 characters, and why per-article translation
was dropped.

## Known rough edges

- The Python package is still named `govnotify`.
- `src/govnotify/tasks/` holds a Celery setup that is unreachable in the
  production path but still referenced by `docker-compose.yml` for self-hosting.
- `documents.summary_hindi` and `documents.affected_audience` are retained but
  no longer written, so historical rows stay readable.
