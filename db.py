from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from activity_points import FORMULA_VERSION, calculate_activity_points
from config import DEFAULT_TIMEZONE, ScoringConfig, get_db_path, get_timezone


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


@dataclass(frozen=True)
class Activity:
    source: str
    external_id: str
    timestamp: datetime
    activity_type: str | None
    duration_minutes: int
    points: float | None = None
    intensity: str | None = None
    notes: str | None = None
    raw_payload: dict[str, Any] | list[Any] | str | None = None
    point_components: dict[str, Any] | list[Any] | str | None = None


@dataclass(frozen=True)
class DailyScore:
    date: str
    score: int
    streak_days: int
    total_points: int
    recent_points: int = 0
    baseline_daily_points: float = 0.0
    expected_recent_points: float = 0.0
    total_minutes: int = 0
    recent_minutes: int = 0
    baseline_daily_minutes: float = 0.0
    expected_recent_minutes: float = 0.0
    streak_pending: bool = False


@dataclass(frozen=True)
class DailyChartPoint:
    day: str
    run_points: int
    other_points: int
    total_points: int
    is_best: bool = False


@dataclass(frozen=True)
class LastRunDetails:
    day: str
    distance_km: float
    duration_minutes: int
    pace_min_per_km: float
    points: int
    elevation_m: float = 0.0


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = get_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate_schema(conn)
    backfill_activity_points(conn)
    conn.commit()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "activities")
    if "points" not in columns:
        conn.execute("ALTER TABLE activities ADD COLUMN points REAL NOT NULL DEFAULT 0")
    if "point_components" not in columns:
        conn.execute("ALTER TABLE activities ADD COLUMN point_components TEXT")


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


def _deserialize_payload(payload: str | None) -> dict[str, Any] | list[Any] | str | None:
    if payload is None:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload


def _points_for_row(row: sqlite3.Row) -> tuple[float, dict[str, Any]]:
    return calculate_activity_points(
        source=str(row["source"]),
        activity_type=row["activity_type"],
        duration_minutes=int(row["duration_minutes"]),
        intensity=row["intensity"],
        raw_payload=_deserialize_payload(row["raw_payload"]),
    )


def backfill_activity_points(conn: sqlite3.Connection) -> int:
    if not {"points", "point_components"}.issubset(_table_columns(conn, "activities")):
        return 0
    rows = conn.execute(
        """
        SELECT id, source, activity_type, duration_minutes, intensity, raw_payload
        FROM activities
        """
    ).fetchall()
    updated = 0
    for row in rows:
        current = conn.execute(
            "SELECT points, point_components FROM activities WHERE id = ?",
            (row["id"],),
        ).fetchone()
        current_components = _deserialize_payload(current["point_components"])
        current_version = 0
        if isinstance(current_components, dict):
            try:
                current_version = int(current_components.get("formula_version") or 0)
            except (TypeError, ValueError):
                current_version = 0
        if float(current["points"] or 0) > 0 and current_version >= FORMULA_VERSION:
            continue
        points, components = _points_for_row(row)
        conn.execute(
            """
            UPDATE activities
            SET points = ?, point_components = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (points, _serialize_payload(components), row["id"]),
        )
        updated += 1
    if updated:
        conn.commit()
    return updated


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
    if activity.points is None:
        points, point_components = calculate_activity_points(
            source=activity.source,
            activity_type=activity.activity_type,
            duration_minutes=activity.duration_minutes,
            intensity=activity.intensity,
            raw_payload=activity.raw_payload,
        )
    else:
        points = activity.points
        point_components = activity.point_components or {"method": "provided"}
    serialized_point_components = _serialize_payload(point_components)
    cursor = conn.execute(
        """
        INSERT INTO activities (
            source, external_id, timestamp, local_date, activity_type,
            duration_minutes, points, point_components, intensity, notes, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
            timestamp = excluded.timestamp,
            local_date = excluded.local_date,
            activity_type = excluded.activity_type,
            duration_minutes = excluded.duration_minutes,
            points = excluded.points,
            point_components = excluded.point_components,
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
            points,
            serialized_point_components,
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


def _sum_points_between(conn: sqlite3.Connection, start_day: date, end_day: date) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(points), 0) AS total_points
        FROM activities
        WHERE local_date >= ? AND local_date <= ?
        """,
        (start_day.isoformat(), end_day.isoformat()),
    ).fetchone()
    return float(row["total_points"])


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


def daily_points_map(
    conn: sqlite3.Connection,
    *,
    start_day: date,
    end_day: date,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT local_date, COALESCE(SUM(points), 0) AS total_points
        FROM activities
        WHERE local_date >= ? AND local_date <= ?
        GROUP BY local_date
        """,
        (start_day.isoformat(), end_day.isoformat()),
    ).fetchall()
    return {str(row["local_date"]): int(round(float(row["total_points"]))) for row in rows}


