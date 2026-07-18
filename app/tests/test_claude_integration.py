import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from app.ai.claude_decision_engine import ClaudeTradeDecision
from app.main import run_bot_scan


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 7, 18, 10, 0)
        if tz is not None:
            return base.replace(tzinfo=tz)
        return base


class _GateResult:
    def __init__(self, allowed, reason="ok"):
        self.allowed = allowed
        self.reason = reason

    def to_dict(self):
        return {"allowed": self.allowed, "reason": self.reason}


def _bars_frame():
    now = datetime.now(timezone.utc)
    rows = []
    for idx in range(30):
        price = 500.0 + (idx * 0.1)
        rows.append(
            {
                "timestamp": now - timedelta(minutes=29 - idx),
                "open": price - 0.1,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price,
                "volume": 10000 + idx,
            }
        )
    return pd.DataFrame(rows)


class TestClaudeIntegration(unittest.TestCase):
    def _claude_decision(self, decision, strategy, reason):
        return ClaudeTradeDecision(
            decision=decision,
            confidence=0.84 if decision in ["CALL", "PUT"] else 0.0,
            strategy=strategy,
            reason=reason,
            supporting_factors=[],
            conflicting_factors=[],
            position_size_percent=0.2 if decision in ["CALL", "PUT"] else 0.0,
            exit_profile="balanced" if decision in ["CALL", "PUT"] else "baseline",
            max_hold_minutes=30 if decision in ["CALL", "PUT"] else 0,
            require_tighter_spread=False,
            risk_notes=[],
            model="claude-sonnet-5",
            decided_at=datetime.now(timezone.utc).isoformat(),
        )

    def _aggregate_decision(self, decision="PUT"):
        return {
            "decision": decision,
            "total_score": 95,
            "confidence": 0.8,
            "quality": "A",
            "signals": [],
            "warnings": [],
        }

    def _analysis(self, direction="bearish"):
        return {"direction": direction, "data": {"regime": "TREND_DOWN"}, "signals": [], "warnings": [], "score": 10, "max_score": 10, "confidence": 0.9}

    def _route(self, direction="PUT", strategy_name="TREND_PULLBACK"):
        return {
            "strategy_name": strategy_name,
            "direction": direction,
            "confidence": 0.82,
            "reason": "route",
            "required_exit_profile": "balanced",
            "recommended_expiry_type": "same_day_or_next",
            "risk_multiplier": 1.0,
            "max_hold_minutes": 30,
        }

    def _contract(self, symbol):
        option_type = "CALL" if "C" in symbol else "PUT"
        return {
            "symbol": symbol,
            "option_type": option_type,
            "expiry_days": 1,
            "delta": 0.42,
            "volume": 3000,
            "open_interest": 5000,
            "mid": 1.1,
            "ask": 1.12,
        }

    def _quote(self):
        return {"quote_valid": True, "bid": 1.08, "ask": 1.12, "spread_percent": 0.03, "price": 1.1}

    def _patch_scan(self, claude_enabled, claude_decision, contract_symbol):
        mocks = {
            "is_market_hours": MagicMock(return_value=(True, "open")),
            "get_open_positions": MagicMock(return_value=[]),
            "monitor_all_open_positions_once": MagicMock(return_value={}),
            "get_latest_prices": MagicMock(return_value={"SPY": 600.0, "QQQ": 500.0, "IWM": 200.0}),
            "get_1min_bars": MagicMock(return_value=_bars_frame()),
            "calculate_ema": MagicMock(side_effect=lambda bars, _: bars["close"]),
            "calculate_vwap": MagicMock(side_effect=lambda bars: bars["close"]),
            "calculate_volume_average": MagicMock(side_effect=lambda bars: bars["volume"]),
            "calculate_premarket_levels": MagicMock(return_value=(501.0, 498.0)),
            "calculate_opening_range": MagicMock(return_value=(500.8, 499.2)),
            "calculate_previous_day_levels": MagicMock(return_value=(502.0, 497.0, 499.0)),
            "analyze_market_structure": MagicMock(return_value=self._analysis("bearish")),
            "analyze_support_resistance": MagicMock(return_value={"direction": "neutral", "data": {"support": 498.5, "resistance": 501.5}, "signals": [], "warnings": [], "score": 0, "max_score": 10, "confidence": 0.0}),
            "analyze_opening_range": MagicMock(return_value=self._analysis("bearish")),
            "analyze_gap_fill": MagicMock(return_value={"direction": "bearish", "data": {"gap_percent": -0.01}, "signals": [], "warnings": [], "score": 8, "max_score": 10, "confidence": 0.8}),
            "get_market_internal_price": MagicMock(return_value=20.0),
            "analyze_trend": MagicMock(return_value={"direction": "bearish", "data": {"vwap_distance_percent": -0.01}, "signals": [], "warnings": [], "score": 12, "max_score": 15, "confidence": 0.8}),
            "analyze_momentum": MagicMock(return_value={"direction": "bearish", "data": {"rsi": 35.0}, "signals": [], "warnings": [], "score": 10, "max_score": 10, "confidence": 1.0}),
            "analyze_volume": MagicMock(return_value={"direction": "bearish", "data": {"rvol": 1.2}, "signals": [], "warnings": [], "score": 10, "max_score": 15, "confidence": 0.7}),
            "analyze_volatility": MagicMock(return_value={"direction": "neutral", "data": {"atr": 1.0}, "signals": [], "warnings": [], "score": 5, "max_score": 10, "confidence": 0.5}),
            "analyze_candles": MagicMock(return_value={"direction": "bearish", "data": {"body_percent": 0.8}, "signals": [], "warnings": [], "score": 8, "max_score": 10, "confidence": 0.8}),
            "analyze_market_internals": MagicMock(return_value=self._analysis("neutral")),
            "analyze_news_risk": MagicMock(return_value={"direction": "neutral", "data": {"can_trade": True}, "signals": [], "warnings": [], "score": 5, "max_score": 5, "confidence": 1.0}),
            "analyze_regime": MagicMock(return_value={"direction": "bearish", "data": {"regime": "TREND_DOWN"}, "signals": [], "warnings": [], "score": 8, "max_score": 10, "confidence": 0.8}),
            "aggregate_scores": MagicMock(return_value=self._aggregate_decision("PUT")),
            "RiskManager": MagicMock(return_value=MagicMock(can_trade=MagicMock(return_value=(True, "Trading allowed")))),
            "calculate_atr": MagicMock(return_value=pd.Series([1.0] * 30)),
            "calculate_entry_quality_score": MagicMock(return_value={"entry_quality_score": 85}),
            "can_open_new_trade": MagicMock(return_value=(True, None)),
            "route_strategy": MagicMock(return_value=self._route(direction="PUT" if "P" in contract_symbol else "CALL")),
            "can_take_new_trade": MagicMock(return_value=True),
            "strategy_enabled": MagicMock(return_value=True),
            "choose_best_contract": MagicMock(return_value=(self._contract(contract_symbol), "ok")),
            "get_option_market_price": MagicMock(return_value=self._quote()),
            "get_total_open_risk": MagicMock(return_value=0.0),
            "submit_option_buy_order": MagicMock(return_value={"submitted": True, "order_id": "paper-1", "broker": "ALPACA_PAPER"}),
            "open_position": MagicMock(return_value={"position_id": "pos-1"}),
            "record_new_trade": MagicMock(),
            "log_trade_event": MagicMock(),
            "log_decision": MagicMock(),
            "get_pause_status": MagicMock(return_value={"paused": False}),
            "get_claude_status": MagicMock(return_value={"last_request_at": None, "enabled": claude_enabled, "model": "claude-sonnet-5", "api_status": "ok"}),
            "evaluate_claude_call_control": MagicMock(side_effect=lambda **kwargs: _GateResult(bool(kwargs.get("enabled") and kwargs.get("risk_allowed") and kwargs.get("market_snapshot", {}).get("latest_prices", {}).get("QQQ") and kwargs.get("paper_trading_confirmed") and kwargs.get("within_strategy_window") and kwargs.get("market_open")), "ok")),
            "get_summary": MagicMock(return_value={"today": {"realized_pnl": 0.0}}),
            "build_position_sizing_decision": MagicMock(return_value={"quantity": 1, "reason": "test"}),
            "get_available_budget": MagicMock(return_value=10000.0),
            "get_claude_trade_decision": MagicMock(return_value=claude_decision),
        }

        class _PatchBundle:
            def __enter__(self_inner):
                self_inner.stack = ExitStack()
                self_inner.stack.enter_context(patch("app.main.datetime", _FixedDateTime))
                self_inner.stack.enter_context(patch("app.main.CLAUDE_DECISION_ENABLED", claude_enabled))
                self_inner.stack.enter_context(patch("app.main.USE_STRATEGY_ROUTER", True))
                self_inner.stack.enter_context(patch("app.main.ENABLE_TRADING", False))
                self_inner.stack.enter_context(patch("app.main.ALPACA_PAPER", True))
                self_inner.stack.enter_context(patch("app.main.USE_ALPACA_PAPER_EXECUTION", True))
                self_inner.stack.enter_context(patch("app.main.USE_BUDGET_POSITION_SIZING", False))
                self_inner.stack.enter_context(patch("app.main.USE_DYNAMIC_POSITION_SIZE", False))
                self_inner.stack.enter_context(patch("app.main.POSITION_QUANTITY", 1))
                self_inner.stack.enter_context(patch("app.main.MAX_OPEN_POSITIONS", 4))
                self_inner.stack.enter_context(patch("app.main.MIN_CONTRACTS_PER_TRADE", 1))
                self_inner.stack.enter_context(patch("app.main.MAX_CONTRACTS_PER_TRADE", 4))
                for name, mock in mocks.items():
                    self_inner.stack.enter_context(patch(f"app.main.{name}", mock))
                return mocks

            def __exit__(self_inner, exc_type, exc, tb):
                return self_inner.stack.__exit__(exc_type, exc, tb)

        return _PatchBundle()

    def test_claude_disabled_keeps_existing_engine_final_source(self):
        decision = self._claude_decision("NO_TRADE", "CLAUDE_NO_TRADE", "disabled")
        with self._patch_scan(False, decision, "QQQ260710P00700000") as mocks:
            run_bot_scan()
        self.assertFalse(mocks["get_claude_trade_decision"].called)
        payload = mocks["log_decision"].call_args_list[0][0][0]
        self.assertEqual(payload["decision_source"], "EXISTING_ENGINE")

    def test_claude_enabled_valid_paper_mode_becomes_final_source_put(self):
        decision = self._claude_decision("PUT", "TREND_PULLBACK", "Bearish alignment")
        with self._patch_scan(True, decision, "QQQ260710P00700000") as mocks:
            run_bot_scan()
        self.assertEqual(mocks["choose_best_contract"].call_args[0][1], "PUT")
        entry_events = [call for call in mocks["log_trade_event"].call_args_list if call[0][0] == "ENTRY"]
        self.assertTrue(entry_events)
        self.assertEqual(entry_events[-1][0][1]["direction"], "PUT")
        self.assertEqual(mocks["submit_option_buy_order"].call_args[0][0], "QQQ260710P00700000")

    def test_claude_enabled_valid_paper_mode_becomes_final_source_call(self):
        decision = self._claude_decision("CALL", "VWAP_BOUNCE", "Bullish alignment")
        with self._patch_scan(True, decision, "QQQ260710C00710000") as mocks:
            run_bot_scan()
        self.assertEqual(mocks["choose_best_contract"].call_args[0][1], "CALL")
        entry_events = [call for call in mocks["log_trade_event"].call_args_list if call[0][0] == "ENTRY"]
        self.assertTrue(entry_events)
        self.assertEqual(entry_events[-1][0][1]["direction"], "CALL")
        self.assertEqual(mocks["submit_option_buy_order"].call_args[0][0], "QQQ260710C00710000")

    def test_direction_mismatch_blocks_execution(self):
        decision = self._claude_decision("CALL", "VWAP_BOUNCE", "Bullish alignment")
        with self._patch_scan(True, decision, "QQQ260710P00700000") as mocks:
            run_bot_scan()
        events = [call for call in mocks["log_trade_event"].call_args_list if call[0][0] == "DIRECTION_MISMATCH_BLOCK"]
        self.assertTrue(events)
        mocks["submit_option_buy_order"].assert_not_called()

    def test_no_claude_request_when_market_closed(self):
        decision = self._claude_decision("PUT", "TREND_PULLBACK", "Bearish alignment")
        with self._patch_scan(True, decision, "QQQ260710P00700000") as mocks:
            mocks["is_market_hours"].return_value = (False, "market_closed")
            run_bot_scan()
        mocks["get_claude_trade_decision"].assert_not_called()

    def test_no_claude_request_outside_strategy_hours(self):
        decision = self._claude_decision("PUT", "TREND_PULLBACK", "Bearish alignment")
        class _EarlyDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                base = datetime(2026, 7, 18, 8, 0)
                if tz is not None:
                    return base.replace(tzinfo=tz)
                return base

        with self._patch_scan(True, decision, "QQQ260710P00700000") as mocks, patch("app.main.datetime", _EarlyDateTime):
            run_bot_scan()
        mocks["get_claude_trade_decision"].assert_not_called()

    def test_no_claude_request_when_daily_risk_blocked(self):
        decision = self._claude_decision("PUT", "TREND_PULLBACK", "Bearish alignment")
        with self._patch_scan(True, decision, "QQQ260710P00700000") as mocks:
            mocks["can_take_new_trade"].return_value = False
            run_bot_scan()
        mocks["get_claude_trade_decision"].assert_not_called()

    def test_no_claude_request_when_market_data_missing(self):
        decision = self._claude_decision("PUT", "TREND_PULLBACK", "Bearish alignment")
        with self._patch_scan(True, decision, "QQQ260710P00700000") as mocks:
            mocks["get_latest_prices"].return_value = {"SPY": 600.0, "QQQ": 0.0, "IWM": 200.0}
            run_bot_scan()
        mocks["get_claude_trade_decision"].assert_not_called()

    def test_one_claude_request_per_scan_enforced(self):
        decision = self._claude_decision("PUT", "TREND_PULLBACK", "Bearish alignment")
        with self._patch_scan(True, decision, "QQQ260710P00700000") as mocks:
            run_bot_scan()
        self.assertEqual(mocks["get_claude_trade_decision"].call_count, 1)


if __name__ == "__main__":
    unittest.main()