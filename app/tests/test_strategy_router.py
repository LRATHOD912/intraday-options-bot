import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.analytics import strategy_performance
from app.risk.strategy_control import strategy_enabled
from app.strategy import strategy_router


class TestStrategyRouter(unittest.TestCase):
    def setUp(self):
        self.now_et = datetime(2026, 7, 7, 13, 0, tzinfo=ZoneInfo("America/New_York"))
        self.base_master = {"total_score": 95}
        self.base_regime = {"data": {"regime": "TREND_UP"}}

    def _route(self, **kwargs):
        context = {
            "regime_result": self.base_regime,
            "master_score": self.base_master,
            "vwap_distance_percent": 0.004,
            "ema_9": 522.0,
            "ema_20": 520.0,
            "latest_close": 523.5,
            "opening_high": 523.0,
            "opening_low": 518.0,
            "prev_day_high": 524.0,
            "prev_day_low": 516.0,
            "support_level": 522.2,
            "resistance_level": 525.5,
            "atr_percent": 0.01,
            "rvol": 2.0,
            "candle_body_percent": 0.6,
            "momentum_direction": "bullish",
            "gap_direction": "bullish",
            "opening_range_result": {"direction": "bullish"},
            "trend_result": {"direction": "bullish"},
            "volume_result": {"direction": "bullish"},
            "candle_result": {"direction": "bullish"},
            "support_resistance_result": {"direction": "bullish", "data": {"support": 522.2, "resistance": 525.5}},
            "current_time_et": self.now_et,
            "option_spread_percent": 0.03,
            "option_liquidity_score": 0.8,
            "option_premium": 0.75,
            "gap_percent": 0.012,
            "gap_fill_direction": "bullish",
            "price_near_support": True,
            "price_near_resistance": False,
        }
        if "base_regime" in kwargs:
            context["regime_result"] = kwargs.pop("base_regime")
        context.update(kwargs)
        return strategy_router.route_strategy(**context)

    def test_momentum_breakout_call(self):
        with patch.object(strategy_router, "ENABLE_MOMENTUM_BREAKOUT", True), patch.object(strategy_router, "ENABLE_MOMENTUM_RUNNER", True):
            route = self._route()
        self.assertEqual(route["strategy_name"], "MOMENTUM_BREAKOUT")
        self.assertEqual(route["direction"], "CALL")
        self.assertEqual(route["required_exit_profile"], "runner")

    def test_momentum_breakout_put(self):
        with patch.object(strategy_router, "ENABLE_MOMENTUM_BREAKOUT", True), patch.object(strategy_router, "ENABLE_MOMENTUM_RUNNER", True):
            route = self._route(
                base_regime={"data": {"regime": "TREND_DOWN"}},
                ema_9=518.0,
                ema_20=520.0,
                latest_close=517.5,
                opening_high=521.5,
                opening_low=518.0,
                vwap_distance_percent=-0.005,
                momentum_direction="bearish",
                volume_result={"direction": "bearish"},
                candle_result={"direction": "bearish"},
                trend_result={"direction": "bearish"},
                gap_direction="bearish",
                gap_fill_direction="bearish",
                support_resistance_result={"direction": "bearish", "data": {"support": 516.5, "resistance": 520.5}},
                price_near_support=False,
                price_near_resistance=True,
                rvol=2.1,
                candle_body_percent=0.62,
            )
        self.assertEqual(route["strategy_name"], "MOMENTUM_BREAKOUT")
        self.assertEqual(route["direction"], "PUT")

    def test_vwap_bounce(self):
        with patch.object(strategy_router, "ENABLE_VWAP_BOUNCE", True):
            route = self._route(
                base_regime={"data": {"regime": "RANGE"}},
                vwap_distance_percent=0.0005,
                latest_close=522.05,
                price_near_support=False,
                price_near_resistance=False,
                gap_direction="neutral",
                gap_fill_direction="neutral",
                rvol=1.3,
                candle_body_percent=0.42,
                momentum_direction="bullish",
                candle_result={"direction": "bullish"},
            )
        self.assertEqual(route["strategy_name"], "VWAP_BOUNCE")
        self.assertEqual(route["direction"], "CALL")

    def test_gap_and_go(self):
        with patch.object(strategy_router, "ENABLE_GAP_AND_GO", True):
            route = self._route(
                base_regime={"data": {"regime": "TREND_UP"}},
                gap_direction="bullish",
                opening_range_result={"direction": "bullish"},
                latest_close=524.0,
                opening_high=523.0,
                opening_low=518.0,
                rvol=1.7,
                momentum_direction="bullish",
                candle_result={"direction": "bullish"},
                volume_result={"direction": "bullish"},
            )
        self.assertEqual(route["strategy_name"], "GAP_AND_GO")
        self.assertEqual(route["direction"], "CALL")

    def test_range_scalp_call(self):
        with patch.object(strategy_router, "ENABLE_RANGE_SCALP_0DTE", True):
            route = self._route(
                base_regime={"data": {"regime": "RANGE"}},
                current_time_et=datetime(2026, 7, 7, 13, 10, tzinfo=ZoneInfo("America/New_York")),
                option_premium=0.85,
                price_near_support=True,
                price_near_resistance=False,
                candle_result={"direction": "bullish"},
                momentum_direction="bullish",
                rvol=1.1,
                latest_close=520.2,
                support_level=520.0,
                resistance_level=523.0,
                vwap_distance_percent=0.0002,
                candle_body_percent=0.44,
            )
        self.assertEqual(route["strategy_name"], "RANGE_SCALP_0DTE")
        self.assertEqual(route["direction"], "CALL")

    def test_range_scalp_put(self):
        with patch.object(strategy_router, "ENABLE_RANGE_SCALP_0DTE", True):
            route = self._route(
                base_regime={"data": {"regime": "CHOPPY"}},
                current_time_et=datetime(2026, 7, 7, 13, 20, tzinfo=ZoneInfo("America/New_York")),
                option_premium=0.9,
                price_near_support=False,
                price_near_resistance=True,
                candle_result={"direction": "bearish"},
                momentum_direction="bearish",
                rvol=1.1,
                latest_close=523.8,
                support_level=520.0,
                resistance_level=524.0,
                vwap_distance_percent=-0.0003,
                candle_body_percent=0.46,
            )
        self.assertEqual(route["strategy_name"], "RANGE_SCALP_0DTE")
        self.assertEqual(route["direction"], "PUT")

    def test_0dte_blocked_outside_range_scalp_window(self):
        with patch.object(strategy_router, "ENABLE_RANGE_SCALP_0DTE", True):
            route = self._route(
                base_regime={"data": {"regime": "RANGE"}},
                current_time_et=datetime(2026, 7, 7, 10, 15, tzinfo=ZoneInfo("America/New_York")),
                option_premium=0.85,
                price_near_support=True,
                price_near_resistance=False,
                candle_result={"direction": "neutral"},
                momentum_direction="neutral",
                rvol=1.1,
                latest_close=520.2,
                support_level=520.0,
                resistance_level=523.0,
                vwap_distance_percent=0.0002,
                candle_body_percent=0.35,
            )
        self.assertNotEqual(route["strategy_name"], "RANGE_SCALP_0DTE")

    def test_auto_disable_after_three_losses(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir) / "strategy_performance.json"
            with patch.object(strategy_performance, "STRATEGY_PERF_PATH", temp_path):
                strategy_performance.record_strategy_trade("MOMENTUM_BREAKOUT", pnl=-10.0, r_multiple=-1.0)
                strategy_performance.record_strategy_trade("MOMENTUM_BREAKOUT", pnl=-8.0, r_multiple=-0.8)
                strategy_performance.record_strategy_trade("MOMENTUM_BREAKOUT", pnl=-12.0, r_multiple=-1.2)
                status = strategy_performance.get_strategy_status()
                self.assertIn("MOMENTUM_BREAKOUT", status["disabled_strategies"])
                self.assertFalse(strategy_enabled("MOMENTUM_BREAKOUT"))


if __name__ == "__main__":
    unittest.main()