from __future__ import annotations

import os
from typing import Any

import requests


def sanitize_sentient_log(text: str, *, max_chars: int = 90) -> str:
    cleaned = " ".join(str(text).strip().split())
    cleaned = cleaned.strip("\"'` ")
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 3)].rstrip() + "..."


def fallback_sentient_log(*, score: int, streak_days: int, today_points: int, max_chars: int = 90) -> str:
    if today_points <= 0 and score < 50:
        text = "Metabolic output below mission tolerance; efficiency loss is now measurable."
    elif today_points <= 0:
        text = "No kinetic input logged; baseline decay monitor remains active."
    elif score >= 80:
        text = "Crew output nominal; physical systems remain within operational baseline."
    else:
        text = f"Kinetic input received; score {score}/100 with {streak_days} day streak retained."
    return sanitize_sentient_log(text, max_chars=max_chars)


def build_sentient_prompt(*, score: int, streak_days: int, today_points: int, max_chars: int = 90) -> str:
    return f"""You are the onboard mainframe computer of a deep-space exploration vessel.
Analyze the current crew member's physical output:
- Current Score: {score}/100
- Streak: {streak_days} days
- Today's workout: {today_points} points

Generate a single-sentence status log for the system dashboard.
Keep it under {max_chars} characters. Be clinical, technical, and dryly realistic.
If they are slacking, highlight their low metabolic output or efficiency drop.
If they are on track, acknowledge the baseline operational status without being overly emotional."""


def _extract_output_text(payload: Any) -> str:
    output_text = getattr(payload, "output_text", None)
    if output_text:
        return str(output_text)
    if isinstance(payload, dict):
        if payload.get("output_text"):
            return str(payload["output_text"])
        parts: list[str] = []
        for item in payload.get("output", []) or []:
            for content in item.get("content", []) or []:
                text = content.get("text") if isinstance(content, dict) else None
                if text:
                    parts.append(str(text))
        if parts:
            return " ".join(parts)
    raise RuntimeError("OpenAI response did not contain output text")


def _generate_with_sdk(*, model: str, prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI()
    response = client.responses.create(
        model=model,
        input=prompt,
        max_output_tokens=40,
    )
    return _extract_output_text(response)


def _generate_with_requests(*, model: str, prompt: str, api_key: str) -> str:
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": prompt,
            "max_output_tokens": 40,
        },
        timeout=20,
    )
    response.raise_for_status()
    return _extract_output_text(response.json())


def generate_sentient_log(
    *,
    score: int,
    streak_days: int,
    today_points: int,
    model: str = "gpt-4o-mini",
    max_chars: int = 90,
) -> str:
    prompt = build_sentient_prompt(
        score=score,
        streak_days=streak_days,
        today_points=today_points,
        max_chars=max_chars,
    )
    try:
        text = _generate_with_sdk(model=model, prompt=prompt)
    except Exception:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise
        text = _generate_with_requests(model=model, prompt=prompt, api_key=api_key)
    return sanitize_sentient_log(text, max_chars=max_chars)
