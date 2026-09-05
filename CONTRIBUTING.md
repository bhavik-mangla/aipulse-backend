# Contributing

Thanks for considering it. This is a small project and contributions of any
size are welcome, including ones that just point out that something is wrong.

## The quickest useful contributions

- **[Add a news source](docs/adding-a-source.md).** Usually one entry in one
  list. The guide covers how to check a feed works and which outlets fit.
- **Report an outlet that has gone bad.** Feeds die quietly, and an outlet's
  editorial standards can change. Both are worth an issue.
- **Improve a summary prompt.** The prompt in `processing/enricher.py` decides
  what every card says. Better wording there improves the whole app.

## Running it locally

You need Python 3.12 and a PostgreSQL database. You do **not** need an API key.

```bash
git clone https://github.com/bhavik-mangla/aipulse-backend
cd aipulse-backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .

cp .env.example .env        # set DATABASE_URL
alembic upgrade head
python scripts/sync_sources.py
```

### Running without a Gemini key

The pipeline can run against a model on your own machine, so nobody needs to
spend quota to contribute:

```bash
ollama serve &
ollama pull llama3.2:3b

export LLM_PROVIDER=local
export LOCAL_LLM_MODEL=llama3.2:3b
python scripts/run_github_ingestion.py
```

Anything with an OpenAI-compatible API works — Ollama, LM Studio, llama.cpp.
Set `LOCAL_LLM_BASE_URL` if it is not on `http://localhost:11434`.

**Pick an instruction-tuned model, not a reasoning one.** Reasoning models
answer a request for JSON with paragraphs of visible deliberation. We measured
`qwen3:4b` taking 145 seconds for a single article and failing to produce
usable JSON at all, against a few seconds for `llama3.2:3b`.

You can also set `ENABLE_LLM=false` to skip summarization entirely. Ingestion
still runs and falls back to an extractive summary, which is enough for working
on crawling or the API.

### Useful commands

```bash
python scripts/check_feed.py <url>        # is this feed usable?
python scripts/check_feed.py --all        # re-check every configured feed
python scripts/sync_sources.py            # reconcile sources into the database
python -m unittest discover -s src/govnotify/tests -t src
```

## How the pieces fit

See [docs/architecture.md](docs/architecture.md). The short version: GitHub
Actions runs ingestion on a schedule, which reads RSS feeds, extracts article
text, summarizes it with an LLM, deduplicates, and writes to Postgres. A
FastAPI app on Vercel serves that to the mobile app. There is no server to
run and no paid infrastructure.

## Pull requests

- Branch off `main`. Please do not commit directly to it.
- Say what you changed and why. If you fixed a bug, say what the bug did.
- Include evidence that it works — command output, a screenshot, whatever
  suits. For a new source, include the `check_feed.py` output.
- Match the surrounding style. Comments explain *why*; the code already says
  what.
- Keep unrelated changes in separate pull requests.

Do not worry about getting this perfect. A working change with a clear
description is better than a polished one that never gets opened.

## Things worth knowing before you dig in

- **Sources live in the database, not in code at runtime.** Ingestion reads its
  work list from the `sources` table. Adding a feed in code does nothing until
  `scripts/sync_sources.py` syncs it.
- **The Python package is still called `govnotify`.** The project began as an
  Indian government notification aggregator and pivoted to general news. The
  rename is outstanding; it is a large mechanical diff and has not been worth
  the churn yet.
- **The free Gemini tier is the binding constraint.** It is why there are
  twelve sources rather than fifty, why they run on staggered schedules, and
  why article text is truncated before summarization. Anything that multiplies
  LLM calls needs to account for that.
- **Deduplication thresholds are calibrated against real data**, not guessed.
  If you change them, measure against real articles; the values in
  `processing/dedup.py` document what was measured.

## Reporting a security issue

Please do not open a public issue. Email the maintainer instead, and give a
reasonable window to respond before disclosing.

## Code of conduct

Be decent to each other. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
