import pandas as pd

from app.models.analysis_result import AnalysisResult


def find_recent_support_resistance(df, lookback=50):
    if df is None or df.empty:
        return None, None
    recent = df.tail(lookback)
    support = recent["low"].min()
    resistance = recent["high"].max()
    return support, resistance


def detect_liquidity_sweep(df, prev_high=None, prev_low=None):
    if df is None or df.empty or len(df) < 2:
        return "NONE"

    latest = df.iloc[-1]
    if prev_low is not None and latest["low"] < prev_low and latest["close"] > prev_low:
        return "BULLISH_SWEEP"
    if prev_high is not None and latest["high"] > prev_high and latest["close"] < prev_high:
        return "BEARISH_SWEEP"
    return "NONE"


def analyze_support_resistance(df, latest_close, prev_high=None, prev_low=None):
    support, resistance = find_recent_support_resistance(df)
    sweep = detect_liquidity_sweep(df, prev_high, prev_low)

    bullish_score = 0
    bearish_score = 0
    signals = []
    warnings = []

    if support is not None and resistance is not None:
        if support > 0:
            support_distance = abs(latest_close - support) / support
            resistance_distance = abs(latest_close - resistance) / resistance
        else:
            support_distance = 0
            resistance_distance = 0

        if support_distance <= 0.0015:
            bullish_score += 4
            signals.append("Near support")
        elif latest_close < support:
            bearish_score += 5
            signals.append("Below support")

        if resistance_distance <= 0.0015:
            bearish_score += 4
            signals.append("Near resistance")
        elif latest_close > resistance:
            bullish_score += 5
            signals.append("Above resistance")

    if sweep == "BULLISH_SWEEP":
        bullish_score += 5
        signals.append("Bullish liquidity sweep")
    elif sweep == "BEARISH_SWEEP":
        bearish_score += 5
        signals.append("Bearish liquidity sweep")

    if bullish_score > bearish_score + 2:
        direction = "bullish"
    elif bearish_score > bullish_score + 2:
        direction = "bearish"
    else:
        direction = "neutral"

    score = bullish_score + bearish_score
    return AnalysisResult(
        engine="support_resistance",
        direction=direction,
        score=min(score, 10),
        max_score=10,
        confidence=min(score / 10, 1),
        signals=signals,
        warnings=warnings,
        data={
            "support": float(support) if support is not None else None,
            "resistance": float(resistance) if resistance is not None else None,
            "prev_high": float(prev_high) if prev_high is not None else None,
            "prev_low": float(prev_low) if prev_low is not None else None,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
        },
    ).to_dict()
