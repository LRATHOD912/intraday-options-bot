import pandas as pd

from app.models.analysis_result import AnalysisResult


def classify_last_candle(row):
    open_price = row["open"]
    high = row["high"]
    low = row["low"]
    close = row["close"]
    body = abs(close - open_price)
    candle_range = high - low
    if candle_range == 0:
        return "FLAT"

    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    body_percent = body / candle_range

    if body_percent < 0.15:
        return "DOJI"
    if close > open_price and body_percent > 0.65:
        return "BULLISH_MARUBOZU"
    if close < open_price and body_percent > 0.65:
        return "BEARISH_MARUBOZU"
    if lower_wick > body * 2 and upper_wick < body:
        return "HAMMER"
    if upper_wick > body * 2 and lower_wick < body:
        return "SHOOTING_STAR"
    if close > open_price:
        return "BULLISH_CANDLE"
    if close < open_price:
        return "BEARISH_CANDLE"
    return "UNKNOWN"


def detect_engulfing(df):
    if len(df) < 2:
        return None

    prev = df.iloc[-2]
    curr = df.iloc[-1]
    prev_body_low = min(prev["open"], prev["close"])
    prev_body_high = max(prev["open"], prev["close"])
    curr_body_low = min(curr["open"], curr["close"])
    curr_body_high = max(curr["open"], curr["close"])

    if curr["close"] > curr["open"] and curr_body_low <= prev_body_low and curr_body_high >= prev_body_high:
        return "BULLISH_ENGULFING"
    if curr["close"] < curr["open"] and curr_body_low <= prev_body_low and curr_body_high >= prev_body_high:
        return "BEARISH_ENGULFING"
    return None


def get_body_percent(row):
    candle_range = row["high"] - row["low"]
    if candle_range == 0:
        return 0.0
    body = abs(row["close"] - row["open"])
    return body / candle_range


def analyze_candles(df: pd.DataFrame) -> dict:
    if df is None or df.empty or len(df) < 3:
        return AnalysisResult(
            engine="candle",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0,
            warnings=["Not enough candles for candle analysis"],
        ).to_dict()

    latest = df.iloc[-1]
    candle_type = classify_last_candle(latest)
    body_percent = get_body_percent(latest)
    engulfing = detect_engulfing(df)
    score = 0
    signals = []
    warnings = []
    direction = "neutral"
    bullish_patterns = ["BULLISH_MARUBOZU", "HAMMER", "BULLISH_CANDLE", "BULLISH_ENGULFING"]
    bearish_patterns = ["BEARISH_MARUBOZU", "SHOOTING_STAR", "BEARISH_CANDLE", "BEARISH_ENGULFING"]
    pattern = engulfing if engulfing else candle_type

    if pattern in bullish_patterns:
        direction = "bullish"
        score += 7
        signals.append(f"Bullish candle pattern: {pattern}")
    elif pattern in bearish_patterns:
        direction = "bearish"
        score += 7
        signals.append(f"Bearish candle pattern: {pattern}")
    elif pattern == "DOJI":
        score += 2
        warnings.append("Doji candle indicates indecision")
    else:
        score += 3
        warnings.append(f"Neutral candle pattern: {pattern}")

    last_3 = df.tail(3)
    green_count = (last_3["close"] > last_3["open"]).sum()
    red_count = (last_3["close"] < last_3["open"]).sum()

    if engulfing == "BEARISH_ENGULFING" and green_count >= 2:
        direction = "neutral"
        score = min(score, 5)
        warnings.append("Candle conflict detected")
    elif engulfing == "BULLISH_ENGULFING" and red_count >= 2:
        direction = "neutral"
        score = min(score, 5)
        warnings.append("Candle conflict detected")
    elif green_count >= 2:
        score += 3
        signals.append("Most recent candles are bullish")
        if direction == "neutral":
            direction = "bullish"
    elif red_count >= 2:
        score += 3
        signals.append("Most recent candles are bearish")
        if direction == "neutral":
            direction = "bearish"

    return AnalysisResult(
        engine="candle",
        direction=direction,
        score=min(score, 10),
        max_score=10,
        confidence=min(score / 10, 1),
        signals=signals,
        warnings=warnings,
        data={
            "last_candle": candle_type,
            "body_percent": round(float(body_percent), 4),
            "engulfing": engulfing,
            "green_count_last_3": int(green_count),
            "red_count_last_3": int(red_count),
        },
    ).to_dict()
