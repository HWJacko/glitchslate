from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable

from config import get_timezone, load_dotenv
from db import Activity, connect, get_sync_state, init_db, set_sync_state, upsert_activity


TELEGRAM_API_BASE = "https://api.telegram.org"


ParsedWorkout = dict[str, Any]
Parser = Callable[[str], ParsedWorkout]


WORKOUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_workout": {"type": "boolean"},
        "activity_type": {"type": "string"},
        "duration_minutes": {"type": "integer"},
        "intensity": {"type": "string"},
        "notes": {"type": "string"},
        "exercises": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "movement": {"type": "string"},
                    "sets": {"type": "integer"},
                    "reps_per_set": {"type": "integer"},
                    "total_reps": {"type": "integer"},
                    "weight_kg": {"type": "number"},
                    "bodyweight": {"type": "boolean"},
                    "movement_multiplier": {"type": "number"},
                },
                "required": [
                    "movement",
                    "sets",
                    "reps_per_set",
                    "total_reps",
                    "weight_kg",
                    "bodyweight",
                    "movement_multiplier",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["is_workout", "activity_type", "duration_minutes", "intensity", "notes", "exercises"],
    "additionalProperties": False,
}


def _workout_prompt(text: str) -> str:
    return (
        "Extract workout information from this message. Return only JSON with keys "
        "is_workout, activity_type, duration_minutes, intensity, notes, exercises. "
        "Use is_workout=false when the text is not a workout check-in. If the message describes sets, reps, weights, or bodyweight exercises but not duration, infer a conservative duration_minutes estimate from the described work. "
        "For exercises, return one object per movement with total_reps, weight_kg, bodyweight, and movement_multiplier. Use weight_kg=0 when no external load is specified, bodyweight=true for bodyweight movements, movement_multiplier=1 unless the movement is clearly partial or unusually demanding, and exercises=[] when reps/loads are unclear.\n\n"
        f"Message: {text}"
    )


def _request_get(url: str, params: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests is required for Telegram sync") from exc
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        raise RuntimeError("Telegram API request failed") from None
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError("Telegram API returned ok=false")
    return data


def fetch_updates(
    token: str,
    *,
    offset: int | None = None,
    limit: int = 100,
    timeout: int = 10,
    request_get: Callable[[str, dict[str, Any], int], dict[str, Any]] = _request_get,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"timeout": timeout, "limit": limit}
    if offset is not None:
        params["offset"] = offset
    data = request_get(f"{TELEGRAM_API_BASE}/bot{token}/getUpdates", params, timeout + 5)
    return list(data.get("result", []))


def parse_workout_with_gemini(text: str) -> ParsedWorkout:
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("google-genai is required for Gemini parsing") from exc

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    client = genai.Client(api_key=api_key)
    prompt = _workout_prompt(text)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": WORKOUT_SCHEMA,
        },
    )
    return json.loads(response.text)


def _extract_openai_output_text(response: Any) -> str | None:
    if isinstance(response, dict):
        output_text = response.get("output_text")
        output = response.get("output", [])
    else:
        output_text = getattr(response, "output_text", None)
        output = getattr(response, "output", [])
    if output_text:
        return str(output_text)

    for item in output:
        if isinstance(item, dict):
            contents = item.get("content", [])
        else:
            contents = getattr(item, "content", [])
        for content in contents:
            if isinstance(content, dict):
                if content.get("type") == "output_text":
                    return content.get("text")
            elif getattr(content, "type", None) == "output_text":
                return getattr(content, "text", None)
    return None


def _parse_workout_with_openai_http(text: str, *, model: str) -> ParsedWorkout:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("openai or requests is required for OpenAI parsing") from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "input": _workout_prompt(text),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "workout_checkin",
                    "strict": True,
                    "schema": WORKOUT_SCHEMA,
                }
            },
        },
        timeout=30,
    )
    response.raise_for_status()
    output_text = _extract_openai_output_text(response.json())
    if not output_text:
        raise RuntimeError("OpenAI response did not include output_text")
    return json.loads(output_text)


def parse_workout_with_openai(
    text: str,
    *,
    client: Any | None = None,
    model: str | None = None,
) -> ParsedWorkout:
    selected_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if client is None:
        try:
            from openai import OpenAI
        except ImportError:
            return _parse_workout_with_openai_http(text, model=selected_model)

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model=selected_model,
        input=_workout_prompt(text),
        text={
            "format": {
                "type": "json_schema",
                "name": "workout_checkin",
                "strict": True,
                "schema": WORKOUT_SCHEMA,
            }
        },
    )
    output_text = _extract_openai_output_text(response)
    if not output_text:
        raise RuntimeError("OpenAI response did not include output_text")
    return json.loads(output_text)


