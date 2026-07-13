from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from config import ScoringConfig
from db import (
    Activity,
    calculate_daily_score,
    connect,
    current_gap_days,
    get_cached_sentient_log,
    get_sync_state,
    init_db,
    minutes_for_day,
    rolling_window_minutes,
    set_cached_sentient_log,
    set_sync_state,
    upsert_activity,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "glitchslate.db"
        self.conn = connect(self.db_path)
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def add_activity(self, external_id: str, day: int, minutes: int) -> None:
        upsert_activity(
            self.conn,
            Activity(
                source="telegram",
                external_id=external_id,
                timestamp=datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc),
                activity_type="workout",
                duration_minutes=minutes,
            ),
        )

    def test_init_creates_tables(self) -> None:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        names = {row["name"] for row in rows}
        self.assertIn("activities", names)
        self.assertIn("daily_state", names)
        self.assertIn("sync_state", names)

    def test_activity_upsert_is_idempotent_for_source_and_external_id(self) -> None:
        activity = Activity(
            source="telegram",
            external_id="42",
            timestamp=datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc),
            activity_type="strength",
            duration_minutes=30,
        )
        upsert_activity(self.conn, activity)
        upsert_activity(self.conn, activity)
        count = self.conn.execute("SELECT COUNT(*) AS count FROM activities").fetchone()["count"]
        self.assertEqual(count, 1)

    def test_sync_state_roundtrip(self) -> None:
        set_sync_state(self.conn, "telegram_last_update_id", 123)
        self.assertEqual(get_sync_state(self.conn, "telegram_last_update_id"), "123")

    def test_rolling_score_is_idempotent_on_same_day(self) -> None:
        self.add_activity("1", 13, 30)
        first = calculate_daily_score(self.conn, today=date(2026, 7, 13))
        second = calculate_daily_score(self.conn, today=date(2026, 7, 13))
        self.assertEqual(first.score, second.score)
        self.assertEqual(second.score, 50)
        self.assertEqual(second.recent_minutes, 30)
        self.assertEqual(second.expected_recent_minutes, 60)
        self.assertEqual(second.streak_days, 1)

    def test_rolling_score_caps_at_100_when_recent_minutes_exceed_target(self) -> None:
        self.add_activity("1", 13, 120)
        score = calculate_daily_score(self.conn, today=date(2026, 7, 13))
        self.assertEqual(score.score, 100)
        self.assertEqual(score.recent_minutes, 120)

    def test_rolling_score_deteriorates_after_five_inactive_days(self) -> None:
        self.add_activity("1", 7, 60)
        score = calculate_daily_score(self.conn, today=date(2026, 7, 13))
        self.assertEqual(score.score, 0)
        self.assertEqual(score.recent_minutes, 0)
        self.assertEqual(score.streak_days, 0)

    def test_rolling_score_uses_30_day_baseline_when_above_minimum(self) -> None:
        config = ScoringConfig(recent_window_days=5, baseline_window_days=30, min_expected_5_day_minutes=60)
        for offset, day in enumerate(range(14, 19), start=1):
            self.add_activity(f"old-{offset}", day, 60)
        self.add_activity("recent", 28, 50)
        score = calculate_daily_score(self.conn, today=date(2026, 7, 28), scoring_config=config)
        self.assertEqual(score.recent_minutes, 50)
        self.assertAlmostEqual(score.baseline_daily_minutes, 350 / 30)
        self.assertAlmostEqual(score.expected_recent_minutes, 60)
        self.assertEqual(score.score, 83)

    def test_gap_days_and_minutes_for_day(self) -> None:
        self.add_activity("a", 10, 30)
        self.assertEqual(minutes_for_day(self.conn, date(2026, 7, 10)), 30)
        self.assertEqual(minutes_for_day(self.conn, date(2026, 7, 11)), 0)
        self.assertEqual(current_gap_days(self.conn, end_day=date(2026, 7, 10)), 0)
        self.assertEqual(current_gap_days(self.conn, end_day=date(2026, 7, 12)), 2)

    def test_sentient_log_cache_roundtrip(self) -> None:
        set_cached_sentient_log(
            self.conn,
            day="2026-07-13",
            score=80,
            streak_days=2,
            today_minutes=30,
            text="Systems nominal.",
        )
        self.assertEqual(
            get_cached_sentient_log(
                self.conn,
                day="2026-07-13",
                score=80,
                streak_days=2,
                today_minutes=30,
            ),
            "Systems nominal.",
        )
        self.assertIsNone(
            get_cached_sentient_log(
                self.conn,
                day="2026-07-13",
                score=79,
                streak_days=2,
                today_minutes=30,
            )
        )

    def test_rolling_window_minutes_handles_sparse_activity(self) -> None:
        self.add_activity("a", 10, 30)
        self.add_activity("b", 13, 20)
        points = rolling_window_minutes(self.conn, end_day=date(2026, 7, 13), point_count=5, window_days=5)
        self.assertEqual([day for day, _ in points], [
            "2026-07-09",
            "2026-07-10",
            "2026-07-11",
            "2026-07-12",
            "2026-07-13",
        ])
        self.assertEqual([minutes for _, minutes in points], [0, 30, 30, 30, 50])

    def test_dry_run_score_does_not_persist_daily_state(self) -> None:
        self.add_activity("1", 13, 30)
        score = calculate_daily_score(self.conn, today=date(2026, 7, 13), persist=False)
        self.assertEqual(score.score, 50)
        row = self.conn.execute("SELECT COUNT(*) AS count FROM daily_state").fetchone()
        self.assertEqual(row["count"], 0)


if __name__ == "__main__":
    unittest.main()
