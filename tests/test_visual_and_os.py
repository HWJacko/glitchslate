from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from os_sync import set_wallpaper
from visual_engine import calculate_glitch_factor, render_wallpaper, system_status, systemd_status_lines, vignette_mode


class VisualAndOsTests(unittest.TestCase):
    def test_glitch_factor_bounds(self) -> None:
        self.assertEqual(calculate_glitch_factor(100), 0.0)
        self.assertEqual(calculate_glitch_factor(0), 1.0)

    def test_status_bands(self) -> None:
        self.assertEqual(system_status(95), "STABLE")
        self.assertEqual(system_status(65), "DRIFTING")
        self.assertEqual(system_status(35), "AT RISK")
        self.assertEqual(system_status(10), "CRITICAL")

    def test_systemd_and_vignette_modes(self) -> None:
        self.assertEqual(vignette_mode(95), "cyan")
        self.assertEqual(vignette_mode(65), "neutral")
        self.assertEqual(vignette_mode(20), "warning")
        self.assertIn("NOMINAL", systemd_status_lines(20, 0)[1])
        self.assertIn("WARNING", systemd_status_lines(0, 1)[1])
        self.assertIn("DEGRADED", systemd_status_lines(0, 3)[1])

    def test_render_writes_timestamped_and_current_wallpapers(self) -> None:
        points = [(f"2026-07-{day:02d}", day * 5) for day in range(1, 31)]
        with tempfile.TemporaryDirectory() as tmp:
            result = render_wallpaper(
                score=50,
                day="2026-07-30",
                output_dir=tmp,
                timestamp=datetime(2026, 7, 30, 12, 0, 1),
                width=320,
                height=180,
                rolling_points=points,
                expected_recent_minutes=100,
                streak_days=3,
                today_minutes=25,
                gap_days=0,
                sentient_log="Crew output nominal; systems remain within baseline.",
            )
            self.assertTrue(result.timestamped_path.exists())
            self.assertTrue(result.current_path.exists())
            self.assertEqual(result.timestamped_path.name, "wallpaper_20260730_120001.png")
            self.assertEqual(result.diagnostics.bar_count, 30)
            self.assertEqual(result.diagnostics.latest_5_day_minutes, 150)
            self.assertEqual(result.diagnostics.max_5_day_minutes, 150)
            self.assertEqual(result.diagnostics.status, "DRIFTING")
            self.assertEqual(result.diagnostics.today_minutes, 25)
            self.assertEqual(result.diagnostics.gap_days, 0)
            self.assertEqual(result.diagnostics.vignette_mode, "neutral")
            self.assertTrue(result.diagnostics.sentient_log_present)

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
