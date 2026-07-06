import json
import csv
from datetime import datetime, timedelta
from pathlib import Path
from datetime import time
from zoneinfo import ZoneInfo

from app.analysis.candle_engine import analyze_candles
from app.analysis.gap_fill_engine import analyze_gap_fill
from app.analysis.market_internals import analyze_market_internals
from app.analysis.market_structure import analyze_market_structure
from app.analysis.momentum_engine import analyze_momentum
from app.analysis.news_engine import analyze_news_risk
from app.analysis.opening_range_engine import analyze_opening_range
from app.analysis.support_resistance import analyze_support_resistance
from app.analysis.trend_engine import analyze_trend
from app.analysis.volatility_engine import analyze_volatility
from app.analysis.volume_engine import analyze_volume
from app.indicators.indicators import calculate_ema, calculate_vwap, calculate_volume_average
from app.market.levels import calculate_previous_day_levels
from app.market.market_data import get_1min_bars, get_market_internal_price
from app.planning.trade_plan import build_trade_plan
from app.scoring.master_score import aggregate_scores


LOG_PATH = Path("logs/backtest_results.jsonl")
DAILY_SUMMARY_CSV = Path("logs/backtest_daily_summary.csv")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _format_avg_time(minutes_values):
    if not minutes_values:
        return "N/A"
    avg_minutes = sum(minutes_values) / len(minutes_values)
    hours = int(avg_minutes // 60)
    minutes = int(round(avg_minutes % 60))
    if minutes == 60:
        hours += 1
        minutes = 0
    return f"{hours:02d}:{minutes:02d}"


def run_backtest(
    session_start=time(9, 45),
    session_end=time(12, 0),
    print_diagnostics=True,
    write_outputs=True,
):
    eastern = ZoneInfo("America/New_York")
    end_time = datetime.now(eastern)
    start_time = end_time - timedelta(days=10)

    qqq_bars = get_1min_bars("QQQ", start_time, end_time)
    if qqq_bars.empty:
        print("No QQQ bars found for the requested window; using fallback values.")
        return

    qqq_bars = qqq_bars.reset_index()
    qqq_bars["ema_9"] = calculate_ema(qqq_bars, 9)
    qqq_bars["ema_20"] = calculate_ema(qqq_bars, 20)
    qqq_bars["vwap"] = calculate_vwap(qqq_bars)
    qqq_bars["avg_volume"] = calculate_volume_average(qqq_bars)

    results = []
    total_signals = 0
    allowed_signals = 0
    wins = 0
    losses = 0
    time_exit = 0
    early_exit = 0
    early_exit_returns = []
    small_win = 0
    small_loss = 0
    flat_exit = 0
    no_exit = 0
    signal_scores = []
    rr_1_values = []
    rr_2_values = []
    time_exit_mfe_values = []
    time_exit_mae_values = []
    time_exit_final_return_values = []
    time_exit_call_count = 0
    time_exit_put_count = 0
    time_exit_vwap_dist_values = []
    time_exit_rvol_values = []
    time_exit_body_values = []
    time_exit_trend_neutral_count = 0
    time_exit_momentum_neutral_count = 0
    time_exit_candle_neutral_count = 0
    small_loss_call_count = 0
    small_loss_put_count = 0
    small_loss_vwap_dist_values = []
    small_loss_rvol_values = []
    small_loss_body_values = []
    small_loss_score_values = []
    small_loss_trend_neutral_count = 0
    small_loss_momentum_neutral_count = 0
    small_loss_candle_neutral_count = 0
    small_loss_opening_range_counts = {"bullish": 0, "bearish": 0, "neutral": 0, "other": 0}
    small_loss_gap_fill_counts = {"bullish": 0, "bearish": 0, "neutral": 0, "other": 0}
    small_loss_volume_counts = {"bullish": 0, "bearish": 0, "neutral": 0, "other": 0}
    winner_scores = []
    winner_vwap_dist_values = []
    winner_rvol_values = []
    winner_body_values = []
    winner_entry_minutes = []
    early_exit_scores = []
    early_exit_vwap_dist_values = []
    early_exit_rvol_values = []
    early_exit_body_values = []
    early_exit_entry_minutes = []
    skipped_counts = {
        "below_score": 0,
        "no_trade": 0,
        "poor_rr": 0,
        "outside_time": 0,
        "cooldown": 0,
        "weak_alignment": 0,
        "low_rvol": 0,
        "weak_candle": 0,
        "low_volatility": 0,
        "vwap_extension": 0,
        "confirmation_failed": 0,
    }
    cooldown_remaining = 0
    vix_proxy_now = get_market_internal_price("VIXY")
    daily_stats = {}

    for i in range(80, len(qqq_bars)):
        if cooldown_remaining > 0:
            skipped_counts["cooldown"] += 1
            cooldown_remaining -= 1
            continue

        current_df = qqq_bars.iloc[: i + 1].copy()
        latest = current_df.iloc[-1]
        prev_high, prev_low, prev_close = calculate_previous_day_levels(current_df)
        today_open = current_df.iloc[0]["open"]

        latest_ts = latest["timestamp"]
        latest_ts = latest_ts.to_pydatetime() if hasattr(latest_ts, "to_pydatetime") else latest_ts
        if latest_ts.tzinfo is None:
            latest_ts_et = latest_ts.replace(tzinfo=ZoneInfo("America/New_York"))
        else:
            latest_ts_et = latest_ts.astimezone(ZoneInfo("America/New_York"))

        if not (session_start <= latest_ts_et.time() <= session_end):
            skipped_counts["outside_time"] += 1
            continue

        market_structure_result = analyze_market_structure(
            current_df,
            latest["close"],
            today_open,
            prev_high,
            prev_low,
            prev_close,
        )
        support_resistance_result = analyze_support_resistance(
            current_df,
            latest["close"],
            prev_high,
            prev_low,
        )
        opening_range_result = analyze_opening_range(current_df)
        gap_fill_result = analyze_gap_fill(current_df, prev_close)

        trend_result = analyze_trend(current_df)
        momentum_result = analyze_momentum(current_df)
        volume_result = analyze_volume(current_df)
        volatility_result = analyze_volatility(current_df)
        candle_result = analyze_candles(current_df)

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
            analyze_market_internals(
                vix_price=vix_proxy_now,
                vix_change=None,
                dxy_change=None,
                ten_year_change=None,
            ),
            analyze_news_risk(),
        ]

        master_decision = aggregate_scores(analysis_results)

        trade_plan = None
        decision = master_decision["decision"]
        if decision not in ["CALL", "PUT"]:
            skipped_counts["no_trade"] += 1
            continue

        expected_dir = "bullish" if decision == "CALL" else "bearish"
        market_structure_dir = market_structure_result.get("direction")
        opening_range_dir = opening_range_result.get("direction")
        volume_dir = volume_result.get("direction")
        trend_dir = trend_result.get("direction")
        momentum_dir = momentum_result.get("direction")
        candle_dir = candle_result.get("direction")

        if not (market_structure_dir == expected_dir or opening_range_dir == expected_dir):
            skipped_counts["weak_alignment"] += 1
            continue

        if volume_dir != expected_dir:
            skipped_counts["weak_alignment"] += 1
            continue

        if trend_dir not in [expected_dir, "neutral"]:
            skipped_counts["weak_alignment"] += 1
            continue

        if momentum_dir not in [expected_dir, "neutral"]:
            skipped_counts["weak_alignment"] += 1
            continue

        if candle_dir not in [expected_dir, "neutral"]:
            skipped_counts["weak_alignment"] += 1
            continue

        vwap_distance_percent = trend_result.get("data", {}).get("vwap_distance_percent")
        if vwap_distance_percent is not None and abs(float(vwap_distance_percent)) > 0.008:
            gap_fill_dir = gap_fill_result.get("direction")
            if not (
                opening_range_dir == expected_dir
                and gap_fill_dir == expected_dir
                and volume_dir == expected_dir
            ):
                skipped_counts["vwap_extension"] += 1
                continue

        close_price = float(latest["close"])
        vwap_price = latest.get("vwap")
        if trend_dir == "neutral" and vwap_price is not None and float(vwap_price) > 0:
            vwap_price = float(vwap_price)
            if decision == "CALL":
                extension = (close_price - vwap_price) / vwap_price
                if extension > 0.006:
                    skipped_counts["vwap_extension"] += 1
                    continue
            elif decision == "PUT":
                extension = (vwap_price - close_price) / vwap_price
                if extension > 0.006:
                    skipped_counts["vwap_extension"] += 1
                    continue

        rvol = volume_result.get("data", {}).get("rvol")
        if rvol is None or float(rvol) < 1.2:
            skipped_counts["low_rvol"] += 1
            continue

        body_percent = candle_result.get("data", {}).get("body_percent")
        if body_percent is None or float(body_percent) < 0.20:
            skipped_counts["weak_candle"] += 1
            continue

        volatility_warnings = volatility_result.get("warnings", [])
        if "Low volatility" in volatility_warnings:
            skipped_counts["low_volatility"] += 1

        confirmation_index = i + 1
        if confirmation_index >= len(qqq_bars):
            skipped_counts["confirmation_failed"] += 1
            continue

        signal_close = float(latest["close"])
        confirmation_candle = qqq_bars.iloc[confirmation_index]
        confirmation_ts = confirmation_candle["timestamp"]
        confirmation_ts = confirmation_ts.to_pydatetime() if hasattr(confirmation_ts, "to_pydatetime") else confirmation_ts
        if confirmation_ts.tzinfo is None:
            confirmation_ts_et = confirmation_ts.replace(tzinfo=ZoneInfo("America/New_York"))
        else:
            confirmation_ts_et = confirmation_ts.astimezone(ZoneInfo("America/New_York"))
        entry_minutes_value = confirmation_ts_et.hour * 60 + confirmation_ts_et.minute
        confirmation_close = float(confirmation_candle["close"])
        if decision == "CALL" and confirmation_close <= signal_close:
            skipped_counts["confirmation_failed"] += 1
            continue
        if decision == "PUT" and confirmation_close >= signal_close:
            skipped_counts["confirmation_failed"] += 1
            continue

        total_signals += 1
        signal_scores.append(float(master_decision["total_score"]))

        trade_date = str(latest_ts_et.date())
        if trade_date not in daily_stats:
            daily_stats[trade_date] = {
                "date": trade_date,
                "total": 0,
                "allowed": 0,
                "wins": 0,
                "losses": 0,
                "early_exit": 0,
                "time_exit": 0,
                "no_exit": 0,
            }
        daily_stats[trade_date]["total"] += 1

        trade_plan = build_trade_plan(
            decision,
            confirmation_close,
            latest["vwap"],
            atr=float(volatility_result.get("data", {}).get("atr")) if volatility_result.get("data", {}).get("atr") is not None else None,
            swing_low=float(current_df.tail(20)["low"].min()) if not current_df.tail(20).empty else None,
            swing_high=float(current_df.tail(20)["high"].max()) if not current_df.tail(20).empty else None,
        )

        score_ok = float(master_decision.get("total_score", 0.0)) >= 90
        quality_ok = master_decision.get("quality") in ["A", "A+"]
        rr_ok = bool(trade_plan.get("valid_rr"))

        if not score_ok or not quality_ok:
            skipped_counts["below_score"] += 1
            gate_allowed = False
            gate_reason = "below_score"
        elif not rr_ok:
            skipped_counts["poor_rr"] += 1
            gate_allowed = False
            gate_reason = "poor_rr"
        else:
            gate_allowed = True
            gate_reason = "backtest_quality_gate_pass"

        if gate_allowed:
            allowed_signals += 1
            daily_stats[trade_date]["allowed"] += 1
            rr_1_values.append(float(trade_plan.get("rr_1", 0.0)))
            rr_2_values.append(float(trade_plan.get("rr_2", 0.0)))
            cooldown_remaining = 10
            entry = float(trade_plan["entry"])
            target_0 = float(trade_plan.get("target_0")) if trade_plan.get("target_0") is not None else (entry * 1.0015 if decision == "CALL" else entry * 0.9985)
            outcome = "time_exit"
            exit_price = None
            exit_reason = None
            early_exit_return_percent = None
            max_favorable_move_percent = None
            max_adverse_move_percent = None
            final_10_candle_return_percent = None

            signal_index = confirmation_index + 1
            horizon = min(len(qqq_bars), signal_index + 10)
            future_bars = qqq_bars.iloc[signal_index:horizon]

            for idx, future_bar in enumerate(future_bars.itertuples(index=False), start=1):
                if decision == "CALL":
                    if future_bar.high >= target_0:
                        outcome = "win"
                        exit_price = float(future_bar.high)
                        exit_reason = "target_0_hit"
                        break
                    if future_bar.low <= trade_plan["stop"]:
                        outcome = "loss"
                        exit_price = float(future_bar.low)
                        exit_reason = "stop_hit"
                        break
                    current_return_percent = ((float(future_bar.close) - entry) / entry) * 100
                    if idx >= 3 and current_return_percent < 0:
                        outcome = "early_exit"
                        exit_price = float(future_bar.close)
                        exit_reason = "early_weakness"
                        early_exit_return_percent = current_return_percent
                        break
                elif decision == "PUT":
                    if future_bar.low <= target_0:
                        outcome = "win"
                        exit_price = float(future_bar.low)
                        exit_reason = "target_0_hit"
                        break
                    if future_bar.high >= trade_plan["stop"]:
                        outcome = "loss"
                        exit_price = float(future_bar.high)
                        exit_reason = "stop_hit"
                        break
                    current_return_percent = ((entry - float(future_bar.close)) / entry) * 100
                    if idx >= 3 and current_return_percent < 0:
                        outcome = "early_exit"
                        exit_price = float(future_bar.close)
                        exit_reason = "early_weakness"
                        early_exit_return_percent = current_return_percent
                        break

            if outcome == "win":
                wins += 1
                daily_stats[trade_date]["wins"] += 1
                winner_scores.append(float(master_decision.get("total_score", 0.0)))
                w_vwap = trend_result.get("data", {}).get("vwap_distance_percent")
                if w_vwap is not None:
                    winner_vwap_dist_values.append(float(w_vwap))
                w_rvol = volume_result.get("data", {}).get("rvol")
                if w_rvol is not None:
                    winner_rvol_values.append(float(w_rvol))
                w_body = candle_result.get("data", {}).get("body_percent")
                if w_body is not None:
                    winner_body_values.append(float(w_body))
                winner_entry_minutes.append(entry_minutes_value)
            elif outcome == "loss":
                losses += 1
                daily_stats[trade_date]["losses"] += 1
            elif outcome == "early_exit":
                early_exit += 1
                daily_stats[trade_date]["early_exit"] += 1
                if early_exit_return_percent is not None:
                    early_exit_returns.append(float(early_exit_return_percent))
                early_exit_scores.append(float(master_decision.get("total_score", 0.0)))
                ee_vwap = trend_result.get("data", {}).get("vwap_distance_percent")
                if ee_vwap is not None:
                    early_exit_vwap_dist_values.append(float(ee_vwap))
                ee_rvol = volume_result.get("data", {}).get("rvol")
                if ee_rvol is not None:
                    early_exit_rvol_values.append(float(ee_rvol))
                ee_body = candle_result.get("data", {}).get("body_percent")
                if ee_body is not None:
                    early_exit_body_values.append(float(ee_body))
                early_exit_entry_minutes.append(entry_minutes_value)
            elif len(future_bars) >= 10:
                time_exit += 1
                daily_stats[trade_date]["time_exit"] += 1

                max_high = float(future_bars["high"].max())
                min_low = float(future_bars["low"].min())
                final_close = float(future_bars.iloc[-1]["close"])
                if decision == "CALL":
                    max_favorable_move_percent = ((max_high - entry) / entry) * 100
                    max_adverse_move_percent = ((entry - min_low) / entry) * 100
                    final_10_candle_return_percent = ((final_close - entry) / entry) * 100
                else:
                    max_favorable_move_percent = ((entry - min_low) / entry) * 100
                    max_adverse_move_percent = ((max_high - entry) / entry) * 100
                    final_10_candle_return_percent = ((entry - final_close) / entry) * 100

                time_exit_mfe_values.append(max_favorable_move_percent)
                time_exit_mae_values.append(max_adverse_move_percent)
                time_exit_final_return_values.append(final_10_candle_return_percent)
                if final_10_candle_return_percent > 0:
                    small_win += 1
                elif final_10_candle_return_percent < 0:
                    small_loss += 1
                    if decision == "CALL":
                        small_loss_call_count += 1
                    elif decision == "PUT":
                        small_loss_put_count += 1

                    vwap_dist_sl = trend_result.get("data", {}).get("vwap_distance_percent")
                    if vwap_dist_sl is not None:
                        small_loss_vwap_dist_values.append(float(vwap_dist_sl))

                    rvol_sl = volume_result.get("data", {}).get("rvol")
                    if rvol_sl is not None:
                        small_loss_rvol_values.append(float(rvol_sl))

                    body_sl = candle_result.get("data", {}).get("body_percent")
                    if body_sl is not None:
                        small_loss_body_values.append(float(body_sl))

                    small_loss_score_values.append(float(master_decision.get("total_score", 0.0)))

                    if trend_dir == "neutral":
                        small_loss_trend_neutral_count += 1
                    if momentum_dir == "neutral":
                        small_loss_momentum_neutral_count += 1
                    if candle_dir == "neutral":
                        small_loss_candle_neutral_count += 1

                    if opening_range_dir in small_loss_opening_range_counts:
                        small_loss_opening_range_counts[opening_range_dir] += 1
                    else:
                        small_loss_opening_range_counts["other"] += 1

                    gap_fill_dir_sl = gap_fill_result.get("direction")
                    if gap_fill_dir_sl in small_loss_gap_fill_counts:
                        small_loss_gap_fill_counts[gap_fill_dir_sl] += 1
                    else:
                        small_loss_gap_fill_counts["other"] += 1

                    if volume_dir in small_loss_volume_counts:
                        small_loss_volume_counts[volume_dir] += 1
                    else:
                        small_loss_volume_counts["other"] += 1
                else:
                    flat_exit += 1
                if decision == "CALL":
                    time_exit_call_count += 1
                elif decision == "PUT":
                    time_exit_put_count += 1

                vwap_dist = trend_result.get("data", {}).get("vwap_distance_percent")
                if vwap_dist is not None:
                    time_exit_vwap_dist_values.append(float(vwap_dist))

                rvol_val = volume_result.get("data", {}).get("rvol")
                if rvol_val is not None:
                    time_exit_rvol_values.append(float(rvol_val))

                body_val = candle_result.get("data", {}).get("body_percent")
                if body_val is not None:
                    time_exit_body_values.append(float(body_val))

                if trend_dir == "neutral":
                    time_exit_trend_neutral_count += 1
                if momentum_dir == "neutral":
                    time_exit_momentum_neutral_count += 1
                if candle_dir == "neutral":
                    time_exit_candle_neutral_count += 1
            else:
                no_exit += 1
                daily_stats[trade_date]["no_exit"] += 1

            result_row = {
                "timestamp": latest["timestamp"].isoformat() if hasattr(latest["timestamp"], "isoformat") else str(latest["timestamp"]),
                "decision": decision,
                "score": float(master_decision["total_score"]),
                "gate_allowed": gate_allowed,
                "gate_reason": gate_reason,
                "trade_plan": trade_plan,
                "signal_close": signal_close,
                "confirmation_close": confirmation_close,
                "target_0": target_0,
                "outcome": outcome,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "early_exit_return_percent": early_exit_return_percent,
                "max_favorable_move_percent": max_favorable_move_percent,
                "max_adverse_move_percent": max_adverse_move_percent,
                "final_10_candle_return_percent": final_10_candle_return_percent,
                "market_structure_direction": market_structure_dir,
                "opening_range_direction": opening_range_dir,
                "gap_fill_direction": gap_fill_result.get("direction"),
                "trend_direction": trend_dir,
                "momentum_direction": momentum_dir,
                "volume_direction": volume_dir,
                "candle_direction": candle_dir,
                "support_resistance_direction": support_resistance_result.get("direction"),
                "vwap_distance_percent": trend_result.get("data", {}).get("vwap_distance_percent"),
                "rvol": volume_result.get("data", {}).get("rvol"),
                "body_percent": candle_result.get("data", {}).get("body_percent"),
            }
            results.append(result_row)
        else:
            result_row = {
                "timestamp": latest["timestamp"].isoformat() if hasattr(latest["timestamp"], "isoformat") else str(latest["timestamp"]),
                "decision": decision,
                "score": float(master_decision["total_score"]),
                "gate_allowed": gate_allowed,
                "gate_reason": gate_reason,
                "trade_plan": trade_plan,
                "signal_close": signal_close,
                "confirmation_close": confirmation_close,
                "target_0": None,
                "outcome": None,
                "exit_price": None,
                "exit_reason": None,
                "early_exit_return_percent": None,
                "max_favorable_move_percent": None,
                "max_adverse_move_percent": None,
                "final_10_candle_return_percent": None,
                "market_structure_direction": None,
                "opening_range_direction": None,
                "gap_fill_direction": None,
                "trend_direction": None,
                "momentum_direction": None,
                "volume_direction": None,
                "candle_direction": None,
                "support_resistance_direction": None,
                "vwap_distance_percent": None,
                "rvol": None,
                "body_percent": None,
            }
            results.append(result_row)

    summary = {
        "total_signals": total_signals,
        "allowed_signals": allowed_signals,
        "wins": wins,
        "losses": losses,
        "time_exit": time_exit,
        "early_exit": early_exit,
        "small_win": small_win,
        "small_loss": small_loss,
        "flat_exit": flat_exit,
        "no_exit": no_exit,
        "win_rate": round(wins / allowed_signals, 4) if allowed_signals else 0.0,
        "loss_rate": round(losses / allowed_signals, 4) if allowed_signals else 0.0,
        "time_exit_rate": round(time_exit / allowed_signals, 4) if allowed_signals else 0.0,
        "early_exit_rate": round(early_exit / allowed_signals, 4) if allowed_signals else 0.0,
        "no_exit_rate": round(no_exit / allowed_signals, 4) if allowed_signals else 0.0,
        "avg_score": round(sum(signal_scores) / len(signal_scores), 2) if signal_scores else 0.0,
        "avg_rr_1": round(sum(rr_1_values) / len(rr_1_values), 4) if rr_1_values else 0.0,
        "avg_rr_2": round(sum(rr_2_values) / len(rr_2_values), 4) if rr_2_values else 0.0,
        "avg_early_exit_return": round(sum(early_exit_returns) / len(early_exit_returns), 4) if early_exit_returns else 0.0,
        "avg_time_exit_mfe": round(sum(time_exit_mfe_values) / len(time_exit_mfe_values), 4) if time_exit_mfe_values else 0.0,
        "avg_time_exit_mae": round(sum(time_exit_mae_values) / len(time_exit_mae_values), 4) if time_exit_mae_values else 0.0,
        "avg_time_exit_final_return": round(sum(time_exit_final_return_values) / len(time_exit_final_return_values), 4) if time_exit_final_return_values else 0.0,
    }

    daily_rows = []
    if write_outputs:
        LOG_PATH.write_text("", encoding="utf-8")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            for record in results:
                fh.write(json.dumps(record, default=str) + "\n")

        DAILY_SUMMARY_CSV.parent.mkdir(parents=True, exist_ok=True)
        with DAILY_SUMMARY_CSV.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(
                csvfile,
                fieldnames=["date", "total", "allowed", "wins", "losses", "early_exit", "time_exit", "no_exit", "win_rate", "early_exit_rate"],
            )
            writer.writeheader()
            for date_key in sorted(daily_stats.keys()):
                row = daily_stats[date_key]
                allowed = row["allowed"]
                row_out = {
                    "date": row["date"],
                    "total": row["total"],
                    "allowed": allowed,
                    "wins": row["wins"],
                    "losses": row["losses"],
                    "early_exit": row["early_exit"],
                    "time_exit": row["time_exit"],
                    "no_exit": row["no_exit"],
                    "win_rate": round(row["wins"] / allowed, 4) if allowed else 0.0,
                    "early_exit_rate": round(row["early_exit"] / allowed, 4) if allowed else 0.0,
                }
                writer.writerow(row_out)

        with DAILY_SUMMARY_CSV.open("r", newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                row_parsed = {
                    "date": row["date"],
                    "allowed": int(row["allowed"]),
                    "wins": int(row["wins"]),
                    "losses": int(row["losses"]),
                    "early_exit": int(row["early_exit"]),
                    "time_exit": int(row["time_exit"]),
                    "win_rate": float(row["win_rate"]),
                }
                daily_rows.append(row_parsed)

    best_day = None
    worst_day = None
    most_allowed_day = None
    most_early_exit_day = None
    if daily_rows:
        best_day = max(daily_rows, key=lambda d: d["win_rate"])
        worst_day = min(daily_rows, key=lambda d: d["win_rate"])
        most_allowed_day = max(daily_rows, key=lambda d: d["allowed"])
        most_early_exit_day = max(daily_rows, key=lambda d: d["early_exit"])

    if print_diagnostics:
        print("========== Backtest Summary ==========")
        print(f"total_signals : {summary['total_signals']}")
        print(f"allowed_signals: {summary['allowed_signals']}")
        print(f"wins          : {summary['wins']}")
        print(f"losses        : {summary['losses']}")
        print(f"time_exit     : {summary['time_exit']}")
        print(f"early_exit    : {summary['early_exit']}")
        print(f"early_exit_rate: {summary['early_exit_rate']}")
        print(f"avg_early_exit_return: {summary['avg_early_exit_return']}")
        print(f"small_win     : {summary['small_win']}")
        print(f"small_loss    : {summary['small_loss']}")
        print(f"flat_exit     : {summary['flat_exit']}")
        print(f"no_exit       : {summary['no_exit']}")
        print(f"win_rate      : {summary['win_rate']}")
        print(f"loss_rate     : {summary['loss_rate']}")
        print(f"time_exit_rate: {summary['time_exit_rate']}")
        print(f"no_exit_rate  : {summary['no_exit_rate']}")
        print(f"avg_score     : {summary['avg_score']}")
        print(f"avg_rr_1      : {summary['avg_rr_1']}")
        print(f"avg_rr_2      : {summary['avg_rr_2']}")
        print(f"avg_time_exit_mfe         : {summary['avg_time_exit_mfe']}")
        print(f"avg_time_exit_mae         : {summary['avg_time_exit_mae']}")
        print(f"avg_time_exit_final_return: {summary['avg_time_exit_final_return']}")
        print("========== Time Exit Diagnostics ==========")
        print(f"CALL count                : {time_exit_call_count}")
        print(f"PUT count                 : {time_exit_put_count}")
        avg_time_exit_vwap_dist = round(sum(time_exit_vwap_dist_values) / len(time_exit_vwap_dist_values), 6) if time_exit_vwap_dist_values else 0.0
        avg_time_exit_rvol = round(sum(time_exit_rvol_values) / len(time_exit_rvol_values), 4) if time_exit_rvol_values else 0.0
        avg_time_exit_body = round(sum(time_exit_body_values) / len(time_exit_body_values), 4) if time_exit_body_values else 0.0
        print(f"avg_vwap_distance_percent : {avg_time_exit_vwap_dist}")
        print(f"avg_rvol                  : {avg_time_exit_rvol}")
        print(f"avg_body_percent          : {avg_time_exit_body}")
        print(f"trend_neutral_count       : {time_exit_trend_neutral_count}")
        print(f"momentum_neutral_count    : {time_exit_momentum_neutral_count}")
        print(f"candle_neutral_count      : {time_exit_candle_neutral_count}")
        print("========== Small Loss Diagnostics ==========")
        print(f"CALL count                : {small_loss_call_count}")
        print(f"PUT count                 : {small_loss_put_count}")
        avg_small_loss_vwap_dist = round(sum(small_loss_vwap_dist_values) / len(small_loss_vwap_dist_values), 6) if small_loss_vwap_dist_values else 0.0
        avg_small_loss_rvol = round(sum(small_loss_rvol_values) / len(small_loss_rvol_values), 4) if small_loss_rvol_values else 0.0
        avg_small_loss_body = round(sum(small_loss_body_values) / len(small_loss_body_values), 4) if small_loss_body_values else 0.0
        avg_small_loss_score = round(sum(small_loss_score_values) / len(small_loss_score_values), 2) if small_loss_score_values else 0.0
        print(f"avg_vwap_distance_percent : {avg_small_loss_vwap_dist}")
        print(f"avg_rvol                  : {avg_small_loss_rvol}")
        print(f"avg_body_percent          : {avg_small_loss_body}")
        print(f"trend_neutral_count       : {small_loss_trend_neutral_count}")
        print(f"momentum_neutral_count    : {small_loss_momentum_neutral_count}")
        print(f"candle_neutral_count      : {small_loss_candle_neutral_count}")
        print(f"avg_score                 : {avg_small_loss_score}")
        print(f"opening_range_direction   : {small_loss_opening_range_counts}")
        print(f"gap_fill_direction        : {small_loss_gap_fill_counts}")
        print(f"volume_direction          : {small_loss_volume_counts}")
        print("========== Skipped Reason Counts ==========")
        print(f"below_score   : {skipped_counts['below_score']}")
        print(f"no_trade      : {skipped_counts['no_trade']}")
        print(f"poor_rr       : {skipped_counts['poor_rr']}")
        print(f"outside_time  : {skipped_counts['outside_time']}")
        print(f"cooldown      : {skipped_counts['cooldown']}")
        print(f"weak_alignment: {skipped_counts['weak_alignment']}")
        print(f"low_rvol      : {skipped_counts['low_rvol']}")
        print(f"weak_candle   : {skipped_counts['weak_candle']}")
        print(f"low_volatility: {skipped_counts['low_volatility']}")
        print(f"vwap_extension: {skipped_counts['vwap_extension']}")
        print(f"confirmation_failed: {skipped_counts['confirmation_failed']}")
        print("========== Winners vs Early Exits ==========")
        winner_avg_score = round(sum(winner_scores) / len(winner_scores), 2) if winner_scores else 0.0
        winner_avg_vwap = round(sum(winner_vwap_dist_values) / len(winner_vwap_dist_values), 6) if winner_vwap_dist_values else 0.0
        winner_avg_rvol = round(sum(winner_rvol_values) / len(winner_rvol_values), 4) if winner_rvol_values else 0.0
        winner_avg_body = round(sum(winner_body_values) / len(winner_body_values), 4) if winner_body_values else 0.0
        winner_avg_time = _format_avg_time(winner_entry_minutes)
        print(f"winners_avg_score                 : {winner_avg_score}")
        print(f"winners_avg_vwap_distance_percent : {winner_avg_vwap}")
        print(f"winners_avg_rvol                  : {winner_avg_rvol}")
        print(f"winners_avg_body_percent          : {winner_avg_body}")
        print(f"winners_avg_entry_time            : {winner_avg_time}")

        early_avg_score = round(sum(early_exit_scores) / len(early_exit_scores), 2) if early_exit_scores else 0.0
        early_avg_vwap = round(sum(early_exit_vwap_dist_values) / len(early_exit_vwap_dist_values), 6) if early_exit_vwap_dist_values else 0.0
        early_avg_rvol = round(sum(early_exit_rvol_values) / len(early_exit_rvol_values), 4) if early_exit_rvol_values else 0.0
        early_avg_body = round(sum(early_exit_body_values) / len(early_exit_body_values), 4) if early_exit_body_values else 0.0
        early_avg_time = _format_avg_time(early_exit_entry_minutes)
        print(f"early_exits_avg_score             : {early_avg_score}")
        print(f"early_exits_avg_vwap_distance_percent: {early_avg_vwap}")
        print(f"early_exits_avg_rvol              : {early_avg_rvol}")
        print(f"early_exits_avg_body_percent      : {early_avg_body}")
        print(f"early_exits_avg_entry_time        : {early_avg_time}")
        print("========== Daily Review ==========")
        if best_day is not None:
            print(f"best_day_by_win_rate      : {best_day['date']}")
            print(f"worst_day_by_win_rate     : {worst_day['date']}")
            print(f"day_with_most_allowed_trades: {most_allowed_day['date']}")
            print(f"day_with_most_early_exits : {most_early_exit_day['date']}")
            for day in daily_rows:
                print(
                    f"{day['date']} allowed={day['allowed']} wins={day['wins']} losses={day['losses']} "
                    f"early_exit={day['early_exit']} time_exit={day['time_exit']} win_rate={day['win_rate']}"
                )
        else:
            print("No daily rows available")
        if write_outputs:
            print(f"Saved results to {LOG_PATH}")
            print(f"Saved daily summary to {DAILY_SUMMARY_CSV}")

    return summary


def run_session_comparison():
    windows = [
        ("Morning", time(9, 45), time(12, 0)),
        ("Midday", time(12, 0), time(13, 30)),
        ("Afternoon", time(13, 30), time(15, 30)),
    ]

    print("========== Session Comparison ==========")
    print("window | allowed | wins | losses | early_exit | time_exit | win_rate | early_exit_rate")
    for label, start_t, end_t in windows:
        summary = run_backtest(
            session_start=start_t,
            session_end=end_t,
            print_diagnostics=False,
            write_outputs=False,
        )
        print(
            f"{label} ({start_t.strftime('%H:%M')}-{end_t.strftime('%H:%M')}) | "
            f"{summary['allowed_signals']} | {summary['wins']} | {summary['losses']} | "
            f"{summary['early_exit']} | {summary['time_exit']} | "
            f"{summary['win_rate']} | {summary['early_exit_rate']}"
        )


if __name__ == "__main__":
    run_backtest()
