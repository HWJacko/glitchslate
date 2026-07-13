from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import DEFAULT_TIMEZONE, get_db_path, get_timezone


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


@dataclass(frozen=True)
class Activity:
    source: str
    external_id: str
    timestamp: datetime
    activity_type: str | None
    duration_minutes: int
    intensity: str | None = None
    notes: str | None = None
    raw_payload: dict[str, Any] | list[Any] | str | None = None


@dataclass(frozen=True)
class DailyScore:
    date: str
    score: int
    streak_days: int
    total_minutes: int


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = get_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def _to_local_date(timestamp: datetime, tz: ZoneInfo) -> str:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(tz).date().isoformat()


def _to_db_timestamp(timestamp: datetime) -> str:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def _serialize_payload(payload: dict[str, Any] | list[Any] | str | None) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str)


def upsert_activity(
    conn: sqlite3.Connection,
    activity: Activity,
    *,
    tz: ZoneInfo | None = None,
) -> bool:
    if activity.duration_minutes < 0:
        raise ValueError("duration_minutes must be non-negative")
    timezone_info = tz or get_timezone()
    local_date = _to_local_date(activity.timestamp, timezone_info)
    timestamp = _to_db_timestamp(activity.timestamp)
    payload = _serialize_payload(activity.raw_payload)
    cursor = conn.execute(
        """
        INSERT INTO activities (
            source, external_id, timestamp, local_date, activity_type,
            duration_minutes, intensity, notes, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
            timestamp = excluded.timestamp,
            local_date = excluded.local_date,
            activity_type = excluded.activity_type,
            duration_minutes = excluded.duration_minutes,
            intensity = excluded.intensity,
            notes = excluded.notes,
            raw_payload = excluded.raw_payload,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            activity.source,
            activity.external_id,
            timestamp,
            local_date,
            activity.activity_type,
            activity.duration_minutes,
            activity.intensity,
            activity.notes,
            payload,
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_sync_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def set_sync_state(conn: sqlite3.Connection, key: str, value: str | int) -> None:
    conn.execute(
        """
        INSERT INTO sync_state (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (key, str(value)),
    )
    conn.commit()


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _date_range_exclusive(start: date, end: date) -> list[date]:
    days = []
    current = start + timedelta(days=1)
    while current < end:
        days.append(current)
        current += timedelta(days=1)
    return days


def calculate_daily_score(
    conn: sqlite3.Connection,
    *,
    today: date | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> DailyScore:
    local_today = today or datetime.now(get_timezone(timezone_name)).date()
    today_key = local_today.isoformat()

    previous = conn.execute(
        """
        SELECT date, score, streak_days
        FROM daily_state
        WHERE date < ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (today_key,),
    ).fetchone()

    if previous is None:
        previous_score = 100
        previous_date = local_today - timedelta(days=1)
        previous_streak_days = 0
    else:
        previous_score = int(previous["score"])
        previous_date = _parse_date(str(previous["date"]))
        previous_streak_days = int(previous["streak_days"])

    missed_days = len(_date_range_exclusive(previous_date, local_today))
    decayed_previous_score = max(0, previous_score - (15 * missed_days))

    row = conn.execute(
        """
        SELECT COALESCE(SUM(duration_minutes), 0) AS total_minutes,
               COUNT(*) AS activity_count
        FROM activities
        WHERE local_date = ?
        """,
        (today_key,),
    ).fetchone()
    total_minutes = int(row["total_minutes"])
    activity_count = int(row["activity_count"])

    score_value = max(0, min(100, decayed_previous_score - 15 + (total_minutes * 0.5)))
    score = int(round(score_value))
    streak_days = previous_streak_days + 1 if activity_count > 0 else 0

    conn.execute(
        """
        INSERT INTO daily_state (date, score, streak_days)
        VALUES (?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            score = excluded.score,
            streak_days = excluded.streak_days,
            updated_at = CURRENT_TIMESTAMP
        """,
        (today_key, score, streak_days),
    )
    conn.commit()
    return DailyScore(date=today_key, score=score, streak_days=streak_days, total_minutes=total_minutes)


def get_daily_score(conn: sqlite3.Connection, day: date | None = None) -> DailyScore | None:
    day_key = (day or date.today()).isoformat()
    row = conn.execute(
        "SELECT date, score, streak_days FROM daily_state WHERE date = ?",
        (day_key,),
    ).fetchone()
    if row is None:
        return None
    minutes_row = conn.execute(
        "SELECT COALESCE(SUM(duration_minutes), 0) AS total_minutes FROM activities WHERE local_date = ?",
        (day_key,),
    ).fetchone()
    return DailyScore(
        date=str(row["date"]),
        score=int(row["score"]),
        streak_days=int(row["streak_days"]),
        total_minutes=int(minutes_row["total_minutes"]),
    )
