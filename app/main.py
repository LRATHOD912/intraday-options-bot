from datetime import datetime, timedelta, time
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
from app.analysis.volatility_engine import analyze_volatility
from app.analysis.volatility_engine import calculate_atr
from app.analysis.volume_engine import analyze_volume
from app.analytics.performance_tracker import get_summary
from app.broker.paper_broker import submit_buy_order as submit_paper_buy_order
from app.broker.orders import submit_option_buy_order
from app.config import (
    ALLOW_MULTIPLE_POSITIONS,
    ALLOW_OPPOSITE_DIRECTION_POSITIONS,
    BASE_POSITION_QUANTITY,
    ENABLE_TRADING,
    ENABLE_HEDGE_MODE,
    MAX_ENTRY_SPREAD_PERCENT,
    MAX_OPTION_PRICE,
    MAX_OPEN_POSITIONS,
    MAX_TOTAL_OPEN_RISK,
    MAX_POSITION_QUANTITY,
    MIN_ENTRY_QUALITY_SCORE,
    MIN_OPTION_PRICE,
    MIN_CONTRACTS_PER_TRADE,
    OPTION_FILTER_STRICTNESS,
    POSITION_QUANTITY,
    SIMULATE_POSITIONS,
    EXIT_PROFILE,
    RANGE_SCALP_ONLY_PAPER,
    TRADE_BUDGET_PERCENT,
    USE_BUDGET_POSITION_SIZING,
    USE_STRATEGY_ROUTER,
    USE_DYNAMIC_POSITION_SIZE,
    USE_REGIME_FILTER,
)
from app.execution.live_monitor import monitor_all_open_positions_once, monitor_open_position_once
from app.execution.monitor import check_exit_rules
from app.execution.position_manager import get_open_position, get_open_positions, get_total_open_risk, open_position
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
from app.market.option_quote import get_option_market_price
from app.market.market_data import get_1min_bars, get_latest_prices, get_market_internal_price
from app.market.options_selector import choose_best_contract
from app.planning.trade_plan import build_trade_plan
from app.risk.auto_pause import can_open_new_trade, get_pause_status
from app.risk.position_sizing import build_position_sizing_decision, get_available_budget
from app.risk.risk_manager import RiskManager
from app.risk.daily_risk_manager import can_take_new_trade, record_new_trade, reset_if_new_day
from app.risk.trade_gate import final_trade_gate
from app.scoring.master_score import aggregate_scores
from app.strategy.decision_engine import decide_final_trade
from app.strategy.scoring import calculate_call_score, calculate_put_score
from app.strategy.strategy_router import route_strategy
from app.risk.strategy_control import strategy_enabled
from app.utils.time_utils import is_market_hours


def _get_open_positions_summary():
    return get_open_positions()


def _has_duplicate_position(open_positions, option_symbol, direction):
    for position in open_positions:
        if str(position.get("option_symbol")) == str(option_symbol) and str(position.get("direction")) == str(direction) and position.get("status") == "OPEN":
            return True
    return False


def _has_conflicting_direction_position(open_positions, symbol, direction):
    for position in open_positions:
        if str(position.get("symbol")) != str(symbol):
            continue
        if position.get("status") != "OPEN":
            continue
        if str(position.get("direction")) != str(direction):
            return True
    return False


