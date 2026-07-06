from datetime import datetime
from zoneinfo import ZoneInfo

from app.models.analysis_result import AnalysisResult

HIGH_IMPACT_KEYWORDS = [
    "CPI",
    "PPI",
    "PCE",
    "NFP",
    "NONFARM",
    "UNEMPLOYMENT",
    "JOLTS",
    "FOMC",
    "FED",
    "POWELL",
    "GDP",
    "ISM",
    "RETAIL SALES",
    "TREASURY AUCTION",
]


def analyze_news_risk(events=None) -> dict:
    """events should be optional list of dicts: [{"name": "CPI", "time": "2026-07-10 08:30:00", "impact": "HIGH"}]"""
    eastern = ZoneInfo("America/New_York")
    now = datetime.now(eastern)
    if not events:
        return AnalysisResult(
            engine="news",
            direction="neutral",
            score=5,
            max_score=5,
            confidence=1,
            signals=["No high-impact news events loaded"],
            warnings=["Economic calendar integration not connected yet"],
            data={"can_trade": True},
        ).to_dict()

    warnings = []
    signals = []
    can_trade = True
    score = 5
    for event in events:
        name = event.get("name", "").upper()
        event_time_raw = event.get("time")
        impact = event.get("impact", "").upper()
        is_high_impact = impact == "HIGH" or any(keyword in name for keyword in HIGH_IMPACT_KEYWORDS)
        if not is_high_impact:
            continue
        try:
            event_time = datetime.fromisoformat(event_time_raw)
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=eastern)
        except Exception:
            warnings.append(f"Unable to parse event time for {name}")
            continue

        minutes_until = abs((event_time - now).total_seconds()) / 60
        if minutes_until <= 15:
            can_trade = False
            score = 0
            warnings.append(f"High-impact event within 15 minutes: {name}")
        elif minutes_until <= 60:
            score = min(score, 2)
            warnings.append(f"High-impact event within 60 minutes: {name}")
        else:
            signals.append(f"High-impact event not immediate: {name}")

    return AnalysisResult(
        engine="news",
        direction="neutral",
        score=score,
        max_score=5,
        confidence=score / 5,
        signals=signals,
        warnings=warnings,
        data={"can_trade": can_trade},
    ).to_dict()
