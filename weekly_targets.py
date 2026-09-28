from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from config import WeeklyTargetConfig


TARGET_ALIASES = {
    "running": "run",
    "runs": "run",
    "cindy_sessions": "cindy",
    "short": "short_story",
    "shorts": "short_story",
    "short-story": "short_story",
    "main": "main_project",
    "project": "main_project",
    "main-project": "main_project",
    "socials": "social",
    "posts": "social",
    "nonfiction": "non_fiction",
    "non-fiction": "non_fiction",
    "nf": "non_fiction",
}
TARGET_POINTS_PER_COMPLETED_TARGET = 1000.0


@dataclass(frozen=True)
class WeeklyTarget:
    week_start: str
    key: str
    label: str
    target: float
    unit: str
    metric: str


@dataclass(frozen=True)
class WeeklyTargetProgress:
    week_start: str
    key: str
    label: str
    value: float
    target: float
    unit: str

    @property
    def percentage(self) -> float:
        if self.target <= 0:
            return 0.0
        return min(100.0, self.value / self.target * 100.0)

    @property
    def complete(self) -> bool:
        return self.value >= self.target


def week_start_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


def canonical_target_key(value: str) -> str:
    key = re.sub(r"\s+", "_", value.strip().lower())
    return TARGET_ALIASES.get(key, key)


def _default_map(defaults: Iterable[WeeklyTargetConfig]) -> dict[str, WeeklyTargetConfig]:
    return {canonical_target_key(item.key): item for item in defaults}


def ensure_weekly_targets(
    conn: sqlite3.Connection,
    defaults: Iterable[WeeklyTargetConfig],
    *,
    week_start: date,
) -> list[WeeklyTarget]:
    """Create this week's rows, inheriting the last configured week when possible."""
    week_key = week_start.isoformat()
    default_values = _default_map(defaults)
    existing = conn.execute(
        "SELECT target_key FROM weekly_targets WHERE week_start = ?",
        (week_key,),
    ).fetchall()
    existing_keys = {str(row["target_key"]) for row in existing}

    previous_rows = conn.execute(
        """
        SELECT target_key, label, target_value, unit, metric
        FROM weekly_targets
        WHERE week_start < ?
        ORDER BY week_start DESC
        """,
        (week_key,),
    ).fetchall()
    previous: dict[str, sqlite3.Row] = {}
    for row in previous_rows:
        previous.setdefault(str(row["target_key"]), row)

    for key, default in default_values.items():
        if key in existing_keys:
            continue
        inherited = previous.get(key)
        values = (
            str(inherited["label"]),
            float(inherited["target_value"]),
            str(inherited["unit"]),
            str(inherited["metric"]),
        ) if inherited is not None else (
            default.label,
            float(default.target),
            default.unit,
            default.metric,
        )
        conn.execute(
            """
            INSERT INTO weekly_targets (week_start, target_key, label, target_value, unit, metric)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_start, target_key) DO NOTHING
            """,
            (week_key, key, *values),
        )
    conn.commit()
    return list_weekly_targets(conn, week_start=week_start)


def list_weekly_targets(conn: sqlite3.Connection, *, week_start: date) -> list[WeeklyTarget]:
    rows = conn.execute(
        """
        SELECT week_start, target_key, label, target_value, unit, metric
        FROM weekly_targets
        WHERE week_start = ?
        ORDER BY rowid
        """,
        (week_start.isoformat(),),
    ).fetchall()
    return [
        WeeklyTarget(
            week_start=str(row["week_start"]),
            key=str(row["target_key"]),
            label=str(row["label"]),
            target=float(row["target_value"]),
            unit=str(row["unit"]),
            metric=str(row["metric"]),
        )
        for row in rows
    ]


def set_weekly_target(
    conn: sqlite3.Connection,
    defaults: Iterable[WeeklyTargetConfig],
    *,
    key: str,
    target: float,
    week_start: date,
) -> WeeklyTarget:
    if target <= 0:
        raise ValueError("weekly target must be positive")
    current = ensure_weekly_targets(conn, defaults, week_start=week_start)
    normalized_key = canonical_target_key(key)
    selected = next((item for item in current if item.key == normalized_key), None)
    if selected is None:
        raise ValueError(f"unknown weekly target: {key}")
    conn.execute(
        """
        UPDATE weekly_targets
        SET target_value = ?, updated_at = CURRENT_TIMESTAMP
        WHERE week_start = ? AND target_key = ?
        """,
        (float(target), week_start.isoformat(), normalized_key),
    )
    conn.commit()
    return next(item for item in list_weekly_targets(conn, week_start=week_start) if item.key == normalized_key)


