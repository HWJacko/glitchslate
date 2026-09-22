from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, date
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from db import connect, init_db
from social_sync import parse_bluesky_rss, social_snapshot_metric, sync_bluesky_posts


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <link>https://bsky.app/profile/example/post/latest</link>
  <description>Latest post</description>
  <pubDate>10 Sep 2026 11:22 +0000</pubDate>
  <guid isPermaLink="false">at://did:example/app.bsky.feed.post/latest</guid>
</item>
<item>
  <link>https://bsky.app/profile/example/post/older</link>
  <description>Older post</description>
  <pubDate>08 Sep 2026 09:00 +0000</pubDate>
  <guid isPermaLink="false">at://did:example/app.bsky.feed.post/older</guid>
</item>
</channel></rss>
"""


class SocialSyncTests(unittest.TestCase):
    def test_parse_bluesky_rss_extracts_posts_in_newest_order(self) -> None:
        posts = parse_bluesky_rss(RSS)

        self.assertEqual([post.id for post in posts], [
            "at://did:example/app.bsky.feed.post/latest",
            "at://did:example/app.bsky.feed.post/older",
        ])
        self.assertEqual(posts[0].published_at.tzinfo, UTC)

    def test_sync_bluesky_posts_records_social_activity_and_reminder_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "glitchslate.db")
            init_db(conn)
            with patch("social_sync.fetch_bluesky_posts", return_value=parse_bluesky_rss(RSS)):
                snapshot = sync_bluesky_posts(
                    conn,
                    url="https://example.invalid/rss",
                    today=date(2026, 9, 14),
                    tz=ZoneInfo("Europe/London"),
                    reminder_after_days=4,
                    post_points=750,
                )

            rows = conn.execute("SELECT source, activity_type, points FROM activities ORDER BY timestamp").fetchall()
            metric = social_snapshot_metric(snapshot)

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["source"], "social")
            self.assertEqual(rows[0]["activity_type"], "bluesky_post")
            self.assertEqual(rows[0]["points"], 750)
            self.assertTrue(snapshot.reminder_due)
            self.assertIsNotNone(metric)
            assert metric is not None
            self.assertEqual(metric.value, "4D AGO")
            self.assertEqual(metric.status, "REMINDER")
            conn.close()


if __name__ == "__main__":
    unittest.main()
