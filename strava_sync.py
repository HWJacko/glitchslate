from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from config import get_timezone, load_dotenv
from db import Activity, connect, get_sync_state, init_db, set_sync_state, upsert_activity


STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"


def _requests_session():
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests is required for Strava sync") from exc
    return requests


def refresh_token(
    conn,
    *,
    client_id: str,
    client_secret: str,
    refresh_token_value: str,
    session: Any | None = None,
) -> str:
    http = session or _requests_session()
    response = http.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token_value,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    access_token = str(payload["access_token"])
    set_sync_state(conn, "strava_access_token", access_token)
    set_sync_state(conn, "strava_refresh_token", str(payload.get("refresh_token", refresh_token_value)))
    set_sync_state(conn, "strava_token_expires_at", str(payload.get("expires_at", 0)))
    return access_token


def get_access_token(
    conn,
    *,
    client_id: str,
    client_secret: str,
    env_refresh_token: str,
    session: Any | None = None,
    now: datetime | None = None,
) -> str:
    current_time = int((now or datetime.now(timezone.utc)).timestamp())
    persisted_token = get_sync_state(conn, "strava_access_token")
    expires_at = int(get_sync_state(conn, "strava_token_expires_at") or "0")
    if persisted_token and expires_at > current_time + 60:
        return persisted_token

    refresh_token_value = get_sync_state(conn, "strava_refresh_token") or env_refresh_token
    return refresh_token(
        conn,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token_value=refresh_token_value,
        session=session,
    )


def fetch_activities(
    access_token: str,
    *,
    after: datetime,
    session: Any | None = None,
) -> list[dict[str, Any]]:
    http = session or _requests_session()
    response = http.get(
        STRAVA_ACTIVITIES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"after": int(after.timestamp()), "per_page": 100},
        timeout=30,
    )
    response.raise_for_status()
    return list(response.json())


def _parse_strava_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def sync_strava(
    conn,
    *,
    client_id: str,
    client_secret: str,
    refresh_token_value: str,
    session: Any | None = None,
    dry_run: bool = False,
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> int:
    local_tz = get_timezone(timezone_name)
    current = now or datetime.now(timezone.utc)
    after = current.astimezone(local_tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)

    token = get_access_token(
        conn,
        client_id=client_id,
        client_secret=client_secret,
        env_refresh_token=refresh_token_value,
        session=session,
        now=current,
    )
    activities = fetch_activities(token, after=after.astimezone(timezone.utc), session=session)
    inserted = 0

    for item in activities:
        if item.get("type") != "Run":
            continue
        duration_minutes = int(item.get("moving_time") or 0) // 60
        if duration_minutes <= 0:
            continue
        timestamp = _parse_strava_timestamp(str(item.get("start_date")))
        if dry_run:
            print(f"strava:{item.get('id')}: run {duration_minutes} minutes at {timestamp.isoformat()}")
            continue
        activity = Activity(
            source="strava",
            external_id=str(item["id"]),
            timestamp=timestamp,
            activity_type="run",
            duration_minutes=duration_minutes,
            raw_payload=item,
        )
        upsert_activity(conn, activity, tz=local_tz)
        inserted += 1
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Strava runs.")
    parser.add_argument("--db", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    refresh_token_value = os.getenv("STRAVA_REFRESH_TOKEN")
    if not client_id or not client_secret or not refresh_token_value:
        print("STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, and STRAVA_REFRESH_TOKEN are required", file=sys.stderr)
        return 2

    conn = connect(args.db)
    init_db(conn)
    try:
        count = sync_strava(
            conn,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token_value=refresh_token_value,
            dry_run=args.dry_run,
            timezone_name=os.getenv("LOCAL_TIMEZONE"),
        )
    except Exception as exc:
        print(f"Strava sync failed: {exc}", file=sys.stderr)
        return 1
    print(f"strava synced {count} run activity records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