def reset_weekly_targets(
    conn: sqlite3.Connection,
    defaults: Iterable[WeeklyTargetConfig],
    *,
    week_start: date,
) -> list[WeeklyTarget]:
    conn.execute("DELETE FROM weekly_targets WHERE week_start = ?", (week_start.isoformat(),))
    conn.commit()
    default_values = _default_map(defaults)
    for key, default in default_values.items():
        conn.execute(
            """
            INSERT INTO weekly_targets (week_start, target_key, label, target_value, unit, metric)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (week_start.isoformat(), key, default.label, float(default.target), default.unit, default.metric),
        )
    conn.commit()
    return list_weekly_targets(conn, week_start=week_start)


def _payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        value = json.loads(row["raw_payload"] or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _writing_words(row: sqlite3.Row) -> float:
    payload = _payload(row)
    if payload.get("day_words") is not None:
        return max(0.0, float(payload["day_words"]))
    points_per_word = payload.get("points_per_word")
    if points_per_word:
        return max(0.0, float(row["points"]) / float(points_per_word))
    return max(0.0, float(row["points"]))


def _run_distance_km(row: sqlite3.Row) -> float:
    payload = _payload(row)
    parser_result = payload.get("parser_result")
    if isinstance(parser_result, dict) and parser_result.get("distance_km") is not None:
        return max(0.0, float(parser_result["distance_km"]))
    if payload.get("distance_km") is not None:
        return max(0.0, float(payload["distance_km"]))
    if payload.get("distance") is not None:
        # Strava stores distance in metres.
        return max(0.0, float(payload["distance"]) / 1000.0)
    return 0.0


def _activity_metric_value(row: sqlite3.Row, target: WeeklyTarget) -> float:
    source = str(row["source"])
    activity_type = str(row["activity_type"] or "").lower()
    if target.metric == "distance_km":
        if source in {"strava", "telegram"} and activity_type in {"run", "running"}:
            return _run_distance_km(row)
        return 0.0
    if target.metric == "cindy_sessions":
        return 1.0 if source == "telegram" and "cindy" in str(row["notes"] or "").lower() else 0.0
    if target.metric == "social_posts":
        return 1.0 if source == "social" else 0.0
    if target.metric == "writing_words":
        if source == "writing" and canonical_target_key(activity_type) == target.key:
            return _writing_words(row)
        return 0.0
    return 0.0


def _target_value(conn: sqlite3.Connection, target: WeeklyTarget, *, week_start: date, end_day: date) -> float:
    rows = conn.execute(
        """
        SELECT source, activity_type, points, notes, raw_payload
        FROM activities
        WHERE local_date >= ? AND local_date <= ?
        ORDER BY local_date, id
        """,
        (week_start.isoformat(), end_day.isoformat()),
    ).fetchall()
    return sum(_activity_metric_value(row, target) for row in rows)


def weekly_target_progress(
    conn: sqlite3.Connection,
    defaults: Iterable[WeeklyTargetConfig],
    *,
    today: date,
) -> list[WeeklyTargetProgress]:
    start = week_start_for(today)
    targets = ensure_weekly_targets(conn, defaults, week_start=start)
    return [
        WeeklyTargetProgress(
            week_start=target.week_start,
            key=target.key,
            label=target.label,
            value=_target_value(conn, target, week_start=start, end_day=today),
            target=target.target,
            unit=target.unit,
        )
        for target in targets
    ]


def target_points_by_day(
    conn: sqlite3.Connection,
    defaults: Iterable[WeeklyTargetConfig],
    *,
    start_day: date,
    end_day: date,
) -> dict[str, dict[str, int]]:
    """Convert heterogeneous weekly inputs into comparable points.

    Completing one target contributes 1,000 points, so a 20 km run target,
    three CINDY sessions, or 1,000 words each have the same full-target value.
    """
    if end_day < start_day:
        return {}
    targets_by_week: dict[date, dict[str, WeeklyTarget]] = {}
    cursor = week_start_for(start_day)
    end_week = week_start_for(end_day)
    while cursor <= end_week:
        targets = ensure_weekly_targets(conn, defaults, week_start=cursor)
        targets_by_week[cursor] = {target.key: target for target in targets}
        cursor += timedelta(days=7)

    rows = conn.execute(
        """
        SELECT local_date, source, activity_type, points, notes, raw_payload
        FROM activities
        WHERE local_date >= ? AND local_date <= ?
        ORDER BY local_date, id
        """,
        (start_day.isoformat(), end_day.isoformat()),
    ).fetchall()
    values: dict[str, dict[str, int]] = {}
    for row in rows:
        day = date.fromisoformat(str(row["local_date"]))
        target_map = targets_by_week.get(week_start_for(day), {})
        for target in target_map.values():
            contribution = _activity_metric_value(row, target)
            if contribution <= 0:
                continue
            points = int(round(contribution / target.target * TARGET_POINTS_PER_COMPLETED_TARGET))
            day_values = values.setdefault(day.isoformat(), {})
            day_values[target.key] = day_values.get(target.key, 0) + points
    return values


def target_chart_points(
    conn: sqlite3.Connection,
    defaults: Iterable[WeeklyTargetConfig],
    *,
    end_day: date,
    point_count: int = 30,
    window_days: int = 3,
) -> list[dict[str, Any]]:
    first_bar_day = end_day - timedelta(days=point_count - 1)
    first_needed_day = first_bar_day - timedelta(days=window_days - 1)
    by_day = target_points_by_day(
        conn,
        defaults,
        start_day=first_needed_day,
        end_day=end_day,
    )
    points: list[dict[str, Any]] = []
    max_total = 0
    for offset in range(point_count):
        bar_day = first_bar_day + timedelta(days=offset)
        buckets: dict[str, int] = {}
        for window_offset in range(window_days):
            day = bar_day - timedelta(days=window_days - 1 - window_offset)
            for bucket, value in by_day.get(day.isoformat(), {}).items():
                buckets[bucket] = buckets.get(bucket, 0) + value
        total = sum(buckets.values())
        max_total = max(max_total, total)
        points.append({
            "day": bar_day.isoformat(),
            "run_points": buckets.get("run", 0),
            "other_points": sum(value for bucket, value in buckets.items() if bucket != "run"),
            "total_points": total,
            "is_best": False,
            "bucket_points": buckets,
        })
    if max_total:
        for point in points:
            point["is_best"] = point["total_points"] == max_total
    return points


def target_baseline_points(
    target_count: int,
    *,
    window_days: int,
    baseline_fraction: float = 0.8,
) -> float:
    """Return the rolling-window point equivalent of the weekly baseline."""
    if target_count <= 0:
        return 0.0
    return (
        target_count
        * TARGET_POINTS_PER_COMPLETED_TARGET
        * baseline_fraction
        * window_days
        / 7.0
    )


def next_target_priority(progress: Iterable[WeeklyTargetProgress], *, today: date) -> str | None:
    items = list(progress)
    incomplete = [item for item in items if not item.complete]
    if not incomplete:
        return "NEXT PRIORITY: All weekly targets met."
    selected = min(incomplete, key=lambda item: (item.percentage, items.index(item)))
    remaining = max(0.0, selected.target - selected.value)
    days_left = max(1, 7 - today.weekday())
    daily_pace = remaining / days_left
    current_value = float(selected.value)
    target_value = float(selected.target)
    current = int(current_value) if current_value.is_integer() else round(current_value, 1)
    target = int(target_value) if target_value.is_integer() else round(target_value, 1)
    remaining_display = int(remaining) if float(remaining).is_integer() else round(float(remaining), 1)
    pace_display = int(daily_pace) if float(daily_pace).is_integer() else round(float(daily_pace), 1)
    if current == 0:
        state = "no contribution yet"
    else:
        state = f"{current}/{target} {selected.unit}"
    return (
        f"NEXT PRIORITY: {selected.label} — {state}; "
        f"{remaining_display} {selected.unit} remaining, aim for about "
        f"{pace_display} {selected.unit}/day through Sunday."
    )


def format_weekly_targets(progress: Iterable[WeeklyTargetProgress]) -> str:
    items = list(progress)
    if not items:
        return "No weekly targets configured."
    lines = [f"WEEKLY TARGETS // WEEK OF {items[0].week_start}"]
    for item in items:
        value_number = float(item.value)
        target_number = float(item.target)
        value = int(value_number) if value_number.is_integer() else round(value_number, 1)
        target = int(target_number) if target_number.is_integer() else round(target_number, 1)
        lines.append(f"{item.label}: {value}/{target} {item.unit} ({item.percentage:.0f}%)")
    return "\n".join(lines)
