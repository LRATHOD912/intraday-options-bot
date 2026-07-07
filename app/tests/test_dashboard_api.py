import unittest
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
        self.assertNotIn("ALPACA", html)
        self.assertNotIn("Start Bot", html)

    @patch("app.server.api.VIEW_TOKEN", "test-view-token")
    @patch("app.server.api._build_public_dashboard_payload", return_value={"status": {"running": True}, "positions": []})
    def test_public_dashboard_data_returns_sanitized_payload(self, _mock_payload):
        client = TestClient(app)

        response = client.get("/public-dashboard-data?token=test-view-token")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("status", body)
        self.assertIn("positions", body)
        self.assertNotIn("API_TOKEN", response.text)
        self.assertNotIn("X-API-Token", response.text)


if __name__ == "__main__":
    unittest.main()