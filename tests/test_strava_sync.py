from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from db import connect, get_sync_state, init_db
from strava_sync import sync_strava


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.post_calls = 0
        self.get_calls = 0

    def post(self, url, data, timeout):
        self.post_calls += 1
        return FakeResponse(
            {
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "expires_at": 2000000000,
            }
        )

    def get(self, url, headers, params, timeout):
        self.get_calls += 1
        return FakeResponse(
            [
                {
                    "id": 101,
                    "type": "Run",
                    "moving_time": 1800,
                    "start_date": "2026-07-13T06:00:00Z",
                },
                {
                    "id": 102,
                    "type": "Ride",
                    "moving_time": 3600,
                    "start_date": "2026-07-13T07:00:00Z",
                },
            ]
        )


class StravaSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmpdir.name) / "test.db")
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def test_token_refresh_persists_updated_tokens_and_duplicate_runs_do_not_duplicate(self) -> None:
        session = FakeSession()
        current = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
        first = sync_strava(
            self.conn,
            client_id="client",
            client_secret="secret",
            refresh_token_value="refresh-old",
            session=session,
            now=current,
        )
        second = sync_strava(
            self.conn,
            client_id="client",
            client_secret="secret",
            refresh_token_value="refresh-old",
            session=session,
            now=current,
        )
        self.assertEqual(first, 1)
        self.assertEqual(second, 1)
        self.assertEqual(get_sync_state(self.conn, "strava_access_token"), "access-new")
        self.assertEqual(get_sync_state(self.conn, "strava_refresh_token"), "refresh-new")
        count = self.conn.execute("SELECT COUNT(*) AS count FROM activities").fetchone()["count"]
        self.assertEqual(count, 1)
        self.assertEqual(session.post_calls, 1)


if __name__ == "__main__":
    unittest.main()
