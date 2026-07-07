from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

from app.analysis.candle_engine import analyze_candles
from app.analysis.entry_quality import calculate_entry_quality_score
from app.analysis.gap_fill_engine import analyze_gap_fill
from app.analysis.market_internals import analyze_market_internals
from app.analysis.market_structure import analyze_market_structure
from app.analysis.momentum_engine import analyze_momentum
from app.analysis.news_engine import analyze_news_risk
from app.analysis.opening_range_engine import analyze_opening_range
from app.analysis.regime_engine import analyze_regime
from app.analysis.support_resistance import analyze_support_resistance
from app.analysis.trend_engine import analyze_trend
from app.analysis.volatility_engine import analyze_volatility, calculate_atr
from app.analysis.volume_engine import analyze_volume
from app.indicators.indicators import calculate_ema, calculate_vwap, calculate_volume_average
from app.market.levels import calculate_previous_day_levels
from app.market.market_data import get_1min_bars, get_market_internal_price
from app.planning.trade_plan import build_trade_plan
from app.scoring.master_score import aggregate_scores
from app.strategy import strategy_router as strategy_router_module
from app.strategy.strategy_router import route_strategy
from app.backtest.backtest_runner import _simulate_baseline_trade, _simulate_staged_trade


OUT_PATH = Path("logs/strategy_router_results.csv")

STRATEGY_ROWS = [
    "MOMENTUM_BREAKOUT",
    "TREND_PULLBACK",
    "VWAP_BOUNCE",
    "OPENING_RANGE_BREAKOUT",
    "GAP_AND_GO",
    "GAP_FILL_REVERSAL",
    "RANGE_SCALP_0DTE",
    "MEAN_REVERSION_0DTE",
    "COMBINED",
]


@dataclass
class TradeRecord:
    strategy_name: str
    pnl: float
    r_multiple: float
    hold_minutes: float
    regime: str
    session: str


def _normalize_ts(value):
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo("America/New_York"))
    return value.astimezone(ZoneInfo("America/New_York"))


def _build_router_context(current_df, latest, regime_result, trend_result, volume_result, candle_result, opening_range_result, support_resistance_result, gap_fill_result, master_decision, now_et):
    support = support_resistance_result.get("data", {}).get("support")
    resistance = support_resistance_result.get("data", {}).get("resistance")
    close_price = float(latest["close"])
    return route_strategy(
        regime_result=regime_result,
        master_score=master_decision,
        vwap_distance_percent=trend_result.get("data", {}).get("vwap_distance_percent"),
        ema_9=float(latest["ema_9"]),
        ema_20=float(latest["ema_20"]),
        latest_close=close_price,
        opening_high=opening_range_result.get("data", {}).get("opening_high"),
        opening_low=opening_range_result.get("data", {}).get("opening_low"),
        prev_day_high=support_resistance_result.get("data", {}).get("prev_high"),
        prev_day_low=support_resistance_result.get("data", {}).get("prev_low"),
        support_level=support,
        resistance_level=resistance,
        atr_percent=(float(calculate_atr(current_df).iloc[-1]) / close_price) if calculate_atr(current_df) is not None and len(calculate_atr(current_df)) > 0 and calculate_atr(current_df).iloc[-1] == calculate_atr(current_df).iloc[-1] else None,
        rvol=volume_result.get("data", {}).get("rvol"),
        candle_body_percent=candle_result.get("data", {}).get("body_percent"),
        momentum_direction=analyze_momentum(current_df).get("direction"),
        gap_direction=gap_fill_result.get("direction"),
        opening_range_result=opening_range_result,
        trend_result=trend_result,
        volume_result=volume_result,
        candle_result=candle_result,
        support_resistance_result=support_resistance_result,
        current_time_et=now_et,
        option_spread_percent=0.03,
        option_liquidity_score=0.8,
        option_premium=float(latest["close"]),
        gap_percent=gap_fill_result.get("data", {}).get("gap_percent"),
        gap_fill_direction=gap_fill_result.get("direction"),
        price_near_support=bool(support is not None and abs(close_price - float(support)) / max(abs(float(support)), 1.0) <= 0.003),
        price_near_resistance=bool(resistance is not None and abs(close_price - float(resistance)) / max(abs(float(resistance)), 1.0) <= 0.003),
    )


