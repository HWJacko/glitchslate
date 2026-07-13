from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import DEFAULT_TIMEZONE, ScoringConfig, get_db_path, get_timezone


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
    recent_minutes: int = 0
    baseline_daily_minutes: float = 0.0
    expected_recent_minutes: float = 0.0


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


def _sum_minutes_between(conn: sqlite3.Connection, start_day: date, end_day: date) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(duration_minutes), 0) AS total_minutes
        FROM activities
        WHERE local_date >= ? AND local_date <= ?
        """,
        (start_day.isoformat(), end_day.isoformat()),
    ).fetchone()
    return int(row["total_minutes"])


def _activity_count_for_day(conn: sqlite3.Connection, day: date) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS activity_count FROM activities WHERE local_date = ?",
        (day.isoformat(),),
    ).fetchone()
    return int(row["activity_count"])


def daily_minutes_map(
    conn: sqlite3.Connection,
    *,
    start_day: date,
    end_day: date,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT local_date, COALESCE(SUM(duration_minutes), 0) AS total_minutes
        FROM activities
        WHERE local_date >= ? AND local_date <= ?
        GROUP BY local_date
        """,
        (start_day.isoformat(), end_day.isoformat()),
    ).fetchall()
    return {str(row["local_date"]): int(row["total_minutes"]) for row in rows}


def minutes_for_day(conn: sqlite3.Connection, day: date) -> int:
    return _sum_minutes_between(conn, day, day)


def current_gap_days(conn: sqlite3.Connection, *, end_day: date) -> int:
    gap = 0
    current = end_day
    while True:
        if minutes_for_day(conn, current) > 0:
            return gap
        gap += 1
        current = current - timedelta(days=1)
        if gap > 365:
            return gap


def sentient_log_cache_key(day: str, score: int, streak_days: int, today_minutes: int) -> str:
    return f"sentient_log:{day}:{score}:{streak_days}:{today_minutes}"


def get_cached_sentient_log(
    conn: sqlite3.Connection,
    *,
    day: str,
    score: int,
    streak_days: int,
    today_minutes: int,
) -> str | None:
    return get_sync_state(conn, sentient_log_cache_key(day, score, streak_days, today_minutes))


def set_cached_sentient_log(
    conn: sqlite3.Connection,
    *,
    day: str,
    score: int,
    streak_days: int,
    today_minutes: int,
    text: str,
) -> None:
    set_sync_state(conn, sentient_log_cache_key(day, score, streak_days, today_minutes), text)


def rolling_window_minutes(
    conn: sqlite3.Connection,
    *,
    end_day: date,
    point_count: int = 30,
    window_days: int = 5,
) -> list[tuple[str, int]]:
    first_bar_day = end_day - timedelta(days=point_count - 1)
    first_needed_day = first_bar_day - timedelta(days=window_days - 1)
    minutes_by_day = daily_minutes_map(conn, start_day=first_needed_day, end_day=end_day)
    points: list[tuple[str, int]] = []
    for offset in range(point_count):
        bar_day = first_bar_day + timedelta(days=offset)
        total = 0
        for window_offset in range(window_days):
            day = bar_day - timedelta(days=window_days - 1 - window_offset)
            total += minutes_by_day.get(day.isoformat(), 0)
        points.append((bar_day.isoformat(), total))
    return points


def calculate_daily_score(
    conn: sqlite3.Connection,
    *,
    today: date | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
    scoring_config: ScoringConfig | None = None,
    persist: bool = True,
) -> DailyScore:
    local_today = today or datetime.now(get_timezone(timezone_name)).date()
    today_key = local_today.isoformat()
    config = scoring_config or ScoringConfig()

    recent_start = local_today - timedelta(days=config.recent_window_days - 1)
    baseline_start = local_today - timedelta(days=config.baseline_window_days - 1)

    recent_minutes = _sum_minutes_between(conn, recent_start, local_today)
    baseline_minutes = _sum_minutes_between(conn, baseline_start, local_today)
    baseline_daily_minutes = baseline_minutes / config.baseline_window_days
    expected_recent_minutes = max(
        float(config.min_expected_5_day_minutes),
        baseline_daily_minutes * config.recent_window_days,
    )
    score_value = (recent_minutes / expected_recent_minutes) * 100 if expected_recent_minutes else 0
    score = int(round(max(0, min(100, score_value))))

    previous = conn.execute(
        """
        SELECT streak_days
        FROM daily_state
        WHERE date < ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (today_key,),
    ).fetchone()
    previous_streak_days = int(previous["streak_days"]) if previous else 0
    activity_count = _activity_count_for_day(conn, local_today)
    streak_days = previous_streak_days + 1 if activity_count > 0 else 0

    if persist:
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
    return DailyScore(
        date=today_key,
        score=score,
        streak_days=streak_days,
        total_minutes=recent_minutes,
        recent_minutes=recent_minutes,
        baseline_daily_minutes=baseline_daily_minutes,
        expected_recent_minutes=expected_recent_minutes,
    )


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
    total_minutes = int(minutes_row["total_minutes"])
    return DailyScore(
        date=str(row["date"]),
        score=int(row["score"]),
        streak_days=int(row["streak_days"]),
        total_minutes=total_minutes,
        recent_minutes=total_minutes,
    )
