from __future__ import annotations

import unittest

from sentient_log import _extract_output_text, build_sentient_prompt, fallback_sentient_log, sanitize_sentient_log


class SentientLogTests(unittest.TestCase):
    def test_sanitize_trims_to_limit(self) -> None:
        self.assertEqual(sanitize_sentient_log("  `hello   world`  "), "hello world")
        self.assertLessEqual(len(sanitize_sentient_log("x" * 100, max_chars=20)), 20)

    def test_prompt_contains_metrics(self) -> None:
        prompt = build_sentient_prompt(score=42, streak_days=3, today_minutes=0)
        self.assertIn("Current Score: 42/100", prompt)
        self.assertIn("Streak: 3 days", prompt)
        self.assertIn("Today's workout: 0 minutes", prompt)

    def test_extract_output_text_from_responses_payload(self) -> None:
        payload = {"output": [{"content": [{"text": "Systems nominal."}]}]}
        self.assertEqual(_extract_output_text(payload), "Systems nominal.")

    def test_fallback_is_single_line_and_bounded(self) -> None:
        text = fallback_sentient_log(score=10, streak_days=0, today_minutes=0, max_chars=45)
        self.assertNotIn("\n", text)
        self.assertLessEqual(len(text), 45)


if __name__ == "__main__":
    unittest.main()
