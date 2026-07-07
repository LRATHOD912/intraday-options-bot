def calculate_entry_quality_score(
    decision,
    master_score,
    trend_direction,
    vwap_aligned,
    ema_aligned,
    opening_range_direction,
    market_structure_direction,
    volume_direction,
    candle_direction,
    momentum_direction,
    support_resistance_direction,
    gap_fill_direction,
    regime,
    option_spread_percent=None,
    option_liquidity_ok=None,
):
    expected = "bullish" if decision == "CALL" else "bearish"
    score = 0
    checks = {}

    trend_ok = trend_direction == expected and ema_aligned
    if trend_ok:
        score += 15
    checks["trend_ema"] = trend_ok

    if vwap_aligned:
        score += 15
    checks["vwap"] = bool(vwap_aligned)

    opening_ok = opening_range_direction == expected
    if opening_ok:
        score += 15
    checks["opening_range"] = opening_ok

    vol_ok = volume_direction == expected
    if vol_ok:
        score += 10
    checks["volume"] = vol_ok

    candle_ok = candle_direction in [expected, "neutral"]
    if candle_ok:
        score += 10
    checks["candle"] = candle_ok

    momentum_ok = momentum_direction in [expected, "neutral"]
    if momentum_ok:
        score += 10
    checks["momentum"] = momentum_ok

    structure_ok = market_structure_direction == expected
    if structure_ok:
        score += 10
    checks["market_structure"] = structure_ok

    sr_ok = support_resistance_direction in [expected, "neutral"]
    if sr_ok:
        score += 5
    checks["support_resistance"] = sr_ok

    gap_ok = gap_fill_direction in [expected, "neutral"]
    if gap_ok:
        score += 5
    checks["gap_fill"] = gap_ok

    liquidity_ok = bool(option_liquidity_ok)
    if option_spread_percent is not None:
        try:
            liquidity_ok = liquidity_ok or float(option_spread_percent) <= 0.05
        except (TypeError, ValueError):
            pass
    if liquidity_ok:
        score += 5
    checks["option_liquidity"] = liquidity_ok

    if regime in ["NEWS_RISK", "CHOPPY"]:
        score = max(score - 20, 0)
    elif regime == "LOW_VOLATILITY":
        score = max(score - 10, 0)

    # Blend in master score influence without exceeding 100.
    try:
        master_component = min(max(float(master_score), 0.0), 100.0) * 0.1
    except (TypeError, ValueError):
        master_component = 0.0

    final_score = min(int(round(score + master_component)), 100)
    return {
        "entry_quality_score": final_score,
        "checks": checks,
        "regime": regime,
    }
