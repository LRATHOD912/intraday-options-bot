import pandas as pd

from app.models.analysis_result import AnalysisResult


def analyze_regime(df: pd.DataFrame, opening_range_result=None, volume_result=None, candle_result=None, vix_price=None, news_result=None) -> dict:
    if df is None or df.empty or len(df) < 20:
        return AnalysisResult(
            engine="regime",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0,
            warnings=["Not enough candles for regime analysis"],
            data={"regime": "CHOPPY"},
        ).to_dict()

    latest = df.iloc[-1]
    ema_9 = float(latest.get("ema_9", latest.get("close", 0.0)))
    ema_20 = float(latest.get("ema_20", latest.get("close", 0.0)))
    close = float(latest.get("close", 0.0))
    vwap = float(latest.get("vwap", close)) if latest.get("vwap") is not None else close

    atr_percent = 0.0
    if "atr" in df.columns:
        atr = df["atr"].iloc[-1]
        if pd.notna(atr) and close > 0:
            atr_percent = float(atr) / close

    body_percent = 0.0
    if candle_result:
        body_percent = float(candle_result.get("data", {}).get("body_percent", 0.0) or 0.0)

    rvol = 0.0
    if volume_result:
        rvol = float(volume_result.get("data", {}).get("rvol", 0.0) or 0.0)

    recent_high = float(df["high"].tail(20).max())
    recent_low = float(df["low"].tail(20).min())
    recent_range_percent = (recent_high - recent_low) / close if close > 0 else 0.0

    opening_dir = (opening_range_result or {}).get("direction", "neutral")
    news_block = bool((news_result or {}).get("data", {}).get("can_trade") is False)

    regime = "RANGE"
    direction = "neutral"
    signals = []
    warnings = []
    score = 5.0

    ema_gap_percent = abs(ema_9 - ema_20) / close if close > 0 else 0.0
    price_vs_vwap = (close - vwap) / close if close > 0 else 0.0

    if news_block:
        warnings.append("News risk regime")
        regime = "HIGH_VOLATILITY"
        score = 2.0
    elif atr_percent <= 0.0035 and recent_range_percent <= 0.009:
        regime = "COMPRESSION"
        warnings.append("Price compression")
        score = 3.0
    elif atr_percent <= 0.0055:
        regime = "LOW_VOLATILITY"
        warnings.append("Low volatility")
        score = 4.0
    elif atr_percent >= 0.014 or recent_range_percent >= 0.022:
        regime = "HIGH_VOLATILITY"
        warnings.append("High volatility")
        score = 6.0

    bullish_trend = close > vwap and ema_9 > ema_20 and body_percent >= 0.45 and rvol >= 1.2
    bearish_trend = close < vwap and ema_9 < ema_20 and body_percent >= 0.45 and rvol >= 1.2

    bullish_breakout = close >= recent_high * 0.998 and opening_dir == "bullish" and rvol >= 1.25
    bearish_breakdown = close <= recent_low * 1.002 and opening_dir == "bearish" and rvol >= 1.25
    bullish_reversal = ema_9 < ema_20 and close > vwap and opening_dir == "bullish" and body_percent >= 0.5
    bearish_reversal = ema_9 > ema_20 and close < vwap and opening_dir == "bearish" and body_percent >= 0.5

    if regime in ["COMPRESSION", "LOW_VOLATILITY", "RANGE"]:
        if bullish_reversal or bearish_reversal:
            regime = "REVERSAL"
            direction = "bullish" if bullish_reversal else "bearish"
            signals.append("Potential reversal structure")
            score = max(score, 6.5)
        elif bullish_breakout or bearish_breakdown:
            regime = "BREAKOUT"
            direction = "bullish" if bullish_breakout else "bearish"
            signals.append("Breakout from recent range")
            score = max(score, 7.0)
        elif bullish_trend:
            regime = "TREND_UP"
            direction = "bullish"
            signals.append("EMA/VWAP bullish trend")
            score = max(score, 7.5)
        elif bearish_trend:
            regime = "TREND_DOWN"
            direction = "bearish"
            signals.append("EMA/VWAP bearish trend")
            score = max(score, 7.5)
        elif regime == "COMPRESSION":
            regime = "CHOPPY"
            warnings.append("No clean directional structure")
            score = min(score, 3.5)

    if regime in ["TREND_UP", "TREND_DOWN", "BREAKOUT"] and (atr_percent >= 0.011 or recent_range_percent >= 0.018):
        regime = "EXPANSION"
        score = max(score, 8.0)
        signals.append("Volatility expansion")

    if regime in ["TREND_UP", "TREND_DOWN"] and ema_gap_percent >= 0.004 and rvol >= 1.8 and body_percent >= 0.55:
        regime = "POWER_TREND"
        score = max(score, 9.0)
        signals.append("Strong directional continuation")
        direction = "bullish" if price_vs_vwap >= 0 else "bearish"

    if vix_price is not None:
        try:
            vix_value = float(vix_price)
            if vix_value > 30:
                warnings.append("VIX proxy elevated")
                if regime not in ["HIGH_VOLATILITY", "EXPANSION", "POWER_TREND"]:
                    regime = "HIGH_VOLATILITY"
        except (TypeError, ValueError):
            pass

    confidence = min(max(score / 10.0, 0.0), 1.0)
    return AnalysisResult(
        engine="regime",
        direction=direction,
        score=score,
        max_score=10,
        confidence=confidence,
        signals=signals,
        warnings=warnings,
        data={
            "regime": regime,
            "ema_gap_percent": round(float(ema_gap_percent), 5),
            "price_vs_vwap": round(float(price_vs_vwap), 5),
            "atr_percent": round(float(atr_percent), 5),
            "recent_range_percent": round(float(recent_range_percent), 5),
            "rvol": round(float(rvol), 4),
            "body_percent": round(float(body_percent), 4),
        },
    ).to_dict()
