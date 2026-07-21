#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import get_timezone, load_config, parse_resolution
from db import (
    Activity,
    calculate_daily_score,
    connect,
    current_gap_days,
    daily_chart_points,
    daily_minutes_map,
    daily_points_map,
    get_last_run_details,
    init_db,
    minutes_for_day,
    points_for_day,
    upsert_activity,
)
from sentient_log import fallback_sentient_log
from visual_engine import render_wallpaper, systemd_status_lines


DEFAULT_END_DAY = date(2026, 7, 13)
DEFAULT_OUTPUT_ROOT = Path("test_output/mock_dataset")
DEFAULT_TIMEZONE = "Europe/London"


MockEntry = dict[str, Any]


def _dt(day: date, hour: int = 7, minute: int = 30) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


def mock_entries(end_day: date = DEFAULT_END_DAY) -> list[MockEntry]:
    workouts = [
        (-44, "telegram", "strength", 32, "moderate", "Dumbbell circuit: curls, press, situps"),
        (-42, "strava", "run", 28, "easy", "Easy aerobic run"),
        (-39, "telegram", "mobility", 18, "easy", "Mobility reset and core"),
        (-36, "telegram", "strength", 42, "hard", "Upper-body strength blocks"),
        (-35, "strava", "run", 34, "moderate", "Tempo intervals"),
        (-31, "telegram", "conditioning", 26, "moderate", "Kettlebell swings and squats"),
        (-29, "telegram", "strength", 45, "hard", "Dumbbell full-body session"),
        (-28, "strava", "run", 52, "hard", "Long steady run"),
        (-25, "telegram", "mobility", 16, "easy", "Stretching and prehab"),
        (-23, "telegram", "strength", 38, "moderate", "Push/pull/core"),
        (-21, "strava", "run", 31, "easy", "Recovery run"),
        (-18, "telegram", "conditioning", 24, "moderate", "Bodyweight density set"),
        (-16, "telegram", "strength", 40, "hard", "Shoulders, arms, situps"),
        (-15, "strava", "run", 47, "moderate", "Progression run"),
        (-12, "telegram", "mobility", 20, "easy", "Hip and shoulder mobility"),
        (-10, "telegram", "strength", 35, "moderate", "Dumbbells and core"),
        (-8, "strava", "run", 29, "easy", "Short easy run"),
        (-6, "telegram", "conditioning", 22, "moderate", "Mixed calisthenics"),
        (-5, "telegram", "strength", 44, "hard", "High-output dumbbell session"),
        (-4, "strava", "run", 36, "moderate", "Aerobic run"),
        (-2, "telegram", "mobility", 15, "easy", "Short mobility maintenance"),
        (0, "telegram", "strength", 30, "moderate", "Mock current-day check-in"),
    ]
    entries: list[MockEntry] = []
    for index, (offset, source, activity_type, minutes, intensity, notes) in enumerate(workouts, start=1):
        day = end_day + timedelta(days=offset)
        entries.append(
            {
                "source": source,
                "external_id": f"mock-{source}-{index:03d}",
                "timestamp": _dt(day, hour=6 + (index % 5)),
                "activity_type": activity_type,
                "duration_minutes": minutes,
                "intensity": intensity,
                "notes": notes,
                "raw_payload": {
                    "mock": True,
                    "source_shape": "telegram_message" if source == "telegram" else "strava_activity",
                    "day_offset": offset,
                    "notes": notes,
                    **(
                        {
                            "type": "Run",
                            "sport_type": "Run",
                            "moving_time": minutes * 60,
                            "elapsed_time": minutes * 62,
                            "distance": minutes * 160,
                            "average_speed": (minutes * 160) / (minutes * 60),
                            "total_elevation_gain": max(4, minutes * 0.45),
                        }
                        if source == "strava"
                        else {
                            "parser_result": {
                                "is_workout": True,
                                "activity_type": activity_type,
                                "duration_minutes": minutes,
                                "intensity": intensity,
                                "notes": notes,
                                "exercises": [],
                            }
                        }
                    ),
                },
            }
        )
    return entries


