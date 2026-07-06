from app.models.analysis_result import AnalysisResult


def analyze_market_internals(vix_price=None, vix_change=None, dxy_change=None, ten_year_change=None) -> dict:
    score = 0
    signals = []
    warnings = []
    bullish = 0
    bearish = 0

    if vix_change is None:
        if vix_price is not None:
            score += 4
            warnings.append("VIX proxy available but change unavailable")
        else:
            score += 3
            warnings.append("VIX change unavailable")
    elif vix_change < 0:
        bullish += 1
        score += 5
        signals.append("VIX falling supports calls")
    elif vix_change > 0:
        bearish += 1
        score += 5
        signals.append("VIX rising supports puts")

    if dxy_change is not None:
        if dxy_change < 0:
            bullish += 1
            score += 2
            signals.append("DXY falling supports equities")
        elif dxy_change > 0:
            bearish += 1
            score += 2
            signals.append("DXY rising pressures equities")
    else:
        warnings.append("DXY unavailable")

    if ten_year_change is not None:
        if ten_year_change < 0:
            bullish += 1
            score += 3
            signals.append("10Y yield falling supports risk assets")
        elif ten_year_change > 0:
            bearish += 1
            score += 3
            signals.append("10Y yield rising pressures growth stocks")
    else:
        warnings.append("10Y yield unavailable")

    if bullish > bearish:
        direction = "bullish"
    elif bearish > bullish:
        direction = "bearish"
    else:
        direction = "neutral"

    return AnalysisResult(
        engine="market_internals",
        direction=direction,
        score=min(score, 10),
        max_score=10,
        confidence=min(score / 10, 1),
        signals=signals,
        warnings=warnings,
        data={
            "vix_price": vix_price,
            "vix_change": vix_change,
            "dxy_change": dxy_change,
            "ten_year_change": ten_year_change,
            "vix_proxy_used": vix_price is not None,
        },
    ).to_dict()
