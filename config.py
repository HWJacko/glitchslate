from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "Europe/London"
DEFAULT_DB_PATH = "glitchslate.db"
DEFAULT_CONFIG_PATH = "config.yaml"
MAX_RENDER_DIMENSION = 16_384
MAX_RENDER_PIXELS = 50_000_000


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
class ChartConfig:
    rolling_window_days: int = 3
    history_days: int = 30


@dataclass(frozen=True)
class ScoringConfig:
    recent_window_days: int = 5
    baseline_window_days: int = 30
    min_expected_5_day_minutes: int = 60
    min_expected_5_day_points: float = 1500.0
    included_sources: tuple[str, ...] = ("telegram", "strava")


@dataclass(frozen=True)
class SentientLogConfig:
    enabled: bool = False
    model: str = "gpt-4o-mini"
    max_chars: int = 90


@dataclass(frozen=True)
class ParserConfig:
    provider: str = "auto"
    openai_model: str = "gpt-4o-mini"
    gemini_model: str = "gemini-2.0-flash"
    max_message_chars: int = 4_000


@dataclass(frozen=True)
class TelemetryConfig:
    show_systemd_box: bool = True
    gap_alert_days: int = 3
    criticality_ramp_enabled: bool = True
    criticality_ramp_start_hour: int = 6
    criticality_ramp_full_hour: int = 22
    criticality_ramp_min_factor: float = 0.15
    show_vignette: bool = True


@dataclass(frozen=True)
class TelegramArchiveConfig:
    enabled: bool = False
    blank_lookback_days: int = 28
    remote_dir: str = "glitchslate-telegram-inbox"
    timeout_seconds: int = 30


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = True
    direct_sync: bool = True
    archive_enabled: bool = False
    request_timeout_seconds: int = 10


@dataclass(frozen=True)
class StravaConfig:
    enabled: bool = False
    lookback_days: int = 2
    request_timeout_seconds: int = 30


@dataclass(frozen=True)
class WritingProjectConfig:
    id: str
    label: str
    path: str
    activity_type: str
    glob: str = "**/*.txt"
    weekly_goal_words: int = 5000
    points_per_word: float = 1.0
    timeout_seconds: int = 20
    enabled: bool = True


@dataclass(frozen=True)
class WritingConfig:
    enabled: bool = False
    projects: tuple[WritingProjectConfig, ...] = ()


@dataclass(frozen=True)
class SocialConfig:
    enabled: bool = False
    bluesky_rss_url: str = "https://bsky.app/profile/your-handle/rss"
    reminder_after_days: int = 4
    post_points: float = 1000.0
    timeout_seconds: int = 10


@dataclass(frozen=True)
class ExternalMetricsConfig:
    portfolio_return_enabled: bool = False
    portfolio_return_path: str = ""
    crypy_headline_enabled: bool = False
    crypy_headline_url: str = ""
    timeout_seconds: int = 20


@dataclass(frozen=True)
class AppConfig:
    visual: VisualConfig = VisualConfig()
    chart: ChartConfig = ChartConfig()
    scoring: ScoringConfig = ScoringConfig()
    sentient_log: SentientLogConfig = SentientLogConfig()
    parser: ParserConfig = ParserConfig()
    telemetry: TelemetryConfig = TelemetryConfig()
    telegram_archive: TelegramArchiveConfig = TelegramArchiveConfig()
    telegram: TelegramConfig = TelegramConfig()
    strava: StravaConfig = StravaConfig()
    writing: WritingConfig = WritingConfig()
    social: SocialConfig = SocialConfig()
    external_metrics: ExternalMetricsConfig = ExternalMetricsConfig()


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
    # Do not implicitly trust an arbitrary working directory's .env file. This
    # matters when the CLI is invoked from a downloaded repository or a folder
    # containing unrelated credentials.
    candidates = [module_dir / ".env"]
    if Path.cwd().resolve() == module_dir:
        candidates.insert(0, Path.cwd() / ".env")
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
    if width > MAX_RENDER_DIMENSION or height > MAX_RENDER_DIMENSION:
        raise ValueError(f"target_resolution dimensions must not exceed {MAX_RENDER_DIMENSION}")
    if width * height > MAX_RENDER_PIXELS:
        raise ValueError(f"target_resolution must not exceed {MAX_RENDER_PIXELS} pixels")
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
        "chart": {
            "rolling_window_days": 3,
            "history_days": 30,
        },
        "scoring": {
            "recent_window_days": 5,
            "baseline_window_days": 30,
            "min_expected_5_day_minutes": 60,
            "min_expected_5_day_points": 1500.0,
            "included_sources": ["telegram", "strava"],
        },
        "sentient_log": {
            "enabled": False,
            "model": "gpt-4o-mini",
            "max_chars": 90,
        },
        "parser": {
            "provider": "auto",
            "openai_model": "gpt-4o-mini",
            "gemini_model": "gemini-2.0-flash",
            "max_message_chars": 4000,
        },
        "telemetry": {
            "show_systemd_box": True,
            "gap_alert_days": 3,
            "criticality_ramp_enabled": True,
            "criticality_ramp_start_hour": 6,
            "criticality_ramp_full_hour": 22,
            "criticality_ramp_min_factor": 0.15,
            "show_vignette": True,
        },
        "telegram_archive": {
            "enabled": False,
            "blank_lookback_days": 28,
            "remote_dir": "glitchslate-telegram-inbox",
            "timeout_seconds": 30,
        },
        "telegram": {
            "enabled": True,
            "direct_sync": True,
            "archive_enabled": False,
            "request_timeout_seconds": 10,
        },
        "strava": {
            "enabled": False,
            "lookback_days": 2,
            "request_timeout_seconds": 30,
        },
        "writing": {
            "enabled": False,
            "projects": [],
        },
        "social": {
            "enabled": False,
            "bluesky_rss_url": "https://bsky.app/profile/your-handle/rss",
            "reminder_after_days": 4,
            "post_points": 1000.0,
            "timeout_seconds": 10,
        },
        "external_metrics": {
            "portfolio_return_enabled": False,
            "portfolio_return_path": "",
            "crypy_headline_enabled": False,
            "crypy_headline_url": "",
            "timeout_seconds": 20,
        },
    }


