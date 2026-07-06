import pandas as pd

from app.models.analysis_result import AnalysisResult


def detect_higher_highs_lows(df, lookback=5):
    recent = df.tail(lookback)
    highs = recent["high"].tolist()
    lows = recent["low"].tolist()

    higher_highs = highs[-1] > highs[0]
    higher_lows = lows[-1] > lows[0]
    lower_highs = highs[-1] < highs[0]
    lower_lows = lows[-1] < lows[0]

    if higher_highs and higher_lows:
        return "BULLISH_STRUCTURE"
    if lower_highs and lower_lows:
        return "BEARISH_STRUCTURE"
    return "CHOPPY_STRUCTURE"


def detect_gap(today_open, prev_close):
    if today_open is None or prev_close is None:
        return "NO_GAP"

    gap_percent = (today_open - prev_close) / prev_close
    if gap_percent > 0.003:
        return "GAP_UP"
    if gap_percent < -0.003:
        return "GAP_DOWN"
    return "NO_GAP"


def detect_price_location(latest_close, prev_high, prev_low, prev_close):
    if prev_high and latest_close > prev_high:
        return "ABOVE_PREVIOUS_HIGH"
    if prev_low and latest_close < prev_low:
        return "BELOW_PREVIOUS_LOW"
    if prev_close and latest_close > prev_close:
        return "ABOVE_PREVIOUS_CLOSE"
    if prev_close and latest_close < prev_close:
        return "BELOW_PREVIOUS_CLOSE"
    return "INSIDE_PREVIOUS_RANGE"


def analyze_market_structure(df: pd.DataFrame, latest_close, today_open, prev_high, prev_low, prev_close) -> dict:
    structure = detect_higher_highs_lows(df)
    gap = detect_gap(today_open, prev_close)
    location = detect_price_location(latest_close, prev_high, prev_low, prev_close)

    bullish_score = 0
    bearish_score = 0
    signals = []
    warnings = []

    if location == "BELOW_PREVIOUS_LOW":
        bearish_score += 10
        signals.append("Below previous day low")
    elif location == "ABOVE_PREVIOUS_HIGH":
        bullish_score += 10
        signals.append("Above previous day high")
    elif location in ["BELOW_PREVIOUS_CLOSE", "ABOVE_PREVIOUS_CLOSE"]:
        if location == "BELOW_PREVIOUS_CLOSE":
            bearish_score += 6
            signals.append("Below previous close")
        else:
            bullish_score += 6
            signals.append("Above previous close")
    else:
        signals.append(location)

    if structure == "BULLISH_STRUCTURE":
        bullish_score += 6
        signals.append("Bullish structure")
    elif structure == "BEARISH_STRUCTURE":
        bearish_score += 6
        signals.append("Bearish structure")
    else:
        warnings.append("Choppy structure")

    if gap == "GAP_DOWN":
        bearish_score += 4
        signals.append("Gap down")
    elif gap == "GAP_UP":
        bullish_score += 4
        signals.append("Gap up")
    else:
        signals.append("No gap")

    if structure == "BULLISH_STRUCTURE" and location == "BELOW_PREVIOUS_LOW":
        warnings.append("Structure/location conflict")
    if structure == "BEARISH_STRUCTURE" and location == "ABOVE_PREVIOUS_HIGH":
        warnings.append("Structure/location conflict")

    if bullish_score > bearish_score + 3:
        direction = "bullish"
    elif bearish_score > bullish_score + 3:
        direction = "bearish"
    else:
        direction = "neutral"

    score = bullish_score + bearish_score
    return AnalysisResult(
        engine="market_structure",
        direction=direction,
        score=min(score, 20),
        max_score=20,
        confidence=min(score / 20, 1),
        signals=signals,
        warnings=warnings,
        data={
            "structure": structure,
            "gap": gap,
            "location": location,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
        },
    ).to_dict()
