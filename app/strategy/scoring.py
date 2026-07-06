def calculate_call_score(signal):
    score = 0
    checks = {
        "above_vwap": signal.get("above_vwap", False),
        "ema_bullish": signal.get("ema_bullish", False),
        "breakout": signal.get("breakout", False),
        "volume_strong": signal.get("volume_strong", False),
        "spy_confirms": signal.get("spy_confirms", False),
        "qqq_confirms": signal.get("qqq_confirms", False),
        "ndx_confirms": signal.get("ndx_confirms", False),
        "vix_ok": signal.get("vix_ok", True),
        "spread_tight": signal.get("spread_tight", True),
    }
    for value in checks.values():
        if value:
            score += 1
    return score, checks


def calculate_put_score(signal):
    score = 0
    checks = {
        "below_vwap": signal.get("below_vwap", False),
        "ema_bearish": signal.get("ema_bearish", False),
        "breakdown": signal.get("breakdown", False),
        "volume_strong": signal.get("volume_strong", False),
        "spy_confirms": signal.get("spy_confirms", False),
        "qqq_confirms": signal.get("qqq_confirms", False),
        "ndx_confirms": signal.get("ndx_confirms", False),
        "vix_ok": signal.get("vix_ok", True),
        "spread_tight": signal.get("spread_tight", True),
    }
    for value in checks.values():
        if value:
            score += 1
    return score, checks
