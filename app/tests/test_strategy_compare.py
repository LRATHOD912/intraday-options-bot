import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from zoneinfo import ZoneInfo

from app.backtest import strategy_compare


class TestStrategyCompareResearch(unittest.TestCase):
    def test_metrics_from_results(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result_path = Path(tmp_dir) / "results.jsonl"
            result_path.write_text(
                "\n".join(
                    [
                        json.dumps({"gate_allowed": True, "realized_pnl": 120.0, "r_multiple": 1.2, "timestamp": "2026-07-05T10:15:00-04:00"}),
                        json.dumps({"gate_allowed": True, "realized_pnl": -40.0, "r_multiple": -0.4, "timestamp": "2026-07-05T11:00:00-04:00"}),
                        json.dumps({"gate_allowed": False, "realized_pnl": 999.0, "timestamp": "2026-07-05T11:30:00-04:00"}),
                    ]
                ),
                encoding="utf-8",
            )

            metrics = strategy_compare._metrics_from_results(result_path)

            self.assertIsNotNone(metrics)
            self.assertEqual(metrics.trades, 2)
            self.assertAlmostEqual(metrics.win_rate, 0.5)
            self.assertEqual(metrics.best_day, "2026-07-05")
            self.assertEqual(metrics.worst_day, "2026-07-05")

    def test_walk_forward_validation_aggregates_fold_metrics(self):
        tz = ZoneInfo("America/New_York")
        timestamps = pd.date_range("2026-07-01 09:30", periods=6, freq="D", tz=tz)
        cache_payload = {
            "qqq_bars": pd.DataFrame({"timestamp": timestamps, "close": [500, 501, 502, 503, 504, 505]}),
            "vix_proxy_now": 12.5,
        }
        config = strategy_compare.StrategyCompareConfig(
            config_name="quick|regime=True|entry_q=75|exit=balanced",
            use_regime_filter=True,
            min_entry_quality_score=75,
            exit_profile="balanced",
            use_tuned_staged_exits=True,
            option_filter_strictness="normal",
            slippage_percent=0.0,
        )

        def fake_run_combo(overrides, cache_payload_arg, timeout_seconds, window=None):
            return {
                "ok": True,
                "elapsed": 0.5,
                "window": window.label if window else None,
                "metrics": strategy_compare.StrategyCompareMetrics(
                    trades=10,
                    win_rate=0.6,
                    avg_r=0.8,
                    expectancy=50.0,
                    profit_factor=1.5,
                    max_drawdown=25.0,
                    avg_profit=120.0,
                    avg_loss=-60.0,
                    best_day="2026-07-02",
                    worst_day="2026-07-03",
                ),
            }

        with patch.object(strategy_compare, "_load_or_build_cache", return_value=cache_payload), patch.object(strategy_compare, "_run_combo", side_effect=fake_run_combo):
            result = strategy_compare.run_walk_forward_validation(config, lookback_days=5, folds=2, fold_days=1, timeout_seconds=5)

        self.assertEqual(result["config_name"], config.config_name)
        self.assertEqual(result["aggregate"]["folds"], 2)
        self.assertEqual(result["aggregate"]["valid_folds"], 2)
        self.assertAlmostEqual(result["aggregate"]["avg_expectancy"], 50.0)
        self.assertEqual(len(result["folds"]), 2)
        self.assertTrue(all(row["ok"] for row in result["folds"]))

    def test_config_to_overrides(self):
        config = strategy_compare.StrategyCompareConfig(
            config_name="full|regime=False|entry_q=80|exit=scalp|strict=strict|slip=2",
            use_regime_filter=False,
            min_entry_quality_score=80,
            exit_profile="scalp",
            use_tuned_staged_exits=True,
            option_filter_strictness="strict",
            slippage_percent=0.02,
        )

        overrides = config.to_overrides()

        self.assertEqual(overrides["config_name"], config.config_name)
        self.assertEqual(overrides["exit_profile"], "scalp")
        self.assertTrue(overrides["use_tuned_staged_exits"])


if __name__ == "__main__":
    unittest.main()