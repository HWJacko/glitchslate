from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path


def _load_mock_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_mock_output.py"
    spec = importlib.util.spec_from_file_location("build_mock_output", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load build_mock_output.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MockOutputTests(unittest.TestCase):
    def test_build_mock_output_creates_local_dataset_and_wallpaper(self) -> None:
        module = _load_mock_module()
        with tempfile.TemporaryDirectory() as tmp:
            summary = module.build_mock_output(
                output_root=Path(tmp),
                end_day=date(2026, 7, 13),
                width=320,
                height=180,
            )
            db_path = Path(summary["database"])
            wallpaper = Path(summary["wallpaper"])
            summary_path = Path(tmp) / "summary.json"

            self.assertTrue(db_path.exists())
            self.assertTrue(wallpaper.exists())
            self.assertTrue(summary_path.exists())
            self.assertEqual(summary["activity_count"], 22)
            self.assertEqual(summary["diagnostics"]["bar_count"], 30)
            self.assertEqual(summary["date"], "2026-07-13")
            self.assertEqual(summary["source_counts"]["telegram"], 15)
            self.assertEqual(summary["source_counts"]["strava"], 7)
            self.assertEqual(json.loads(summary_path.read_text())["score"], summary["score"])


if __name__ == "__main__":
    unittest.main()
