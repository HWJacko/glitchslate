from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from config import WritingProjectConfig
from db import connect, get_sync_state, init_db
from writing_sync import count_project_words, sync_writing_projects


class WritingSyncTests(unittest.TestCase):
    def test_count_project_words_counts_txt_stack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "one.txt").write_text("one two\nthree", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "two.txt").write_text("four five", encoding="utf-8")
            (root / "ignored.md").write_text("not counted", encoding="utf-8")

            self.assertEqual(count_project_words(root), (5, 2))

    def test_sync_writing_project_records_positive_daily_delta_and_week_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "draft"
            root.mkdir()
            draft = root / "chapter.txt"
            draft.write_text("one two", encoding="utf-8")
            db_path = Path(tmp) / "glitchslate.db"
            conn = connect(db_path)
            init_db(conn)
            project = WritingProjectConfig(
                id="shorts",
                label="SHORT STORIES",
                path=str(root),
                activity_type="short_story",
                weekly_goal_words=1000,
            )

            first = sync_writing_projects(
                conn,
                projects=(project,),
                today=date(2026, 9, 14),
                now=datetime(2026, 9, 14, 8, 0),
                tz=None,
            )
            draft.write_text("one two three four five", encoding="utf-8")
            second = sync_writing_projects(
                conn,
                projects=(project,),
                today=date(2026, 9, 14),
                now=datetime(2026, 9, 14, 9, 0),
                tz=None,
            )

            row = conn.execute("SELECT source, activity_type, points, raw_payload FROM activities").fetchone()
            self.assertEqual(first[0].day_words, 0)
            self.assertEqual(second[0].delta_words, 3)
            self.assertEqual(second[0].day_words, 3)
            self.assertEqual(second[0].week_words, 3)
            self.assertEqual(row["source"], "writing")
            self.assertEqual(row["activity_type"], "short_story")
            self.assertEqual(row["points"], 3)
            self.assertEqual(get_sync_state(conn, "writing:shorts:week:2026-09-14:baseline_words"), "2")
            init_db(conn)
            row = conn.execute("SELECT points FROM activities").fetchone()
            self.assertEqual(row["points"], 3)
            conn.close()


if __name__ == "__main__":
    unittest.main()
