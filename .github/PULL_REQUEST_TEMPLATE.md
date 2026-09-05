## What does this change?

<!-- If it fixes a bug, say what the bug did. -->

## Why?

## Evidence it works

<!--
Command output, a screenshot, whatever suits.
Adding a source? Paste the `python scripts/check_feed.py <url>` output and a
couple of summaries the pipeline produced for that outlet.
-->

## Checklist

- [ ] Ran the tests (`python -m unittest discover -s src/govnotify/tests -t src`)
- [ ] Added a source? Updated `SOURCE_NAMES` in `constants.py` too
- [ ] Changed the schema? Included an Alembic migration
- [ ] Anything that changes per-article LLM calls is noted above
