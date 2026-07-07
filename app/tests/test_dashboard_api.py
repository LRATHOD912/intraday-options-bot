import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.server.api import app, dashboard, ui


class TestDashboardApi(unittest.TestCase):
    @patch("app.server.api.API_TOKEN", "test-token")
    def test_dashboard_returns_multi_position_payload(self):
        payload = dashboard(True)

        self.assertIn("status", payload)
        self.assertIn("positions", payload)
        self.assertIn("risk", payload)
        self.assertIn("config_summary", payload)
        self.assertIn("last_scan_decision", payload)
        self.assertIsInstance(payload["positions"], list)

    @patch("app.server.api.API_TOKEN", "test-token")
    def test_ui_returns_html(self):
        response = ui(api_token="test-token")

        self.assertEqual(response.media_type, "text/html")
        self.assertIn("Intraday Options Bot", response.body.decode("utf-8"))
        self.assertIn("/dashboard?api_token=", response.body.decode("utf-8"))
        self.assertNotIn("ΓÇ", response.body.decode("utf-8"))

    @patch("app.main.is_market_hours", return_value=(False, "market_closed"))
    @patch("app.main.log_decision")
    def test_early_market_closed_rejection_includes_gate_metadata(self, mock_log_decision, _mock_market_hours):
        from app.main import run_bot_scan

        run_bot_scan()

        payload = mock_log_decision.call_args[0][0]
        self.assertFalse(payload["trade_found"])
        self.assertTrue(payload["trade_rejected"])
        self.assertEqual(payload["rejected_by_gate"], "market_hours_gate")
        self.assertEqual(payload["gate_result"]["gate"], "market_hours_gate")
        self.assertEqual(payload["trace"]["rejected_by_gate"], "market_hours_gate")

    @patch("app.server.api.VIEW_TOKEN", "test-view-token")
    def test_public_view_rejects_invalid_token(self):
        client = TestClient(app)

        response = client.get("/view?token=wrong-token")

        self.assertEqual(response.status_code, 401)

    @patch("app.server.api.VIEW_TOKEN", "test-view-token")
    def test_public_view_returns_read_only_html(self):
        client = TestClient(app)

        response = client.get("/view?token=test-view-token")

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Intraday Options Bot", html)
        self.assertIn("/public-dashboard-data?token=", html)
        self.assertIn("setInterval(refreshDashboard, 10000)", html)
        self.assertNotIn("Start", html)
        self.assertNotIn("Stop", html)
        self.assertNotIn("Scan", html)
        self.assertNotIn("API_TOKEN", html)
        self.assertNotIn("ALPACA_SECRET_KEY", html)
        self.assertNotIn("Start Bot", html)
        self.assertNotIn("/start", html)
        self.assertNotIn("/stop", html)
        self.assertNotIn("/scan-once", html)

    @patch("app.server.api.VIEW_TOKEN", "test-view-token")
    @patch(
        "app.server.api._build_public_dashboard_payload",
        return_value={
            "status": {
                "running": True,
                "trade_found": True,
                "trade_rejected": True,
                "exact_rejection_reason": "Rejected because Entry Quality 48 < threshold 75",
                "rejected_by_gate": "entry_quality_gate",
                "next_retry_time": "2026-01-01T09:46:00-05:00",
                "adaptive_entry_threshold": 62,
                "static_entry_threshold": 75,
                "regime_risk_multiplier": 0.5,
                "regime_note": "Reduced threshold, reduced size, quick exits only",
                "entry_quality_passed": False,
                "entry_quality_gap": -14,
            },
            "positions": [],
            "risk": {},
            "orders": [],
            "journal": [],
            "decision_history": [{
                "timestamp": "2026-01-01T09:45:00-05:00",
                "symbol": "QQQ",
                "reason": "No valid setup",
                "reason_exact": "Rejected because Entry Quality 48 < threshold 75",
                "rejected_by_gate": "entry_quality_gate",
                "entry_quality_score": 48,
                "adaptive_entry_threshold": 62,
                "static_entry_threshold": 75,
                "entry_quality_passed": False,
                "entry_quality_gap": -14,
                "regime_risk_multiplier": 0.5,
                "regime_note": "Reduced threshold, reduced size, quick exits only",
            }],
            "last_scan_decision": {},
        },
    )
    def test_public_dashboard_data_returns_sanitized_payload(self, _mock_payload):
        client = TestClient(app)

        response = client.get("/public-dashboard-data?token=test-view-token")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("status", body)
        self.assertIn("positions", body)
        self.assertIn("risk", body)
        self.assertIn("orders", body)
        self.assertIn("journal", body)
        self.assertIn("decision_history", body)
        self.assertIn("last_scan_decision", body)
        self.assertEqual(body["decision_history"][0]["symbol"], "QQQ")
        self.assertTrue(body["status"]["trade_found"])
        self.assertTrue(body["status"]["trade_rejected"])
        self.assertEqual(body["status"]["rejected_by_gate"], "entry_quality_gate")
        self.assertIn("Entry Quality 48 < threshold 75", body["status"]["exact_rejection_reason"])
        self.assertEqual(body["status"]["adaptive_entry_threshold"], 62)
        self.assertEqual(body["status"]["static_entry_threshold"], 75)
        self.assertEqual(body["status"]["regime_risk_multiplier"], 0.5)
        self.assertIn("Reduced threshold", body["status"]["regime_note"])
        self.assertFalse(body["status"]["entry_quality_passed"])
        self.assertEqual(body["status"]["entry_quality_gap"], -14)
        self.assertIn("adaptive_entry_threshold", body["decision_history"][0])
        self.assertIn("entry_quality_score", body["decision_history"][0])
        self.assertNotIn("API_TOKEN", response.text)
        self.assertNotIn("X-API-Token", response.text)


if __name__ == "__main__":
    unittest.main()