from app.config import (
    REGIME_THRESHOLD_BREAKOUT,
    REGIME_THRESHOLD_CHOPPY,
    REGIME_THRESHOLD_COMPRESSION,
    REGIME_THRESHOLD_DEFAULT,
    REGIME_THRESHOLD_EXPANSION,
    REGIME_THRESHOLD_HIGH_VOLATILITY,
    REGIME_THRESHOLD_LOW_VOLATILITY,
    REGIME_THRESHOLD_POWER_TREND,
    REGIME_THRESHOLD_RANGE,
    REGIME_THRESHOLD_REVERSAL,
    REGIME_THRESHOLD_TREND_DOWN,
    REGIME_THRESHOLD_TREND_UP,
)


_THRESHOLD_MAP = {
    "TREND_UP": REGIME_THRESHOLD_TREND_UP,
    "TREND_DOWN": REGIME_THRESHOLD_TREND_DOWN,
    "POWER_TREND": REGIME_THRESHOLD_POWER_TREND,
    "BREAKOUT": REGIME_THRESHOLD_BREAKOUT,
    "EXPANSION": REGIME_THRESHOLD_EXPANSION,
    "REVERSAL": REGIME_THRESHOLD_REVERSAL,
    "RANGE": REGIME_THRESHOLD_RANGE,
    "CHOPPY": REGIME_THRESHOLD_CHOPPY,
    "LOW_VOLATILITY": REGIME_THRESHOLD_LOW_VOLATILITY,
    "HIGH_VOLATILITY": REGIME_THRESHOLD_HIGH_VOLATILITY,
    "COMPRESSION": REGIME_THRESHOLD_COMPRESSION,
}


_RISK_MULTIPLIER_MAP = {
    "TREND_UP": 1.0,
    "TREND_DOWN": 1.0,
    "POWER_TREND": 1.2,
    "BREAKOUT": 1.1,
    "EXPANSION": 1.1,
    "REVERSAL": 0.7,
    "RANGE": 0.6,
    "CHOPPY": 0.5,
    "LOW_VOLATILITY": 0.4,
    "HIGH_VOLATILITY": 0.7,
    "COMPRESSION": 0.4,
}


_NOTE_MAP = {
    "CHOPPY": "Reduced threshold, reduced size, quick exits only",
    "LOW_VOLATILITY": "Stricter threshold because premium movement may be weak",
    "POWER_TREND": "Higher size allowed only if risk checks pass",
    "REVERSAL": "Lower threshold with conservative size and confirmation needed",
    "RANGE": "Lower threshold with reduced size and faster exits",
    "COMPRESSION": "Stricter threshold until breakout confirms",
    "BREAKOUT": "Moderate threshold with momentum confirmation",
    "EXPANSION": "Moderate threshold with controlled risk scaling",
    "HIGH_VOLATILITY": "Moderate threshold with reduced size due to volatility",
    "TREND_UP": "Standard trend threshold and standard sizing",
    "TREND_DOWN": "Standard trend threshold and standard sizing",
}


def get_entry_quality_threshold(regime: str) -> int:
    regime_key = str(regime or "").upper().strip()
    return int(_THRESHOLD_MAP.get(regime_key, REGIME_THRESHOLD_DEFAULT))


def get_regime_risk_multiplier(regime: str) -> float:
    regime_key = str(regime or "").upper().strip()
    return float(_RISK_MULTIPLIER_MAP.get(regime_key, 1.0))


def get_regime_notes(regime: str) -> str:
    regime_key = str(regime or "").upper().strip()
    return _NOTE_MAP.get(regime_key, "Standard regime controls")
