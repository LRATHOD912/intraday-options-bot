from datetime import datetime, timedelta, time
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
from app.analysis.volatility_engine import calculate_atr
from app.analysis.volume_engine import analyze_volume
from app.broker.paper_broker import submit_buy_order as submit_paper_buy_order
from app.broker.orders import submit_option_buy_order
from app.config import ENABLE_TRADING, POSITION_QUANTITY, SIMULATE_POSITIONS
from app.execution.live_monitor import monitor_open_position_once
from app.execution.monitor import check_exit_rules
from app.execution.position_manager import get_open_position, has_open_position, open_position
from app.execution.trade_manager import build_trade_decision
from app.indicators.indicators import (
    calculate_ema,
    calculate_vwap,
    calculate_volume_average,
)
from app.logs.decision_logger import log_decision
from app.logs.logger import log_message
from app.logs.trade_journal import log_trade_event
from app.market.levels import (
    calculate_opening_range,
    calculate_premarket_levels,
    calculate_previous_day_levels,
    detect_breakout,
    detect_breakdown,
)
from app.market.market_data import get_1min_bars, get_latest_prices, get_market_internal_price
from app.market.options_selector import choose_best_contract
from app.planning.trade_plan import build_trade_plan
from app.risk.risk_manager import RiskManager
from app.risk.daily_risk_manager import can_take_new_trade, record_new_trade, reset_if_new_day
from app.risk.trade_gate import final_trade_gate
from app.scoring.master_score import aggregate_scores
from app.strategy.decision_engine import decide_final_trade
from app.strategy.scoring import calculate_call_score, calculate_put_score
from app.utils.time_utils import is_market_hours


