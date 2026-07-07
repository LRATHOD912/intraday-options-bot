import unittest
from unittest.mock import patch

from app.execution.monitor import check_exit_rules


class TestExitMonitorGuards(unittest.TestCase):
    @patch("app.execution.monitor.submit_option_sell_order")
    @patch("app.execution.monitor.has_open_position", return_value=False)
    def test_no_open_position_skips_exit_monitor(self, _mock_has_position, mock_submit_sell):
        result = check_exit_rules("QQQ260705C00500000", entry_price=2.0, current_price=1.5, qty=1)

        self.assertFalse(result["exit"])
        self.assertEqual(result["reason"], "No open position")
        self.assertIsNone(result["order"])
        mock_submit_sell.assert_not_called()

    @patch("app.execution.monitor.submit_option_sell_order", return_value={"submitted": True, "order_id": "sell-1"})
    @patch("app.execution.monitor.has_open_position", return_value=True)
    def test_real_open_position_executes_exit_monitor(self, _mock_has_position, mock_submit_sell):
        result = check_exit_rules("QQQ260705C00500000", entry_price=2.0, current_price=1.5, qty=1)

        self.assertTrue(result["exit"])
        self.assertEqual(result["reason"], "Stop loss hit")
        self.assertEqual(result["order"], {"submitted": True, "order_id": "sell-1"})
        mock_submit_sell.assert_called_once_with("QQQ260705C00500000", 1)


if __name__ == "__main__":
    unittest.main()
