#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import get_timezone, load_dotenv
from telegram_sync import _message_datetime, _message_from_update, _user_id, fetch_updates


DEFAULT_INBOX_DIR = "glitchslate-telegram-inbox"


def _read_state(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("last_update_id")
    return int(value) if value is not None else None


def _write_state(path: Path, last_update_id: int) -> None:
    path.write_text(
        json.dumps(
            {
                "last_update_id": last_update_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _append_update(inbox_dir: Path, day_key: str, update: dict[str, Any]) -> None:
    path = inbox_dir / f"{day_key}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(update, ensure_ascii=True, separators=(",", ":")))
        handle.write("\n")


def cleanup_old_files(inbox_dir: Path, *, retention_days: int, today: date) -> int:
    cutoff = today - timedelta(days=max(1, retention_days) - 1)
    removed = 0
    for path in inbox_dir.glob("*.jsonl"):
        try:
            file_day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_day < cutoff:
            path.unlink()
            removed += 1
    return removed


def archive_once(
    *,
    token: str,
    allowed_user_id: int,
    inbox_dir: Path,
    retention_days: int = 28,
    timezone_name: str | None = None,
) -> tuple[int, int]:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    state_path = inbox_dir / ".state.json"
    last_update_id = _read_state(state_path)
    offset = last_update_id + 1 if last_update_id is not None else None
    updates = fetch_updates(token, offset=offset, timeout=10)
    highest_update_id: int | None = None
    archived = 0
    tz = get_timezone(timezone_name)

    for update in updates:
        update_id = update.get("update_id")
        if update_id is not None:
            highest_update_id = max(highest_update_id or int(update_id), int(update_id))

        message = _message_from_update(update)
        if not message or _user_id(message) != allowed_user_id or not message.get("text"):
            continue
        day_key = _message_datetime(message).astimezone(tz).date().isoformat()
        _append_update(inbox_dir, day_key, update)
        archived += 1

    if highest_update_id is not None:
        _write_state(state_path, highest_update_id)

    removed = cleanup_old_files(
        inbox_dir,
        retention_days=retention_days,
        today=datetime.now(tz).date(),
    )
    return archived, removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive Telegram bot updates into dated JSONL files.")
    parser.add_argument("--inbox-dir", default=os.getenv("TELEGRAM_ARCHIVE_DIR", DEFAULT_INBOX_DIR))
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--retention-days", type=int, default=28)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    allowed_user_id = os.getenv("TELEGRAM_ALLOWED_USER_ID")
    if not token or not allowed_user_id:
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_ID are required")

    while True:
        archived, removed = archive_once(
            token=token,
            allowed_user_id=int(allowed_user_id),
            inbox_dir=Path(args.inbox_dir),
            retention_days=args.retention_days,
            timezone_name=os.getenv("LOCAL_TIMEZONE"),
        )
        print(f"telegram archive saved {archived} updates, removed {removed} old files", flush=True)
        if args.once:
            return 0
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
