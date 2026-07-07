import argparse
import csv
import json
import pickle
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.backtest.backtest_runner import LOG_PATH, run_backtest
from app.market.market_data import get_1min_bars as fetch_1min_bars
from app.market.market_data import get_market_internal_price as fetch_market_internal_price


OUT_PATH = Path("logs/strategy_compare.csv")
CACHE_PATH = Path("logs/strategy_compare_cache.pkl")
CACHE_VERSION = 4
QUICK_LOOKBACK_DAYS = 2
FULL_LOOKBACK_DAYS = 5
MAX_COMBINATIONS = 20
COMBO_TIMEOUT_SECONDS = 15


def _metrics_from_results(path: Path):
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

    return {
        "trades": len(pnls),
        "win_rate": (len(wins) / len(pnls)) if pnls else 0.0,
        "avg_R": (sum(rs) / len(rs)) if rs else 0.0,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "avg_profit": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "best_day": best_day,
        "worst_day": worst_day,
    }


def _build_configs(quick: bool):
    if quick:
        return [
            {
                "config_name": f"quick|regime={use_regime_filter}|entry_q={min_entry_quality_score}|exit={exit_profile}",
                "use_regime_filter": use_regime_filter,
                "min_entry_quality_score": min_entry_quality_score,
                "exit_profile": exit_profile,
                "use_tuned_staged_exits": exit_profile != "baseline",
                "option_filter_strictness": "normal",
                "slippage_percent": 0.0,
            }
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
                            {
                                "config_name": (
                                    f"full|regime={use_regime_filter}|entry_q={min_entry_quality_score}"
                                    f"|exit={exit_profile}|strict={option_filter_strictness}|slip={int(slippage_percent * 100)}"
                                ),
                                "use_regime_filter": use_regime_filter,
                                "min_entry_quality_score": min_entry_quality_score,
                                "exit_profile": exit_profile,
                                "use_tuned_staged_exits": exit_profile != "baseline",
                                "option_filter_strictness": option_filter_strictness,
                                "slippage_percent": slippage_percent,
                            }
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
    payload = {"cache_version": CACHE_VERSION, "lookback_days": int(lookback_days), "qqq_bars": bars, "vix_proxy_now": vix_proxy}
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("wb") as fh:
        pickle.dump(payload, fh)
    return payload


def _install_cached_data(cache_payload):
    import app.backtest.backtest_runner as backtest_runner

    backtest_runner.get_1min_bars = lambda symbol, start_time, end_time: cache_payload["qqq_bars"].copy()
    backtest_runner.get_market_internal_price = lambda symbol: cache_payload["vix_proxy_now"]


def _run_combo(overrides, cache_payload, timeout_seconds):
    _install_cached_data(cache_payload)
    start = time.monotonic()
    run_backtest(print_diagnostics=False, write_outputs=True, overrides=overrides)
    elapsed = time.monotonic() - start
    if elapsed > timeout_seconds:
        return {"ok": False, "error": f"timeout after {timeout_seconds}s", "elapsed": elapsed}
    metrics = _metrics_from_results(LOG_PATH)
    return {"ok": True, "metrics": metrics, "elapsed": elapsed}


def run_strategy_compare(quick=True, max_combinations=MAX_COMBINATIONS, timeout_seconds=COMBO_TIMEOUT_SECONDS):
    configs = _build_configs(quick=quick)
    if len(configs) > max_combinations:
        configs = configs[: int(max_combinations)]

    lookback_days = QUICK_LOOKBACK_DAYS if quick else FULL_LOOKBACK_DAYS
    cache_payload = _load_or_build_cache(lookback_days)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    total = len(configs)

    for index, overrides in enumerate(configs, start=1):
        config_name = overrides["config_name"]
        print(f"Running combo {index}/{total}: {config_name}", flush=True)
        result = _run_combo(overrides, cache_payload, timeout_seconds)
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

        metrics = result.get("metrics") or {}
        comments = []
        if metrics.get("expectancy", 0.0) <= 0:
            comments.append("expectancy<=0")
        if metrics.get("profit_factor", 0.0) <= 1.2:
            comments.append("pf<=1.2")
        if metrics.get("trades", 0) < 20:
            comments.append("trades<20")

        rows.append(
            {
                "config_name": config_name,
                "trades": metrics.get("trades", 0),
                "win_rate": metrics.get("win_rate", 0.0),
                "avg_R": metrics.get("avg_R", 0.0),
                "expectancy": metrics.get("expectancy", 0.0),
                "profit_factor": metrics.get("profit_factor", 0.0),
                "max_drawdown": metrics.get("max_drawdown", 0.0),
                "avg_profit": metrics.get("avg_profit", 0.0),
                "avg_loss": metrics.get("avg_loss", 0.0),
                "best_day": metrics.get("best_day"),
                "worst_day": metrics.get("worst_day"),
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
        "best_drawdown_adjusted": best_drawdown_adjusted,
        "rows": len(rows),
        "output": str(OUT_PATH),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare strategy configurations safely and quickly")
    parser.add_argument("--quick", action="store_true", help="Run the quick comparison matrix")
    parser.add_argument("--full", action="store_true", help="Run the full comparison matrix (capped by MAX_COMBINATIONS unless overridden)")
    parser.add_argument("--max-combinations", type=int, default=MAX_COMBINATIONS, help="Maximum combinations to run")
    parser.add_argument("--timeout-seconds", type=int, default=COMBO_TIMEOUT_SECONDS, help="Timeout per combination")
    args = parser.parse_args(argv)

    quick = True
    if args.full:
        quick = False
    elif args.quick:
        quick = True

    result = run_strategy_compare(quick=quick, max_combinations=args.max_combinations, timeout_seconds=args.timeout_seconds)
    print(result)
    return result


if __name__ == "__main__":
    main()
