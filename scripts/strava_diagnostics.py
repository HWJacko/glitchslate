from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key, value.strip().strip("'\""))


def request_json(
    url: str,
    *,
    data: dict[str, str] | None = None,
    access_token: str | None = None,
) -> tuple[int, Any]:
    encoded_data = urllib.parse.urlencode(data).encode("utf-8") if data else None
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    request = urllib.request.Request(url, data=encoded_data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            payload: Any = json.loads(body)
        except json.JSONDecodeError:
            payload = body[:500]
        return exc.code, payload


def main() -> int:
    load_env()
    required = ["STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        print(f"missing: {', '.join(missing)}")
        return 2

    token_status, token_payload = request_json(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": os.environ["STRAVA_CLIENT_ID"],
            "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
            "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
    )
    print(f"token_exchange status={token_status}")
    if token_status != 200:
        print(f"token_error={token_payload}")
        return 1

    access_token = str(token_payload["access_token"])
    print(f"scope={token_payload.get('scope', '<not returned on refresh>')}")
    athlete = token_payload.get("athlete") or {}
    print(f"token_athlete_id={athlete.get('id', '<not returned on refresh>')}")
    print(f"expires_in={token_payload.get('expires_in', '<unknown>')}")

    athlete_status, athlete_payload = request_json(
        "https://www.strava.com/api/v3/athlete",
        access_token=access_token,
    )
    athlete_id = athlete_payload.get("id") if isinstance(athlete_payload, dict) else "<unavailable>"
    print(f"athlete status={athlete_status} id={athlete_id}")
    if athlete_status != 200:
        print(f"athlete_error={athlete_payload}")

    activities_status, activities_payload = request_json(
        "https://www.strava.com/api/v3/athlete/activities?per_page=5",
        access_token=access_token,
    )
    print(f"activities status={activities_status}")
    if activities_status == 200 and isinstance(activities_payload, list):
        for item in activities_payload:
            print(
                "activity "
                f"id={item.get('id')} type={item.get('type')} "
                f"sport_type={item.get('sport_type')} start_date={item.get('start_date')} "
                f"moving_time={item.get('moving_time')}"
            )
    else:
        print(f"activities_error={activities_payload}")

    return 0 if athlete_status == 200 and activities_status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
