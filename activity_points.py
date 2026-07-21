from __future__ import annotations

import math
from typing import Any


DEFAULT_GENERIC_MINUTE_VALUE = 30.0
DEFAULT_RUNNING_MINUTE_VALUE = 50.0
DEFAULT_BODYWEIGHT_REP_VALUE = 3.0
FORMULA_VERSION = 2


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _int(value: Any, default: int = 0) -> int:
    return int(round(_number(value, float(default))))


def _intensity_multiplier(intensity: str | None) -> float:
    normalized = (intensity or "").strip().lower()
    if normalized in {"hard", "high", "heavy", "intense"}:
        return 1.25
    if normalized in {"easy", "low", "light"}:
        return 0.8
    return 1.0


def _pace_multiplier(pace_min_per_km: float) -> float:
    if pace_min_per_km <= 0:
        return 1.0
    if pace_min_per_km < 4.5:
        return 1.3
    if pace_min_per_km < 5.5:
        return 1.15
    if pace_min_per_km <= 7.0:
        return 1.0
    return 0.85


def calculate_strava_run_points(payload: dict[str, Any], duration_minutes: int) -> tuple[float, dict[str, Any]]:
    moving_seconds = _number(payload.get("moving_time"), duration_minutes * 60.0)
    moving_minutes = max(duration_minutes, moving_seconds / 60.0)
    distance_m = _number(payload.get("distance"))
    elevation_m = max(0.0, _number(payload.get("total_elevation_gain")))
    pace_min_per_km = 0.0
    if distance_m > 0 and moving_seconds > 0:
        pace_min_per_km = moving_seconds / 60.0 / (distance_m / 1000.0)

    pace_value = _pace_multiplier(pace_min_per_km)
    elevation_value = 1.0
    if distance_m > 0:
        elevation_value += min((elevation_m / distance_m) * 10.0, 0.25)

    sport_type = str(payload.get("sport_type") or payload.get("type") or "")
    terrain_value = 1.1 if sport_type.lower() == "trailrun" else 1.0
    running_value = DEFAULT_RUNNING_MINUTE_VALUE * pace_value * elevation_value * terrain_value
    points = moving_minutes * running_value
    return round(points, 1), {
        "method": "strava_run",
        "formula_version": FORMULA_VERSION,
        "moving_minutes": round(moving_minutes, 2),
        "distance_m": round(distance_m, 1),
        "pace_min_per_km": round(pace_min_per_km, 2),
        "elevation_m": round(elevation_m, 1),
        "running_value": round(running_value, 2),
        "pace_multiplier": pace_value,
        "elevation_multiplier": round(elevation_value, 3),
        "terrain_multiplier": terrain_value,
    }


def _exercise_points(exercise: dict[str, Any]) -> float:
    total_reps = _int(exercise.get("total_reps"))
    if total_reps <= 0:
        total_reps = max(1, _int(exercise.get("sets"), 1)) * _int(exercise.get("reps_per_set"))
    if total_reps <= 0:
        return 0.0

    movement_multiplier = max(0.1, _number(exercise.get("movement_multiplier"), 1.0))
    if bool(exercise.get("bodyweight")):
        return total_reps * DEFAULT_BODYWEIGHT_REP_VALUE * movement_multiplier

    weight_kg = _number(exercise.get("weight_kg"))
    if weight_kg <= 0:
        return 0.0

    return total_reps * weight_kg * movement_multiplier


def calculate_telegram_points(
    parser_result: dict[str, Any],
    *,
    duration_minutes: int,
    intensity: str | None,
) -> tuple[float, dict[str, Any]]:
    exercises = parser_result.get("exercises")
    exercise_points = 0.0
    exercise_count = 0
    if isinstance(exercises, list):
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            value = _exercise_points(exercise)
            if value <= 0:
                continue
            exercise_points += value
            exercise_count += 1

    if exercise_points > 0:
        return round(exercise_points, 1), {
            "method": "telegram_reps_weight",
            "formula_version": FORMULA_VERSION,
            "exercise_count": exercise_count,
        }

    minute_value = DEFAULT_GENERIC_MINUTE_VALUE * _intensity_multiplier(intensity)
    return round(duration_minutes * minute_value, 1), {
        "method": "telegram_duration",
        "formula_version": FORMULA_VERSION,
        "duration_minutes": duration_minutes,
        "minute_value": round(minute_value, 2),
    }


def calculate_activity_points(
    *,
    source: str,
    activity_type: str | None,
    duration_minutes: int,
    intensity: str | None,
    raw_payload: dict[str, Any] | list[Any] | str | None,
) -> tuple[float, dict[str, Any]]:
    if source == "strava" and isinstance(raw_payload, dict):
        if str(raw_payload.get("type") or activity_type).lower() == "run":
            return calculate_strava_run_points(raw_payload, duration_minutes)

    if source == "telegram" and isinstance(raw_payload, dict):
        parser_result = raw_payload.get("parser_result")
        if isinstance(parser_result, dict):
            return calculate_telegram_points(
                parser_result,
                duration_minutes=duration_minutes,
                intensity=intensity,
            )

    minute_value = DEFAULT_GENERIC_MINUTE_VALUE * _intensity_multiplier(intensity)
    return round(duration_minutes * minute_value, 1), {
        "method": "duration_fallback",
        "formula_version": FORMULA_VERSION,
        "duration_minutes": duration_minutes,
        "minute_value": round(minute_value, 2),
    }
