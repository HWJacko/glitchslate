from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from db import connect, get_sync_state, init_db
from telegram_sync import _request_get, get_workout_parser, parse_workout_with_openai, sync_telegram


class FakeOpenAIResponses:
    def __init__(self) -> None:
        self.call = None

    def create(self, **kwargs):
        self.call = kwargs
        return type(
            "FakeOpenAIResponse",
            (),
            {
                "output_text": (
                    '{"is_workout":true,"activity_type":"strength",'
                    '"duration_minutes":45,"intensity":"medium","notes":"Upper body",'
                    '"exercises":[]}'
                )
            },
        )()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeOpenAIResponses()


class TelegramSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmpdir.name) / "test.db")
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def test_unauthorized_user_is_ignored_before_parsing(self) -> None:
        def request_get(url, params, timeout):
            return {
                "ok": True,
                "result": [
                    {
                        "update_id": 5,
                        "message": {
                            "message_id": 10,
                            "date": 1783929600,
                            "from": {"id": 999},
                            "text": "45 minutes strength",
                        },
                    }
                ],
            }

        def parser(text):
            raise AssertionError("parser should not be called for unauthorized users")

        count = sync_telegram(
            self.conn,
            token="token",
            allowed_user_id=123,
            parser=parser,
            request_get=request_get,
        )
        self.assertEqual(count, 0)
        self.assertEqual(get_sync_state(self.conn, "telegram_last_update_id"), "5")

    def test_authorized_message_persists_offset_and_activity(self) -> None:
        def request_get(url, params, timeout):
            self.assertNotIn("offset", params)
            return {
                "ok": True,
                "result": [
                    {
                        "update_id": 8,
                        "message": {
                            "message_id": 77,
                            "date": 1783929600,
                            "from": {"id": 123},
                            "text": "45 minutes strength",
                        },
                    }
                ],
            }

        def parser(text):
            return {
                "is_workout": True,
                "activity_type": "strength",
                "duration_minutes": 45,
                "intensity": "medium",
                "notes": "Upper body",
                "exercises": [
                    {
                        "movement": "curl",
                        "sets": 3,
                        "reps_per_set": 10,
                        "total_reps": 30,
                        "weight_kg": 10,
                        "bodyweight": False,
                        "movement_multiplier": 1,
                    }
                ],
            }

        count = sync_telegram(
            self.conn,
            token="token",
            allowed_user_id=123,
            parser=parser,
            request_get=request_get,
        )
        self.assertEqual(count, 1)
        self.assertEqual(get_sync_state(self.conn, "telegram_last_update_id"), "8")
        row = self.conn.execute("SELECT * FROM activities WHERE source = 'telegram'").fetchone()
        self.assertEqual(row["external_id"], "77")
        self.assertEqual(row["duration_minutes"], 45)
        self.assertEqual(row["points"], 300)


    def test_dry_run_does_not_persist_offset_or_activity(self) -> None:
        def request_get(url, params, timeout):
            return {
                "ok": True,
                "result": [
                    {
                        "update_id": 9,
                        "message": {
                            "message_id": 78,
                            "date": 1783929600,
                            "from": {"id": 123},
                            "text": "45 minutes strength",
                        },
                    }
                ],
            }

        count = sync_telegram(
            self.conn,
            token="token",
            allowed_user_id=123,
            parser=lambda text: {"is_workout": True, "duration_minutes": 45},
            request_get=request_get,
            dry_run=True,
        )
        self.assertEqual(count, 0)
        self.assertIsNone(get_sync_state(self.conn, "telegram_last_update_id"))
        rows = self.conn.execute("SELECT COUNT(*) AS count FROM activities").fetchone()
        self.assertEqual(rows["count"], 0)

    def test_openai_parser_uses_structured_output_schema(self) -> None:
        client = FakeOpenAIClient()
        parsed = parse_workout_with_openai("45 minutes strength", client=client, model="test-model")
        self.assertTrue(parsed["is_workout"])
        self.assertEqual(parsed["duration_minutes"], 45)
        self.assertEqual(client.responses.call["model"], "test-model")
        self.assertEqual(client.responses.call["text"]["format"]["type"], "json_schema")
        self.assertEqual(client.responses.call["text"]["format"]["name"], "workout_checkin")

    def test_provider_selection_prefers_openai_when_key_exists(self) -> None:
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "test-key", "WORKOUT_PARSER_PROVIDER": ""},
            clear=False,
        ):
            self.assertIs(get_workout_parser(), parse_workout_with_openai)

    def test_telegram_request_error_does_not_expose_bot_url(self) -> None:
        import requests

        tokenized_url = "https://api.telegram.org/botsecret-token/getUpdates"
        with patch("requests.get", side_effect=requests.ConnectionError(tokenized_url)):
            with self.assertRaises(RuntimeError) as raised:
                _request_get(tokenized_url, {}, 1)
        self.assertEqual(str(raised.exception), "Telegram API request failed")
        self.assertIsNone(raised.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
