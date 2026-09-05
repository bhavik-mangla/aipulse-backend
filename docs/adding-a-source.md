# Adding a news source

Adding an outlet is the most useful contribution you can make, and it is a
small one: for most outlets it is a single entry in a list. This guide covers
the whole path, including how to check an outlet is a reasonable fit before you
spend time on it.

## 1. Check the feed actually works

Most of the effort in adding a source goes into discovering that its RSS feed is
dead. Check first. Reuters and AP, for example, both retired their public feeds
and now return 401 and 404.

```bash
python scripts/check_feed.py https://feeds.bbci.co.uk/news/rss.xml
```

You want to see items, publication dates, and ideally per-item images. A feed
without dates still works, but articles will be ordered by when we ingested
them rather than when they were published.

## 2. Check the outlet fits

We are not trying to carry everything. The selection rule is:

**Prefer outlets whose editorial independence is structural** — public
broadcasters operating under an independence charter, and papers with a
straight-news reporting record.

**Exclude** outlets whose ownership or funding gives a documented editorial
steer, and any outlet with a documented paid-content practice.

This rules out some outlets that report perfectly well. It is a deliberate
trade: a reader opening a short-news app cannot evaluate each story's framing
for themselves, so the selection has to do that work.

Wire services (Reuters, AP, AFP, PTI) are the ideal and are welcome whenever
they are actually reachable.

If you are not sure, open an issue with the
[new source template](https://github.com/bhavik-mangla/aipulse-backend/issues/new?template=new_source.yml)
before writing code. Disagreement about an outlet is better had in an issue
than in a pull request.

## 3. Add it

Sources live in one list in `src/govnotify/sources/news_rss_source.py`:

```python
NEWS_FEEDS = [
    {
        "id": "bbc_world",              # unique; convention is <outlet>_<scope>
        "name": "BBC News",             # shown on the card
        "country": Country.WORLD.value, # world | in | us
        "url": "https://feeds.bbci.co.uk/news/rss.xml",
    },
    ...
]
```

Add the display name to `SOURCE_NAMES` in `src/govnotify/constants.py` too.
A test asserts the two stay in step, so you will be told if you forget.

### Adding a new country

If your outlet is from a country we do not carry yet, add it to `Country` and
`COUNTRIES` in `src/govnotify/constants.py`. A scope with fewer than about
three outlets feels thin, so it is usually worth adding a few at once.

Be aware of the cost: every source consumes LLM calls on every run, and the
project runs on the Gemini free tier. If you are adding a scope, say so in the
pull request so we can look at the quota together.

## 4. Run it

Sources are stored in the database, not read from code at runtime, so a new
entry does nothing until it is synced:

```bash
python scripts/sync_sources.py     # reconcile code into the sources table
python scripts/run_github_ingestion.py
```

You do **not** need a Gemini API key. Point the pipeline at a local model
instead:

```bash
export LLM_PROVIDER=local
export LOCAL_LLM_MODEL=qwen3:4b     # or any model you have pulled
ollama serve &
ollama pull qwen3:4b
```

Anything exposing an OpenAI-compatible API works — Ollama, LM Studio,
llama.cpp. Set `LOCAL_LLM_BASE_URL` if it is not on `http://localhost:11434`.

## 5. What to include in the pull request

- The feed check output from step 1.
- A sentence on why the outlet meets the selection rule.
- A couple of example summaries the pipeline produced, so we can see the
  extraction works on that site's article markup. Some sites need a different
  extraction path, and this is where that shows up.

## When an outlet needs more than an RSS entry

Some sites block extraction, or publish a feed with headlines but no article
body. The crawler already impersonates a browser via `curl_cffi` and falls back
to the feed's own summary when full extraction fails, which handles most cases.

If an outlet needs genuinely different handling, subclass `NewsRSSSource` and
override `_build_document`. Please open an issue first — if a site needs custom
code, it is worth checking whether it is the right outlet to carry at all.
