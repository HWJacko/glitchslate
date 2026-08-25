from __future__ import annotations

import unittest

from known_workouts import parse_known_workout


class KnownWorkoutTests(unittest.TestCase):
    def test_cindy_round_submission_expands_to_bodyweight_exercises(self) -> None:
        parsed = parse_known_workout("CINDY 7 Rounds")

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(parsed["is_workout"])
        self.assertEqual(parsed["activity_type"], "bodyweight")
        self.assertEqual(parsed["duration_minutes"], 20)
        self.assertEqual(parsed["intensity"], "hard")
        self.assertEqual(
            parsed["exercises"],
            [
                {
                    "movement": "pullups",
                    "sets": 7,
                    "reps_per_set": 5,
                    "total_reps": 35,
                    "weight_kg": 0,
                    "bodyweight": True,
                    "movement_multiplier": 1,
                },
                {
                    "movement": "situps",
                    "sets": 7,
                    "reps_per_set": 10,
                    "total_reps": 70,
                    "weight_kg": 0,
                    "bodyweight": True,
                    "movement_multiplier": 1,
                },
                {
                    "movement": "standing squats",
                    "sets": 7,
                    "reps_per_set": 15,
                    "total_reps": 105,
                    "weight_kg": 0,
                    "bodyweight": True,
                    "movement_multiplier": 1,
                },
            ],
        )

    def test_unknown_text_returns_none(self) -> None:
        self.assertIsNone(parse_known_workout("45 min easy run"))


if __name__ == "__main__":
    unittest.main()
