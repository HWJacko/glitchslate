from __future__ import annotations

import re
from typing import Any


KNOWN_WORKOUTS: dict[str, dict[str, Any]] = {
    "cindy": {
        "display_name": "CINDY",
        "activity_type": "bodyweight",
        "duration_minutes": 20,
        "intensity": "hard",
        "round_movements": [
            ("pullups", 5),
            ("situps", 10),
            ("standing squats", 15),
        ],
    },
}


ROUND_SUBMISSION_RE = re.compile(
    r"\b(?P<name>cindy)\b(?:\s*[:=-]?\s*|\s+)(?P<rounds>\d+)\s*(?:rounds?|rds?)\b",
    re.IGNORECASE,
)


def parse_known_workout(text: str) -> dict[str, Any] | None:
    match = ROUND_SUBMISSION_RE.search(text)
    if match is None:
        return None

    workout = KNOWN_WORKOUTS.get(match.group("name").lower())
    if workout is None:
        return None

    rounds = int(match.group("rounds"))
    if rounds <= 0:
        return None

    display_name = str(workout["display_name"])
    exercises = [
        {
            "movement": movement,
            "sets": rounds,
            "reps_per_set": reps_per_round,
            "total_reps": rounds * reps_per_round,
            "weight_kg": 0,
            "bodyweight": True,
            "movement_multiplier": 1,
        }
        for movement, reps_per_round in workout["round_movements"]
    ]

    return {
        "is_workout": True,
        "activity_type": workout["activity_type"],
        "duration_minutes": workout["duration_minutes"],
        "intensity": workout["intensity"],
        "notes": f"{display_name} {rounds} rounds",
        "exercises": exercises,
    }
