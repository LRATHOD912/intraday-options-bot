import unittest
from datetime import datetime, timedelta, timezone

from app.ai.claude_safety_gate import evaluate_claude_call_control, evaluate_claude_execution_gate


class TestClaudeSafetyGate(unittest.TestCase):
    def _snapshot(self, age_seconds=5):
        now = datetime.now(timezone.utc)
        ts = (now - timedelta(seconds=age_seconds)).isoformat()
        return {
            "latest_prices": {"QQQ": 500.0},
            "latest_bar": {
                "timestamp": ts,
                "open": 499.0,
                "high": 501.0,
                "low": 498.0,
                "close": 500.0,
                "volume": 1000.0,
                "vwap": 499.5,
                "ema_9": 499.8,
                "ema_20": 499.2,
                "avg_volume": 950.0,
            },
            "analysis_results": [{"engine": "x"}],
        }

    def _contract(self, symbol="QQQ260710P00700000", expiry_days=1, delta=0.42, volume=2000, open_interest=3000, option_type="PUT"):
        return {
            "symbol": symbol,
            "expiry_days": expiry_days,
            "delta": delta,
            "volume": volume,
            "open_interest": open_interest,
            "option_type": option_type,
            "mid": 1.1,
            "ask": 1.12,
        }

    def _quote(self, bid=1.08, ask=1.12, quote_valid=True):
        return {"bid": bid, "ask": ask, "quote_valid": quote_valid, "spread_percent": 0.03, "price": 1.1}

    def test_call_control_blocks_market_closed(self):
        result = evaluate_claude_call_control(
            enabled=True,
            paper_trading_confirmed=True,
            market_open=False,
            within_strategy_window=True,
            risk_allowed=True,
            market_snapshot=self._snapshot(),
            last_called_at=None,
            min_seconds_between_calls=15,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "market_closed")

    def test_call_control_blocks_missing_market_data(self):
        result = evaluate_claude_call_control(
            enabled=True,
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            risk_allowed=True,
            market_snapshot={},
            last_called_at=None,
            min_seconds_between_calls=15,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "missing_market_data")

    def test_call_control_enforces_min_seconds_between_calls(self):
        now = datetime.now(timezone.utc)
        result = evaluate_claude_call_control(
            enabled=True,
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            risk_allowed=True,
            market_snapshot=self._snapshot(),
            last_called_at=(now - timedelta(seconds=3)).isoformat(),
            min_seconds_between_calls=15,
            now=now,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "claude_rate_limited")

    def test_execution_gate_blocks_unconfirmed_paper_mode(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=False,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "paper_mode_unconfirmed")

    def test_execution_gate_blocks_placeholder_symbol(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(symbol="QQQ_TEST_PLACEHOLDER", option_type="PUT"),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "placeholder_option_symbol")

    def test_execution_gate_blocks_missing_bid_ask(self):
        quote = {"quote_valid": True, "bid": None, "ask": 1.1}
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(),
            option_quote=quote,
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "missing_bid_ask")

    def test_execution_gate_blocks_spread(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(),
            option_quote=self._quote(),
            spread_percent=0.07,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "spread_too_wide")

    def test_execution_gate_blocks_zero_dte(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(expiry_days=0),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "zero_dte_not_allowed")

    def test_execution_gate_blocks_volume(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(volume=100),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "option_volume_too_low")

    def test_execution_gate_blocks_open_interest(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(open_interest=100),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "option_open_interest_too_low")

    def test_execution_gate_blocks_price_bounds(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=20.0,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "option_price_out_of_bounds")

    def test_execution_gate_blocks_buying_power(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=2,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=100.0,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "buying_power_insufficient")

    def test_execution_gate_blocks_daily_loss_limit(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=False,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "daily_risk_limit_reached")

    def test_execution_gate_blocks_max_open_risk(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=490.0,
            new_trade_risk=20.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "total_open_risk_exceeded")

    def test_execution_gate_blocks_max_positions(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=4,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "max_open_positions_reached")

    def test_execution_gate_blocks_duplicate_position(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=True,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "duplicate_position")

    def test_execution_gate_blocks_direction_mismatch(self):
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=datetime.now(timezone.utc).isoformat(),
            decision_direction="CALL",
            trade_plan_direction="CALL",
            selector_direction="CALL",
            contract=self._contract(symbol="QQQ260710P00700000", option_type="PUT"),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "direction_mismatch")

    def test_execution_gate_blocks_stale_claude_response(self):
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        result = evaluate_claude_execution_gate(
            paper_trading_confirmed=True,
            market_open=True,
            within_strategy_window=True,
            market_snapshot=self._snapshot(),
            claude_decided_at=stale_time,
            decision_direction="PUT",
            trade_plan_direction="PUT",
            selector_direction="PUT",
            contract=self._contract(),
            option_quote=self._quote(),
            spread_percent=0.03,
            spread_limit=0.05,
            entry_price=1.1,
            trade_quantity=1,
            allow_0dte=False,
            preferred_delta_min=0.35,
            preferred_delta_max=0.5,
            min_option_volume=500,
            min_option_open_interest=1000,
            min_option_price=0.5,
            max_option_price=15.0,
            buying_power=1000,
            daily_risk_ok=True,
            total_open_risk=0.0,
            new_trade_risk=50.0,
            max_total_open_risk=500.0,
            total_open_positions=0,
            max_open_positions=4,
            duplicate_position=False,
            conflicting_position=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "stale_claude_decision")


if __name__ == "__main__":
    unittest.main()