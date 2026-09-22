from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from external_metrics import ExternalMetric
from social_sync import SocialSnapshot


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
                    "GLITCHSLATE_CONFIG_PATH": str(Path(tmp) / "missing-config.yaml"),
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
            generate_log.assert_not_called()

    def test_dry_run_skips_sentient_log_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                "os.environ",
                {
                    "GLITCHSLATE_DB_PATH": str(Path(tmp) / "test.db"),
                    "GLITCHSLATE_CONFIG_PATH": str(Path(tmp) / "missing-config.yaml"),
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
            chart_points = [
                {
                    "day": "2026-09-09",
                    "run_points": 1000,
                    "other_points": 500,
                    "total_points": 1500,
                    "is_best": True,
                }
            ]

            def fake_render_wallpaper(**kwargs):
                captured["top_right_metrics"] = kwargs["top_right_metrics"]
                captured["chart_points"] = kwargs["chart_points"]
                captured["expected_recent_points"] = kwargs["expected_recent_points"]

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
                    "GLITCHSLATE_CONFIG_PATH": str(Path(tmp) / "missing-config.yaml"),
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
                main, "rolling_chart_points", return_value=chart_points
            ) as rolling_chart_points, patch.object(
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
            self.assertEqual(captured["chart_points"], chart_points)
            self.assertEqual(captured["expected_recent_points"], 900)
            rolling_chart_points.assert_called_once()
            self.assertEqual(rolling_chart_points.call_args.kwargs["window_days"], 3)

    def test_pipeline_runs_enabled_writing_and_social_collectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                "sentient_log:\n  enabled: false\n"
                "writing:\n"
                "  enabled: true\n"
                "  projects:\n"
                "    - id: shorts\n"
                "      label: SHORT STORIES\n"
                "      path: /tmp/shorts\n"
                "      activity_type: short_story\n"
                "social:\n"
                "  enabled: true\n"
                "  bluesky_rss_url: https://example.invalid/rss\n",
                encoding="utf-8",
            )
            captured = {}
            writing_snapshot = type(
                "WritingSnapshot",
                (),
                {
                    "stale": False,
                    "project_id": "shorts",
                    "total_words": 100,
                    "delta_words": 10,
                    "day_words": 10,
                    "week_words": 10,
                    "weekly_goal_words": 5000,
                },
            )()

            def fake_render_wallpaper(**kwargs):
                captured["top_right_metrics"] = kwargs["top_right_metrics"]

                class Diagnostics:
                    backend = "pillow"
                    bar_count = 30
                    latest_day_points = 0
                    max_day_points = 0
                    bar_scale_points = 2100.0
                    status = "DRIFTING"
                    vignette_mode = "neutral"
                    sentient_log_present = False
                    top_right_metric_count = 1
                    stale_top_right_metric_count = 1

                class Result:
                    timestamped_path = Path(tmp) / "assets" / "wallpaper.png"
                    glitch_factor = 0.39
                    diagnostics = Diagnostics()

                return Result()

            with patch.dict(
                "os.environ",
                {
                    "GLITCHSLATE_DB_PATH": str(Path(tmp) / "test.db"),
                    "LOCAL_TIMEZONE": "Europe/London",
                },
                clear=True,
            ), patch.object(main, "load_dotenv", lambda: None), patch.object(
                main, "sync_writing_projects", return_value=[writing_snapshot]
            ) as sync_writing, patch.object(
                main,
                "sync_bluesky_posts",
                return_value=SocialSnapshot(
                    latest_post_at=None,
                    days_since_latest_post=5,
                    post_count=1,
                    reminder_due=True,
                ),
            ) as sync_social, patch.object(
                main, "portfolio_return_metric", return_value=None
            ), patch.object(
                main, "crypy_headline_metrics", return_value=[]
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
                    config_path=config_path,
                )

            self.assertEqual(result, 0)
            sync_writing.assert_called_once()
            sync_social.assert_called_once()
            self.assertEqual(captured["top_right_metrics"][0].label, "SOCIAL POST")
            self.assertEqual(captured["top_right_metrics"][0].status, "REMINDER")


if __name__ == "__main__":
    unittest.main()
