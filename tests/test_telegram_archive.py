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
from telegram_archive import fetch_remote_archive_days, sync_telegram_archive, telegram_archive_days, telegram_blank_days


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

    def test_blank_days_can_include_today_when_archive_is_primary_receiver(self) -> None:
        days = telegram_blank_days(
            self.conn,
            today=date(2026, 7, 20),
            lookback_days=1,
            include_today=True,
        )

        self.assertEqual(days, ["2026-07-19", "2026-07-20"])

    def test_archive_days_includes_every_recent_day_for_idempotent_resync(self) -> None:
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

        days = telegram_archive_days(today=date(2026, 7, 20), lookback_days=2)

        self.assertEqual(days, ["2026-07-18", "2026-07-19", "2026-07-20"])

    def test_fetch_remote_archive_days_reads_only_requested_day_files(self) -> None:
        update = {"update_id": 12, "message": {"message_id": 7, "from": {"id": 123}, "text": "20 pressups"}}

        def runner(args, **kwargs):
            self.assertEqual(args[0], "ssh")
            self.assertEqual(len(args), 3)
            self.assertIn("sh -lc", args[-1])
            self.assertIn("2026-07-18", args[-1])
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(update) + "\n")

        updates = fetch_remote_archive_days(
            ["2026-07-18"],
            ssh_target="glitchslate@example",
            remote_dir="glitchslate-telegram-inbox",
            runner=runner,
        )

        self.assertEqual(updates, [update])

    def test_archive_sync_processes_remote_updates_for_recent_days(self) -> None:
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

        result = sync_telegram_archive(
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

    def test_archive_sync_checks_existing_days_to_find_new_same_day_messages(self) -> None:
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
        update = {
            "update_id": 13,
            "message": {
                "message_id": 8,
                "date": int(datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo("Europe/London")).timestamp()),
                "from": {"id": 123},
                "text": "10 situps",
            },
        }

        def runner(args, **kwargs):
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(update) + "\n")

        result = sync_telegram_archive(
            self.conn,
            allowed_user_id=123,
            ssh_target="glitchslate@example",
            remote_dir="glitchslate-telegram-inbox",
            lookback_days=1,
            parser=lambda text: {
                "is_workout": True,
                "activity_type": "bodyweight",
                "duration_minutes": 3,
                "intensity": "moderate",
                "notes": text,
                "exercises": [
                    {
                        "movement": "situps",
                        "sets": 1,
                        "reps_per_set": 10,
                        "total_reps": 10,
                        "weight_kg": 0,
                        "bodyweight": True,
                        "movement_multiplier": 1,
                    }
                ],
            },
            timezone_name="Europe/London",
            today=date(2026, 7, 19),
            include_today=False,
            runner=runner,
        )

        rows = self.conn.execute("SELECT external_id FROM activities ORDER BY external_id").fetchall()
        self.assertEqual(result.checked_days, ["2026-07-18"])
        self.assertEqual(result.fetched_updates, 1)
        self.assertEqual(result.inserted, 1)
        self.assertEqual([row["external_id"] for row in rows], ["8", "existing"])

    def test_archive_sync_skips_existing_message_ids_without_parsing(self) -> None:
        upsert_activity(
            self.conn,
            Activity(
                source="telegram",
                external_id="8",
                timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
                activity_type="workout",
                duration_minutes=10,
            ),
        )
        update = {
            "update_id": 13,
            "message": {
                "message_id": 8,
                "date": int(datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo("Europe/London")).timestamp()),
                "from": {"id": 123},
                "text": "10 situps",
            },
        }

        result = sync_telegram_archive(
            self.conn,
            allowed_user_id=123,
            ssh_target="glitchslate@example",
            remote_dir="glitchslate-telegram-inbox",
            lookback_days=1,
            parser=lambda text: (_ for _ in ()).throw(AssertionError("parser should not be called")),
            timezone_name="Europe/London",
            today=date(2026, 7, 19),
            include_today=False,
            runner=lambda args, **kwargs: subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(update) + "\n",
            ),
        )

        self.assertEqual(result.fetched_updates, 1)
        self.assertEqual(result.inserted, 0)

    def test_archive_sync_can_process_today_when_direct_sync_is_disabled(self) -> None:
        update = {
            "update_id": 13,
            "message": {
                "message_id": 8,
                "date": int(datetime(2026, 7, 19, 12, 0, tzinfo=ZoneInfo("Europe/London")).timestamp()),
                "from": {"id": 123},
                "text": "10 situps",
            },
        }

        def runner(args, **kwargs):
            self.assertIn("2026-07-19", args[-1])
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(update) + "\n")

        result = sync_telegram_archive(
            self.conn,
            allowed_user_id=123,
            ssh_target="glitchslate@example",
            remote_dir="glitchslate-telegram-inbox",
            lookback_days=0,
            parser=lambda text: {
                "is_workout": True,
                "activity_type": "bodyweight",
                "duration_minutes": 3,
                "intensity": "moderate",
                "notes": text,
                "exercises": [
                    {
                        "movement": "situps",
                        "sets": 1,
                        "reps_per_set": 10,
                        "total_reps": 10,
                        "weight_kg": 0,
                        "bodyweight": True,
                        "movement_multiplier": 1,
                    }
                ],
            },
            timezone_name="Europe/London",
            today=date(2026, 7, 19),
            include_today=True,
            runner=runner,
        )

        row = self.conn.execute("SELECT external_id, local_date, points FROM activities").fetchone()
        self.assertEqual(result.inserted, 1)
        self.assertEqual(row["external_id"], "8")
        self.assertEqual(row["local_date"], "2026-07-19")
        self.assertEqual(row["points"], 30)

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
