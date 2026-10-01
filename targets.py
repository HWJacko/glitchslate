from __future__ import annotations

import argparse
from datetime import date

from config import load_config, load_dotenv
from db import connect, init_db
from weekly_targets import (
    format_weekly_targets,
    format_weekly_points,
    reset_weekly_targets,
    reset_weekly_points_target,
    set_weekly_target,
    set_weekly_points_target,
    weekly_points_progress,
    weekly_target_progress,
    week_start_for,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Glitchslate weekly targets.")
    parser.add_argument("command", choices=("list", "set", "reset"), nargs="?", default="list")
    parser.add_argument("key", nargs="?")
    parser.add_argument("value", nargs="?", type=float)
    parser.add_argument("--db", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--week", default=None, help="Monday date (YYYY-MM-DD); defaults to this week.")
    args = parser.parse_args()

    load_dotenv()
    config = load_config(args.config)
    today = date.fromisoformat(args.week) if args.week else date.today()
    week_start = week_start_for(today)
    conn = connect(args.db)
    init_db(conn)
    try:
        if not config.targets.enabled:
            print("Weekly targets are disabled in config.")
            return 0
        if args.command == "set":
            if not args.key or args.value is None:
                parser.error("set requires KEY and VALUE")
            if args.key.lower() in {"points", "weekly_points", "total", "weekly_total"}:
                changed = set_weekly_points_target(
                    conn,
                    config.targets.weekly_points_target,
                    target=args.value,
                    week_start=week_start,
                )
                print(f"Set weekly points target to {changed:g} for week {week_start}.")
            else:
                changed = set_weekly_target(
                    conn,
                    config.targets.defaults,
                    key=args.key,
                    target=args.value,
                    week_start=week_start,
                )
                print(f"Set {changed.label} to {changed.target:g} {changed.unit} for week {week_start}.")
        elif args.command == "reset":
            reset_weekly_targets(conn, config.targets.defaults, week_start=week_start)
            reset_weekly_points_target(conn, config.targets.weekly_points_target, week_start=week_start)
            print(f"Reset weekly targets for week {week_start}.")
        print(format_weekly_points(weekly_points_progress(
            conn,
            config.targets.weekly_points_target,
            today=today,
            source_names=config.targets.weekly_points_sources,
        )))
        progress = weekly_target_progress(conn, config.targets.defaults, today=today)
        print(format_weekly_targets(progress))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
