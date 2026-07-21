from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from config import get_timezone
from telegram_sync import Parser, sync_telegram_updates


RemoteRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class TelegramArchiveResult:
    checked_days: list[str]
    fetched_updates: int
    inserted: int


def telegram_blank_days(
    conn,
    *,
    today: date,
    lookback_days: int = 28,
    include_today: bool = False,
) -> list[str]:
    start_day = today - timedelta(days=max(1, lookback_days))
    end_day = today if include_today else today - timedelta(days=1)
    days: list[str] = []
    for offset in range((end_day - start_day).days + 1):
        day = start_day + timedelta(days=offset)
        day_key = day.isoformat()
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM activities
            WHERE source = 'telegram' AND local_date = ?
            """,
            (day_key,),
        ).fetchone()
        if int(row["count"]) == 0:
            days.append(day_key)
    return days


def _parse_jsonl(text: str) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        value = json.loads(stripped)
        if isinstance(value, dict):
            updates.append(value)
    return updates


def fetch_remote_archive_days(
    days: list[str],
    *,
    ssh_target: str,
    remote_dir: str,
    timeout: int = 30,
    runner: RemoteRunner = subprocess.run,
) -> list[dict[str, Any]]:
    if not days:
        return []

    quoted_days = " ".join(shlex.quote(day) for day in days)
    remote_script = (
        f"dir={shlex.quote(remote_dir)}; "
        f"for day in {quoted_days}; do "
        'file="$dir/$day.jsonl"; '
        'if [ -f "$file" ]; then cat "$file"; printf "\\n"; fi; '
        "done"
    )
    remote_command = f"sh -lc {shlex.quote(remote_script)}"
    try:
        result = runner(
            ["ssh", ssh_target, remote_command],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Hetzner Telegram archive fetch failed") from exc
    return _parse_jsonl(result.stdout)


def sync_telegram_archive_for_blank_days(
    conn,
    *,
    allowed_user_id: int,
    ssh_target: str,
    remote_dir: str,
    lookback_days: int = 28,
    parser: Parser | None = None,
    dry_run: bool = False,
    timezone_name: str | None = None,
    today: date | None = None,
    include_today: bool = False,
    runner: RemoteRunner = subprocess.run,
) -> TelegramArchiveResult:
    tz = get_timezone(timezone_name)
    local_today = today or datetime.now(tz).date()
    days = telegram_blank_days(
        conn,
        today=local_today,
        lookback_days=lookback_days,
        include_today=include_today,
    )
    updates = fetch_remote_archive_days(
        days,
        ssh_target=ssh_target,
        remote_dir=remote_dir,
        runner=runner,
    )
    inserted = sync_telegram_updates(
        conn,
        updates,
        allowed_user_id=allowed_user_id,
        parser=parser,
        dry_run=dry_run,
        timezone_name=timezone_name,
        allowed_local_dates=set(days),
    )
    return TelegramArchiveResult(
        checked_days=days,
        fetched_updates=len(updates),
        inserted=inserted,
    )
