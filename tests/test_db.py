from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from db import Activity, calculate_daily_score, connect, get_sync_state, init_db, set_sync_state, upsert_activity


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "glitchslate.db"
        self.conn = connect(self.db_path)
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

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

    def test_scoring_is_idempotent_on_same_day(self) -> None:
        upsert_activity(
            self.conn,
            Activity(
                source="telegram",
                external_id="1",
                timestamp=datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc),
                activity_type="yoga",
                duration_minutes=30,
            ),
        )
        first = calculate_daily_score(self.conn, today=date(2026, 7, 13))
        second = calculate_daily_score(self.conn, today=date(2026, 7, 13))
        self.assertEqual(first.score, second.score)
        self.assertEqual(second.score, 100)
        self.assertEqual(second.streak_days, 1)

    def test_scoring_applies_cumulative_missed_day_decay(self) -> None:
        self.conn.execute(
            "INSERT INTO daily_state (date, score, streak_days) VALUES (?, ?, ?)",
            ("2026-07-10", 100, 3),
        )
        self.conn.commit()
        score = calculate_daily_score(self.conn, today=date(2026, 7, 13))
        self.assertEqual(score.score, 55)
        self.assertEqual(score.streak_days, 0)


if __name__ == "__main__":
    unittest.main()