@contextmanager
def _enabled_router_flags():
    flag_names = [
        "ENABLE_MOMENTUM_BREAKOUT",
        "ENABLE_TREND_PULLBACK",
        "ENABLE_VWAP_BOUNCE",
        "ENABLE_OPENING_RANGE_BREAKOUT",
        "ENABLE_GAP_AND_GO",
        "ENABLE_GAP_FILL_REVERSAL",
        "ENABLE_RANGE_SCALP_0DTE",
        "ENABLE_MEAN_REVERSION_0DTE",
        "ENABLE_MOMENTUM_RUNNER",
    ]
    original = {name: getattr(strategy_router_module, name) for name in flag_names}
    try:
        for name in flag_names:
            setattr(strategy_router_module, name, True)
        yield
    finally:
        for name, value in original.items():
            setattr(strategy_router_module, name, value)


def _simulate_router_trade(decision, trade_plan, future_bars, profile):
    entry = float(trade_plan["entry"])
    stop = float(trade_plan["stop"])
    target_1x = float(trade_plan.get("target_1x", trade_plan.get("target_0", entry)))
    target_2x = float(trade_plan.get("target_2x", trade_plan.get("target_1", entry)))
    target_3x = float(trade_plan.get("target_3x", trade_plan.get("target_2", entry)))
    target_4x = float(trade_plan.get("target_4x", target_3x))

    risk = abs(entry - stop)
    if risk <= 0:
        return {"pnl": 0.0, "r_multiple": 0.0, "hold_minutes": 0.0, "outcome": "flat", "exit_reason": "invalid_risk"}

    original_qty = 4
    remaining_qty = original_qty
    realized_pnl = 0.0
    highest = entry
    lowest = entry
    stop_moved_to_be = False
    took_1x = False
    took_2x = False
    exit_index = len(future_bars)
    exit_reason = "TIME_EXIT"

    def pnl_contract(exit_px):
        return (entry - exit_px) if decision == "PUT" else (exit_px - entry)

    for idx, bar in enumerate(future_bars.itertuples(index=False), start=1):
        high = float(bar.high)
        low = float(bar.low)

        if decision == "CALL" and low <= stop:
            realized_pnl += remaining_qty * pnl_contract(stop)
            remaining_qty = 0
            exit_index = idx
            exit_reason = "STOP_LOSS_EXIT"
            break
        if decision == "PUT" and high >= stop:
            realized_pnl += remaining_qty * pnl_contract(stop)
            remaining_qty = 0
            exit_index = idx
            exit_reason = "STOP_LOSS_EXIT"
            break

        one_r_hit = (decision == "CALL" and high >= target_1x) or (decision == "PUT" and low <= target_1x)
        if one_r_hit:
            if profile == "scalp":
                realized_pnl += remaining_qty * pnl_contract(target_1x)
                remaining_qty = 0
                exit_index = idx
                exit_reason = "FINAL_EXIT"
                break

            if not took_1x and remaining_qty > 0:
                sell_qty = min(remaining_qty, 1)
                realized_pnl += sell_qty * pnl_contract(target_1x)
                remaining_qty -= sell_qty
                took_1x = True
            stop_moved_to_be = True

        if stop_moved_to_be and remaining_qty > 0:
            if decision == "CALL":
                highest = max(highest, high)
                trailing = max(entry, highest - (2.0 * risk if profile == "runner" else 1.5 * risk))
                trail_hit = low <= trailing
            else:
                lowest = min(lowest, low)
                trailing = min(entry, lowest + (2.0 * risk if profile == "runner" else 1.5 * risk))
                trail_hit = high >= trailing

            two_r_hit = (decision == "CALL" and high >= target_2x) or (decision == "PUT" and low <= target_2x)
            if two_r_hit and not took_2x:
                sell_qty = min(remaining_qty, 1 if profile != "runner" else max(1, int(round(original_qty * 0.5))))
                realized_pnl += sell_qty * pnl_contract(target_2x)
                remaining_qty -= sell_qty
                took_2x = True

            if profile == "balanced":
                three_r_hit = (decision == "CALL" and high >= target_3x) or (decision == "PUT" and low <= target_3x)
                if three_r_hit and remaining_qty > 0:
                    realized_pnl += remaining_qty * pnl_contract(target_3x)
                    remaining_qty = 0
                    exit_index = idx
                    exit_reason = "FINAL_EXIT"
                    break

            if trail_hit and remaining_qty > 0:
                realized_pnl += remaining_qty * pnl_contract(trailing)
                remaining_qty = 0
                exit_index = idx
                exit_reason = "TRAILING_STOP_EXIT"
                break

        if profile == "runner" and remaining_qty > 0:
            final_hit = (decision == "CALL" and high >= target_4x) or (decision == "PUT" and low <= target_4x)
            if final_hit:
                realized_pnl += remaining_qty * pnl_contract(target_4x)
                remaining_qty = 0
                exit_index = idx
                exit_reason = "FINAL_EXIT"
                break

    if remaining_qty > 0 and len(future_bars) > 0:
        final_close = float(future_bars.iloc[-1]["close"])
        realized_pnl += remaining_qty * pnl_contract(final_close)
        exit_reason = "TIME_EXIT"

    r_multiple = realized_pnl / (risk * original_qty) if risk > 0 else 0.0
    outcome = "win" if realized_pnl > 0 else "loss" if realized_pnl < 0 else "flat"
    return {
        "pnl": float(realized_pnl),
        "r_multiple": float(r_multiple),
        "hold_minutes": float(max(exit_index, 1)),
        "outcome": outcome,
        "exit_reason": exit_reason,
    }