def build_mock_output(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    end_day: date = DEFAULT_END_DAY,
    width: int | None = None,
    height: int | None = None,
    config_path: str | Path | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    assets_dir = output_root / "assets"
    db_path = output_root / "mock_glitchslate.db"
    summary_path = output_root / "summary.json"

    if db_path.exists():
        db_path.unlink()

    app_config = load_config(config_path)
    configured_width, configured_height = parse_resolution(app_config.visual.target_resolution)
    render_width = width or configured_width
    render_height = height or configured_height
    tz = get_timezone(timezone_name)

    conn = connect(db_path)
    init_db(conn)
    entries = mock_entries(end_day)
    for entry in entries:
        upsert_activity(
            conn,
            Activity(
                source=entry["source"],
                external_id=entry["external_id"],
                timestamp=entry["timestamp"],
                activity_type=entry["activity_type"],
                duration_minutes=entry["duration_minutes"],
                intensity=entry["intensity"],
                notes=entry["notes"],
                raw_payload=entry["raw_payload"],
            ),
            tz=tz,
        )

    score = calculate_daily_score(
        conn,
        today=end_day,
        timezone_name=timezone_name,
        scoring_config=app_config.scoring,
        persist=True,
    )
    chart_points = daily_chart_points(
        conn,
        end_day=end_day,
        point_count=app_config.scoring.baseline_window_days,
    )
    today_minutes = minutes_for_day(conn, end_day)
    today_points = points_for_day(conn, end_day)
    gap_days = current_gap_days(conn, end_day=end_day)
    last_run_details = get_last_run_details(conn)
    sentient_log = fallback_sentient_log(
        score=score.score,
        streak_days=score.streak_days,
        today_points=today_points,
        max_chars=app_config.sentient_log.max_chars,
    )
    render_result = render_wallpaper(
        score=score.score,
        day=end_day.isoformat(),
        output_dir=assets_dir,
        timestamp=datetime(end_day.year, end_day.month, end_day.day, 12, 0, 0),
        width=render_width,
        height=render_height,
        visual_config=app_config.visual,
        chart_points=chart_points,
        streak_days=score.streak_days,
        streak_pending=score.streak_pending,
        expected_recent_points=score.expected_recent_points,
        today_points=today_points,
        gap_days=gap_days,
        last_run_details=last_run_details,
        sentient_log=sentient_log,
        show_systemd_box=app_config.telemetry.show_systemd_box,
        show_vignette=app_config.telemetry.show_vignette,
        systemd_alert_gap_days=app_config.telemetry.gap_alert_days,
    )

    start_day = end_day - timedelta(days=44)
    daily_minutes = daily_minutes_map(conn, start_day=start_day, end_day=end_day)
    daily_points = daily_points_map(conn, start_day=start_day, end_day=end_day)
    source_counts = {
        row["source"]: int(row["count"])
        for row in conn.execute("SELECT source, COUNT(*) AS count FROM activities GROUP BY source").fetchall()
    }
    source_minutes = {
        row["source"]: int(row["minutes"])
        for row in conn.execute("SELECT source, SUM(duration_minutes) AS minutes FROM activities GROUP BY source").fetchall()
    }
    source_points = {
        row["source"]: int(round(float(row["points"])))
        for row in conn.execute("SELECT source, SUM(points) AS points FROM activities GROUP BY source").fetchall()
    }
    serialized_chart_points = [
        {
            "day": point.day,
            "run_points": point.run_points,
            "other_points": point.other_points,
            "total_points": point.total_points,
            "is_best": point.is_best,
        }
        for point in chart_points
    ]
    summary = {
        "mock": True,
        "output_root": str(output_root),
        "database": str(db_path),
        "wallpaper": str(render_result.timestamped_path),
        "wallpaper_current": str(render_result.current_path),
        "date": score.date,
        "score": score.score,
        "streak_days": score.streak_days,
        "streak_pending": score.streak_pending,
        "total_minutes": score.total_minutes,
        "recent_minutes": score.recent_minutes,
        "baseline_daily_minutes": score.baseline_daily_minutes,
        "expected_recent_minutes": score.expected_recent_minutes,
        "total_points": score.total_points,
        "recent_points": score.recent_points,
        "baseline_daily_points": score.baseline_daily_points,
        "expected_recent_points": score.expected_recent_points,
        "today_minutes": today_minutes,
        "today_points": today_points,
        "gap_days": gap_days,
        "systemd_lines": systemd_status_lines(today_points, gap_days, alert_gap_days=app_config.telemetry.gap_alert_days),
        "sentient_log": sentient_log,
        "activity_count": len(entries),
        "source_counts": source_counts,
        "source_minutes": source_minutes,
        "source_points": source_points,
        "daily_minutes": daily_minutes,
        "daily_points": daily_points,
        "daily_chart_points": serialized_chart_points,
        "diagnostics": {
            "backend": render_result.diagnostics.backend,
            "bar_count": render_result.diagnostics.bar_count,
            "latest_day_points": render_result.diagnostics.latest_day_points,
            "max_day_points": render_result.diagnostics.max_day_points,
            "bar_scale_points": render_result.diagnostics.bar_scale_points,
            "status": render_result.diagnostics.status,
            "vignette_mode": render_result.diagnostics.vignette_mode,
            "sentient_log_present": render_result.diagnostics.sentient_log_present,
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    conn.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local-only mock Glitchslate dataset and wallpaper output.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--date", default=DEFAULT_END_DAY.isoformat(), help="End date for the mock dataset, formatted YYYY-MM-DD.")
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    args = parser.parse_args()

    summary = build_mock_output(
        output_root=Path(args.output_root),
        end_day=date.fromisoformat(args.date),
        width=args.width,
        height=args.height,
        config_path=args.config,
        timezone_name=args.timezone,
    )
    print(f"mock output root: {summary['output_root']}")
    print(f"database: {summary['database']}")
    print(f"wallpaper: {summary['wallpaper']}")
    print(
        f"score={summary['score']} streak={summary['streak_days']} "
        f"recent_points={summary['recent_points']} status={summary['diagnostics']['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
