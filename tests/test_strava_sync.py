from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from db import connect, get_sync_state, init_db, set_sync_state
from strava_sync import sync_strava


class FakeHttpError(Exception):
    def __init__(self, status_code: int, response=None) -> None:
        self.response = response or type("FakeErrorResponse", (), {"status_code": status_code})()
        super().__init__(f"{status_code} Client Error")


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.post_calls = 0
        self.get_calls = 0
        self.post_data = []

    def post(self, url, data, timeout):
        self.post_calls += 1
        self.post_data.append(data)
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
        self.assertEqual(get_sync_state(self.conn, "strava_config_refresh_token"), "refresh-old")
        count = self.conn.execute("SELECT COUNT(*) AS count FROM activities").fetchone()["count"]
        self.assertEqual(count, 1)
        row = self.conn.execute("SELECT points FROM activities WHERE source = 'strava'").fetchone()
        self.assertEqual(row["points"], 1500)
        self.assertEqual(session.post_calls, 1)

    def test_rejected_cached_access_token_refreshes_and_retries_once(self) -> None:
        class RetrySession(FakeSession):
            def __init__(self) -> None:
                super().__init__()
                self.get_headers = []

            def get(self, url, headers, params, timeout):
                self.get_calls += 1
                self.get_headers.append(headers)
                if self.get_calls == 1:
                    raise FakeHttpError(401)
                return FakeResponse(
                    [
                        {
                            "id": 201,
                            "type": "Run",
                            "moving_time": 2400,
                            "start_date": "2026-07-15T06:00:00Z",
                        },
                    ]
                )

        session = RetrySession()
        current = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        set_sync_state(self.conn, "strava_access_token", "access-stale")
        set_sync_state(self.conn, "strava_refresh_token", "refresh-persisted")
        set_sync_state(self.conn, "strava_config_refresh_token", "refresh-persisted")
        set_sync_state(self.conn, "strava_token_expires_at", 2000000000)

        synced = sync_strava(
            self.conn,
            client_id="client",
            client_secret="secret",
            refresh_token_value="refresh-persisted",
            session=session,
            now=current,
        )

        self.assertEqual(synced, 1)
        self.assertEqual(session.post_calls, 1)
        self.assertEqual(session.get_calls, 2)
        self.assertEqual(session.get_headers[0]["Authorization"], "Bearer access-stale")
        self.assertEqual(session.get_headers[1]["Authorization"], "Bearer access-new")
        self.assertEqual(get_sync_state(self.conn, "strava_refresh_token"), "refresh-new")

    def test_changed_env_refresh_token_overrides_cached_token_state(self) -> None:
        session = FakeSession()
        current = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        set_sync_state(self.conn, "strava_access_token", "access-stale")
        set_sync_state(self.conn, "strava_refresh_token", "refresh-old-scope")
        set_sync_state(self.conn, "strava_config_refresh_token", "refresh-old-scope")
        set_sync_state(self.conn, "strava_token_expires_at", 2000000000)

        synced = sync_strava(
            self.conn,
            client_id="client",
            client_secret="secret",
            refresh_token_value="refresh-new-scope",
            session=session,
            now=current,
        )

        self.assertEqual(synced, 1)
        self.assertEqual(session.post_calls, 1)
        self.assertEqual(session.post_data[0]["refresh_token"], "refresh-new-scope")
        self.assertEqual(get_sync_state(self.conn, "strava_refresh_token"), "refresh-new")
        self.assertEqual(get_sync_state(self.conn, "strava_config_refresh_token"), "refresh-new-scope")

    def test_missing_activity_read_permission_has_actionable_error(self) -> None:
        class MissingScopeResponse(FakeResponse):
            def raise_for_status(self) -> None:
                raise FakeHttpError(401, self)

        class MissingScopeSession(FakeSession):
            def get(self, url, headers, params, timeout):
                self.get_calls += 1
                return MissingScopeResponse(
                    {
                        "message": "Authorization Error",
                        "errors": [
                            {
                                "resource": "AccessToken",
                                "field": "activity:read_permission",
                                "code": "missing",
                            }
                        ],
                    },
                    status_code=401,
                )

        session = MissingScopeSession()
        current = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

        with self.assertRaisesRegex(RuntimeError, "activity read permission"):
            sync_strava(
                self.conn,
                client_id="client",
                client_secret="secret",
                refresh_token_value="refresh-old",
                session=session,
                now=current,
            )


if __name__ == "__main__":
    unittest.main()
