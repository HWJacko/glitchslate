from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

from config import get_timezone, load_dotenv
from db import calculate_daily_score, connect, init_db
from os_sync import cleanup_old_wallpapers, set_wallpaper
from strava_sync import sync_strava
from telegram_sync import sync_telegram
from visual_engine import HEIGHT, WIDTH, render_wallpaper


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def run_pipeline(
    *,
    db_path: str | None = None,
    dry_run: bool = False,
    assets_dir: str | Path = "assets",
    width: int = WIDTH,
    height: int = HEIGHT,
) -> int:
    load_dotenv()
    conn = connect(db_path)
    init_db(conn)
    timezone_name = os.getenv("LOCAL_TIMEZONE", "Europe/London")
    today = None
    today_key = datetime.now(get_timezone(timezone_name)).date().isoformat()

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_user = os.getenv("TELEGRAM_ALLOWED_USER_ID")
    if telegram_token and telegram_user:
        try:
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
    else:
        _warn("Telegram sync skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_USER_ID is missing")

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

    score = calculate_daily_score(conn, today=today, timezone_name=timezone_name)
    result = render_wallpaper(score=score.score, day=today_key, output_dir=assets_dir, width=width, height=height)
    cleanup_old_wallpapers(assets_dir)

    try:
        command = set_wallpaper(result.timestamped_path, dry_run=dry_run)
    except Exception as exc:
        _warn(f"OS sync warning: {exc}")
        command = []

    print(
        f"score={score.score} streak={score.streak_days} minutes={score.total_minutes} "
        f"glitch_factor={result.glitch_factor:.2f} wallpaper={result.timestamped_path}"
    )
    if dry_run and command:
        print("dry-run wallpaper command:", " ".join(command))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Glitchslate pipeline.")
    parser.add_argument("--db", default=None)
    parser.add_argument("--assets-dir", default="assets")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--width", type=int, default=WIDTH)
    parser.add_argument("--height", type=int, default=HEIGHT)
    args = parser.parse_args()
    return run_pipeline(
        db_path=args.db,
        dry_run=args.dry_run,
        assets_dir=args.assets_dir,
        width=args.width,
        height=args.height,
    )


if __name__ == "__main__":
    raise SystemExit(main())
