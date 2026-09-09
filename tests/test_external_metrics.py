from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from external_metrics import crypy_headline_metrics, load_portfolio_return_snapshot, portfolio_return_metric


class ExternalMetricTests(unittest.TestCase):
    def _write_snapshot(self, path: Path, captured_at: datetime) -> None:
        path.write_text(
            json.dumps(
                {
                    "captured_at": captured_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                    "environment": "LIVE",
                    "currency": "GBP",
                    "total_return_pct": "-0.2388408258585000796136086195",
                    "recommended_max_age_seconds": 5400,
                }
            ),
            encoding="utf-8",
        )

    def test_portfolio_return_snapshot_preserves_decimal_and_freshness_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio-return.json"
            now = datetime(2026, 9, 2, 13, 10, tzinfo=UTC)
            self._write_snapshot(path, now - timedelta(seconds=5399))

            snapshot = load_portfolio_return_snapshot(path)

            self.assertEqual(snapshot.total_return_pct, Decimal("-0.2388408258585000796136086195"))
            self.assertFalse(snapshot.is_stale(now))
            self.assertTrue(snapshot.is_stale(now + timedelta(seconds=2)))

    def test_portfolio_return_metric_marks_stale_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio-return.json"
            now = datetime(2026, 9, 2, 13, 10, tzinfo=UTC)
            self._write_snapshot(path, now - timedelta(seconds=5401))

            metric = portfolio_return_metric(path, now=now)

            self.assertIsNotNone(metric)
            assert metric is not None
            self.assertEqual(metric.label, "PORTFOLIO RETURN")
            self.assertEqual(metric.value, "-0.24%")
            self.assertEqual(metric.status, "STALE")
            self.assertTrue(metric.stale)
            self.assertEqual(metric.polarity, "negative")

    def test_crypy_headline_metrics_returns_empty_without_credentials(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(crypy_headline_metrics(), [])

    def test_crypy_headline_metrics_fetches_authenticated_values(self) -> None:
        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, str]:
                return {
                    "portfolio_value_gbp": "617.59",
                    "portfolio_vs_btc_1d_percent": "-0.02",
                    "active_realized_pnl_1d_gbp": "12.345",
                }

        with mock.patch.dict(
            "os.environ",
            {"CRYPY_HEADLINE_USER": "user", "CRYPY_HEADLINE_PASS": "pass"},
            clear=True,
        ), mock.patch("external_metrics.requests.get", return_value=Response()) as get:
            metrics = crypy_headline_metrics()

        get.assert_called_once_with(
            "https://hwjacko2.eu.pythonanywhere.com/api/headline",
            auth=("user", "pass"),
            timeout=20,
        )
        self.assertEqual(
            [metric.label for metric in metrics],
            ["CRYPY PORTFOLIO", "CRYPY VS BTC 1D", "CRYPY REALISED 1D"],
        )
        self.assertEqual([metric.value for metric in metrics], ["GBP 617.59", "-0.02%", "GBP +12.34"])
        self.assertEqual([metric.polarity for metric in metrics], ["neutral", "negative", "positive"])
        self.assertTrue(all(metric.status == "LIVE" for metric in metrics))


if __name__ == "__main__":
    unittest.main()
