from datetime import datetime, timedelta
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
from app.indicators.indicators import calculate_ema, calculate_vwap, calculate_volume_average
from app.logs.decision_logger import log_decision
from app.market.levels import calculate_previous_day_levels
from app.market.market_data import get_1min_bars, get_market_internal_price
from app.planning.trade_plan import build_trade_plan
from app.risk.risk_manager import RiskManager
from app.risk.trade_gate import final_trade_gate
from app.scoring.master_score import aggregate_scores


def run_intelligence_scan():
    eastern = ZoneInfo("America/New_York")
    end_time = datetime.now(eastern)
    start_time = end_time - timedelta(days=5)

    qqq_bars = get_1min_bars("QQQ", start_time, end_time)
    if qqq_bars.empty:
        print("No QQQ bars found for the requested window; using fallback values.")
        return

    qqq_bars = qqq_bars.reset_index()
    qqq_bars["ema_9"] = calculate_ema(qqq_bars, 9)
    qqq_bars["ema_20"] = calculate_ema(qqq_bars, 20)
    qqq_bars["vwap"] = calculate_vwap(qqq_bars)
    qqq_bars["avg_volume"] = calculate_volume_average(qqq_bars)

    latest = qqq_bars.iloc[-1]
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

    analysis_results = [
        market_structure_result,
        support_resistance_result,
        opening_range_result,
        gap_fill_result,
        analyze_trend(qqq_bars),
        analyze_momentum(qqq_bars),
        analyze_volume(qqq_bars),
        analyze_volatility(qqq_bars),
        analyze_candles(qqq_bars),
        analyze_market_internals(
            vix_price=vix_proxy_now,
            vix_change=None,
            dxy_change=None,
            ten_year_change=None,
        ),
        analyze_news_risk(),
    ]

    master_decision = aggregate_scores(analysis_results)
    risk = RiskManager()
    risk_allowed, risk_reason = risk.can_trade()
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
    latest_bar_timestamp = qqq_bars.iloc[-1]["timestamp"]
    gate_result = final_trade_gate(
        master_decision,
        risk_allowed,
        risk_reason,
        news_result=analysis_results[-1],
        latest_bar_timestamp=latest_bar_timestamp,
        trade_plan=trade_plan,
    )

    print("\n========== Intelligence Engine Results ==========")
    for result in analysis_results:
        print(result)

    print("\n========== Master Decision ==========")
    print(master_decision)

    print("\n========== Final Trade Gate ==========")
    print(gate_result)

    if trade_plan is not None:
        print("\n========== Trade Plan ==========")
        print(trade_plan)

    decision_payload = {
        "master_decision": master_decision,
        "gate_result": gate_result,
        "risk_allowed": risk_allowed,
        "risk_reason": risk_reason,
    }
    log_decision(decision_payload)
    print("\n========== Decision Log ==========")
    print("Saved to logs/decisions.jsonl")


if __name__ == "__main__":
    run_intelligence_scan()
