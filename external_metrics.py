from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests


DEFAULT_PORTFOLIO_RETURN_PATH: Path | None = None
DEFAULT_MAX_AGE_SECONDS = 5400
CRYPY_HEADLINE_URL = ""
CRYPY_HEADLINE_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class ExternalMetric:
    label: str
    value: str
    status: str = ""
    stale: bool = False
    polarity: str = "neutral"


@dataclass(frozen=True)
class PortfolioReturnSnapshot:
    total_return_pct: Decimal
    captured_at: datetime
    recommended_max_age_seconds: int
    environment: str = ""
    currency: str = ""

    def is_stale(self, now: datetime | None = None) -> bool:
        reference = _aware_utc(now or datetime.now(UTC))
        age_seconds = (reference - self.captured_at).total_seconds()
        return age_seconds > self.recommended_max_age_seconds


def _aware_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _parse_captured_at(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("captured_at is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return _aware_utc(datetime.fromisoformat(text))


def _format_pct(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    prefix = "+" if quantized > 0 else ""
    return f"{prefix}{quantized}%"


def _decimal_field(payload: dict[str, Any], field: str) -> Decimal:
    try:
        return Decimal(str(payload[field]))
    except (InvalidOperation, KeyError) as exc:
        raise ValueError(f"{field} must be a decimal-compatible value") from exc


def _format_gbp(value: Decimal, *, signed: bool = True) -> str:
    quantized = value.quantize(Decimal("0.01"))
    prefix = "+" if signed and quantized > 0 else ""
    return f"GBP {prefix}{quantized}"


def _polarity(value: Decimal) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def load_portfolio_return_snapshot(path: str | Path) -> PortfolioReturnSnapshot:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    return PortfolioReturnSnapshot(
        total_return_pct=_decimal_field(payload, "total_return_pct"),
        captured_at=_parse_captured_at(payload.get("captured_at")),
        recommended_max_age_seconds=int(payload.get("recommended_max_age_seconds", DEFAULT_MAX_AGE_SECONDS)),
        environment=str(payload.get("environment", "") or ""),
        currency=str(payload.get("currency", "") or ""),
    )


def portfolio_return_metric(
    path: str | Path | None = DEFAULT_PORTFOLIO_RETURN_PATH,
    *,
    now: datetime | None = None,
) -> ExternalMetric | None:
    if not path:
        return None
    source = Path(path).expanduser()
    if not source.exists():
        return None

    snapshot = load_portfolio_return_snapshot(source)
    stale = snapshot.is_stale(now)
    status = "STALE" if stale else snapshot.environment or "FRESH"
    return ExternalMetric(
        label="PORTFOLIO RETURN",
        value=_format_pct(snapshot.total_return_pct),
        status=status,
        stale=stale,
        polarity=_polarity(snapshot.total_return_pct),
    )


def load_crypy_headline(
    *,
    url: str = CRYPY_HEADLINE_URL,
    timeout: int = CRYPY_HEADLINE_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    if not url:
        return None
    user = os.getenv("CRYPY_HEADLINE_USER")
    password = os.getenv("CRYPY_HEADLINE_PASS")
    if not user or not password:
        return None

    response = requests.get(url, auth=(user, password), timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("crypy headline response must be a JSON object")
    return data


def crypy_headline_metrics(
    *,
    url: str = CRYPY_HEADLINE_URL,
    timeout: int = CRYPY_HEADLINE_TIMEOUT_SECONDS,
) -> list[ExternalMetric]:
    data = load_crypy_headline(url=url, timeout=timeout)
    if data is None:
        return []

    portfolio_value = _decimal_field(data, "portfolio_value_gbp")
    portfolio_vs_btc_1d = _decimal_field(data, "portfolio_vs_btc_1d_percent")
    realised_1d = _decimal_field(data, "active_realized_pnl_1d_gbp")
    return [
        ExternalMetric("CRYPY PORTFOLIO", _format_gbp(portfolio_value, signed=False), "LIVE"),
        ExternalMetric(
            "CRYPY VS BTC 1D",
            _format_pct(portfolio_vs_btc_1d),
            "LIVE",
            polarity=_polarity(portfolio_vs_btc_1d),
        ),
        ExternalMetric("CRYPY REALISED 1D", _format_gbp(realised_1d), "LIVE", polarity=_polarity(realised_1d)),
    ]