def run_bot_scan():
    log_message("Starting bot scan")
    reset_if_new_day()

    market_open, market_reason = is_market_hours()
    if not market_open:
        print("========== Market Status ==========")
        print(market_reason)
        print("NO TRADE")
        return

    open_positions = _get_open_positions_summary()
    if open_positions:
        print("========== Open Position Monitor ==========")
        print(open_positions)
        monitor_result = monitor_all_open_positions_once()
        print("========== Monitor Result ==========")
        print(monitor_result)

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
    regime_result = analyze_regime(
        qqq_bars,
        opening_range_result=opening_range_result,
        volume_result=volume_result,
        candle_result=candle_result,
        vix_price=vix_proxy_now,
        news_result=news_result,
    )
    analysis_results.extend(
        [
            trend_result,
            momentum_result,
            volume_result,
            volatility_result,
            candle_result,
            regime_result,
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

    regime_name = regime_result.get("data", {}).get("regime", "CHOPPY")
    if USE_REGIME_FILTER and master_decision.get("decision") in ["CALL", "PUT"]:
        expected = "TREND_UP" if master_decision["decision"] == "CALL" else "TREND_DOWN"
        breakout_ok = bool(regime_result.get("direction") == ("bullish" if master_decision["decision"] == "CALL" else "bearish"))
        if regime_name == "NEWS_RISK":
            allowed = False
            allow_reason = "regime_news_risk"
        elif regime_name in ["CHOPPY", "LOW_VOLATILITY"]:
            align_ok = (
                opening_range_result.get("direction") == ("bullish" if master_decision["decision"] == "CALL" else "bearish")
                and volume_result.get("direction") == ("bullish" if master_decision["decision"] == "CALL" else "bearish")
                and candle_result.get("direction") in [("bullish" if master_decision["decision"] == "CALL" else "bearish"), "neutral"]
            )
            if not align_ok:
                allowed = False
                allow_reason = "regime_choppy_low_vol_block"
        elif regime_name not in [expected, "HIGH_VOLATILITY", "RANGE"] and not breakout_ok:
            allowed = False
            allow_reason = "regime_direction_block"

    entry_quality = calculate_entry_quality_score(
        decision=master_decision.get("decision"),
        master_score=master_decision.get("total_score", 0),
        trend_direction=trend_result.get("direction"),
        vwap_aligned=(latest["close"] > latest["vwap"]) if master_decision.get("decision") == "CALL" else (latest["close"] < latest["vwap"]),
        ema_aligned=(latest["ema_9"] > latest["ema_20"]) if master_decision.get("decision") == "CALL" else (latest["ema_9"] < latest["ema_20"]),
        opening_range_direction=opening_range_result.get("direction"),
        market_structure_direction=market_structure_result.get("direction"),
        volume_direction=volume_result.get("direction"),
        candle_direction=candle_result.get("direction"),
        momentum_direction=momentum_result.get("direction"),
        support_resistance_direction=support_resistance_result.get("direction"),
        gap_fill_direction=gap_fill_result.get("direction"),
        regime=regime_name,
    )
    entry_quality_score = int(entry_quality.get("entry_quality_score", 0))
    if master_decision.get("decision") in ["CALL", "PUT"] and entry_quality_score < int(MIN_ENTRY_QUALITY_SCORE):
        allowed = False
        allow_reason = "entry_quality_below_threshold"
        log_trade_event(
            "ENTRY_QUALITY_BLOCK",
            {
                "symbol": "QQQ",
                "decision": master_decision.get("decision"),
                "entry_quality_score": entry_quality_score,
                "threshold": int(MIN_ENTRY_QUALITY_SCORE),
            },
        )

    auto_pause_ok, auto_pause_reason = can_open_new_trade()
    if not auto_pause_ok:
        allowed = False
        allow_reason = f"auto_pause:{auto_pause_reason}"
        log_trade_event("AUTO_PAUSE_TRIGGERED", {"reason": auto_pause_reason})

    strategy_route = route_strategy(
        regime_result=regime_result,
        master_score=master_decision,
        vwap_distance_percent=trend_result.get("data", {}).get("vwap_distance_percent"),
        ema_9=float(latest["ema_9"]),
        ema_20=float(latest["ema_20"]),
        latest_close=float(latest["close"]),
        opening_high=opening_high,
        opening_low=opening_low,
        prev_day_high=prev_high,
        prev_day_low=prev_low,
        support_level=support_resistance_result.get("data", {}).get("support"),
        resistance_level=support_resistance_result.get("data", {}).get("resistance"),
        atr_percent=(float(volatility_result.get("data", {}).get("atr")) / float(latest["close"])) if volatility_result.get("data", {}).get("atr") else None,
        rvol=volume_result.get("data", {}).get("rvol"),
        candle_body_percent=candle_result.get("data", {}).get("body_percent"),
        momentum_direction=momentum_result.get("direction"),
        gap_direction=gap_fill_result.get("direction"),
        opening_range_result=opening_range_result,
        trend_result=trend_result,
        volume_result=volume_result,
        candle_result=candle_result,
        support_resistance_result=support_resistance_result,
        current_time_et=now_et,
        option_spread_percent=None,
        option_liquidity_score=None,
        option_premium=None,
        gap_percent=gap_fill_result.get("data", {}).get("gap_percent"),
        gap_fill_direction=gap_fill_result.get("direction"),
        price_near_support=bool(
            support_resistance_result.get("data", {}).get("support") is not None
            and abs(float(latest["close"]) - float(support_resistance_result.get("data", {}).get("support")))
            / max(abs(float(support_resistance_result.get("data", {}).get("support"))), 1.0)
            <= 0.003
        ),
        price_near_resistance=bool(
            support_resistance_result.get("data", {}).get("resistance") is not None
            and abs(float(latest["close"]) - float(support_resistance_result.get("data", {}).get("resistance")))
            / max(abs(float(support_resistance_result.get("data", {}).get("resistance"))), 1.0)
            <= 0.003
        ),
    )

    decision_payload = {
        "master_decision": master_decision,
        "gate_result": {"allowed": allowed, "reason": allow_reason},
        "risk_allowed": can_trade,
        "risk_reason": risk_reason,
        "entry_quality_score": entry_quality_score,
        "regime": regime_name,
        "strategy_route": strategy_route,
        "pause_status": get_pause_status(),
        "market_price": float(latest["close"]),
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
    print("\n========== Strategy Router ==========")
    print(strategy_route)

    if trade_plan is not None:
        print("\n========== Trade Plan ==========")
        print(trade_plan)

    print("\n========== Option Contract Selection ==========")
    if allowed and master_decision["decision"] in ["CALL", "PUT"]:
        open_positions = _get_open_positions_summary()
        total_open_positions = len(open_positions)
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

        if not ALLOW_MULTIPLE_POSITIONS and total_open_positions > 0:
            print("NO TRADE: multiple positions disabled")
            log_trade_event(
                "ORDER_SKIPPED",
                {
                    "phase": "ENTRY",
                    "symbol": "QQQ",
                    "reason": "multiple_positions_disabled",
                },
            )
            return

        route_name = strategy_route.get("strategy_name", "NO_TRADE")
        route_direction = strategy_route.get("direction", "NO_TRADE")
        route_enabled = USE_STRATEGY_ROUTER and route_name != "NO_TRADE" and strategy_enabled(route_name)
        if USE_STRATEGY_ROUTER and not route_enabled:
            print(f"NO TRADE: strategy router blocked {route_name}")
            log_trade_event(
                "STRATEGY_ROUTED_NO_TRADE",
                {
                    "symbol": "QQQ",
                    "decision": master_decision.get("decision"),
                    "strategy_route": strategy_route,
                },
            )
            return

        if USE_STRATEGY_ROUTER and route_name == "RANGE_SCALP_0DTE" and ENABLE_TRADING and RANGE_SCALP_ONLY_PAPER:
            print("NO TRADE: range scalp 0DTE is paper-only by config")
            log_trade_event(
                "STRATEGY_ROUTED_NO_TRADE",
                {
                    "symbol": "QQQ",
                    "decision": master_decision.get("decision"),
                    "strategy_route": strategy_route,
                    "reason": "range_scalp_paper_only",
                },
            )
            return

        if total_open_positions >= int(MAX_OPEN_POSITIONS):
            print("NO TRADE: max open positions reached")
            log_trade_event(
                "RISK_BLOCK",
                {
                    "symbol": "QQQ",
                    "decision": master_decision.get("decision"),
                    "reason": "max_open_positions_reached",
                    "max_open_positions": int(MAX_OPEN_POSITIONS),
                    "current_open_positions": total_open_positions,
                },
            )
            return

        contract, reason = choose_best_contract(
            "QQQ",
            route_direction if USE_STRATEGY_ROUTER and route_direction in ["CALL", "PUT"] else master_decision["decision"],
            prices["QQQ"],
            strictness=OPTION_FILTER_STRICTNESS,
            strategy_name=route_name if USE_STRATEGY_ROUTER else None,
            allow_0dte_override=True if route_name == "RANGE_SCALP_0DTE" else None,
        )
        print(f"{master_decision['decision']} Contract:")
        print(reason)
        print(contract)
        if contract:
            if _has_duplicate_position(open_positions, contract.get("symbol"), master_decision["decision"]):
                log_trade_event(
                    "ORDER_SKIPPED",
                    {
                        "phase": "ENTRY",
                        "symbol": "QQQ",
                        "option_symbol": contract.get("symbol"),
                        "reason": "duplicate_position",
                    },
                )
                print("NO TRADE: duplicate position")
                return

            if not (ALLOW_OPPOSITE_DIRECTION_POSITIONS or ENABLE_HEDGE_MODE) and _has_conflicting_direction_position(open_positions, "QQQ", master_decision["decision"]):
                log_trade_event(
                    "ORDER_SKIPPED",
                    {
                        "phase": "ENTRY",
                        "symbol": "QQQ",
                        "option_symbol": contract.get("symbol"),
                        "reason": "opposite_direction_position_exists",
                    },
                )
                print("NO TRADE: opposite direction position exists")
                return

            option_quote = get_option_market_price(contract.get("symbol"))
            spread_percent = None
            if option_quote is not None:
                spread_percent = option_quote.get("spread_percent")

            if option_quote is None or not option_quote.get("quote_valid", False):
                log_trade_event(
                    "ORDER_SKIPPED",
                    {
                        "phase": "ENTRY",
                        "symbol": "QQQ",
                        "option_symbol": contract.get("symbol"),
                        "reason": "invalid_option_quote",
                    },
                )
                return
            if option_quote.get("bid") is None or option_quote.get("ask") is None:
                log_trade_event("ORDER_SKIPPED", {"phase": "ENTRY", "symbol": "QQQ", "option_symbol": contract.get("symbol"), "reason": "missing_bid_ask"})
                return
            if spread_percent is not None and float(spread_percent) > float(MAX_ENTRY_SPREAD_PERCENT):
                log_trade_event("ORDER_SKIPPED", {"phase": "ENTRY", "symbol": "QQQ", "option_symbol": contract.get("symbol"), "reason": "spread_too_wide", "spread_percent": spread_percent})
                return

            entry_price = contract.get("mid") or contract.get("ask")
            if entry_price is None:
                entry_price = option_quote.get("price")
            entry_price = float(entry_price) if entry_price is not None else None
            if entry_price is None or entry_price < float(MIN_OPTION_PRICE) or entry_price > float(MAX_OPTION_PRICE):
                log_trade_event("ORDER_SKIPPED", {"phase": "ENTRY", "symbol": "QQQ", "option_symbol": contract.get("symbol"), "reason": "option_price_out_of_bounds", "entry_price": entry_price})
                return

            budget_decision = {
                "quantity": max(int(POSITION_QUANTITY), 1),
                "buying_power": None,
                "trade_budget": None,
                "contract_cost": float(entry_price) * 100.0,
                "reason": "budget_sizing_disabled",
            }
            trade_quantity = max(int(POSITION_QUANTITY), 1)
            if USE_DYNAMIC_POSITION_SIZE:
                trade_quantity = int(BASE_POSITION_QUANTITY)
                if entry_quality_score >= 93:
                    trade_quantity = 4
                elif entry_quality_score >= 85:
                    trade_quantity = 2
                elif entry_quality_score >= 75:
                    trade_quantity = 1

                if regime_name == "HIGH_VOLATILITY":
                    trade_quantity = max(1, int(round(trade_quantity * 0.5)))

                if spread_percent is not None and float(spread_percent) > 0.08:
                    trade_quantity = 1

                if USE_STRATEGY_ROUTER:
                    trade_quantity = max(1, int(round(trade_quantity * float(strategy_route.get("risk_multiplier", 1.0) or 1.0))))

                perf = get_summary(limit_last=20)
                if float(perf.get("today", {}).get("realized_pnl", 0.0)) < 0:
                    trade_quantity = 1

                trade_quantity = min(max(1, trade_quantity), int(MAX_POSITION_QUANTITY))

            if USE_BUDGET_POSITION_SIZING:
                budget_decision = build_position_sizing_decision(entry_price, buying_power=None, budget_percent=TRADE_BUDGET_PERCENT)
                trade_quantity = int(budget_decision.get("quantity", 0))
                log_trade_event(
                    "POSITION_SIZING_DECISION",
                    {
                        "symbol": "QQQ",
                        "option_symbol": contract.get("symbol"),
                        "decision": master_decision.get("decision"),
                        "buying_power": budget_decision.get("buying_power"),
                        "trade_budget": budget_decision.get("trade_budget"),
                        "contract_cost": budget_decision.get("contract_cost"),
                        "quantity": trade_quantity,
                        "budget_percent": TRADE_BUDGET_PERCENT,
                        "reason": budget_decision.get("reason"),
                    },
                )

            if trade_quantity < int(MIN_CONTRACTS_PER_TRADE):
                log_trade_event(
                    "ORDER_SKIPPED",
                    {
                        "phase": "ENTRY",
                        "symbol": "QQQ",
                        "option_symbol": contract.get("symbol"),
                        "reason": "budget_too_small",
                        "buying_power": budget_decision.get("buying_power"),
                        "trade_budget": budget_decision.get("trade_budget"),
                    },
                )
                return

            new_trade_risk = float(trade_plan.get("risk_per_contract", trade_plan.get("risk_per_share", 0.0)) or 0.0) * float(trade_quantity) * 100.0
            total_open_risk = float(get_total_open_risk())
            if total_open_risk + new_trade_risk > float(MAX_TOTAL_OPEN_RISK):
                log_trade_event(
                    "RISK_BLOCK",
                    {
                        "symbol": "QQQ",
                        "decision": master_decision.get("decision"),
                        "reason": "total_open_risk_exceeded",
                        "total_open_risk": round(total_open_risk, 2),
                        "new_trade_risk": round(new_trade_risk, 2),
                        "max_total_open_risk": float(MAX_TOTAL_OPEN_RISK),
                    },
                )
                print("NO TRADE: total open risk exceeded")
                return

            order_result = submit_option_buy_order(contract["symbol"], qty=trade_quantity, limit_price=entry_price, timeout_seconds=5)
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
                            strategy_name=strategy_route.get("strategy_name") if USE_STRATEGY_ROUTER else None,
                            broker=order_result.get("broker", "ALPACA"),
                            metadata={
                                "entry_quality_score": entry_quality_score,
                                "regime": regime_name,
                                "exit_profile": strategy_route.get("required_exit_profile", EXIT_PROFILE) if USE_STRATEGY_ROUTER else EXIT_PROFILE,
                                "setup_type": "scan_default",
                                "strategy_name": strategy_route.get("strategy_name") if USE_STRATEGY_ROUTER else None,
                                "strategy_reason": strategy_route.get("reason") if USE_STRATEGY_ROUTER else None,
                                "strategy_confidence": strategy_route.get("confidence") if USE_STRATEGY_ROUTER else None,
                                "recommended_expiry_type": contract.get("expiry_type") if isinstance(contract, dict) else None,
                                "liquidity_score": contract.get("liquidity_score") if isinstance(contract, dict) else None,
                                "option_quality_score": contract.get("option_quality_score") if isinstance(contract, dict) else None,
                                "strategy_max_hold_minutes": strategy_route.get("max_hold_minutes") if USE_STRATEGY_ROUTER else None,
                            },
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
                                "entry_quality_score": entry_quality_score,
                                "regime": regime_name,
                                "strategy_name": strategy_route.get("strategy_name") if USE_STRATEGY_ROUTER else None,
                                "strategy_confidence": strategy_route.get("confidence") if USE_STRATEGY_ROUTER else None,
                                "position_id": saved_position.get("position_id"),
                                "spread_percent": spread_percent,
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
            log_trade_event("OPTION_SELECTION_BLOCK", {"symbol": "QQQ", "decision": master_decision.get("decision"), "reason": reason})
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
