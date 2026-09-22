from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from multiprocessing import get_context
from pathlib import Path
from queue import Empty
from zoneinfo import ZoneInfo

from config import WritingProjectConfig
from db import Activity, get_sync_state, set_sync_state, upsert_activity


WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class WritingProjectSnapshot:
    project_id: str
    label: str
    path: str
    file_count: int
    total_words: int
    delta_words: int
    day_words: int
    week_words: int
    weekly_goal_words: int
    stale: bool = False
    status: str = "OK"


def _state_key(project_id: str, name: str) -> str:
    return f"writing:{project_id}:{name}"


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _int_state(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def count_project_words(path: str | Path, pattern: str = "**/*.txt") -> tuple[int, int]:
    root = Path(path).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"Writing project path does not exist: {root}")
    files = sorted(file for file in root.glob(pattern) if file.is_file())
    total = 0
    for file in files:
        text = file.read_text(encoding="utf-8", errors="replace")
        total += len(WORD_RE.findall(text))
    return total, len(files)


def _count_worker(path: str, pattern: str, queue) -> None:
    try:
        total_words, file_count = count_project_words(path, pattern)
    except Exception as exc:
        queue.put(("error", repr(exc)))
    else:
        queue.put(("ok", total_words, file_count))


def _count_with_timeout(project: WritingProjectConfig) -> tuple[int, int]:
    context = get_context("fork")
    queue = context.Queue()
    process = context.Process(target=_count_worker, args=(project.path, project.glob, queue))
    process.start()
    process.join(project.timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(2)
        raise TimeoutError(f"Timed out counting writing project {project.id}") from None
    if process.exitcode not in {0, None}:
        raise RuntimeError(f"Word count process failed for writing project {project.id}")
    try:
        result = queue.get(timeout=1)
    except Empty:
        return 0, 0
    if result[0] == "error":
        raise RuntimeError(result[1])
    return int(result[1]), int(result[2])


def sync_writing_projects(
    conn,
    *,
    projects: tuple[WritingProjectConfig, ...],
    today: date,
    now: datetime,
    tz: ZoneInfo | None,
    dry_run: bool = False,
) -> list[WritingProjectSnapshot]:
    snapshots: list[WritingProjectSnapshot] = []
    for project in projects:
        if not project.enabled:
            continue
        try:
            total_words, file_count = _count_with_timeout(project)
        except Exception as exc:
            snapshots.append(
                WritingProjectSnapshot(
                    project_id=project.id,
                    label=project.label,
                    path=project.path,
                    file_count=0,
                    total_words=0,
                    delta_words=0,
                    day_words=0,
                    week_words=0,
                    weekly_goal_words=project.weekly_goal_words,
                    stale=True,
                    status=str(exc),
                )
            )
            continue

        week_start = _week_start(today)
        last_total = _int_state(get_sync_state(conn, _state_key(project.id, "last_total_words")))
        delta_words = max(0, total_words - last_total) if last_total is not None else 0

        baseline_key = _state_key(project.id, f"week:{week_start.isoformat()}:baseline_words")
        baseline_words = _int_state(get_sync_state(conn, baseline_key))
        if baseline_words is None:
            baseline_words = max(0, total_words - delta_words)

        day_key = _state_key(project.id, f"day:{today.isoformat()}:words")
        previous_day_words = _int_state(get_sync_state(conn, day_key)) or 0
        day_words = previous_day_words + delta_words
        week_words = max(0, total_words - baseline_words)

        if not dry_run:
            upsert_activity(
                conn,
                Activity(
                    source="writing",
                    external_id=f"{project.id}:{today.isoformat()}",
                    timestamp=now,
                    activity_type=project.activity_type,
                    duration_minutes=0,
                    points=day_words * project.points_per_word,
                    notes=project.label,
                    raw_payload={
                        "project_id": project.id,
                        "label": project.label,
                        "path": project.path,
                        "file_count": file_count,
                        "total_words": total_words,
                        "delta_words": delta_words,
                        "day_words": day_words,
                        "week_words": week_words,
                        "weekly_goal_words": project.weekly_goal_words,
                        "week_start": week_start.isoformat(),
                    },
                    point_components={
                        "method": "writing_word_delta",
                        "points_per_word": project.points_per_word,
                    },
                ),
                tz=tz,
            )
            set_sync_state(conn, baseline_key, baseline_words)
            set_sync_state(conn, _state_key(project.id, "last_total_words"), total_words)
            set_sync_state(conn, day_key, day_words)

        snapshots.append(
            WritingProjectSnapshot(
                project_id=project.id,
                label=project.label,
                path=project.path,
                file_count=file_count,
                total_words=total_words,
                delta_words=delta_words,
                day_words=day_words,
                week_words=week_words,
                weekly_goal_words=project.weekly_goal_words,
            )
        )
    return snapshots