def daily_source_points(
    conn: sqlite3.Connection,
    *,
    start_day: date,
    end_day: date,
) -> dict[str, dict[str, int]]:
    rows = conn.execute(
        """
        SELECT
            local_date,
            CASE
                WHEN source = 'strava' AND LOWER(COALESCE(activity_type, '')) = 'run' THEN 'run'
                ELSE 'other'
            END AS bucket,
            COALESCE(SUM(points), 0) AS total_points
        FROM activities
        WHERE local_date >= ? AND local_date <= ?
        GROUP BY local_date, bucket
        """,
        (start_day.isoformat(), end_day.isoformat()),
    ).fetchall()
    values: dict[str, dict[str, int]] = {}
    for row in rows:
        day = str(row["local_date"])
        bucket = str(row["bucket"])
        values.setdefault(day, {"run": 0, "other": 0})[bucket] = int(round(float(row["total_points"])))
    return values


def minutes_for_day(conn: sqlite3.Connection, day: date) -> int:
    return _sum_minutes_between(conn, day, day)


def points_for_day(conn: sqlite3.Connection, day: date) -> int:
    return int(round(_sum_points_between(conn, day, day)))


def current_gap_days(conn: sqlite3.Connection, *, end_day: date) -> int:
    gap = 0
    current = end_day
    while True:
        if points_for_day(conn, current) > 0:
            return gap
        gap += 1
        current = current - timedelta(days=1)
        if gap > 365:
            return gap


def sentient_log_cache_key(day: str, score: int, streak_days: int, today_points: int) -> str:
    return f"sentient_log:{day}:{score}:{streak_days}:{today_points}"


def get_cached_sentient_log(
    conn: sqlite3.Connection,
    *,
    day: str,
    score: int,
    streak_days: int,
    today_points: int,
) -> str | None:
    return get_sync_state(conn, sentient_log_cache_key(day, score, streak_days, today_points))


def set_cached_sentient_log(
    conn: sqlite3.Connection,
    *,
    day: str,
    score: int,
    streak_days: int,
    today_points: int,
    text: str,
) -> None:
    set_sync_state(conn, sentient_log_cache_key(day, score, streak_days, today_points), text)


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


def rolling_window_points(
    conn: sqlite3.Connection,
    *,
    end_day: date,
    point_count: int = 30,
    window_days: int = 5,
) -> list[tuple[str, int]]:
    first_bar_day = end_day - timedelta(days=point_count - 1)
    first_needed_day = first_bar_day - timedelta(days=window_days - 1)
    points_by_day = daily_points_map(conn, start_day=first_needed_day, end_day=end_day)
    rolling_points: list[tuple[str, int]] = []
    for offset in range(point_count):
        bar_day = first_bar_day + timedelta(days=offset)
        total = 0
        for window_offset in range(window_days):
            day = bar_day - timedelta(days=window_days - 1 - window_offset)
            total += points_by_day.get(day.isoformat(), 0)
        rolling_points.append((bar_day.isoformat(), total))
    return rolling_points


def daily_chart_points(
    conn: sqlite3.Connection,
    *,
    end_day: date,
    point_count: int = 30,
) -> list[DailyChartPoint]:
    first_day = end_day - timedelta(days=point_count - 1)
    by_day = daily_source_points(conn, start_day=first_day, end_day=end_day)
    points: list[DailyChartPoint] = []
    max_total = 0
    for offset in range(point_count):
        day = first_day + timedelta(days=offset)
        values = by_day.get(day.isoformat(), {"run": 0, "other": 0})
        run_points = values.get("run", 0)
        other_points = values.get("other", 0)
        total = run_points + other_points
        max_total = max(max_total, total)
        points.append(
            DailyChartPoint(
                day=day.isoformat(),
                run_points=run_points,
                other_points=other_points,
                total_points=total,
            )
        )
    if max_total <= 0:
        return points
    return [
        DailyChartPoint(
            day=point.day,
            run_points=point.run_points,
            other_points=point.other_points,
            total_points=point.total_points,
            is_best=point.total_points == max_total,
        )
        for point in points
    ]


