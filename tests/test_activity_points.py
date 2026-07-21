from __future__ import annotations

import unittest

from activity_points import calculate_telegram_points


class ActivityPointsTests(unittest.TestCase):
    def test_bodyweight_reps_use_rep_value_not_default_weight_load(self) -> None:
        points, components = calculate_telegram_points(
            {
                "exercises": [
                    {
                        "movement": "press-ups",
                        "sets": 1,
                        "reps_per_set": 50,
                        "total_reps": 50,
                        "weight_kg": 0,
                        "bodyweight": True,
                        "movement_multiplier": 1,
                    },
                    {
                        "movement": "sit-ups",
                        "sets": 1,
                        "reps_per_set": 100,
                        "total_reps": 100,
                        "weight_kg": 0,
                        "bodyweight": True,
                        "movement_multiplier": 1,
                    },
                ]
            },
            duration_minutes=10,
            intensity="moderate",
        )

        self.assertEqual(points, 450)
        self.assertEqual(components["method"], "telegram_reps_weight")


if __name__ == "__main__":
    unittest.main()