def _summary_from_records(records: list[TradeRecord]) -> dict:
    if not records:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_R": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "average_hold_time": 0.0,
            "best_session": None,
            "worst_session": None,
            "best_regime": None,
            "worst_regime": None,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
        }

    pnls = [record.pnl for record in records]
    rs = [record.r_multiple for record in records]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    by_session = {}
    by_regime = {}
    for record in records:
        equity += record.pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        by_session.setdefault(record.session, 0.0)
        by_session[record.session] += record.pnl
        by_regime.setdefault(record.regime, 0.0)
        by_regime[record.regime] += record.pnl

    best_session = max(by_session, key=by_session.get) if by_session else None
    worst_session = min(by_session, key=by_session.get) if by_session else None
    best_regime = max(by_regime, key=by_regime.get) if by_regime else None
    worst_regime = min(by_regime, key=by_regime.get) if by_regime else None
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (9999.0 if gross_profit > 0 else 0.0)
    expectancy = sum(pnls) / len(pnls)

    return {
        "trades": len(records),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(records),
        "avg_R": sum(rs) / len(rs),
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "average_hold_time": sum(record.hold_minutes for record in records) / len(records),
        "best_session": best_session,
        "worst_session": worst_session,
        "best_regime": best_regime,
        "worst_regime": worst_regime,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
    }


