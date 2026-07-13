from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "Europe/London"
DEFAULT_DB_PATH = "glitchslate.db"


def _load_one_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_dotenv(path: str | Path | None = None) -> None:
    if path is not None:
        _load_one_env(Path(path))
        return

    module_dir = Path(__file__).resolve().parent
    candidates = [
        Path.cwd() / ".env",
        module_dir / ".env",
        module_dir.parent / ".env",
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        _load_one_env(candidate)


def get_timezone(name: str | None = None) -> ZoneInfo:
    return ZoneInfo(name or os.getenv("LOCAL_TIMEZONE", DEFAULT_TIMEZONE))


def get_db_path(path: str | Path | None = None) -> Path:
    return Path(path or os.getenv("GLITCHSLATE_DB_PATH", DEFAULT_DB_PATH))
