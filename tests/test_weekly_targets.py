from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from dataclasses import replace
from pathlib import Path

from config import app_config_from_dict
from db import Activity, connect, init_db, upsert_activity
from telegram_sync import sync_telegram
from weekly_targets import (
    format_weekly_targets,
    next_target_priority,
    set_weekly_target,
    target_baseline_points,
    target_chart_points,
    weekly_target_progress,
)


class WeeklyTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmpdir.name) / "targets.db")
        init_db(self.conn)
        self.defaults = app_config_from_dict(
            {
                "targets": {
                    "enabled": True,
                    "defaults": [
                        {"key": "run", "label": "RUN", "target": 20, "unit": "km", "metric": "distance_km"},
                        {"key": "cindy", "label": "CINDY", "target": 3, "unit": "sessions", "metric": "cindy_sessions"},
                        {"key": "short_story", "label": "SHORT STORY", "target": 1000, "unit": "words", "metric": "writing_words"},
                        {"key": "main_project", "label": "MAIN PROJECT", "target": 1000, "unit": "words", "metric": "writing_words"},
                        {"key": "social", "label": "SOCIALS", "target": 2, "unit": "posts", "metric": "social_posts"},
                        {"key": "non_fiction", "label": "NON-FICTION", "target": 200, "unit": "words", "metric": "writing_words"},
                    ],
                }
            }
        ).targets.defaults
        self.today = date(2026, 9, 16)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def test_defaults_seed_and_manual_change_carries_to_next_week(self) -> None:
        first = weekly_target_progress(self.conn, self.defaults, today=self.today)
        self.assertEqual([(item.key, item.target) for item in first], [
            ("run", 20.0),
            ("cindy", 3.0),
            ("short_story", 1000.0),
            ("main_project", 1000.0),
            ("social", 2.0),
            ("non_fiction", 200.0),
        ])
        set_weekly_target(
            self.conn,
            self.defaults,
            key="socials",
            target=4,
            week_start=date(2026, 9, 14),
        )
        next_week = weekly_target_progress(self.conn, self.defaults, today=date(2026, 9, 23))
        self.assertEqual(next(item.target for item in next_week if item.key == "social"), 4.0)

    def test_progress_uses_run_distance_cindy_words_and_social_posts(self) -> None:
        upsert_activity(
            self.conn,
            Activity(
                source="strava",
                external_id="run",
                timestamp=datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc),
                activity_type="run",
                duration_minutes=30,
                raw_payload={"distance": 12_500},
            ),
        )
        for external_id in ("cindy-1", "cindy-2"):
            upsert_activity(
                self.conn,
                Activity(
                    source="telegram",
                    external_id=external_id,
                    timestamp=datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc),
                    activity_type="bodyweight",
                    duration_minutes=20,
                    notes="CINDY 10 rounds",
                ),
            )
        for key, activity_type, words in (
            ("short", "short_story", 600),
            ("main", "main_project", 250),
            ("nf", "non_fiction", 125),
        ):
            upsert_activity(
                self.conn,
                Activity(
                    source="writing",
                    external_id=key,
                    timestamp=datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc),
                    activity_type=activity_type,
                    duration_minutes=0,
                    points=words,
                    raw_payload=json.dumps({"day_words": words}),
                ),
            )
        upsert_activity(
            self.conn,
            Activity(
                source="social",
                external_id="post",
                timestamp=datetime(2026, 9, 16, 11, 0, tzinfo=timezone.utc),
                activity_type="bluesky_post",
                duration_minutes=0,
                points=1000,
            ),
        )

        progress = {item.key: item for item in weekly_target_progress(self.conn, self.defaults, today=self.today)}
        self.assertEqual(progress["run"].value, 12.5)
        self.assertEqual(progress["cindy"].value, 2)
        self.assertEqual(progress["short_story"].value, 600)
        self.assertEqual(progress["main_project"].value, 250)
        self.assertEqual(progress["social"].value, 1)
        self.assertEqual(progress["non_fiction"].value, 125)
        self.assertIn("RUN: 12.5/20 km (62%)", format_weekly_targets(progress.values()))

    def test_target_chart_uses_normalized_points_and_baseline(self) -> None:
        upsert_activity(
            self.conn,
            Activity(
                source="writing",
                external_id="short",
                timestamp=datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc),
                activity_type="short_story",
                duration_minutes=0,
                points=1000,
                raw_payload={"day_words": 1000},
            ),
        )
        chart = target_chart_points(
            self.conn,
            self.defaults,
            end_day=self.today,
            point_count=1,
            window_days=3,
        )
        self.assertEqual(chart[0]["bucket_points"], {"short_story": 1000})
        self.assertEqual(chart[0]["total_points"], 1000)
        self.assertAlmostEqual(target_baseline_points(6, window_days=3), 2057.142857, places=5)

    def test_next_priority_flags_target_with_no_contribution(self) -> None:
        progress = weekly_target_progress(self.conn, self.defaults, today=self.today)
        progress = [
            replace(item, value=1 if item.key != "short_story" else 0)
            for item in progress
        ]
        priority = next_target_priority(progress, today=date(2026, 9, 16))
        self.assertIsNotNone(priority)
        self.assertIn("SHORT STORY", priority or "")
        self.assertIn("no contribution yet", priority or "")

    def test_telegram_target_command_updates_central_target_and_replies(self) -> None:
        replies = []

        def request_get(url, params, timeout):
            return {
                "ok": True,
                "result": [{
                    "update_id": 100,
                    "message": {
                        "message_id": 200,
                        "date": 1789545600,
                        "from": {"id": 123},
                        "chat": {"id": 123},
                        "text": "/target run 25km",
                    },
                }],
            }

        def request_post(url, data, timeout):
            replies.append((url, data, timeout))
            return {"ok": True}

        count = sync_telegram(
            self.conn,
            token="token",
            allowed_user_id=123,
            parser=lambda text: {},
            request_get=request_get,
            request_post=request_post,
            target_defaults=self.defaults,
        )
        self.assertEqual(count, 0)
        current = weekly_target_progress(self.conn, self.defaults, today=date(2026, 9, 16))
        self.assertEqual(next(item.target for item in current if item.key == "run"), 25)
        self.assertEqual(len(replies), 1)
        self.assertIn("RUN target set to 25 km", replies[0][1]["text"])


if __name__ == "__main__":
    unittest.main()
