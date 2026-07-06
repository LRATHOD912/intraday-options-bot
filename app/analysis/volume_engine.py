import pandas as pd

from app.models.analysis_result import AnalysisResult


def analyze_volume(df: pd.DataFrame) -> dict:
    if df is None or df.empty or len(df) < 20:
        return AnalysisResult(
            engine="volume",
            direction="neutral",
            score=0,
            max_score=15,
            confidence=0,
            warnings=["Not enough candles for volume analysis"],
        ).to_dict()

    df = df.copy()
    df["avg_volume_20"] = df["volume"].rolling(20).mean()
    latest = df.iloc[-1]
    avg_volume = latest["avg_volume_20"]
    current_volume = latest["volume"]
    score = 0
    signals = []
    warnings = []

    if avg_volume == 0 or pd.isna(avg_volume):
        rvol = 0
    else:
        rvol = current_volume / avg_volume

    latest_close = latest["close"]
    latest_open = latest["open"]
    if rvol >= 2:
        score += 7
        signals.append("Strong relative volume")
    elif rvol >= 1.2:
        score += 5
        signals.append("Good relative volume")
    elif rvol >= 0.8:
        score += 3
        signals.append("Normal volume")
    else:
        score += 1
        warnings.append("Weak volume")

    if latest_close > latest_open:
        direction = "bullish"
        score += 5
        signals.append("Buying candle on volume")
    elif latest_close < latest_open:
        direction = "bearish"
        score += 5
        signals.append("Selling candle on volume")
    else:
        direction = "neutral"
        score += 2
        warnings.append("Doji/flat candle")

    recent_volume = df["volume"].tail(5).mean()
    older_volume = df["volume"].tail(20).head(15).mean()
    if older_volume and recent_volume > older_volume:
        score += 3
        signals.append("Volume expanding")
    else:
        warnings.append("Volume not expanding")

    return AnalysisResult(
        engine="volume",
        direction=direction,
        score=min(score, 15),
        max_score=15,
        confidence=min(score / 15, 1),
        signals=signals,
        warnings=warnings,
        data={
            "current_volume": float(current_volume),
            "avg_volume_20": round(float(avg_volume), 2) if not pd.isna(avg_volume) else None,
            "rvol": round(float(rvol), 2),
        },
    ).to_dict()