def run_bot_scan():
    log_message("Starting bot scan")
    reset_if_new_day()

    market_open, market_reason = is_market_hours()
    if not market_open:
        print("========== Market Status ==========")
        print(market_reason)
        print("NO TRADE")
        return

    # Open position lifecycle runs before any new-trade scan.
    if has_open_position():
        print("========== Open Position Monitor ==========")
        print(get_open_position())
        monitor_result = monitor_open_position_once()
        print("========== Monitor Result ==========")
        print(monitor_result)
        return

    eastern = ZoneInfo("America/New_York")
    now_et = datetime.now(eastern)
    if not (time(9, 45) <= now_et.time() <= time(12, 0)):
        print("NO TRADE: outside strategy window")
        return

    symbols = ["SPY", "QQQ", "IWM"]
    prices = get_latest_prices(symbols)

    print("========== Latest Prices ==========")
    for symbol, price in prices.items():
        print(f"{symbol}: {price}")

    end_time = now_et
    start_time = end_time - timedelta(days=5)

    qqq_bars = get_1min_bars("QQQ", start_time, end_time)
    if qqq_bars.empty:
        print("No QQQ bars found for the requested window; using fallback values.")
        qqq_bars = qqq_bars.copy()
        qqq_bars["open"] = [prices["QQQ"]]
        qqq_bars["close"] = [prices["QQQ"]]
        qqq_bars["high"] = [prices["QQQ"]]
        qqq_bars["low"] = [prices["QQQ"]]
        qqq_bars["volume"] = [0]
        qqq_bars["timestamp"] = [end_time]

    qqq_bars = qqq_bars.reset_index()
    qqq_bars["ema_9"] = calculate_ema(qqq_bars, 9)
    qqq_bars["ema_20"] = calculate_ema(qqq_bars, 20)
    qqq_bars["vwap"] = calculate_vwap(qqq_bars)
    qqq_bars["avg_volume"] = calculate_volume_average(qqq_bars)

    latest = qqq_bars.iloc[-1]

    premarket_high, premarket_low = calculate_premarket_levels(qqq_bars)
    opening_high, opening_low = calculate_opening_range(qqq_bars)
    prev_high, prev_low, prev_close = calculate_previous_day_levels(qqq_bars)
    today_open = qqq_bars.iloc[0]["open"]
    market_structure_result = analyze_market_structure(
        qqq_bars,
        latest["close"],
        today_open,
        prev_high,
        prev_low,
        prev_close,
    )

    support_resistance_result = analyze_support_resistance(
        qqq_bars,
        latest["close"],
        prev_high,
        prev_low,
    )
    opening_range_result = analyze_opening_range(qqq_bars)
    gap_fill_result = analyze_gap_fill(qqq_bars, prev_close)
    vix_proxy_now = get_market_internal_price("VIXY")
    vix_proxy_prev = None

    analysis_results = []
    analysis_results.append(market_structure_result)
    analysis_results.append(support_resistance_result)
    analysis_results.append(opening_range_result)
    analysis_results.append(gap_fill_result)
    trend_result = analyze_trend(qqq_bars)
    momentum_result = analyze_momentum(qqq_bars)
    volume_result = analyze_volume(qqq_bars)
    volatility_result = analyze_volatility(qqq_bars)
    candle_result = analyze_candles(qqq_bars)
    internals_result = analyze_market_internals(
        vix_price=vix_proxy_now,
        vix_change=None,
        dxy_change=None,
        ten_year_change=None,
    )
    news_result = analyze_news_risk()
    analysis_results.extend(
        [
            trend_result,
            momentum_result,
            volume_result,
            volatility_result,
            candle_result,
            internals_result,
            news_result,
        ]
    )
    master_decision = aggregate_scores(analysis_results)
    risk = RiskManager()
    can_trade, risk_reason = risk.can_trade()
    trade_plan = None
    if master_decision["decision"] in ["CALL", "PUT"]:
        atr_series = calculate_atr(qqq_bars)
        atr_value = None
        if atr_series is not None and len(atr_series) > 0:
            latest_atr = atr_series.iloc[-1]
            if latest_atr == latest_atr:
                atr_value = float(latest_atr)

        recent_window = qqq_bars.tail(20)
        swing_low = float(recent_window["low"].min()) if not recent_window.empty else None
        swing_high = float(recent_window["high"].max()) if not recent_window.empty else None

        trade_plan = build_trade_plan(
            master_decision["decision"],
            latest["close"],
            latest["vwap"],
            atr=atr_value,
            swing_low=swing_low,
            swing_high=swing_high,
        )
    gate_result = final_trade_gate(
        master_decision,
        can_trade,
        risk_reason,
        news_result=news_result,
        latest_bar_timestamp=latest["timestamp"],
        trade_plan=trade_plan,
    )
    allowed = gate_result["allowed"]
    allow_reason = gate_result["reason"]
    decision_payload = {
        "master_decision": master_decision,
        "gate_result": gate_result,
        "risk_allowed": can_trade,
        "risk_reason": risk_reason,
    }
    log_decision(decision_payload)

    breakout_high = premarket_high or opening_high or prev_high
    breakdown_low = premarket_low or opening_low or prev_low
    signal = {
        "above_vwap": latest["close"] > latest["vwap"],
        "below_vwap": latest["close"] < latest["vwap"],
        "ema_bullish": latest["ema_9"] > latest["ema_20"],
        "ema_bearish": latest["ema_9"] < latest["ema_20"],
        "breakout": latest["close"] > breakout_high if breakout_high else False,
        "breakdown": latest["close"] < breakdown_low if breakdown_low else False,
        "volume_strong": latest["volume"] > latest["avg_volume"],
        "spy_confirms": prices["SPY"] > 0,
        "qqq_confirms": prices["QQQ"] > 0,
        "ndx_confirms": True,
        "vix_ok": True,
        "spread_tight": True,
    }

    call_score, call_checks = calculate_call_score(signal)
    put_score, put_checks = calculate_put_score(signal)

    call_decision = build_trade_decision("QQQ", "CALL", call_score, call_checks)
    put_decision = build_trade_decision("QQQ", "PUT", put_score, put_checks)

    final_decision = decide_final_trade(call_decision, put_decision)

    print("\n========== Signal Check ==========")
    print(f"Latest QQQ Close : {latest['close']}")
    print(f"VWAP             : {latest['vwap']}")
    print(f"EMA 9            : {latest['ema_9']}")
    print(f"EMA 20           : {latest['ema_20']}")
    print(f"Volume           : {latest['volume']}")
    print(f"Avg Volume       : {latest['avg_volume']}")
    print(f"Premarket High   : {premarket_high}")
    print(f"Premarket Low    : {premarket_low}")
    print(f"Opening High     : {opening_high}")
    print(f"Opening Low      : {opening_low}")
    print(f"Previous High    : {prev_high}")
    print(f"Previous Low     : {prev_low}")
    print(f"Previous Close   : {prev_close}")
    print(f"Breakout Level   : {breakout_high}")
    print(f"Breakdown Level  : {breakdown_low}")

    print("\n========== Market Structure ==========")
    print(market_structure_result)

    print("\n========== Call Decision ==========")
    print(call_decision)
    print("\n========== Put Decision ==========")
    print(put_decision)
    print("\n========== Final Decision ==========")
    print(final_decision)

    print("\n========== Intelligence Engine Results ==========")
    for result in analysis_results:
        print(result)

    print("\n========== Master Score ==========")
    print(master_decision)
    print("\n========== Master Trade Permission ==========")
    print(f"Allowed: {allowed}")
    print(f"Reason : {allow_reason}")
    print("\n========== Decision Log ==========")
    print("Saved to logs/decisions.jsonl")

    if trade_plan is not None:
        print("\n========== Trade Plan ==========")
        print(trade_plan)

    print("\n========== Option Contract Selection ==========")
    if gate_result["allowed"] and master_decision["decision"] in ["CALL", "PUT"]:
        if not can_take_new_trade():
            print("NO TRADE: daily risk limit reached")
            log_trade_event(
                "RISK_BLOCK",
                {
                    "symbol": "QQQ",
                    "decision": master_decision.get("decision"),
                    "reason": "daily_risk_limit_reached",
                },
            )
            return

        if has_open_position():
            print("NO TRADE: existing open position")
            print(get_open_position())
            return

        contract, reason = choose_best_contract(
            "QQQ",
            master_decision["decision"],
            prices["QQQ"],
        )
        print(f"{master_decision['decision']} Contract:")
        print(reason)
        print(contract)
        if contract:
            entry_price = contract.get("mid") or contract.get("ask")
            trade_quantity = max(int(POSITION_QUANTITY), 1)
            order_result = submit_option_buy_order(contract["symbol"], qty=trade_quantity)
            if order_result.get("submitted"):
                pass
            elif SIMULATE_POSITIONS:
                paper_order = submit_paper_buy_order(
                    symbol=contract["symbol"],
                    qty=trade_quantity,
                    price=entry_price,
                )
                order_result = {
                    "submitted": True,
                    "order_id": paper_order.get("order_id"),
                    "status": paper_order.get("status", "FILLED"),
                    "broker": "INTERNAL_SIM",
                    "symbol": contract["symbol"],
                    "qty": trade_quantity,
                    "route_reason": "SIMULATE_POSITIONS=true fallback",
                }

            print("\n========== Order Result ==========")
            print(order_result)

            order_submitted = bool(order_result.get("submitted"))
            simulation_save_allowed = (not ENABLE_TRADING) and SIMULATE_POSITIONS
            if order_submitted or simulation_save_allowed:
                if entry_price is None:
                    print("Position not saved: missing contract mid/ask for entry price")
                    log_trade_event(
                        "ORDER_SKIPPED",
                        {
                            "phase": "ENTRY",
                            "symbol": "QQQ",
                            "option_symbol": contract.get("symbol"),
                            "quantity": trade_quantity,
                            "reason": "missing_contract_entry_price",
                        },
                    )
                elif trade_plan is None:
                    print("Position not saved: trade plan unavailable")
                    log_trade_event(
                        "ORDER_SKIPPED",
                        {
                            "phase": "ENTRY",
                            "symbol": "QQQ",
                            "option_symbol": contract.get("symbol"),
                            "quantity": trade_quantity,
                            "reason": "trade_plan_unavailable",
                        },
                    )
                else:
                    target_1x = trade_plan.get("target_1x", trade_plan.get("target_0"))
                    target_2x = trade_plan.get("target_2x", trade_plan.get("target_1"))
                    target_3x = trade_plan.get("target_3x", trade_plan.get("target_2"))
                    target_4x = trade_plan.get("target_4x")
                    try:
                        saved_position = open_position(
                            symbol="QQQ",
                            option_symbol=contract["symbol"],
                            direction=master_decision["decision"],
                            quantity=trade_quantity,
                            entry_price=entry_price,
                            stop_price=trade_plan["stop"],
                            target_0=trade_plan.get("target_0"),
                            target_1=trade_plan["target_1"],
                            target_2=trade_plan["target_2"],
                            target_3=target_3x,
                            target_4=target_4x,
                            risk_per_contract=trade_plan.get("risk_per_contract", trade_plan.get("risk_per_share")),
                            order_id=order_result.get("order_id", "SIMULATED_NO_ORDER"),
                        )
                        record_new_trade()
                        print("\n========== Position Saved ==========")
                        print(saved_position)
                        log_trade_event(
                            "ENTRY",
                            {
                                "symbol": "QQQ",
                                "option_symbol": contract.get("symbol"),
                                "direction": master_decision.get("decision"),
                                "quantity": trade_quantity,
                                "entry_price": entry_price,
                                "stop_price": trade_plan.get("stop"),
                                "target_0": trade_plan.get("target_0"),
                                "target_1": trade_plan.get("target_1"),
                                "target_2": trade_plan.get("target_2"),
                                "target_1x": target_1x,
                                "target_2x": target_2x,
                                "target_3x": target_3x,
                                "target_4x": target_4x,
                                "risk_per_contract": trade_plan.get("risk_per_contract", trade_plan.get("risk_per_share")),
                                "order_id": order_result.get("order_id"),
                                "broker": order_result.get("broker", "ALPACA"),
                            },
                        )
                    except ValueError as exc:
                        print(f"Position not saved: {exc}")
                        log_trade_event(
                            "ORDER_SKIPPED",
                            {
                                "phase": "ENTRY",
                                "symbol": "QQQ",
                                "option_symbol": contract.get("symbol"),
                                "quantity": trade_quantity,
                                "reason": str(exc),
                            },
                        )
            else:
                print("Position not saved: order not submitted and simulation mode disabled")
                log_trade_event(
                    "ORDER_SKIPPED",
                    {
                        "phase": "ENTRY",
                        "symbol": "QQQ",
                        "option_symbol": contract.get("symbol"),
                        "quantity": trade_quantity,
                        "reason": order_result.get("reason", "Order not submitted"),
                    },
                )
        else:
            log_trade_event(
                "ORDER_SKIPPED",
                {
                    "phase": "ENTRY",
                    "symbol": "QQQ",
                    "reason": reason,
                },
            )
    else:
        print("No valid trade, skipping option selection")

    print("\n========== Risk Check ==========")
    print(f"Can Trade: {can_trade}")
    print(f"Reason   : {risk_reason}")

    print("\n========== Exit Monitor Test ==========")
    exit_test = check_exit_rules(
        option_symbol="QQQ_TEST_CONTRACT",
        entry_price=2.00,
        current_price=1.55,
        qty=1,
    )
    print(exit_test)

    log_message("Bot scan completed")


if __name__ == "__main__":
    run_bot_scan()
