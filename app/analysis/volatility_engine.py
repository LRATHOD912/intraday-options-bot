import pandas as pd

from app.models.analysis_result import AnalysisResult


def calculate_atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(period).mean()


def analyze_volatility(df: pd.DataFrame) -> dict:
    if df is None or df.empty or len(df) < 20:
        return AnalysisResult(
            engine="volatility",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0,
            warnings=["Not enough candles for volatility analysis"],
        ).to_dict()

    df = df.copy()
    df["atr"] = calculate_atr(df)
    latest = df.iloc[-1]
    atr = latest["atr"]
    close = latest["close"]
    score = 0
    signals = []
    warnings = []

    if pd.isna(atr) or close == 0:
        atr_percent = 0
    else:
        atr_percent = atr / close

    recent_range = (df["high"].tail(5).max() - df["low"].tail(5).min()) / close
    if atr_percent > 0.01:
        score += 5
        signals.append("High volatility")
    elif atr_percent > 0.004:
        score += 4
        signals.append("Normal tradeable volatility")
    else:
        score += 1
        warnings.append("Low volatility")

    if recent_range > atr_percent:
        score += 5
        signals.append("Range expansion detected")
    else:
        score += 2
        warnings.append("No strong range expansion")

    return AnalysisResult(
        engine="volatility",
        direction="neutral",
        score=min(score, 10),
        max_score=10,
        confidence=min(score / 10, 1),
        signals=signals,
        warnings=warnings,
        data={
            "atr": round(float(atr), 4) if not pd.isna(atr) else None,
            "atr_percent": round(float(atr_percent), 5),
            "recent_range": round(float(recent_range), 5),
        },
    ).to_dict()
