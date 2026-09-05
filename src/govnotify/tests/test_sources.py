"""
Tests guarding the source registry.

These exist mainly for contributors adding an outlet: they catch the two
mistakes that are easy to make and annoying to debug, namely forgetting the
display name and using a scope that does not exist.
"""
import unittest

from govnotify.constants import SOURCE_NAMES, Country, is_valid_country
from govnotify.sources.news_rss_source import NEWS_FEEDS, SCHEDULES
from govnotify.sources.registry import SourceRegistry


class TestNewsFeeds(unittest.TestCase):
    def test_every_feed_has_a_display_name(self):
        """A source without an entry in SOURCE_NAMES shows a slug on the card."""
        missing = [f["id"] for f in NEWS_FEEDS if f["id"] not in SOURCE_NAMES]
        self.assertEqual(
            missing,
            [],
            f"add these to SOURCE_NAMES in constants.py: {missing}",
        )

    def test_no_orphaned_display_names(self):
        """A name with no feed behind it is a leftover from a removed source."""
        feed_ids = {f["id"] for f in NEWS_FEEDS}
        orphans = [name for name in SOURCE_NAMES if name not in feed_ids]
        self.assertEqual(
            orphans,
            [],
            f"remove these from SOURCE_NAMES, they have no feed: {orphans}",
        )

    def test_feed_ids_are_unique(self):
        ids = [f["id"] for f in NEWS_FEEDS]
        duplicates = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(duplicates, set(), f"duplicate source ids: {duplicates}")

    def test_every_feed_has_a_valid_scope(self):
        for feed in NEWS_FEEDS:
            with self.subTest(source=feed["id"]):
                self.assertTrue(
                    is_valid_country(feed["country"]),
                    f"{feed['id']} has scope {feed['country']!r}, which is not in COUNTRIES",
                )

    def test_every_feed_url_is_http(self):
        for feed in NEWS_FEEDS:
            with self.subTest(source=feed["id"]):
                self.assertTrue(
                    feed["url"].startswith(("http://", "https://")),
                    f"{feed['id']} has a non-HTTP url",
                )

    def test_every_scope_has_at_least_one_source(self):
        """A region offered in the app with no outlets behind it is an empty feed."""
        scopes = {f["country"] for f in NEWS_FEEDS}
        for country in Country:
            with self.subTest(scope=country.value):
                self.assertIn(
                    country.value,
                    scopes,
                    f"{country.value} is offered to readers but has no sources",
                )

    def test_sources_register_themselves(self):
        """Importing the module should populate the registry."""
        registered = set(SourceRegistry.list_ids())
        for feed in NEWS_FEEDS:
            with self.subTest(source=feed["id"]):
                self.assertIn(feed["id"], registered)

    def test_schedules_are_staggered(self):
        """
        Sources share a small pool of cron windows so that a single ingestion
        run stays small enough to finish inside a GitHub Actions job.
        """
        self.assertGreater(len(SCHEDULES), 1)
        used = {s.source_config.schedule_cron for s in SourceRegistry.all()}
        self.assertGreater(
            len(used), 1, "every source is on the same schedule; they should be staggered"
        )


if __name__ == "__main__":
    unittest.main()