def run_strategy_router_backtest(strategy_name: str | None = None):
    eastern = ZoneInfo("America/New_York")
    end_time = datetime.now(eastern)
    start_time = end_time - timedelta(days=10)
    qqq_bars = get_1min_bars("QQQ", start_time, end_time)
    if qqq_bars.empty:
        return {"rows": [], "output": str(OUT_PATH)}

    qqq_bars = qqq_bars.reset_index()
    qqq_bars["ema_9"] = calculate_ema(qqq_bars, 9)
    qqq_bars["ema_20"] = calculate_ema(qqq_bars, 20)
    qqq_bars["vwap"] = calculate_vwap(qqq_bars)
    qqq_bars["avg_volume"] = calculate_volume_average(qqq_bars)

    vix_proxy_now = get_market_internal_price("VIXY")
    strategy_targets = [strategy_name] if strategy_name and strategy_name != "ALL" else STRATEGY_ROWS
    results = []

    with _enabled_router_flags():
        for target_strategy in strategy_targets:
            print(f"Running strategy router backtest: {target_strategy}", flush=True)
            trade_records: list[TradeRecord] = []

            for i in range(80, len(qqq_bars) - 2):
                current_df = qqq_bars.iloc[: i + 1].copy()
                latest = current_df.iloc[-1]
                latest_ts = _normalize_ts(latest["timestamp"])
                if not (time(9, 45) <= latest_ts.time() <= time(12, 0)):
                    continue

                prev_high, prev_low, prev_close = calculate_previous_day_levels(current_df)
                today_open = current_df.iloc[0]["open"]
                market_structure_result = analyze_market_structure(current_df, latest["close"], today_open, prev_high, prev_low, prev_close)
                support_resistance_result = analyze_support_resistance(current_df, latest["close"], prev_high, prev_low)
                opening_range_result = analyze_opening_range(current_df)
                gap_fill_result = analyze_gap_fill(current_df, prev_close)
                trend_result = analyze_trend(current_df)
                momentum_result = analyze_momentum(current_df)
                volume_result = analyze_volume(current_df)
                volatility_result = analyze_volatility(current_df)
                candle_result = analyze_candles(current_df)
                news_result = analyze_news_risk()
                analysis_results = [
                    market_structure_result,
                    support_resistance_result,
                    opening_range_result,
                    gap_fill_result,
                    trend_result,
                    momentum_result,
                    volume_result,
                    volatility_result,
                    candle_result,
                    analyze_market_internals(vix_price=vix_proxy_now, vix_change=None, dxy_change=None, ten_year_change=None),
                    news_result,
                ]
                regime_result = analyze_regime(current_df, opening_range_result=opening_range_result, volume_result=volume_result, candle_result=candle_result, vix_price=vix_proxy_now, news_result=news_result)
                analysis_results.insert(-2, regime_result)
                master_decision = aggregate_scores(analysis_results)

                if master_decision.get("decision") not in ["CALL", "PUT"]:
                    continue

                atr_series = calculate_atr(current_df)
                atr_value = float(atr_series.iloc[-1]) if atr_series is not None and len(atr_series) > 0 and atr_series.iloc[-1] == atr_series.iloc[-1] else None
                recent_window = current_df.tail(20)
                trade_plan = build_trade_plan(
                    master_decision["decision"],
                    latest["close"],
                    latest["vwap"],
                    atr=atr_value,
                    swing_low=float(recent_window["low"].min()) if not recent_window.empty else None,
                    swing_high=float(recent_window["high"].max()) if not recent_window.empty else None,
                )
                if not trade_plan.get("valid_rr", False):
                    continue

                current_time_et = latest_ts
                router = _build_router_context(current_df, latest, regime_result, trend_result, volume_result, candle_result, opening_range_result, support_resistance_result, gap_fill_result, master_decision, current_time_et)
                if router.get("strategy_name") == "NO_TRADE":
                    continue
                if target_strategy != "COMBINED" and router.get("strategy_name") != target_strategy:
                    continue

                confirmation_index = i + 1
                if confirmation_index >= len(qqq_bars):
                    continue
                signal_close = float(latest["close"])
                confirmation_candle = qqq_bars.iloc[confirmation_index]
                confirmation_ts = _normalize_ts(confirmation_candle["timestamp"])
                if master_decision["decision"] == "CALL" and float(confirmation_candle["close"]) <= signal_close:
                    continue
                if master_decision["decision"] == "PUT" and float(confirmation_candle["close"]) >= signal_close:
                    continue

                future_bars = qqq_bars.iloc[confirmation_index + 1 : min(len(qqq_bars), confirmation_index + 11)]
                profile = str(router.get("required_exit_profile", "balanced")).lower()
                if profile == "baseline":
                    sim = _simulate_baseline_trade(master_decision["decision"], trade_plan["entry"], trade_plan["stop"], trade_plan.get("target_1x"), trade_plan.get("target_2x"), trade_plan.get("target_3x"), trade_plan.get("target_4x"), future_bars, quantity=4, profile=profile)
                else:
                    sim = _simulate_staged_trade(master_decision["decision"], trade_plan["entry"], trade_plan["stop"], trade_plan.get("target_1x"), trade_plan.get("target_2x"), trade_plan.get("target_3x"), trade_plan.get("target_4x"), future_bars, quantity=4, profile=profile)

                trade_records.append(
                    TradeRecord(
                        strategy_name=str(router.get("strategy_name")),
                        pnl=float(sim.get("realized_pnl", 0.0)),
                        r_multiple=float(sim.get("r_multiple", 0.0)),
                        hold_minutes=float(sim.get("hold_minutes", len(future_bars))),
                        regime=str(regime_result.get("data", {}).get("regime", "CHOPPY")),
                        session=confirmation_ts.date().isoformat(),
                    )
                )

            summary = _summary_from_records(trade_records)
            summary["strategy_name"] = target_strategy
            summary["recommended_enabled"] = bool(
                summary["trades"] >= 20
                and summary["profit_factor"] > 1.2
                and summary["expectancy"] > 0
                and summary["max_drawdown"] <= max(1.0, summary["gross_profit"] * 0.6)
            )
            summary["enabled_by_default"] = False
            results.append(summary)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "strategy_name",
            "trades",
            "wins",
            "losses",
            "win_rate",
            "avg_R",
            "expectancy",
            "profit_factor",
            "max_drawdown",
            "average_hold_time",
            "best_session",
            "worst_session",
            "best_regime",
            "worst_regime",
            "gross_profit",
            "gross_loss",
            "recommended_enabled",
            "enabled_by_default",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    return {"rows": results, "output": str(OUT_PATH)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backtest the strategy router against historical QQQ bars")
    parser.add_argument("--strategy", default="ALL", help="Specific strategy name or ALL")
    args = parser.parse_args(argv)
    result = run_strategy_router_backtest(strategy_name=args.strategy)
    print(result)
    return result


if __name__ == "__main__":
    main()