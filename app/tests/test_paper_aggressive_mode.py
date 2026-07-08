import unittest
from unittest.mock import patch

from app.main import _paper_aggressive_override


class TestPaperAggressiveMode(unittest.TestCase):
    @patch("app.main.PAPER_AGGRESSIVE_MODE", False)
    def test_aggressive_mode_false_keeps_normal_behavior(self):
        result = _paper_aggressive_override(
            strategy_route={"confidence": 0.9},
            entry_quality_score=59,
            option_spread_percent=0.03,
        )
        self.assertFalse(result["active"])
        self.assertFalse(result["allowed"])

    @patch("app.main.PAPER_AGGRESSIVE_MODE", True)
    @patch("app.main.ENABLE_TRADING", False)
    @patch("app.main.ALPACA_PAPER", True)
    @patch("app.main.USE_ALPACA_PAPER_EXECUTION", True)
    def test_aggressive_mode_true_allows_reversal_entry_quality_59(self):
        result = _paper_aggressive_override(
            strategy_route={"confidence": 0.86},
            entry_quality_score=59,
            option_spread_percent=0.07,
        )
        self.assertTrue(result["active"])
        self.assertTrue(result["allowed"])
        self.assertIn("entry_quality threshold relaxed", result["relaxed_rules"])

    @patch("app.main.PAPER_AGGRESSIVE_MODE", True)
    @patch("app.main.ENABLE_TRADING", False)
    @patch("app.main.ALPACA_PAPER", True)
    @patch("app.main.USE_ALPACA_PAPER_EXECUTION", True)
    def test_aggressive_mode_true_allows_choppy_entry_quality_64_when_route_exists(self):
        result = _paper_aggressive_override(
            strategy_route={"confidence": 0.70, "strategy_name": "VWAP_BOUNCE"},
            entry_quality_score=64,
            option_spread_percent=0.06,
        )
        self.assertTrue(result["active"])
        self.assertTrue(result["allowed"])

    @patch("app.main.PAPER_AGGRESSIVE_MODE", False)
    def test_strict_mode_still_rejects_same_setup(self):
        result = _paper_aggressive_override(
            strategy_route={"confidence": 0.86, "strategy_name": "GAP_FILL_REVERSAL"},
            entry_quality_score=59,
            option_spread_percent=0.07,
        )
        self.assertFalse(result["active"])
        self.assertFalse(result["allowed"])

    @patch("app.main.PAPER_AGGRESSIVE_MODE", True)
    @patch("app.main.ENABLE_TRADING", False)
    @patch("app.main.ALPACA_PAPER", True)
    @patch("app.main.USE_ALPACA_PAPER_EXECUTION", True)
    def test_aggressive_mode_still_blocks_spread_over_8_percent(self):
        result = _paper_aggressive_override(
            strategy_route={"confidence": 0.70},
            entry_quality_score=59,
            option_spread_percent=0.09,
        )
        self.assertTrue(result["active"])
        self.assertFalse(result["allowed"])

    @patch("app.main.PAPER_AGGRESSIVE_MODE", True)
    @patch("app.main.ENABLE_TRADING", False)
    @patch("app.main.ALPACA_PAPER", False)
    @patch("app.main.USE_ALPACA_PAPER_EXECUTION", True)
    def test_aggressive_mode_cannot_activate_when_not_paper(self):
        result = _paper_aggressive_override(
            strategy_route={"confidence": 0.70},
            entry_quality_score=59,
            option_spread_percent=0.07,
        )
        self.assertFalse(result["active"])
        self.assertFalse(result["allowed"])

    @patch("app.main.PAPER_AGGRESSIVE_MODE", True)
    @patch("app.main.ENABLE_TRADING", False)
    @patch("app.main.ALPACA_PAPER", True)
    @patch("app.main.USE_ALPACA_PAPER_EXECUTION", True)
    def test_aggressive_mode_still_blocks_invalid_contract_in_pre_buy_gate(self):
        from app.main import _validate_pre_buy_gate

        allowed, reason = _validate_pre_buy_gate(
            contract={"symbol": "", "expiry_days": 1, "delta": 0.4, "volume": 1000, "open_interest": 2000},
            option_quote={"quote_valid": True, "bid": 1.0, "ask": 1.02},
            spread_percent=0.02,
            entry_price=1.01,
            trade_quantity=1,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "missing_option_symbol")

    @patch("app.main.get_available_budget", return_value=50.0)
    def test_buying_power_insufficient_still_blocks(self, _mock_budget):
        from app.main import _validate_pre_buy_gate

        allowed, reason = _validate_pre_buy_gate(
            contract={"symbol": "QQQ260705C00500000", "expiry_days": 1, "delta": 0.4, "volume": 1000, "open_interest": 2000},
            option_quote={"quote_valid": True, "bid": 1.0, "ask": 1.02},
            spread_percent=0.02,
            entry_price=1.01,
            trade_quantity=2,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "buying_power_insufficient")


if __name__ == "__main__":
    unittest.main()
