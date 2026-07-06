from datetime import time

import pandas as pd

from app.models.analysis_result import AnalysisResult


def _ensure_et_timestamps(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty or "timestamp" not in df.columns:
        return pd.Series(dtype="datetime64[ns, America/New_York]")

    timestamps = pd.to_datetime(df["timestamp"], errors="coerce")
    if timestamps.empty:
        return pd.Series(dtype="datetime64[ns, America/New_York]")

    if getattr(timestamps.dt, "tz", None) is None:
        timestamps = timestamps.dt.tz_localize("America/New_York")
    else:
        timestamps = timestamps.dt.tz_convert("America/New_York")

    return timestamps


def analyze_opening_range(df: pd.DataFrame) -> dict:
    if df is None or df.empty or "timestamp" not in df.columns:
        return AnalysisResult(
            engine="opening_range",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0.0,
            signals=[],
            warnings=["No timestamp column available"],
            data={
                "opening_high": None,
                "opening_low": None,
                "opening_mid": None,
                "latest_close": None,
                "latest_high": None,
                "latest_low": None,
                "bullish_score": 0,
                "bearish_score": 0,
            },
        ).to_dict()

    ts_et = _ensure_et_timestamps(df)
    df = df.copy()
    df["timestamp_et"] = ts_et
    df = df.dropna(subset=["timestamp_et"])

    if df.empty:
        return AnalysisResult(
            engine="opening_range",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0.0,
            signals=[],
            warnings=["No valid timestamp data"],
            data={
                "opening_high": None,
                "opening_low": None,
                "opening_mid": None,
                "latest_close": None,
                "latest_high": None,
                "latest_low": None,
                "bullish_score": 0,
                "bearish_score": 0,
            },
        ).to_dict()

    latest_date = df["timestamp_et"].dt.normalize().max().date()
    daily_df = df[df["timestamp_et"].dt.normalize() == pd.Timestamp(latest_date, tz="America/New_York")]

    if daily_df.empty:
        return AnalysisResult(
            engine="opening_range",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0.0,
            signals=[],
            warnings=["No data for latest trading date"],
            data={
                "opening_high": None,
                "opening_low": None,
                "opening_mid": None,
                "latest_close": None,
                "latest_high": None,
                "latest_low": None,
                "bullish_score": 0,
                "bearish_score": 0,
            },
        ).to_dict()

    opening_range_df = daily_df[
        (daily_df["timestamp_et"].dt.time >= time(9, 30))
        & (daily_df["timestamp_et"].dt.time <= time(9, 45))
    ]

    latest_row = daily_df.iloc[-1]

    if opening_range_df.empty:
        return AnalysisResult(
            engine="opening_range",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0.0,
            signals=[],
            warnings=["No opening range exists for latest trading date"],
            data={
                "opening_high": None,
                "opening_low": None,
                "opening_mid": None,
                "latest_close": float(latest_row["close"]),
                "latest_high": float(latest_row["high"]),
                "latest_low": float(latest_row["low"]),
                "bullish_score": 0,
                "bearish_score": 0,
            },
        ).to_dict()

    opening_high = float(opening_range_df["high"].max())
    opening_low = float(opening_range_df["low"].min())
    opening_mid = (opening_high + opening_low) / 2

    latest_close = float(latest_row["close"])
    latest_high = float(latest_row["high"])
    latest_low = float(latest_row["low"])

    bullish_score = 0
    bearish_score = 0
    signals = []
    warnings = []

    if latest_close > opening_high:
        bullish_score += 7
        signals.append("Close above opening range high")
    elif latest_close < opening_low:
        bearish_score += 7
        signals.append("Close below opening range low")
    elif latest_high > opening_high and latest_close < opening_high:
        bearish_score += 5
        signals.append("Failed breakout above opening range")
    elif latest_low < opening_low and latest_close > opening_low:
        bullish_score += 5
        signals.append("Failed breakdown below opening range")
    else:
        signals.append("Price inside opening range")
        warnings.append("Price inside opening range")
        score = 2
        return AnalysisResult(
            engine="opening_range",
            direction="neutral",
            score=score,
            max_score=10,
            confidence=0.2,
            signals=signals,
            warnings=warnings,
            data={
                "opening_high": opening_high,
                "opening_low": opening_low,
                "opening_mid": opening_mid,
                "latest_close": latest_close,
                "latest_high": latest_high,
                "latest_low": latest_low,
                "bullish_score": 0,
                "bearish_score": 0,
            },
        ).to_dict()

    if bullish_score > bearish_score + 2:
        direction = "bullish"
    elif bearish_score > bullish_score + 2:
        direction = "bearish"
    else:
        direction = "neutral"

    score = min(bullish_score + bearish_score, 10)
    return AnalysisResult(
        engine="opening_range",
        direction=direction,
        score=score,
        max_score=10,
        confidence=min(score / 10, 1),
        signals=signals,
        warnings=warnings,
        data={
            "opening_high": opening_high,
            "opening_low": opening_low,
            "opening_mid": opening_mid,
            "latest_close": latest_close,
            "latest_high": latest_high,
            "latest_low": latest_low,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
        },
    ).to_dict()
