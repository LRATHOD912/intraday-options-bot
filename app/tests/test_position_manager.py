import json
import tempfile
import unittest
from pathlib import Path

from app.execution.position_manager import PositionManager


class TestPositionManager(unittest.TestCase):
    def test_open_position_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "positions.json"
            manager = PositionManager(str(json_path))

            self.assertFalse(manager.has_open_position())
            opened = manager.open_position(
                symbol="QQQ",
                option_symbol="QQQ260705C00500000",
                direction="CALL",
                quantity=1,
                entry_price=2.15,
                stop_price=1.70,
                target_0=2.25,
                target_1=2.45,
                target_2=2.75,
                entry_time="2026-07-05T10:15:00",
                order_id="order-123",
            )

            self.assertTrue(manager.has_open_position())
            self.assertEqual(opened["status"], "OPEN")
            self.assertEqual(opened["direction"], "CALL")
            self.assertEqual(opened["original_quantity"], 1)
            self.assertEqual(opened["remaining_quantity"], 1)
            self.assertIn("risk_per_contract", opened)
            self.assertIn("target_1x", opened)
            self.assertIn("target_2x", opened)
            self.assertIn("target_3x", opened)
            self.assertIn("target_4x", opened)
            self.assertFalse(opened["took_1x_profit"])
            self.assertFalse(opened["took_2x_profit"])
            self.assertFalse(opened["stop_moved_to_breakeven"])

            persisted = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["position"]["option_symbol"], "QQQ260705C00500000")
            self.assertEqual(persisted["position"]["status"], "OPEN")

            reloaded_manager = PositionManager(str(json_path))
            reloaded_open = reloaded_manager.get_open_position()
            self.assertIsNotNone(reloaded_open)
            self.assertEqual(reloaded_open["order_id"], "order-123")

    def test_partial_update_persists_remaining_quantity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "positions.json"
            manager = PositionManager(str(json_path))

            manager.open_position(
                symbol="QQQ",
                option_symbol="QQQ260705C00500000",
                direction="CALL",
                quantity=4,
                entry_price=2.00,
                stop_price=1.60,
                target_0=2.40,
                target_1=2.80,
                target_2=3.20,
                target_3=3.60,
                target_4=4.00,
                risk_per_contract=0.40,
                order_id="order-staged-1",
            )

            updated = manager.update_open_position(
                {
                    "remaining_quantity": 2,
                    "quantity": 2,
                    "took_1x_profit": True,
                    "stop_moved_to_breakeven": True,
                    "trailing_stop_price": 2.10,
                }
            )

            self.assertIsNotNone(updated)
            self.assertEqual(updated["remaining_quantity"], 2)
            self.assertEqual(updated["quantity"], 2)
            self.assertTrue(updated["took_1x_profit"])
            self.assertTrue(updated["stop_moved_to_breakeven"])
            self.assertEqual(updated["trailing_stop_price"], 2.10)

            reloaded_manager = PositionManager(str(json_path))
            reloaded = reloaded_manager.get_open_position()
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded["remaining_quantity"], 2)
            self.assertTrue(reloaded["took_1x_profit"])

    def test_only_one_open_position(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "positions.json"
            manager = PositionManager(str(json_path))

            manager.open_position(
                symbol="QQQ",
                option_symbol="QQQ260705P00500000",
                direction="PUT",
                quantity=1,
                entry_price=1.95,
                stop_price=2.30,
                target_0=1.85,
                target_1=1.70,
                target_2=1.50,
                order_id="order-put-1",
            )

            with self.assertRaises(ValueError):
                manager.open_position(
                    symbol="QQQ",
                    option_symbol="QQQ260705C00510000",
                    direction="CALL",
                    quantity=1,
                    entry_price=2.10,
                    stop_price=1.80,
                    target_0=2.30,
                    target_1=2.55,
                    target_2=2.90,
                    order_id="order-call-2",
                )

    def test_close_position_and_restart_state(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "positions.json"
            manager = PositionManager(str(json_path))

            manager.open_position(
                symbol="QQQ",
                option_symbol="QQQ260705C00500000",
                direction="CALL",
                quantity=2,
                entry_price=2.00,
                stop_price=1.60,
                target_0=2.10,
                target_1=2.30,
                target_2=2.60,
                order_id="order-xyz",
            )

            closed = manager.close_position(close_time="2026-07-05T10:30:00", exit_price=2.35)
            self.assertIsNotNone(closed)
            self.assertEqual(closed["status"], "CLOSED")
            self.assertEqual(closed["exit_price"], 2.35)
            self.assertFalse(manager.has_open_position())
            self.assertIsNone(manager.get_open_position())

            reloaded_manager = PositionManager(str(json_path))
            self.assertFalse(reloaded_manager.has_open_position())

            persisted = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["position"]["status"], "CLOSED")


if __name__ == "__main__":
    unittest.main()
