import pandas as pd

from app.models.analysis_result import AnalysisResult


def analyze_trend(df: pd.DataFrame) -> dict:
    if df is None or df.empty or len(df) < 50:
        return AnalysisResult(
            engine="trend",
            direction="neutral",
            score=0,
            max_score=15,
            confidence=0,
            warnings=["Not enough candles for trend analysis"],
        ).to_dict()

    latest = df.iloc[-1]
    signals = []
    warnings = []
    score = 0
    close = latest["close"]
    vwap = latest.get("vwap")
    ema_9 = latest.get("ema_9")
    ema_20 = latest.get("ema_20")
    bullish = 0
    bearish = 0

    if vwap is not None:
        if close > vwap:
            bullish += 1
            score += 4
            signals.append("Price above VWAP")
        else:
            bearish += 1
            score += 4
            signals.append("Price below VWAP")

    if ema_9 is not None and ema_20 is not None:
        if ema_9 > ema_20:
            bullish += 1
            score += 4
            signals.append("EMA 9 above EMA 20")
        else:
            bearish += 1
            score += 4
            signals.append("EMA 9 below EMA 20")

    recent = df.tail(10)
    if recent["close"].iloc[-1] > recent["close"].iloc[0]:
        bullish += 1
        score += 3
        signals.append("Recent price trend is rising")
    else:
        bearish += 1
        score += 3
        signals.append("Recent price trend is falling")

    if recent["high"].iloc[-1] > recent["high"].iloc[0] and recent["low"].iloc[-1] > recent["low"].iloc[0]:
        bullish += 1
        score += 2
        signals.append("Higher high and higher low detected")
    if recent["high"].iloc[-1] < recent["high"].iloc[0] and recent["low"].iloc[-1] < recent["low"].iloc[0]:
        bearish += 1
        score += 2
        signals.append("Lower high and lower low detected")

    structure_bullish = recent["high"].iloc[-1] > recent["high"].iloc[0] and recent["low"].iloc[-1] > recent["low"].iloc[0]
    structure_bearish = recent["high"].iloc[-1] < recent["high"].iloc[0] and recent["low"].iloc[-1] < recent["low"].iloc[0]
    vwap_bias = "bullish" if close > vwap else "bearish" if vwap is not None and close < vwap else "neutral"
    ema_bias = "bullish" if ema_9 is not None and ema_20 is not None and ema_9 > ema_20 else "bearish" if ema_9 is not None and ema_20 is not None and ema_9 < ema_20 else "neutral"
    vwap_distance_percent = ((close - vwap) / vwap) if vwap not in (None, 0) else 0

    if vwap_bias != "neutral" and ema_bias != "neutral" and vwap_bias != ema_bias:
        warnings.append("VWAP and EMA disagree")
        score = max(0, score - 3)

    if abs(bullish - bearish) <= 1:
        direction = "neutral"
        warnings.append("Mixed trend signals")
    elif close < vwap and ema_bias == "bullish":
        if recent["close"].iloc[-1] > recent["close"].iloc[0] and structure_bullish and abs(vwap_distance_percent) <= 0.002:
            direction = "bullish"
        else:
            direction = "neutral"
            warnings.append("Trend conflict: price below VWAP")
    elif close > vwap and ema_bias == "bearish":
        if recent["close"].iloc[-1] < recent["close"].iloc[0] and structure_bearish and abs(vwap_distance_percent) <= 0.002:
            direction = "bearish"
        else:
            direction = "neutral"
            warnings.append("Trend conflict: price above VWAP")
    elif bullish > bearish:
        direction = "bullish"
    else:
        direction = "bearish"

    confidence = min(score / 15, 1)
    return AnalysisResult(
        engine="trend",
        direction=direction,
        score=min(score, 15),
        max_score=15,
        confidence=confidence,
        signals=signals,
        warnings=warnings,
        data={
            "close": float(close),
            "vwap": float(vwap) if vwap is not None else None,
            "ema_9": float(ema_9) if ema_9 is not None else None,
            "ema_20": float(ema_20) if ema_20 is not None else None,
            "vwap_distance_percent": round(float(vwap_distance_percent), 6),
        },
    ).to_dict()
