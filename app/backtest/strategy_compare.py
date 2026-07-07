"""Strategy comparison and walk-forward research utilities.

The default path remains the existing quick/full compare runner. A separate
walk-forward validation mode can be enabled explicitly through flags or config
without affecting live or paper execution paths.
"""

import argparse
import csv
import json
import pickle
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from app.backtest.backtest_runner import LOG_PATH, run_backtest
from app.config import BACKTEST_ENABLE_WALK_FORWARD, BACKTEST_WALK_FORWARD_DAYS, BACKTEST_WALK_FORWARD_FOLDS
from app.market.market_data import get_1min_bars as fetch_1min_bars
from app.market.market_data import get_market_internal_price as fetch_market_internal_price


OUT_PATH = Path("logs/strategy_compare.csv")
CACHE_PATH = Path("logs/strategy_compare_cache.pkl")
CACHE_VERSION = 4
QUICK_LOOKBACK_DAYS = 2
FULL_LOOKBACK_DAYS = 5
MAX_COMBINATIONS = 20
COMBO_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class StrategyCompareConfig:
    """Single strategy-comparison configuration with explicit overrides."""

    config_name: str
    use_regime_filter: bool
    min_entry_quality_score: int
    exit_profile: str
    use_tuned_staged_exits: bool
    option_filter_strictness: str
    slippage_percent: float = 0.0

    def to_overrides(self) -> dict:
        return {
            "config_name": self.config_name,
            "use_regime_filter": self.use_regime_filter,
            "min_entry_quality_score": self.min_entry_quality_score,
            "exit_profile": self.exit_profile,
            "use_tuned_staged_exits": self.use_tuned_staged_exits,
            "option_filter_strictness": self.option_filter_strictness,
            "slippage_percent": self.slippage_percent,
        }


@dataclass(frozen=True)
class StrategyCompareMetrics:
    """Normalized result metrics from a backtest output file."""

    trades: int
    win_rate: float
    avg_r: float
    expectancy: float
    profit_factor: float
    max_drawdown: float
    avg_profit: float
    avg_loss: float
    best_day: Optional[str]
    worst_day: Optional[str]

    def to_row(self) -> dict:
        return {
            "trades": self.trades,
            "win_rate": self.win_rate,
            "avg_R": self.avg_r,
            "expectancy": self.expectancy,
            "profit_factor": self.profit_factor,
            "max_drawdown": self.max_drawdown,
            "avg_profit": self.avg_profit,
            "avg_loss": self.avg_loss,
            "best_day": self.best_day,
            "worst_day": self.worst_day,
        }


@dataclass(frozen=True)
class WalkForwardWindow:
    """A single rolling validation window within cached market data."""

    label: str
    start_time: datetime
    end_time: datetime


