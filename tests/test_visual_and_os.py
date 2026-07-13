from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from os_sync import set_wallpaper
from visual_engine import calculate_glitch_factor, render_wallpaper


class VisualAndOsTests(unittest.TestCase):
    def test_glitch_factor_bounds(self) -> None:
        self.assertEqual(calculate_glitch_factor(100), 0.0)
        self.assertEqual(calculate_glitch_factor(0), 1.0)

    def test_render_writes_timestamped_and_current_wallpapers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = render_wallpaper(
                score=50,
                day="2026-07-13",
                output_dir=tmp,
                timestamp=datetime(2026, 7, 13, 12, 0, 1),
                width=320,
                height=180,
            )
            self.assertTrue(result.timestamped_path.exists())
            self.assertTrue(result.current_path.exists())
            self.assertEqual(result.timestamped_path.name, "wallpaper_20260713_120001.png")

    def test_os_sync_dry_run_does_not_call_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "wallpaper.png"
            image.write_bytes(b"not really a png")
            with patch("platform.system", return_value="Darwin"), patch("subprocess.run") as run:
                command = set_wallpaper(image, dry_run=True)
            self.assertEqual(command[0], "osascript")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
