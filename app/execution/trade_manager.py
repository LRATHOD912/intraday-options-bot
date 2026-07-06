def build_trade_decision(symbol, direction, score, checks):
    if direction == "CALL":
        if not checks.get("above_vwap"):
            return {
                "trade_valid": False,
                "symbol": symbol,
                "direction": direction,
                "score": score,
                "reason": "Call rejected: price below VWAP",
                "checks": checks,
            }
        if not checks.get("breakout"):
            return {
                "trade_valid": False,
                "symbol": symbol,
                "direction": direction,
                "score": score,
                "reason": "Call rejected: no breakout",
                "checks": checks,
            }

    if direction == "PUT":
        if not checks.get("below_vwap"):
            return {
                "trade_valid": False,
                "symbol": symbol,
                "direction": direction,
                "score": score,
                "reason": "Put rejected: price above VWAP",
                "checks": checks,
            }
        if not checks.get("breakdown"):
            return {
                "trade_valid": False,
                "symbol": symbol,
                "direction": direction,
                "score": score,
                "reason": "Put rejected: no breakdown",
                "checks": checks,
            }

    if score < 7:
        return {
            "trade_valid": False,
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "reason": "Score below 7",
            "checks": checks,
        }

    return {
        "trade_valid": True,
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "reason": "Valid trade setup",
        "checks": checks,
    }
