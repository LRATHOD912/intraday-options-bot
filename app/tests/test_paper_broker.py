import importlib
import json
import tempfile
import unittest
from pathlib import Path

from app.broker import paper_broker


class TestPaperBroker(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.tmp_dir.name) / "paper_orders.jsonl"
        paper_broker.LOG_PATH = self.log_path
        paper_broker._ORDERS.clear()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_buy_order_creates_filled_order(self):
        order = paper_broker.submit_buy_order("QQQ260705C00500000", qty=1, price=2.25)

        self.assertEqual(order["side"], "BUY")
        self.assertEqual(order["status"], "FILLED")
        self.assertEqual(order["qty"], 1)
        self.assertIsNotNone(order["order_id"])
        self.assertTrue(self.log_path.exists())

    def test_sell_order_creates_filled_order(self):
        order = paper_broker.submit_sell_order("QQQ260705P00500000", qty=2, price=1.85)

        self.assertEqual(order["side"], "SELL")
        self.assertEqual(order["status"], "FILLED")
        self.assertEqual(order["qty"], 2)

    def test_get_order_status_returns_saved_order(self):
        created = paper_broker.submit_buy_order("QQQ260705C00510000", qty=1, price=2.05)
        status = paper_broker.get_order_status(created["order_id"])

        self.assertIsNotNone(status)
        self.assertEqual(status["order_id"], created["order_id"])
        self.assertEqual(status["symbol"], created["symbol"])

    def test_cancel_order_changes_status_if_not_filled(self):
        pending_order = {
            "order_id": "test-pending-order",
            "symbol": "QQQ260705C00520000",
            "qty": 1,
            "side": "BUY",
            "price": 2.1,
            "status": "NEW",
            "timestamp": "2026-07-05T10:00:00-04:00",
        }
        paper_broker._ORDERS[pending_order["order_id"]] = dict(pending_order)
        paper_broker._append_order_event(pending_order)

        cancelled = paper_broker.cancel_order(pending_order["order_id"])
        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled["status"], "CANCELLED")

        reloaded = importlib.reload(paper_broker)
        reloaded.LOG_PATH = self.log_path
        reloaded._load_orders_from_log()
        status = reloaded.get_order_status(pending_order["order_id"])
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
