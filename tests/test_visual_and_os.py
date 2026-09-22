from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from os_sync import _escape_applescript_string, set_wallpaper
from visual_engine import (
    _metric_value_color,
    calculate_glitch_factor,
    criticality_factor_for_time,
    render_wallpaper,
    score_with_time_criticality,
    system_status,
    systemd_status_lines,
    vignette_mode,
)


class VisualAndOsTests(unittest.TestCase):
    def test_glitch_factor_bounds(self) -> None:
        self.assertEqual(calculate_glitch_factor(100), 0.0)
        self.assertEqual(calculate_glitch_factor(0), 1.0)

    def test_status_bands(self) -> None:
        self.assertEqual(system_status(95), "STABLE")
        self.assertEqual(system_status(65), "DRIFTING")
        self.assertEqual(system_status(35), "AT RISK")
        self.assertEqual(system_status(10), "CRITICAL")

    def test_time_criticality_ramps_shortfall_through_day(self) -> None:
        morning = datetime(2026, 7, 30, 6, 0)
        midday = datetime(2026, 7, 30, 14, 0)
        evening = datetime(2026, 7, 30, 22, 0)

        self.assertEqual(criticality_factor_for_time(morning), 0.15)
        self.assertAlmostEqual(criticality_factor_for_time(midday), 0.575)
        self.assertEqual(criticality_factor_for_time(evening), 1.0)
        self.assertEqual(score_with_time_criticality(0, 0.15), 85)
        self.assertEqual(score_with_time_criticality(0, 1.0), 0)
        self.assertEqual(score_with_time_criticality(50, 0.5), 75)

    def test_systemd_and_vignette_modes(self) -> None:
        self.assertEqual(vignette_mode(95), "cyan")
        self.assertEqual(vignette_mode(65), "neutral")
        self.assertEqual(vignette_mode(20), "warning")
        self.assertIn("NOMINAL", systemd_status_lines(20, 0)[1])
        self.assertIn("WARNING", systemd_status_lines(0, 1)[1])
        self.assertIn("DEGRADED", systemd_status_lines(0, 3)[1])
        self.assertIn("WARNING", systemd_status_lines(0, 3, criticality_score=85)[1])
        self.assertIn("DEGRADED", systemd_status_lines(0, 3, criticality_score=20)[1])

    def test_metric_value_color_uses_polarity(self) -> None:
        self.assertEqual(
            _metric_value_color({"polarity": "positive"}, positive="green", negative="red", neutral="white"),
            "green",
        )
        self.assertEqual(
            _metric_value_color({"polarity": "negative"}, positive="green", negative="red", neutral="white"),
            "red",
        )
        self.assertEqual(
            _metric_value_color({"polarity": "neutral"}, positive="green", negative="red", neutral="white"),
            "white",
        )

    def test_render_writes_timestamped_and_current_wallpapers(self) -> None:
        points = [
            {
                "day": f"2026-07-{day:02d}",
                "run_points": day * 3 if day % 2 == 0 else 0,
                "other_points": day * 2,
                "total_points": day * 5,
                "is_best": day == 30,
            }
            for day in range(1, 31)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = render_wallpaper(
                score=50,
                day="2026-07-30",
                output_dir=tmp,
                timestamp=datetime(2026, 7, 30, 12, 0, 1),
                width=320,
                height=180,
                chart_points=points,
                expected_recent_points=100,
                streak_days=3,
                streak_pending=True,
                today_points=25,
                gap_days=0,
                last_run_details={
                    "day": "2026-07-30",
                    "distance_km": 4.2,
                    "duration_minutes": 25,
                    "pace_min_per_km": 5.95,
                    "points": 1300,
                    "elevation_m": 12,
                },
                sentient_log="Crew output nominal; systems remain within baseline.",
                top_right_metrics=[
                    {
                        "label": "PORTFOLIO RETURN",
                        "value": "-0.24%",
                        "status": "STALE",
                        "stale": True,
                        "polarity": "negative",
                    },
                    {
                        "label": "CRYPY PORTFOLIO",
                        "value": "GBP 1234.56",
                        "status": "LIVE",
                        "stale": False,
                        "polarity": "neutral",
                    },
                    {
                        "label": "CRYPY VS BTC 1D",
                        "value": "+1.20%",
                        "status": "LIVE",
                        "stale": False,
                        "polarity": "positive",
                    },
                    {
                        "label": "CRYPY REALISED 1D",
                        "value": "GBP -12.00",
                        "status": "LIVE",
                        "stale": False,
                        "polarity": "negative",
                    },
                ],
            )
            self.assertTrue(result.timestamped_path.exists())
            self.assertTrue(result.current_path.exists())
            self.assertEqual(result.timestamped_path.name, "wallpaper_20260730_120001.png")
            self.assertEqual(result.diagnostics.bar_count, 30)
            self.assertEqual(result.diagnostics.latest_day_points, 150)
            self.assertEqual(result.diagnostics.max_day_points, 150)
            self.assertEqual(result.diagnostics.status, "DRIFTING")
            self.assertEqual(result.diagnostics.criticality_factor, 1.0)
            self.assertEqual(result.diagnostics.today_points, 25)
            self.assertEqual(result.diagnostics.gap_days, 0)
            self.assertEqual(result.diagnostics.vignette_mode, "neutral")
            self.assertTrue(result.diagnostics.sentient_log_present)
            self.assertEqual(result.diagnostics.top_right_metric_count, 4)
            self.assertEqual(result.diagnostics.stale_top_right_metric_count, 1)

    def test_os_sync_dry_run_does_not_call_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "wallpaper.png"
            image.write_bytes(b"not really a png")
            with patch("platform.system", return_value="Darwin"), patch("subprocess.run") as run:
                command = set_wallpaper(image, dry_run=True)
            self.assertEqual(command[0], "osascript")
            run.assert_not_called()

    def test_applescript_path_escaping(self) -> None:
        self.assertEqual(_escape_applescript_string('a\\b"c\nd'), 'a\\\\b\\"c\\nd')


if __name__ == "__main__":
    unittest.main()
