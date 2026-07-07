import unittest
from unittest.mock import patch

from app.server.api import dashboard, ui


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
        self.assertIn("QQQ Intraday Options Bot", response.body.decode("utf-8"))
        self.assertIn("/dashboard?api_token=", response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()