def _normalize_visual(raw: dict[str, Any]) -> VisualConfig:
    values = dict(raw)
    gradient = values.get("active_gradient", ["#06b6d4", "#8b5cf6"])
    if not isinstance(gradient, (list, tuple)) or len(gradient) != 2:
        raise ValueError("visual.active_gradient must contain exactly two colors")
    values["active_gradient"] = (str(gradient[0]), str(gradient[1]))
    return VisualConfig(**values)


def _normalize_scoring(raw: dict[str, Any]) -> ScoringConfig:
    values = dict(raw)
    included = values.get("included_sources", ["telegram", "strava"])
    if not isinstance(included, (list, tuple)) or not included:
        raise ValueError("scoring.included_sources must be a non-empty list")
    values["included_sources"] = tuple(str(source).strip() for source in included if str(source).strip())
    return ScoringConfig(**values)


def _normalize_chart(raw: dict[str, Any]) -> ChartConfig:
    return ChartConfig(**dict(raw))


def _validate_http_url(value: str, field: str, *, allow_placeholder: bool = False) -> None:
    parsed = urlparse(value)
    if allow_placeholder and value == "https://bsky.app/profile/your-handle/rss":
        return
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{field} must be an https URL without embedded credentials")


def _normalize_writing(raw: dict[str, Any]) -> WritingConfig:
    values = dict(raw)
    projects = values.get("projects", [])
    if not isinstance(projects, (list, tuple)):
        raise ValueError("writing.projects must be a list")
    normalized_projects = []
    for index, project in enumerate(projects):
        if not isinstance(project, dict):
            raise ValueError(f"writing.projects[{index}] must be a mapping")
        project_values = dict(project)
        if "activity_type" not in project_values:
            project_values["activity_type"] = str(project_values.get("id", f"project_{index}"))
        normalized_projects.append(WritingProjectConfig(**project_values))
    values["projects"] = tuple(normalized_projects)
    return WritingConfig(**values)


