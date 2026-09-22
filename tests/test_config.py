from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config import app_config_from_dict, load_config, parse_resolution


class ConfigTests(unittest.TestCase):
    def test_default_config(self) -> None:
        config = app_config_from_dict({})
        self.assertEqual(config.visual.bg_color, "#0b0f19")
        self.assertEqual(config.visual.active_gradient, ("#06b6d4", "#8b5cf6"))
        self.assertEqual(config.visual.width, 3840)
        self.assertEqual(config.chart.rolling_window_days, 3)
        self.assertEqual(config.scoring.recent_window_days, 5)
        self.assertEqual(config.scoring.included_sources, ("telegram", "strava"))
        self.assertFalse(config.sentient_log.enabled)
        self.assertEqual(config.sentient_log.model, "gpt-4o-mini")
        self.assertTrue(config.telemetry.show_systemd_box)
        self.assertEqual(config.telemetry.gap_alert_days, 3)
        self.assertTrue(config.telemetry.criticality_ramp_enabled)
        self.assertEqual(config.telemetry.criticality_ramp_start_hour, 6)
        self.assertEqual(config.telemetry.criticality_ramp_full_hour, 22)
        self.assertEqual(config.telemetry.criticality_ramp_min_factor, 0.15)
        self.assertFalse(config.telegram_archive.enabled)
        self.assertEqual(config.telegram_archive.blank_lookback_days, 28)
        self.assertFalse(config.writing.enabled)
        self.assertEqual(config.writing.projects, ())
        self.assertFalse(config.social.enabled)
        self.assertEqual(config.social.reminder_after_days, 4)
        self.assertFalse(config.sentient_log.enabled)
        self.assertFalse(config.strava.enabled)
        self.assertFalse(config.external_metrics.portfolio_return_enabled)
        self.assertFalse(config.external_metrics.crypy_headline_enabled)

    def test_load_config_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                "visual:\n  target_resolution: 800x600\n  bg_color: '#000000'\n"
                "chart:\n  rolling_window_days: 4\n"
                "scoring:\n  included_sources: ['telegram']\n"
                "telegram_archive:\n  enabled: true\n  blank_lookback_days: 7\n",
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(config.visual.bg_color, "#000000")
            self.assertEqual(config.visual.width, 800)
            self.assertEqual(config.visual.height, 600)
            self.assertEqual(config.chart.rolling_window_days, 4)
            self.assertEqual(config.scoring.included_sources, ("telegram",))
            self.assertTrue(config.telegram_archive.enabled)
            self.assertEqual(config.telegram_archive.blank_lookback_days, 7)

    def test_loads_writing_and_social_config(self) -> None:
        config = app_config_from_dict(
            {
                "writing": {
                    "enabled": True,
                    "projects": [
                        {
                            "id": "shorts",
                            "label": "SHORT STORIES",
                            "path": "/tmp/shorts",
                            "activity_type": "short_story",
                        }
                    ],
                },
                "social": {
                    "enabled": True,
                    "reminder_after_days": 5,
                    "post_points": 750,
                },
            }
        )

        self.assertTrue(config.writing.enabled)
        self.assertEqual(config.writing.projects[0].id, "shorts")
        self.assertEqual(config.writing.projects[0].activity_type, "short_story")
        self.assertTrue(config.social.enabled)
        self.assertEqual(config.social.reminder_after_days, 5)
        self.assertEqual(config.social.post_points, 750)

    def test_invalid_color_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            app_config_from_dict({"visual": {"bg_color": "navy"}})

    def test_parse_resolution(self) -> None:
        self.assertEqual(parse_resolution("320x180"), (320, 180))
        with self.assertRaises(ValueError):
            parse_resolution("320")

    def test_invalid_chart_window_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            app_config_from_dict({"chart": {"rolling_window_days": 0}})

    def test_external_metric_urls_require_https_without_credentials(self) -> None:
        with self.assertRaises(ValueError):
            app_config_from_dict(
                {
                    "external_metrics": {
                        "crypy_headline_enabled": True,
                        "crypy_headline_url": "http://example.test/headline",
                    }
                }
            )

    def test_render_resolution_has_a_resource_limit(self) -> None:
        with self.assertRaises(ValueError):
            parse_resolution("20000x1000")


if __name__ == "__main__":
    unittest.main()
