def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_trade_plan(decision, latest_close, vwap, atr=None, swing_low=None, swing_high=None):
    entry = _to_float(latest_close)
    vwap_value = _to_float(vwap)
    atr_value = _to_float(atr)
    swing_low_value = _to_float(swing_low)
    swing_high_value = _to_float(swing_high)

    # Backward-compatible fallback model when ATR is unavailable or invalid.
    use_fallback_model = atr_value is None or atr_value <= 0

    if decision == "CALL":
        if use_fallback_model:
            # Fixed-percentage fallback stop: 0.4% below entry.
            tight_stop = entry * 0.996
            # If VWAP is between entry and tight stop, use VWAP as a tighter stop.
            if vwap_value is not None and vwap_value < entry and vwap_value >= tight_stop:
                stop = vwap_value
            else:
                stop = tight_stop

            # Fixed-percentage fallback targets: +0.3% and +0.6% from entry.
            target_1 = entry * 1.003
            target_2 = entry * 1.006

            # Risk/reward geometry in price units.
            risk_per_share = entry - stop
            reward_1 = target_1 - entry
            reward_2 = target_2 - entry
        else:
            # ATR stop anchor for CALL: entry - 1.2 * ATR.
            atr_stop = entry - (atr_value * 1.2)
            # Dynamic stop per spec: max(ATR stop, recent swing low if available).
            if swing_low_value is not None:
                stop = max(atr_stop, swing_low_value)
            else:
                stop = atr_stop

            # Ensure stop stays below entry to keep risk positive.
            if stop >= entry:
                stop = atr_stop

            # Dynamic risk in price units.
            risk_per_share = abs(entry - stop)

            # Dynamic targets from risk units for CALL:
            # target_0 = entry + 1R, target_1 = entry + 2R, target_2 = entry + 3R.
            target_0 = entry + (1.0 * risk_per_share)
            target_1 = entry + (2.0 * risk_per_share)
            target_2 = entry + (3.0 * risk_per_share)

            reward_1 = target_1 - entry
            reward_2 = target_2 - entry

            rr_1 = reward_1 / risk_per_share if risk_per_share else 0.0
            rr_2 = reward_2 / risk_per_share if risk_per_share else 0.0
            valid_rr = rr_1 >= 1.0 or rr_2 >= 1.5
            warnings = []
            if not valid_rr:
                warnings.append("Poor risk/reward")

            return {
                "decision": decision,
                "entry": float(entry),
                "stop": float(stop),
                "target_0": float(target_0),
                "target_1": float(target_1),
                "target_2": float(target_2),
                "risk_per_share": float(risk_per_share),
                "reward_1": float(reward_1),
                "reward_2": float(reward_2),
                "rr_1": float(rr_1),
                "rr_2": float(rr_2),
                "valid_rr": valid_rr,
                "warnings": warnings,
            }
    elif decision == "PUT":
        if use_fallback_model:
            # Fixed-percentage fallback stop: 0.4% above entry.
            tight_stop = entry * 1.004
            # If VWAP is between entry and tight stop, use VWAP as a tighter stop.
            if vwap_value is not None and vwap_value > entry and vwap_value <= tight_stop:
                stop = vwap_value
            else:
                stop = tight_stop

            # Fixed-percentage fallback targets: -0.3% and -0.6% from entry.
            target_1 = entry * 0.997
            target_2 = entry * 0.994

            # Risk/reward geometry in price units.
            risk_per_share = stop - entry
            reward_1 = entry - target_1
            reward_2 = entry - target_2
        else:
            # ATR stop anchor for PUT: entry + 1.2 * ATR.
            atr_stop = entry + (atr_value * 1.2)
            # Dynamic stop per spec: min(ATR stop, recent swing high if available).
            if swing_high_value is not None:
                stop = min(atr_stop, swing_high_value)
            else:
                stop = atr_stop

            # Ensure stop stays above entry to keep risk positive.
            if stop <= entry:
                stop = atr_stop

            # Dynamic risk in price units.
            risk_per_share = abs(entry - stop)

            # Dynamic targets from risk units for PUT:
            # target_0 = entry - 1R, target_1 = entry - 2R, target_2 = entry - 3R.
            target_0 = entry - (1.0 * risk_per_share)
            target_1 = entry - (2.0 * risk_per_share)
            target_2 = entry - (3.0 * risk_per_share)

            reward_1 = entry - target_1
            reward_2 = entry - target_2

            rr_1 = reward_1 / risk_per_share if risk_per_share else 0.0
            rr_2 = reward_2 / risk_per_share if risk_per_share else 0.0
            valid_rr = rr_1 >= 1.0 or rr_2 >= 1.5
            warnings = []
            if not valid_rr:
                warnings.append("Poor risk/reward")

            return {
                "decision": decision,
                "entry": float(entry),
                "stop": float(stop),
                "target_0": float(target_0),
                "target_1": float(target_1),
                "target_2": float(target_2),
                "risk_per_share": float(risk_per_share),
                "reward_1": float(reward_1),
                "reward_2": float(reward_2),
                "rr_1": float(rr_1),
                "rr_2": float(rr_2),
                "valid_rr": valid_rr,
                "warnings": warnings,
            }
    else:
        entry = entry
        stop = entry
        target_0 = entry
        target_1 = entry
        target_2 = entry
        risk_per_share = 0.0
        reward_1 = 0.0
        reward_2 = 0.0

    rr_1 = reward_1 / risk_per_share if risk_per_share else 0.0
    rr_2 = reward_2 / risk_per_share if risk_per_share else 0.0
    valid_rr = rr_1 >= 1.0 or rr_2 >= 1.5
    warnings = []
    if not valid_rr:
        warnings.append("Poor risk/reward")

    return {
        "decision": decision,
        "entry": float(entry),
        "stop": float(stop),
        # Backward-compatible key now always present.
        "target_0": float(entry + risk_per_share) if decision == "CALL" else float(entry - risk_per_share) if decision == "PUT" else float(target_0),
        "target_1": float(target_1),
        "target_2": float(target_2),
        "risk_per_share": float(risk_per_share),
        "reward_1": float(reward_1),
        "reward_2": float(reward_2),
        "rr_1": float(rr_1),
        "rr_2": float(rr_2),
        "valid_rr": valid_rr,
        "warnings": warnings,
    }
