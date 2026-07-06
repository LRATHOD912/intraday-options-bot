def aggregate_scores(results):
    total_score = 0
    max_score = 0
    bullish_score = 0
    bearish_score = 0
    neutral_score = 0
    signals = []
    warnings = []

    for result in results:
        score = result.get("score", 0)
        max_points = result.get("max_score", 0)
        direction = result.get("direction", "neutral")
        total_score += score
        max_score += max_points

        if direction == "bullish":
            bullish_score += score
        elif direction == "bearish":
            bearish_score += score
        else:
            neutral_score += score

        signals.extend(result.get("signals", []))
        warnings.extend(result.get("warnings", []))

    confidence = total_score / max_score if max_score else 0
    if abs(bullish_score - bearish_score) < 10:
        direction = "NO TRADE"
        warnings.append("Directional conflict detected")
    elif bullish_score >= bearish_score + 10:
        direction = "CALL"
    elif bearish_score >= bullish_score + 10:
        direction = "PUT"
    else:
        direction = "NO TRADE"

    if total_score >= 90:
        quality = "A+"
    elif total_score >= 80:
        quality = "A"
    else:
        quality = "NO TRADE"

    if quality == "NO TRADE":
        direction = "NO TRADE"

    return {
        "decision": direction,
        "total_score": round(total_score, 2),
        "max_score": max_score,
        "confidence": round(confidence, 2),
        "quality": quality,
        "bullish_score": round(bullish_score, 2),
        "bearish_score": round(bearish_score, 2),
        "neutral_score": round(neutral_score, 2),
        "signals": signals,
        "warnings": warnings,
        "engine_results": results,
    }


def should_trade(master_decision, min_score=80):
    if master_decision["decision"] == "NO TRADE":
        return False, "Decision is NO TRADE"
    if master_decision["total_score"] < min_score:
        return False, f"Score below minimum threshold: {master_decision['total_score']}"
    return True, "Trade allowed by master score"
