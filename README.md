# AI Pulse — backend

Short, readable news cards from outlets chosen for editorial independence.
Pick a region, swipe through the day, tap a card for the detail.

This repository is the ingestion pipeline and API. The mobile app lives in
[ai-pulse-app](https://github.com/bhavik-mangla/ai-pulse-app).

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

---

## What it does

Every couple of hours it reads a set of RSS feeds, extracts the full article
text, has an LLM write a two-sentence summary plus a few key details,
deduplicates stories that several outlets are carrying, and serves the result
as JSON.

**It runs entirely on free tiers.** GitHub Actions for the scheduled work,
Vercel for the API, a free Postgres. There is no server to administer, and that
constraint shapes most of the design — see
[docs/architecture.md](docs/architecture.md).

## Regions and sources

| Region | Outlets |
|---|---|
| 🌍 World | BBC News, France 24, DW |
| 🇮🇳 India | The Hindu, Indian Express, Economic Times, Mint, Business Standard |
| 🇺🇸 United States | NPR, PBS NewsHour, CBS News, ABC News |

Outlets are selected on one rule: **prefer structural editorial independence** —
public broadcasters operating under an independence charter, and papers with a
straight-news reporting record. Outlets whose ownership or funding gives a
documented editorial steer are excluded, as is anyone running paid content.

Wire services would be ideal, but Reuters and AP have both retired their public
RSS feeds.

Disagree with a call? [Open an issue](../../issues/new?template=new_source.yml).
It is a judgement, and it should be arguable.

## Getting started

You need Python 3.12 and PostgreSQL. **You do not need an API key.**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .

cp .env.example .env        # set DATABASE_URL
alembic upgrade head
python scripts/sync_sources.py

# Run the pipeline against a model on your own machine
ollama serve & ollama pull llama3.2:3b
LLM_PROVIDER=local LOCAL_LLM_MODEL=llama3.2:3b python scripts/run_github_ingestion.py

# Serve the API
uvicorn govnotify.main:app --reload --app-dir src
```

Docs at `/docs` once it is running.

## Contributing

**Adding a news source is usually one entry in one list**, and it is the most
useful thing you can do here. [docs/adding-a-source.md](docs/adding-a-source.md)
walks through checking a feed works and whether an outlet fits.

Other good places to start:

- An outlet's feed has died, or its standards have changed — both are worth an
  issue
- The summary prompt in `processing/enricher.py` decides what every card says
- A region we do not carry yet

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, and read
[docs/architecture.md](docs/architecture.md) before a larger change.

## Useful commands

```bash
python scripts/check_feed.py <url>     # is this feed usable?
python scripts/check_feed.py --all     # re-check every configured feed
python scripts/sync_sources.py         # reconcile sources into the database
python -m unittest discover -s src/govnotify/tests -t src
```

## Things that will surprise you

- **Sources live in the database.** Ingestion reads its work list from the
  `sources` table, so adding a feed in code does nothing until
  `scripts/sync_sources.py` runs.
- **The package is called `govnotify`.** The project started as an Indian
  government notification aggregator and pivoted to general news. The rename is
  outstanding.
- **Use an instruction-tuned local model, not a reasoning one.** Reasoning
  models answer a request for JSON with paragraphs of deliberation. Measured on
  the same article: `qwen3:4b` took **141.6s**, `llama3.2:3b` took **9.1s**.

## Licence

MIT — see [LICENSE](LICENSE).
