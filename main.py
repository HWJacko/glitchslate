from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from config import get_timezone, load_config, load_dotenv, parse_resolution
from db import (
    calculate_daily_score,
    connect,
    current_gap_days,
    daily_chart_points,
    get_cached_sentient_log,
    get_last_run_details,
    init_db,
    points_for_day,
    set_cached_sentient_log,
    set_sync_state,
)
from os_sync import cleanup_old_wallpapers, set_wallpaper
from sentient_log import fallback_sentient_log, generate_sentient_log
from strava_sync import sync_strava
from telegram_archive import sync_telegram_archive_for_blank_days
from telegram_sync import sync_telegram
from visual_engine import render_wallpaper


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def run_pipeline(
    *,
    db_path: str | None = None,
    dry_run: bool = False,
    apply_wallpaper: bool = True,
    assets_dir: str | Path = "assets",
    width: int | None = None,
    height: int | None = None,
    telegram_replay_from: int | None = None,
    config_path: str | Path | None = None,
    resolution: str | None = None,
) -> int:
    load_dotenv()
    app_config = load_config(config_path)
    configured_width, configured_height = parse_resolution(resolution or app_config.visual.target_resolution)
    render_width = width or configured_width
    render_height = height or configured_height

    conn = connect(db_path)
    init_db(conn)
    timezone_name = os.getenv("LOCAL_TIMEZONE", "Europe/London")
    today = datetime.now(get_timezone(timezone_name)).date()
    today_key = today.isoformat()

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_user = os.getenv("TELEGRAM_ALLOWED_USER_ID")
    direct_telegram_enabled = _env_flag("TELEGRAM_DIRECT_SYNC", True)
    if direct_telegram_enabled and telegram_token and telegram_user:
        try:
            if telegram_replay_from is not None and not dry_run:
                set_sync_state(conn, "telegram_last_update_id", max(0, telegram_replay_from - 1))
            telegram_count = sync_telegram(
                conn,
                token=telegram_token,
                allowed_user_id=int(telegram_user),
                dry_run=dry_run,
                timezone_name=timezone_name,
            )
            print(f"telegram synced {telegram_count} workout activity records")
        except Exception as exc:
            _warn(f"Telegram sync warning: {exc}")
    elif not direct_telegram_enabled:
        _warn("Telegram sync skipped: TELEGRAM_DIRECT_SYNC is disabled")
    else:
        _warn("Telegram sync skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_USER_ID is missing")

    archive_enabled = _env_flag("TELEGRAM_ARCHIVE_ENABLED", app_config.telegram_archive.enabled)
    if archive_enabled:
        archive_ssh = os.getenv("HETZNER_TELEGRAM_SSH")
        if telegram_user and archive_ssh:
            try:
                archive_result = sync_telegram_archive_for_blank_days(
                    conn,
                    allowed_user_id=int(telegram_user),
                    ssh_target=archive_ssh,
                    remote_dir=os.getenv("HETZNER_TELEGRAM_REMOTE_DIR", app_config.telegram_archive.remote_dir),
                    lookback_days=app_config.telegram_archive.blank_lookback_days,
                    dry_run=dry_run,
                    timezone_name=timezone_name,
                    today=today,
                )
                print(
                    "telegram archive checked "
                    f"{len(archive_result.checked_days)} blank days, "
                    f"fetched {archive_result.fetched_updates} updates, "
                    f"synced {archive_result.inserted} workout activity records"
                )
            except Exception as exc:
                _warn(f"Telegram archive sync warning: {exc}")
        else:
            _warn("Telegram archive skipped: HETZNER_TELEGRAM_SSH or TELEGRAM_ALLOWED_USER_ID is missing")

    strava_client_id = os.getenv("STRAVA_CLIENT_ID")
    strava_client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    strava_refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")
    if strava_client_id and strava_client_secret and strava_refresh_token:
        try:
            strava_count = sync_strava(
                conn,
                client_id=strava_client_id,
                client_secret=strava_client_secret,
                refresh_token_value=strava_refresh_token,
                dry_run=dry_run,
                timezone_name=timezone_name,
            )
            print(f"strava synced {strava_count} run activity records")
        except Exception as exc:
            _warn(f"Strava sync warning: {exc}")
    else:
        _warn("Strava sync skipped: Strava credentials are incomplete")

    score = calculate_daily_score(
        conn,
        today=today,
        timezone_name=timezone_name,
        scoring_config=app_config.scoring,
        persist=not dry_run,
    )
    chart_points = daily_chart_points(
        conn,
        end_day=today,
        point_count=app_config.scoring.baseline_window_days,
    )
    today_points = points_for_day(conn, today)
    gap_days = current_gap_days(conn, end_day=today)
    last_run_details = get_last_run_details(conn)
    sentient_log = None
    if app_config.sentient_log.enabled and not dry_run:
        sentient_log = get_cached_sentient_log(
            conn,
            day=today_key,
            score=score.score,
            streak_days=score.streak_days,
            today_points=today_points,
        )
        if sentient_log is None:
            try:
                sentient_log = generate_sentient_log(
                    score=score.score,
                    streak_days=score.streak_days,
                    today_points=today_points,
                    model=app_config.sentient_log.model,
                    max_chars=app_config.sentient_log.max_chars,
                )
                set_cached_sentient_log(
                    conn,
                    day=today_key,
                    score=score.score,
                    streak_days=score.streak_days,
                    today_points=today_points,
                    text=sentient_log,
                )
            except Exception as exc:
                _warn(f"OpenAI sentient log warning: {exc}")
                sentient_log = fallback_sentient_log(
                    score=score.score,
                    streak_days=score.streak_days,
                    today_points=today_points,
                    max_chars=app_config.sentient_log.max_chars,
                )
    result = render_wallpaper(
        score=score.score,
        day=today_key,
        output_dir=assets_dir,
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
    if not app_config.visual.keep_archive_images:
        cleanup_old_wallpapers(assets_dir, older_than_hours=app_config.visual.archive_retention_hours)

    try:
        command = set_wallpaper(result.timestamped_path, dry_run=dry_run or not apply_wallpaper)
    except Exception as exc:
        _warn(f"OS sync warning: {exc}")
        command = []

    print(
        f"score={score.score} streak={score.streak_days} "
        f"streak_pending={score.streak_pending} "
        f"today_score_points={score.recent_points} "
        f"baseline_daily_points={score.baseline_daily_points:.2f} "
        f"expected_daily_points={score.expected_recent_points:.2f} "
        f"today_points={today_points} gap_days={gap_days} "
        f"glitch_factor={result.glitch_factor:.2f} wallpaper={result.timestamped_path}"
    )
    print(
        "wallpaper diagnostics: "
        f"backend={result.diagnostics.backend} "
        f"bar_count={result.diagnostics.bar_count} "
        f"latest_day_points={result.diagnostics.latest_day_points} "
        f"max_day_points={result.diagnostics.max_day_points} "
        f"bar_scale_points={result.diagnostics.bar_scale_points:.2f} "
        f"status={result.diagnostics.status} "
        f"vignette={result.diagnostics.vignette_mode} "
        f"sentient_log={result.diagnostics.sentient_log_present}"
    )
    if dry_run and command:
        print("dry-run wallpaper command:", " ".join(command))
    elif not apply_wallpaper and command:
        print("no-apply wallpaper command:", " ".join(command))
    conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Glitchslate pipeline.")
    parser.add_argument("--db", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--assets-dir", default="assets")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-apply", action="store_true", help="Ingest and render, but do not change the desktop wallpaper.")
    parser.add_argument(
        "--telegram-replay-from",
        type=int,
        default=None,
        help="Reset Telegram polling offset to this update id before syncing.",
    )
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--resolution", default=None)
    args = parser.parse_args()
    return run_pipeline(
        db_path=args.db,
        dry_run=args.dry_run,
        apply_wallpaper=not args.no_apply,
        assets_dir=args.assets_dir,
        width=args.width,
        height=args.height,
        telegram_replay_from=args.telegram_replay_from,
        config_path=args.config,
        resolution=args.resolution,
    )


if __name__ == "__main__":
    raise SystemExit(main())
