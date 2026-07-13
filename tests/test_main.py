from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class MainPipelineTests(unittest.TestCase):
    def test_no_apply_renders_but_does_not_apply_wallpaper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def fake_set_wallpaper(path, *, dry_run=False):
                calls.append((Path(path), dry_run))
                return ["set-wallpaper", str(path)]

            with patch.dict(
                "os.environ",
                {
                    "GLITCHSLATE_DB_PATH": str(Path(tmp) / "test.db"),
                    "LOCAL_TIMEZONE": "Europe/London",
                },
                clear=True,
            ), patch.object(main, "load_dotenv", lambda: None), patch.object(
                main, "generate_sentient_log", return_value="Crew output nominal."
            ) as generate_log, patch.object(
                main, "set_wallpaper", side_effect=fake_set_wallpaper
            ):
                result = main.run_pipeline(
                    db_path=str(Path(tmp) / "test.db"),
                    apply_wallpaper=False,
                    assets_dir=Path(tmp) / "assets",
                    width=80,
                    height=45,
                )

            self.assertEqual(result, 0)
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0][1])
            self.assertTrue((Path(tmp) / "assets" / "wallpaper_current.png").exists())
            generate_log.assert_called_once()

    def test_dry_run_skips_sentient_log_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                "os.environ",
                {
                    "GLITCHSLATE_DB_PATH": str(Path(tmp) / "test.db"),
                    "LOCAL_TIMEZONE": "Europe/London",
                },
                clear=True,
            ), patch.object(main, "load_dotenv", lambda: None), patch.object(
                main, "generate_sentient_log", return_value="Crew output nominal."
            ) as generate_log, patch.object(main, "set_wallpaper", return_value=["set-wallpaper"]):
                result = main.run_pipeline(
                    db_path=str(Path(tmp) / "test.db"),
                    dry_run=True,
                    assets_dir=Path(tmp) / "assets",
                    width=80,
                    height=45,
                )

            self.assertEqual(result, 0)
            generate_log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
