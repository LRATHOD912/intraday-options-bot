def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_trade_plan(decision, latest_close, vwap, atr=None):
    entry = _to_float(latest_close)
    vwap_value = _to_float(vwap)

    if decision == "CALL":
        tight_stop = entry * 0.996
        if vwap_value is not None and vwap_value < entry and vwap_value >= tight_stop:
            stop = vwap_value
        else:
            stop = tight_stop
        target_1 = entry * 1.003
        target_2 = entry * 1.006
        risk_per_share = entry - stop
        reward_1 = target_1 - entry
        reward_2 = target_2 - entry
    elif decision == "PUT":
        tight_stop = entry * 1.004
        if vwap_value is not None and vwap_value > entry and vwap_value <= tight_stop:
            stop = vwap_value
        else:
            stop = tight_stop
        target_1 = entry * 0.997
        target_2 = entry * 0.994
        risk_per_share = stop - entry
        reward_1 = entry - target_1
        reward_2 = entry - target_2
    else:
        entry = entry
        stop = entry
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