def _metrics_from_results(path: Path) -> Optional[StrategyCompareMetrics]:
    rows = []
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    trades = [r for r in rows if r.get("gate_allowed") and r.get("realized_pnl") is not None]
    pnls = [float(t.get("realized_pnl", 0.0)) for t in trades]
    rs = [float(t.get("r_multiple", 0.0)) for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    by_day = {}
    for row in trades:
        ts = str(row.get("timestamp", ""))
        day_key = ts[:10]
        by_day.setdefault(day_key, 0.0)
        by_day[day_key] += float(row.get("realized_pnl", 0.0))

    best_day = max(by_day, key=lambda day: by_day[day]) if by_day else None
    worst_day = min(by_day, key=lambda day: by_day[day]) if by_day else None

    expectancy = (sum(pnls) / len(pnls)) if pnls else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else (9999.0 if wins else 0.0)

    return StrategyCompareMetrics(
        trades=len(pnls),
        win_rate=(len(wins) / len(pnls)) if pnls else 0.0,
        avg_r=(sum(rs) / len(rs)) if rs else 0.0,
        expectancy=expectancy,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        avg_profit=(sum(wins) / len(wins)) if wins else 0.0,
        avg_loss=(sum(losses) / len(losses)) if losses else 0.0,
        best_day=best_day,
        worst_day=worst_day,
    )


def _build_configs(quick: bool) -> list[StrategyCompareConfig]:
    if quick:
        return [
            StrategyCompareConfig(
                config_name=f"quick|regime={use_regime_filter}|entry_q={min_entry_quality_score}|exit={exit_profile}",
                use_regime_filter=use_regime_filter,
                min_entry_quality_score=min_entry_quality_score,
                exit_profile=exit_profile,
                use_tuned_staged_exits=exit_profile != "baseline",
                option_filter_strictness="normal",
                slippage_percent=0.0,
            )
            for use_regime_filter in [False, True]
            for min_entry_quality_score in [75, 80]
            for exit_profile in ["baseline", "balanced"]
        ]

    configs = []
    for use_regime_filter in [False, True]:
        for min_entry_quality_score in [70, 75, 80, 85]:
            for exit_profile in ["baseline", "scalp", "balanced", "runner"]:
                for option_filter_strictness in ["loose", "normal", "strict"]:
                    for slippage_percent in [0.0, 0.02, 0.05]:
                        configs.append(
                            StrategyCompareConfig(
                                config_name=(
                                    f"full|regime={use_regime_filter}|entry_q={min_entry_quality_score}"
                                    f"|exit={exit_profile}|strict={option_filter_strictness}|slip={int(slippage_percent * 100)}"
                                ),
                                use_regime_filter=use_regime_filter,
                                min_entry_quality_score=min_entry_quality_score,
                                exit_profile=exit_profile,
                                use_tuned_staged_exits=exit_profile != "baseline",
                                option_filter_strictness=option_filter_strictness,
                                slippage_percent=slippage_percent,
                            )
                        )
    return configs


def _load_or_build_cache(lookback_days):
    if CACHE_PATH.exists():
        with CACHE_PATH.open("rb") as fh:
            payload = pickle.load(fh)
            if payload.get("cache_version") == CACHE_VERSION and payload.get("lookback_days") == int(lookback_days):
                return payload

    eastern = ZoneInfo("America/New_York")
    end_time = datetime.now(eastern)
    start_time = end_time - timedelta(days=int(lookback_days))
    bars = fetch_1min_bars("QQQ", start_time, end_time)
    vix_proxy = fetch_market_internal_price("VIXY")
    payload = {
        "cache_version": CACHE_VERSION,
        "lookback_days": int(lookback_days),
        "start_time": start_time,
        "end_time": end_time,
        "qqq_bars": bars,
        "vix_proxy_now": vix_proxy,
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("wb") as fh:
        pickle.dump(payload, fh)
    return payload


def _slice_cached_bars(cache_payload, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None):
    bars = cache_payload["qqq_bars"]
    if bars is None:
        return None
    if len(bars) == 0:
        return bars.copy()

    sliced = bars
    if start_time is not None:
        sliced = sliced[sliced["timestamp"] >= start_time]
    if end_time is not None:
        sliced = sliced[sliced["timestamp"] <= end_time]
    return sliced.copy()


def _build_walk_forward_windows(cache_payload, folds: int, fold_days: int):
    bars = cache_payload["qqq_bars"]
    if bars is None or len(bars) == 0:
        return []

    timestamps = bars["timestamp"]
    latest_ts = timestamps.max()
    if hasattr(latest_ts, "to_pydatetime"):
        latest_ts = latest_ts.to_pydatetime()
    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.replace(tzinfo=ZoneInfo("America/New_York"))

    windows = []
    fold_days = max(int(fold_days), 1)
    folds = max(int(folds), 1)
    for index in range(folds):
        end_time = latest_ts - timedelta(days=index * fold_days)
        start_time = end_time - timedelta(days=fold_days)
        windows.append(
            WalkForwardWindow(
                label=f"fold_{folds - index}",
                start_time=start_time,
                end_time=end_time,
            )
        )
    return list(reversed(windows))


def _install_cached_data(cache_payload, window: Optional[WalkForwardWindow] = None):
    import app.backtest.backtest_runner as backtest_runner

    if window is None:
        backtest_runner.get_1min_bars = lambda symbol, start_time, end_time: cache_payload["qqq_bars"].copy()
    else:
        backtest_runner.get_1min_bars = lambda symbol, start_time, end_time: _slice_cached_bars(
            cache_payload,
            start_time=window.start_time,
            end_time=window.end_time,
        )
    backtest_runner.get_market_internal_price = lambda symbol: cache_payload["vix_proxy_now"]


def _run_combo(overrides, cache_payload, timeout_seconds, window: Optional[WalkForwardWindow] = None):
    _install_cached_data(cache_payload, window=window)
    start = time.monotonic()
    run_backtest(print_diagnostics=False, write_outputs=True, overrides=overrides)
    elapsed = time.monotonic() - start
    if elapsed > timeout_seconds:
        return {"ok": False, "error": f"timeout after {timeout_seconds}s", "elapsed": elapsed}
    metrics = _metrics_from_results(LOG_PATH)
    return {"ok": True, "metrics": metrics, "elapsed": elapsed, "window": window.label if window else None}


def run_walk_forward_validation(config: StrategyCompareConfig, lookback_days: int, folds: int = 3, fold_days: int = 1, timeout_seconds: int = COMBO_TIMEOUT_SECONDS):
    """Run the same config across rolling historical windows.

    This is intentionally opt-in and reuses the existing backtest engine. It
    validates whether a winning compare configuration remains stable out of
    sample, without changing the default compare flow.
    """

    cache_payload = _load_or_build_cache(lookback_days)
    windows = _build_walk_forward_windows(cache_payload, folds=folds, fold_days=fold_days)
    fold_rows = []
    for window in windows:
        result = _run_combo(config.to_overrides(), cache_payload, timeout_seconds, window=window)
        metrics = result.get("metrics")
        fold_rows.append(
            {
                "window": window.label,
                "start_time": window.start_time.isoformat(),
                "end_time": window.end_time.isoformat(),
                "ok": bool(result.get("ok")),
                "elapsed": round(float(result.get("elapsed", 0.0)), 2),
                "metrics": metrics.to_row() if metrics else None,
                "error": result.get("error"),
            }
        )

    valid_folds = [row for row in fold_rows if row["ok"] and row["metrics"]]
    aggregate = {
        "folds": len(fold_rows),
        "valid_folds": len(valid_folds),
        "avg_trades": (sum(row["metrics"]["trades"] for row in valid_folds) / len(valid_folds)) if valid_folds else 0.0,
        "avg_win_rate": (sum(row["metrics"]["win_rate"] for row in valid_folds) / len(valid_folds)) if valid_folds else 0.0,
        "avg_expectancy": (sum(row["metrics"]["expectancy"] for row in valid_folds) / len(valid_folds)) if valid_folds else 0.0,
        "avg_profit_factor": (sum(row["metrics"]["profit_factor"] for row in valid_folds) / len(valid_folds)) if valid_folds else 0.0,
        "avg_max_drawdown": (sum(row["metrics"]["max_drawdown"] for row in valid_folds) / len(valid_folds)) if valid_folds else 0.0,
    }
    return {"config_name": config.config_name, "aggregate": aggregate, "folds": fold_rows, "output": str(OUT_PATH)}


def run_strategy_compare(quick=True, max_combinations=MAX_COMBINATIONS, timeout_seconds=COMBO_TIMEOUT_SECONDS):
    configs = _build_configs(quick=quick)
    if len(configs) > max_combinations:
        configs = configs[: int(max_combinations)]
    config_lookup = {config.config_name: config for config in configs}

    lookback_days = QUICK_LOOKBACK_DAYS if quick else FULL_LOOKBACK_DAYS
    cache_payload = _load_or_build_cache(lookback_days)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    total = len(configs)

    for index, overrides in enumerate(configs, start=1):
        config_name = overrides.config_name
        print(f"Running combo {index}/{total}: {config_name}", flush=True)
        result = _run_combo(overrides.to_overrides(), cache_payload, timeout_seconds)
        if not result.get("ok"):
            rows.append(
                {
                    "config_name": config_name,
                    "trades": 0,
                    "win_rate": 0.0,
                    "avg_R": 0.0,
                    "expectancy": 0.0,
                    "profit_factor": 0.0,
                    "max_drawdown": 0.0,
                    "avg_profit": 0.0,
                    "avg_loss": 0.0,
                    "best_day": None,
                    "worst_day": None,
                    "comments": result.get("error", "error"),
                }
            )
            continue

        metrics = result.get("metrics")
        metrics_row = metrics.to_row() if metrics is not None else {}
        comments = []
        if metrics_row.get("expectancy", 0.0) <= 0:
            comments.append("expectancy<=0")
        if metrics_row.get("profit_factor", 0.0) <= 1.2:
            comments.append("pf<=1.2")
        if metrics_row.get("trades", 0) < 20:
            comments.append("trades<20")

        rows.append(
            {
                "config_name": config_name,
                "trades": metrics_row.get("trades", 0),
                "win_rate": metrics_row.get("win_rate", 0.0),
                "avg_R": metrics_row.get("avg_R", 0.0),
                "expectancy": metrics_row.get("expectancy", 0.0),
                "profit_factor": metrics_row.get("profit_factor", 0.0),
                "max_drawdown": metrics_row.get("max_drawdown", 0.0),
                "avg_profit": metrics_row.get("avg_profit", 0.0),
                "avg_loss": metrics_row.get("avg_loss", 0.0),
                "best_day": metrics_row.get("best_day"),
                "worst_day": metrics_row.get("worst_day"),
                "comments": ";".join(comments),
            }
        )

    with OUT_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "config_name",
                "trades",
                "win_rate",
                "avg_R",
                "expectancy",
                "profit_factor",
                "max_drawdown",
                "avg_profit",
                "avg_loss",
                "best_day",
                "worst_day",
                "comments",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    eligible = [r for r in rows if r["expectancy"] > 0 and r["profit_factor"] > 1.2 and r["trades"] >= 20]
    if not eligible:
        return {"selected": None, "reason": "No config met minimums", "rows": len(rows), "output": str(OUT_PATH)}

    best_expectancy = max(eligible, key=lambda r: (r["expectancy"], r["avg_R"], -r["max_drawdown"]))
    best_drawdown_adjusted = max(eligible, key=lambda r: (r["expectancy"] / max(r["max_drawdown"], 1.0), r["expectancy"], r["avg_R"]))
    return {
        "selected": best_expectancy,
        "selected_overrides": config_lookup[best_expectancy["config_name"]].to_overrides(),
        "best_drawdown_adjusted": best_drawdown_adjusted,
        "best_drawdown_adjusted_overrides": config_lookup[best_drawdown_adjusted["config_name"]].to_overrides(),
        "rows": len(rows),
        "output": str(OUT_PATH),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare strategy configurations safely and quickly")
    parser.add_argument("--quick", action="store_true", help="Run the quick comparison matrix")
    parser.add_argument("--full", action="store_true", help="Run the full comparison matrix (capped by MAX_COMBINATIONS unless overridden)")
    parser.add_argument("--max-combinations", type=int, default=MAX_COMBINATIONS, help="Maximum combinations to run")
    parser.add_argument("--timeout-seconds", type=int, default=COMBO_TIMEOUT_SECONDS, help="Timeout per combination")
    parser.add_argument("--walk-forward", action="store_true", help="Validate the selected config across rolling out-of-sample windows")
    parser.add_argument("--walk-forward-folds", type=int, default=BACKTEST_WALK_FORWARD_FOLDS, help="Number of walk-forward windows to validate")
    parser.add_argument("--walk-forward-days", type=int, default=BACKTEST_WALK_FORWARD_DAYS, help="Days per walk-forward validation fold")
    args = parser.parse_args(argv)

    quick = True
    if args.full:
        quick = False
    elif args.quick:
        quick = True

    result = run_strategy_compare(quick=quick, max_combinations=args.max_combinations, timeout_seconds=args.timeout_seconds)
    if (args.walk_forward or BACKTEST_ENABLE_WALK_FORWARD) and result.get("selected"):
        selected_overrides = result.get("selected_overrides") or {}
        walk_forward_result = run_walk_forward_validation(
            StrategyCompareConfig(
                config_name=str(selected_overrides.get("config_name", "selected")),
                use_regime_filter=bool(selected_overrides.get("use_regime_filter", False)),
                min_entry_quality_score=int(selected_overrides.get("min_entry_quality_score", 75)),
                exit_profile=str(selected_overrides.get("exit_profile", "baseline")),
                use_tuned_staged_exits=bool(selected_overrides.get("use_tuned_staged_exits", False)),
                option_filter_strictness=str(selected_overrides.get("option_filter_strictness", "normal")),
                slippage_percent=float(selected_overrides.get("slippage_percent", 0.0)),
            ),
            lookback_days=FULL_LOOKBACK_DAYS if not quick else QUICK_LOOKBACK_DAYS,
            folds=args.walk_forward_folds,
            fold_days=args.walk_forward_days,
            timeout_seconds=args.timeout_seconds,
        )
        result = {**result, "walk_forward": walk_forward_result}
    print(result)
    return result


if __name__ == "__main__":
    main()
