from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from db import Activity, connect, init_db, upsert_activity
from scripts.telegram_archive_collector import cleanup_old_files
from telegram_archive import fetch_remote_archive_days, sync_telegram_archive_for_blank_days, telegram_blank_days


class TelegramArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmpdir.name) / "test.db")
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def test_blank_days_excludes_existing_telegram_days_and_today(self) -> None:
        upsert_activity(
            self.conn,
            Activity(
                source="telegram",
                external_id="existing",
                timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
                activity_type="workout",
                duration_minutes=10,
            ),
        )

        days = telegram_blank_days(self.conn, today=date(2026, 7, 20), lookback_days=3)

        self.assertEqual(days, ["2026-07-17", "2026-07-19"])

    def test_fetch_remote_archive_days_reads_only_requested_day_files(self) -> None:
        update = {"update_id": 12, "message": {"message_id": 7, "from": {"id": 123}, "text": "20 pressups"}}

        def runner(args, **kwargs):
            self.assertEqual(args[0], "ssh")
            self.assertIn("2026-07-18", args[-1])
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(update) + "\n")

        updates = fetch_remote_archive_days(
            ["2026-07-18"],
            ssh_target="glitchslate@example",
            remote_dir="glitchslate-telegram-inbox",
            runner=runner,
        )

        self.assertEqual(updates, [update])

    def test_archive_sync_processes_remote_updates_for_blank_days(self) -> None:
        update = {
            "update_id": 12,
            "message": {
                "message_id": 7,
                "date": int(datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo("Europe/London")).timestamp()),
                "from": {"id": 123},
                "text": "20 pressups",
            },
        }

        def runner(args, **kwargs):
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(update) + "\n")

        def parser(text):
            self.assertEqual(text, "20 pressups")
            return {
                "is_workout": True,
                "activity_type": "bodyweight",
                "duration_minutes": 5,
                "intensity": "moderate",
                "notes": text,
                "exercises": [
                    {
                        "movement": "pressups",
                        "sets": 1,
                        "reps_per_set": 20,
                        "total_reps": 20,
                        "weight_kg": 0,
                        "bodyweight": True,
                        "movement_multiplier": 1,
                    }
                ],
            }

        result = sync_telegram_archive_for_blank_days(
            self.conn,
            allowed_user_id=123,
            ssh_target="glitchslate@example",
            remote_dir="glitchslate-telegram-inbox",
            lookback_days=1,
            parser=parser,
            timezone_name="Europe/London",
            today=date(2026, 7, 19),
            runner=runner,
        )

        row = self.conn.execute("SELECT external_id, local_date, points FROM activities").fetchone()
        self.assertEqual(result.fetched_updates, 1)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(row["external_id"], "7")
        self.assertEqual(row["local_date"], "2026-07-18")
        self.assertEqual(row["points"], 60)

    def test_archive_sync_does_not_ssh_when_no_blank_days(self) -> None:
        upsert_activity(
            self.conn,
            Activity(
                source="telegram",
                external_id="existing",
                timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
                activity_type="workout",
                duration_minutes=10,
            ),
        )

        def runner(args, **kwargs):
            raise AssertionError("SSH should not be called without blank days")

        result = sync_telegram_archive_for_blank_days(
            self.conn,
            allowed_user_id=123,
            ssh_target="glitchslate@example",
            remote_dir="glitchslate-telegram-inbox",
            lookback_days=1,
            parser=lambda text: {},
            timezone_name="Europe/London",
            today=date(2026, 7, 19),
            runner=runner,
        )

        self.assertEqual(result.checked_days, [])
        self.assertEqual(result.fetched_updates, 0)
        self.assertEqual(result.inserted, 0)

    def test_collector_archives_allowed_text_and_removes_old_files(self) -> None:
        inbox = Path(self.tmpdir.name) / "inbox"
        old_file = inbox / "2026-06-01.jsonl"
        old_file.parent.mkdir()
        old_file.write_text("{}\n", encoding="utf-8")

        removed = cleanup_old_files(inbox, retention_days=28, today=date(2026, 7, 20))
        self.assertEqual(removed, 1)
        self.assertFalse(old_file.exists())


if __name__ == "__main__":
    unittest.main()
