from datetime import datetime

import pandas as pd

from app.models.analysis_result import AnalysisResult


def analyze_gap_fill(df: pd.DataFrame, prev_close: float) -> dict:
    if df is None or df.empty or "timestamp" not in df.columns:
        return AnalysisResult(
            engine="gap_fill",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0.0,
            signals=[],
            warnings=["Missing required timestamp data"],
            data={
                "today_open": None,
                "prev_close": prev_close,
                "latest_close": None,
                "gap_percent": None,
                "gap_type": "NO_GAP",
                "bullish_score": 0,
                "bearish_score": 0,
            },
        ).to_dict()

    if prev_close is None:
        return AnalysisResult(
            engine="gap_fill",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0.0,
            signals=[],
            warnings=["Previous close unavailable"],
            data={
                "today_open": None,
                "prev_close": None,
                "latest_close": None,
                "gap_percent": None,
                "gap_type": "NO_GAP",
                "bullish_score": 0,
                "bearish_score": 0,
            },
        ).to_dict()

    df = df.copy()
    if df["timestamp"].dtype != "datetime64[ns, America/New_York]":
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        if getattr(df["timestamp"].dt, "tz", None) is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize("America/New_York")
        else:
            df["timestamp"] = df["timestamp"].dt.tz_convert("America/New_York")

    df = df.dropna(subset=["timestamp"])
    if df.empty:
        return AnalysisResult(
            engine="gap_fill",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0.0,
            signals=[],
            warnings=["No valid timestamps"],
            data={
                "today_open": None,
                "prev_close": prev_close,
                "latest_close": None,
                "gap_percent": None,
                "gap_type": "NO_GAP",
                "bullish_score": 0,
                "bearish_score": 0,
            },
        ).to_dict()

    latest_date = df["timestamp"].dt.normalize().max().date()
    daily_df = df[df["timestamp"].dt.normalize() == pd.Timestamp(latest_date, tz="America/New_York")]
    if daily_df.empty:
        return AnalysisResult(
            engine="gap_fill",
            direction="neutral",
            score=0,
            max_score=10,
            confidence=0.0,
            signals=[],
            warnings=["No data for latest trading date"],
            data={
                "today_open": None,
                "prev_close": prev_close,
                "latest_close": None,
                "gap_percent": None,
                "gap_type": "NO_GAP",
                "bullish_score": 0,
                "bearish_score": 0,
            },
        ).to_dict()

    today_open = float(daily_df.iloc[0]["open"])
    latest_close = float(daily_df.iloc[-1]["close"])
    gap_percent = (today_open - prev_close) / prev_close

    bullish_score = 0
    bearish_score = 0
    signals = []
    warnings = []

    if abs(gap_percent) < 0.003:
        direction = "neutral"
        score = 2
        signals.append("No meaningful gap")
        return AnalysisResult(
            engine="gap_fill",
            direction=direction,
            score=score,
            max_score=10,
            confidence=0.2,
            signals=signals,
            warnings=warnings,
            data={
                "today_open": today_open,
                "prev_close": prev_close,
                "latest_close": latest_close,
                "gap_percent": round(gap_percent, 6),
                "gap_type": "NO_GAP",
                "bullish_score": bullish_score,
                "bearish_score": bearish_score,
            },
        ).to_dict()

    if gap_percent >= 0.003:
        gap_type = "GAP_UP"
        if latest_close > today_open:
            bullish_score += 6
            signals.append("Gap up holding and extending")
        elif latest_close < today_open and latest_close > prev_close:
            signals.append("Gap up partially filling")
            warnings.append("Gap up partially filling")
            bullish_score += 0
            bearish_score += 0
        elif latest_close <= prev_close:
            bearish_score += 8
            signals.append("Gap up fully filled")
        else:
            signals.append("Gap up stable")
    elif gap_percent <= -0.003:
        gap_type = "GAP_DOWN"
        if latest_close < today_open:
            bearish_score += 6
            signals.append("Gap down holding and extending")
        elif latest_close > today_open and latest_close < prev_close:
            signals.append("Gap down partially filling")
            warnings.append("Gap down partially filling")
            bullish_score += 0
            bearish_score += 0
        elif latest_close >= prev_close:
            bullish_score += 8
            signals.append("Gap down fully filled")
        else:
            signals.append("Gap down stable")
    else:
        gap_type = "NO_GAP"

    if bullish_score > bearish_score + 2:
        direction = "bullish"
    elif bearish_score > bullish_score + 2:
        direction = "bearish"
    else:
        direction = "neutral"

    score = min(bullish_score + bearish_score, 10)
    return AnalysisResult(
        engine="gap_fill",
        direction=direction,
        score=score,
        max_score=10,
        confidence=min(score / 10, 1),
        signals=signals,
        warnings=warnings,
        data={
            "today_open": today_open,
            "prev_close": prev_close,
            "latest_close": latest_close,
            "gap_percent": round(gap_percent, 6),
            "gap_type": gap_type,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
        },
    ).to_dict()
