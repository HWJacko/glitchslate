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
        self.assertEqual(config.scoring.recent_window_days, 5)
        self.assertTrue(config.sentient_log.enabled)
        self.assertEqual(config.sentient_log.model, "gpt-4o-mini")
        self.assertTrue(config.telemetry.show_systemd_box)
        self.assertEqual(config.telemetry.gap_alert_days, 3)
        self.assertFalse(config.telegram_archive.enabled)
        self.assertEqual(config.telegram_archive.blank_lookback_days, 28)

    def test_load_config_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                "visual:\n  target_resolution: 800x600\n  bg_color: '#000000'\n"
                "telegram_archive:\n  enabled: true\n  blank_lookback_days: 7\n",
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(config.visual.bg_color, "#000000")
            self.assertEqual(config.visual.width, 800)
            self.assertEqual(config.visual.height, 600)
            self.assertTrue(config.telegram_archive.enabled)
            self.assertEqual(config.telegram_archive.blank_lookback_days, 7)

    def test_invalid_color_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            app_config_from_dict({"visual": {"bg_color": "navy"}})

    def test_parse_resolution(self) -> None:
        self.assertEqual(parse_resolution("320x180"), (320, 180))
        with self.assertRaises(ValueError):
            parse_resolution("320")


if __name__ == "__main__":
    unittest.main()
