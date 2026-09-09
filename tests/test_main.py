from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from external_metrics import ExternalMetric


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
            ), patch.object(main, "portfolio_return_metric", return_value=None), patch.object(
                main, "crypy_headline_metrics", return_value=[]
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
                with patch.object(main, "portfolio_return_metric", return_value=None), patch.object(
                    main, "crypy_headline_metrics", return_value=[]
                ):
                    result = main.run_pipeline(
                        db_path=str(Path(tmp) / "test.db"),
                        dry_run=True,
                        assets_dir=Path(tmp) / "assets",
                        width=80,
                        height=45,
                    )

            self.assertEqual(result, 0)
            generate_log.assert_not_called()

    def test_pipeline_passes_external_metrics_to_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            captured = {}

            def fake_render_wallpaper(**kwargs):
                captured["top_right_metrics"] = kwargs["top_right_metrics"]

                class Diagnostics:
                    backend = "pillow"
                    bar_count = 30
                    latest_day_points = 0
                    max_day_points = 0
                    bar_scale_points = 300.0
                    status = "AT RISK"
                    vignette_mode = "warning"
                    sentient_log_present = False
                    top_right_metric_count = 4
                    stale_top_right_metric_count = 1

                class Result:
                    timestamped_path = Path(tmp) / "assets" / "wallpaper.png"
                    glitch_factor = 0.58
                    diagnostics = Diagnostics()

                return Result()

            portfolio_metric = ExternalMetric("PORTFOLIO RETURN", "-0.24%", "STALE", True, "negative")
            crypy_metrics = [
                ExternalMetric("CRYPY PORTFOLIO", "GBP 617.59", "LIVE"),
                ExternalMetric("CRYPY VS BTC 1D", "-0.02%", "LIVE", polarity="negative"),
                ExternalMetric("CRYPY REALISED 1D", "GBP +12.34", "LIVE", polarity="positive"),
            ]
            with patch.dict(
                "os.environ",
                {
                    "GLITCHSLATE_DB_PATH": str(Path(tmp) / "test.db"),
                    "LOCAL_TIMEZONE": "Europe/London",
                },
                clear=True,
            ), patch.object(main, "load_dotenv", lambda: None), patch.object(
                main, "portfolio_return_metric", return_value=portfolio_metric
            ), patch.object(
                main, "crypy_headline_metrics", return_value=crypy_metrics
            ), patch.object(
                main, "render_wallpaper", side_effect=fake_render_wallpaper
            ), patch.object(
                main, "set_wallpaper", return_value=["set-wallpaper"]
            ), patch.object(
                main, "cleanup_old_wallpapers"
            ):
                result = main.run_pipeline(
                    db_path=str(Path(tmp) / "test.db"),
                    dry_run=True,
                    assets_dir=Path(tmp) / "assets",
                    width=80,
                    height=45,
                )

            self.assertEqual(result, 0)
            self.assertEqual(captured["top_right_metrics"], [portfolio_metric, *crypy_metrics])


if __name__ == "__main__":
    unittest.main()
