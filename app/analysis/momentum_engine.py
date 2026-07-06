import pandas as pd

from app.models.analysis_result import AnalysisResult


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def analyze_momentum(df: pd.DataFrame) -> dict:
    if df is None or df.empty or len(df) < 30:
        return AnalysisResult(
            engine="momentum",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0,
            warnings=["Not enough candles for momentum analysis"],
        ).to_dict()

    df = df.copy()
    df["rsi"] = calculate_rsi(df["close"])
    df["roc"] = df["close"].pct_change(periods=5)
    latest = df.iloc[-1]
    rsi = latest["rsi"]
    roc = latest["roc"]
    score = 0
    signals = []
    warnings = []

    if pd.isna(rsi):
        rsi = 50
    if pd.isna(roc):
        roc = 0

    bullish = 0
    bearish = 0
    if 55 <= rsi <= 70:
        bullish += 1
        score += 4
        signals.append("RSI bullish but not overbought")
    elif rsi > 70:
        bullish += 1
        score += 2
        warnings.append("RSI overbought")
    elif 30 <= rsi <= 45:
        bearish += 1
        score += 4
        signals.append("RSI bearish but not oversold")
    elif rsi < 30:
        bearish += 1
        score += 2
        warnings.append("RSI oversold")
    else:
        score += 2
        signals.append("RSI neutral")

    if roc > 0:
        bullish += 1
        score += 3
        signals.append("Positive rate of change")
    elif roc < 0:
        bearish += 1
        score += 3
        signals.append("Negative rate of change")

    last_3 = df["close"].tail(3)
    if last_3.iloc[-1] > last_3.iloc[0]:
        bullish += 1
        score += 3
        signals.append("Short-term momentum rising")
    elif last_3.iloc[-1] < last_3.iloc[0]:
        bearish += 1
        score += 3
        signals.append("Short-term momentum falling")

    if roc > 0 and last_3.iloc[-1] < last_3.iloc[0]:
        direction = "neutral"
        warnings.append("Momentum conflict detected")
    elif roc < 0 and last_3.iloc[-1] > last_3.iloc[0]:
        direction = "neutral"
        warnings.append("Momentum conflict detected")
    elif bullish > bearish:
        direction = "bullish"
    elif bearish > bullish:
        direction = "bearish"
    else:
        direction = "neutral"

    return AnalysisResult(
        engine="momentum",
        direction=direction,
        score=min(score, 10),
        max_score=10,
        confidence=min(score / 10, 1),
        signals=signals,
        warnings=warnings,
        data={
            "rsi": round(float(rsi), 2),
            "roc": round(float(roc), 5),
        },
    ).to_dict()