def get_last_run_details(conn: sqlite3.Connection) -> LastRunDetails | None:
    row = conn.execute(
        """
        SELECT local_date, duration_minutes, points, raw_payload, point_components
        FROM activities
        WHERE source = 'strava' AND LOWER(COALESCE(activity_type, '')) = 'run'
        ORDER BY timestamp DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    payload = _deserialize_payload(row["raw_payload"])
    components = _deserialize_payload(row["point_components"])
    distance_m = float(payload.get("distance") or 0) if isinstance(payload, dict) else 0.0
    elevation_m = float(payload.get("total_elevation_gain") or 0) if isinstance(payload, dict) else 0.0
    pace = 0.0
    if isinstance(components, dict):
        try:
            pace = float(components.get("pace_min_per_km") or 0)
        except (TypeError, ValueError):
            pace = 0.0
    return LastRunDetails(
        day=str(row["local_date"]),
        distance_km=round(distance_m / 1000.0, 2),
        duration_minutes=int(row["duration_minutes"]),
        pace_min_per_km=pace,
        points=int(round(float(row["points"]))),
        elevation_m=round(elevation_m, 1),
    )


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

    today_points = _sum_points_between(conn, local_today, local_today)
    baseline_points = _sum_points_between(conn, baseline_start, local_today)
    today_minutes = _sum_minutes_between(conn, local_today, local_today)
    baseline_minutes = _sum_minutes_between(conn, baseline_start, local_today)
    baseline_daily_points = baseline_points / config.baseline_window_days
    baseline_daily_minutes = baseline_minutes / config.baseline_window_days
    expected_today_points = max(
        float(config.min_expected_5_day_points) / max(1, config.recent_window_days),
        baseline_daily_points,
    )
    expected_today_minutes = max(
        float(config.min_expected_5_day_minutes) / max(1, config.recent_window_days),
        baseline_daily_minutes,
    )
    score_value = (today_points / expected_today_points) * 100 if expected_today_points else 0
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
    achieved_streak_days = previous_streak_days + 1 if activity_count > 0 else 0
    streak_pending = activity_count == 0 and previous_streak_days > 0
    display_streak_days = achieved_streak_days if activity_count > 0 else previous_streak_days + 1 if streak_pending else 0

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
            (today_key, score, achieved_streak_days),
        )
        conn.commit()
    return DailyScore(
        date=today_key,
        score=score,
        streak_days=display_streak_days,
        total_points=int(round(today_points)),
        recent_points=int(round(today_points)),
        baseline_daily_points=baseline_daily_points,
        expected_recent_points=expected_today_points,
        total_minutes=today_minutes,
        recent_minutes=today_minutes,
        baseline_daily_minutes=baseline_daily_minutes,
        expected_recent_minutes=expected_today_minutes,
        streak_pending=streak_pending,
    )


def get_daily_score(conn: sqlite3.Connection, day: date | None = None) -> DailyScore | None:
    day_key = (day or date.today()).isoformat()
    row = conn.execute(
        "SELECT date, score, streak_days FROM daily_state WHERE date = ?",
        (day_key,),
    ).fetchone()
    if row is None:
        return None
    totals_row = conn.execute(
        "SELECT COALESCE(SUM(duration_minutes), 0) AS total_minutes, COALESCE(SUM(points), 0) AS total_points FROM activities WHERE local_date = ?",
        (day_key,),
    ).fetchone()
    total_minutes = int(totals_row["total_minutes"])
    total_points = int(round(float(totals_row["total_points"])))
    return DailyScore(
        date=str(row["date"]),
        score=int(row["score"]),
        streak_days=int(row["streak_days"]),
        total_points=total_points,
        recent_points=total_points,
        total_minutes=total_minutes,
        recent_minutes=total_minutes,
    )