def app_config_from_dict(raw: dict[str, Any]) -> AppConfig:
    data = _deep_merge(default_config_dict(), raw or {})
    config = AppConfig(
        visual=_normalize_visual(data["visual"]),
        chart=_normalize_chart(data["chart"]),
        scoring=_normalize_scoring(data["scoring"]),
        sentient_log=SentientLogConfig(**data["sentient_log"]),
        parser=ParserConfig(**data["parser"]),
        telemetry=TelemetryConfig(**data["telemetry"]),
        telegram_archive=TelegramArchiveConfig(**data["telegram_archive"]),
        telegram=TelegramConfig(**data["telegram"]),
        strava=StravaConfig(**data["strava"]),
        writing=_normalize_writing(data["writing"]),
        social=SocialConfig(**data["social"]),
        external_metrics=ExternalMetricsConfig(**data["external_metrics"]),
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
    if config.chart.rolling_window_days <= 0:
        raise ValueError("chart.rolling_window_days must be positive")
    if config.chart.history_days <= 0:
        raise ValueError("chart.history_days must be positive")
    if config.chart.history_days < config.chart.rolling_window_days:
        raise ValueError("chart.history_days must be at least rolling_window_days")
    if config.scoring.recent_window_days <= 0:
        raise ValueError("scoring.recent_window_days must be positive")
    if config.scoring.baseline_window_days < config.scoring.recent_window_days:
        raise ValueError("scoring.baseline_window_days must be at least recent_window_days")
    if config.scoring.min_expected_5_day_minutes <= 0:
        raise ValueError("scoring.min_expected_5_day_minutes must be positive")
    if not config.scoring.included_sources:
        raise ValueError("scoring.included_sources must not be empty")
    if config.sentient_log.max_chars <= 0:
        raise ValueError("sentient_log.max_chars must be positive")
    if config.parser.provider.lower() not in {"auto", "openai", "gemini"}:
        raise ValueError("parser.provider must be 'auto', 'openai', or 'gemini'")
    if not config.parser.openai_model.strip() or not config.parser.gemini_model.strip():
        raise ValueError("parser model names must not be empty")
    if not 1 <= config.parser.max_message_chars <= 100_000:
        raise ValueError("parser.max_message_chars must be between 1 and 100000")
    if config.telemetry.gap_alert_days <= 0:
        raise ValueError("telemetry.gap_alert_days must be positive")
    if not 0 <= config.telemetry.criticality_ramp_start_hour <= 23:
        raise ValueError("telemetry.criticality_ramp_start_hour must be between 0 and 23")
    if not 1 <= config.telemetry.criticality_ramp_full_hour <= 24:
        raise ValueError("telemetry.criticality_ramp_full_hour must be between 1 and 24")
    if config.telemetry.criticality_ramp_full_hour <= config.telemetry.criticality_ramp_start_hour:
        raise ValueError("telemetry.criticality_ramp_full_hour must be after criticality_ramp_start_hour")
    if not 0 <= config.telemetry.criticality_ramp_min_factor <= 1:
        raise ValueError("telemetry.criticality_ramp_min_factor must be between 0 and 1")
    if config.telegram_archive.blank_lookback_days <= 0:
        raise ValueError("telegram_archive.blank_lookback_days must be positive")
    if config.telegram_archive.blank_lookback_days > 28:
        raise ValueError("telegram_archive.blank_lookback_days must not exceed 28")
    if not config.telegram_archive.remote_dir:
        raise ValueError("telegram_archive.remote_dir must not be empty")
    if config.telegram_archive.timeout_seconds <= 0:
        raise ValueError("telegram_archive.timeout_seconds must be positive")
    if config.telegram.request_timeout_seconds <= 0:
        raise ValueError("telegram.request_timeout_seconds must be positive")
    if config.strava.lookback_days <= 0:
        raise ValueError("strava.lookback_days must be positive")
    if config.strava.request_timeout_seconds <= 0:
        raise ValueError("strava.request_timeout_seconds must be positive")
    seen_project_ids: set[str] = set()
    for project in config.writing.projects:
        if not project.id.strip():
            raise ValueError("writing.projects[].id must not be empty")
        if project.id in seen_project_ids:
            raise ValueError(f"writing project id must be unique: {project.id}")
        seen_project_ids.add(project.id)
        if not project.label.strip():
            raise ValueError(f"writing project {project.id} label must not be empty")
        if not project.path.strip():
            raise ValueError(f"writing project {project.id} path must not be empty")
        if not project.activity_type.strip():
            raise ValueError(f"writing project {project.id} activity_type must not be empty")
        if project.weekly_goal_words <= 0:
            raise ValueError(f"writing project {project.id} weekly_goal_words must be positive")
        if project.points_per_word <= 0:
            raise ValueError(f"writing project {project.id} points_per_word must be positive")
        if project.timeout_seconds <= 0:
            raise ValueError(f"writing project {project.id} timeout_seconds must be positive")
    if config.social.reminder_after_days <= 0:
        raise ValueError("social.reminder_after_days must be positive")
    if config.social.post_points <= 0:
        raise ValueError("social.post_points must be positive")
    if config.social.timeout_seconds <= 0:
        raise ValueError("social.timeout_seconds must be positive")
    _validate_http_url(config.social.bluesky_rss_url, "social.bluesky_rss_url", allow_placeholder=True)
    if config.external_metrics.portfolio_return_enabled and not config.external_metrics.portfolio_return_path.strip():
        raise ValueError("external_metrics.portfolio_return_path is required when portfolio_return_enabled")
    if config.external_metrics.crypy_headline_enabled and not config.external_metrics.crypy_headline_url.strip():
        raise ValueError("external_metrics.crypy_headline_url is required when crypy_headline_enabled")
    if config.external_metrics.crypy_headline_url:
        _validate_http_url(config.external_metrics.crypy_headline_url, "external_metrics.crypy_headline_url")
    if config.external_metrics.timeout_seconds <= 0:
        raise ValueError("external_metrics.timeout_seconds must be positive")
