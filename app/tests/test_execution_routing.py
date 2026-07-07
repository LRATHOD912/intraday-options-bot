import unittest
from unittest.mock import patch

from app.broker import orders


class TestExecutionRouting(unittest.TestCase):
    @patch("app.broker.orders.get_trading_client")
    @patch("app.broker.orders.USE_ALPACA_PAPER_EXECUTION", True)
    @patch("app.broker.orders.ALPACA_PAPER", "true")
    @patch("app.broker.orders.ENABLE_TRADING", False)
    def test_routes_to_alpaca_paper_when_configured(self, mock_get_client):
        fake_client = mock_get_client.return_value
        fake_order = type("Order", (), {"id": "order-paper-1", "status": "accepted"})()
        fake_client.submit_order.return_value = fake_order

        result = orders.submit_option_buy_order("QQQ260705C00500000", qty=1)

        self.assertTrue(result["submitted"])
        self.assertEqual(result["broker"], "ALPACA_PAPER")
        self.assertIn("USE_ALPACA_PAPER_EXECUTION=true", result.get("route_reason", ""))
        mock_get_client.assert_called_once()
        fake_client.submit_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