def get_workout_parser(provider: str | None = None) -> Parser:
    selected = (provider or os.getenv("WORKOUT_PARSER_PROVIDER") or "").strip().lower()
    if not selected:
        selected = "openai" if os.getenv("OPENAI_API_KEY") else "gemini"
    if selected == "openai":
        return parse_workout_with_openai
    if selected == "gemini":
        return parse_workout_with_gemini
    raise ValueError("WORKOUT_PARSER_PROVIDER must be 'openai' or 'gemini'")


def _message_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    return update.get("message") or update.get("edited_message")


def _user_id(message: dict[str, Any]) -> int | None:
    user = message.get("from") or {}
    user_id = user.get("id")
    return int(user_id) if user_id is not None else None


def _message_datetime(message: dict[str, Any]) -> datetime:
    timestamp = int(message.get("date", datetime.now(timezone.utc).timestamp()))
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def sync_telegram_updates(
    conn,
    updates: list[dict[str, Any]],
    *,
    allowed_user_id: int,
    parser: Parser | None = None,
    dry_run: bool = False,
    timezone_name: str | None = None,
    allowed_local_dates: set[str] | None = None,
) -> int:
    inserted = 0
    tz = get_timezone(timezone_name)
    workout_parser = parser

    for update in updates:
        message = _message_from_update(update)
        if not message:
            continue
        if _user_id(message) != allowed_user_id:
            print("Ignoring Telegram message from unauthorized user", file=sys.stderr)
            continue
        text = message.get("text")
        if not text:
            continue

        message_datetime = _message_datetime(message)
        if allowed_local_dates is not None:
            local_date = message_datetime.astimezone(tz).date().isoformat()
            if local_date not in allowed_local_dates:
                continue

        if dry_run:
            print(f"telegram:{message.get('message_id')}: {text}")
            continue

        if workout_parser is None:
            workout_parser = get_workout_parser()
        try:
            parsed = workout_parser(text)
        except Exception as exc:
            print(f"Telegram parse failed: {exc}", file=sys.stderr)
            continue
        if not parsed.get("is_workout"):
            continue

        duration = int(parsed.get("duration_minutes") or 0)
        if duration <= 0:
            continue

        activity = Activity(
            source="telegram",
            external_id=str(message["message_id"]),
            timestamp=message_datetime,
            activity_type=str(parsed.get("activity_type") or "workout"),
            duration_minutes=duration,
            intensity=str(parsed.get("intensity") or "") or None,
            notes=str(parsed.get("notes") or "") or None,
            raw_payload={"message": message, "parser_result": parsed},
        )
        upsert_activity(conn, activity, tz=tz)
        inserted += 1

    return inserted


def sync_telegram(
    conn,
    *,
    token: str,
    allowed_user_id: int,
    parser: Parser | None = None,
    request_get: Callable[[str, dict[str, Any], int], dict[str, Any]] = _request_get,
    dry_run: bool = False,
    timezone_name: str | None = None,
) -> int:
    last_update = get_sync_state(conn, "telegram_last_update_id")
    offset = int(last_update) + 1 if last_update is not None else None
    updates = fetch_updates(token, offset=offset, request_get=request_get)
    highest_update_id: int | None = None

    for update in updates:
        update_id = update.get("update_id")
        if update_id is not None:
            highest_update_id = max(highest_update_id or int(update_id), int(update_id))

    inserted = sync_telegram_updates(
        conn,
        updates,
        allowed_user_id=allowed_user_id,
        parser=parser,
        dry_run=dry_run,
        timezone_name=timezone_name,
    )

    if highest_update_id is not None and not dry_run:
        set_sync_state(conn, "telegram_last_update_id", highest_update_id)
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Telegram workout check-ins.")
    parser.add_argument("--db", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    allowed_user_id = os.getenv("TELEGRAM_ALLOWED_USER_ID")
    if not token or not allowed_user_id:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_ID are required", file=sys.stderr)
        return 2

    conn = connect(args.db)
    init_db(conn)
    count = sync_telegram(
        conn,
        token=token,
        allowed_user_id=int(allowed_user_id),
        dry_run=args.dry_run,
        timezone_name=os.getenv("LOCAL_TIMEZONE"),
    )
    print(f"telegram synced {count} workout activity records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
