from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "Europe/London"
DEFAULT_DB_PATH = "glitchslate.db"
DEFAULT_CONFIG_PATH = "config.yaml"


@dataclass(frozen=True)
class VisualConfig:
    target_resolution: str = "3840x2160"
    bg_color: str = "#0b0f19"
    grid_color: str = "#1e293b"
    active_gradient: tuple[str, str] = ("#06b6d4", "#8b5cf6")
    empty_color: str = "#1e293b"
    text_color: str = "#f8fafc"
    muted_text_color: str = "#94a3b8"
    alert_color: str = "#ef4444"
    keep_archive_images: bool = False
    archive_retention_hours: int = 48

    @property
    def width(self) -> int:
        return parse_resolution(self.target_resolution)[0]

    @property
    def height(self) -> int:
        return parse_resolution(self.target_resolution)[1]


@dataclass(frozen=True)
class ScoringConfig:
    recent_window_days: int = 5
    baseline_window_days: int = 30
    min_expected_5_day_minutes: int = 60


@dataclass(frozen=True)
class AppConfig:
    visual: VisualConfig = VisualConfig()
    scoring: ScoringConfig = ScoringConfig()


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
    candidates = [Path.cwd() / ".env", module_dir / ".env", module_dir.parent / ".env"]
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


def parse_resolution(value: str) -> tuple[int, int]:
    parts = value.lower().split("x", 1)
    if len(parts) != 2:
        raise ValueError("target_resolution must be formatted like 3840x2160")
    width, height = int(parts[0]), int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError("target_resolution dimensions must be positive")
    return width, height


def _deep_merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def default_config_dict() -> dict[str, Any]:
    return {
        "visual": {
            "target_resolution": "3840x2160",
            "bg_color": "#0b0f19",
            "grid_color": "#1e293b",
            "active_gradient": ["#06b6d4", "#8b5cf6"],
            "empty_color": "#1e293b",
            "text_color": "#f8fafc",
            "muted_text_color": "#94a3b8",
            "alert_color": "#ef4444",
            "keep_archive_images": False,
            "archive_retention_hours": 48,
        },
        "scoring": {
            "recent_window_days": 5,
            "baseline_window_days": 30,
            "min_expected_5_day_minutes": 60,
        },
    }


def _normalize_visual(raw: dict[str, Any]) -> VisualConfig:
    values = dict(raw)
    gradient = values.get("active_gradient", ["#06b6d4", "#8b5cf6"])
    if not isinstance(gradient, (list, tuple)) or len(gradient) != 2:
        raise ValueError("visual.active_gradient must contain exactly two colors")
    values["active_gradient"] = (str(gradient[0]), str(gradient[1]))
    return VisualConfig(**values)


def app_config_from_dict(raw: dict[str, Any]) -> AppConfig:
    data = _deep_merge(default_config_dict(), raw or {})
    config = AppConfig(
        visual=_normalize_visual(data["visual"]),
        scoring=ScoringConfig(**data["scoring"]),
    )
    validate_config(config)
    return config


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or os.getenv("GLITCHSLATE_CONFIG_PATH", DEFAULT_CONFIG_PATH))
    if not config_path.exists():
        return app_config_from_dict({})
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read config.yaml. Run: python3 -m pip install -r requirements.txt") from exc
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config.yaml must contain a YAML mapping")
    return app_config_from_dict(raw)


def _validate_hex_color(value: str, field: str) -> None:
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"{field} must be a #RRGGBB color")
    int(value[1:], 16)


def validate_config(config: AppConfig) -> None:
    parse_resolution(config.visual.target_resolution)
    for field in [
        "bg_color",
        "grid_color",
        "empty_color",
        "text_color",
        "muted_text_color",
        "alert_color",
    ]:
        _validate_hex_color(getattr(config.visual, field), f"visual.{field}")
    for index, color in enumerate(config.visual.active_gradient):
        _validate_hex_color(color, f"visual.active_gradient[{index}]")
    if config.visual.archive_retention_hours < 0:
        raise ValueError("visual.archive_retention_hours must not be negative")
    if config.scoring.recent_window_days <= 0:
        raise ValueError("scoring.recent_window_days must be positive")
    if config.scoring.baseline_window_days < config.scoring.recent_window_days:
        raise ValueError("scoring.baseline_window_days must be at least recent_window_days")
    if config.scoring.min_expected_5_day_minutes <= 0:
        raise ValueError("scoring.min_expected_5_day_minutes must be positive")
