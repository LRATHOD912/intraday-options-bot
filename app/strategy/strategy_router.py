from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Optional

from app.config import (
    ALLOW_0DTE_FOR_RANGE_SCALP,
    ENABLE_GAP_AND_GO,
    ENABLE_GAP_FILL_REVERSAL,
    ENABLE_MEAN_REVERSION_0DTE,
    ENABLE_MOMENTUM_BREAKOUT,
    ENABLE_MOMENTUM_RUNNER,
    ENABLE_OPENING_RANGE_BREAKOUT,
    ENABLE_RANGE_SCALP_0DTE,
    ENABLE_TREND_PULLBACK,
    ENABLE_VWAP_BOUNCE,
    MEAN_REVERSION_MAX_HOLD_MINUTES,
    MOMENTUM_BREAKOUT_MAX_HOLD_MINUTES,
    RANGE_SCALP_MAX_HOLD_MINUTES,
    VWAP_BOUNCE_MAX_HOLD_MINUTES,
)
from app.risk.regime_thresholds import get_entry_quality_threshold


STRATEGIES = {
    "MOMENTUM_BREAKOUT",
    "TREND_PULLBACK",
    "VWAP_BOUNCE",
    "OPENING_RANGE_BREAKOUT",
    "GAP_AND_GO",
    "GAP_FILL_REVERSAL",
    "RANGE_SCALP_0DTE",
    "MEAN_REVERSION_0DTE",
    "NO_TRADE",
}


@dataclass(frozen=True)
class StrategyRoute:
    strategy_name: str
    direction: str
    confidence: float
    reason: str
    required_exit_profile: str
    recommended_expiry_type: str
    risk_multiplier: float
    max_hold_minutes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "direction": self.direction,
            "confidence": round(float(self.confidence), 4),
            "reason": self.reason,
            "required_exit_profile": self.required_exit_profile,
            "recommended_expiry_type": self.recommended_expiry_type,
            "risk_multiplier": round(float(self.risk_multiplier), 4),
            "max_hold_minutes": int(self.max_hold_minutes),
        }


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_regime_name(regime_result: Optional[dict]) -> str:
    if not isinstance(regime_result, dict):
        return "CHOPPY"
    return str(regime_result.get("data", {}).get("regime", regime_result.get("regime", "CHOPPY")))


def _get_score(master_score: Optional[dict]) -> float:
    if not isinstance(master_score, dict):
        return 0.0
    return float(master_score.get("total_score", master_score.get("score", 0.0)) or 0.0)


def _get_direction_result(result: Optional[dict]) -> str:
    if not isinstance(result, dict):
        return "neutral"
    return str(result.get("direction", "neutral"))


def _near(value: Optional[float], level: Optional[float], pct: float = 0.0025) -> bool:
    if value is None or level in [None, 0]:
        return False
    return abs(float(value) - float(level)) / abs(float(level)) <= pct


def _flat(vwap_distance: Optional[float], threshold: float = 0.0015) -> bool:
    if vwap_distance is None:
        return False
    return abs(float(vwap_distance)) <= threshold


def _liquidity_ok(option_spread_percent: Optional[float], option_liquidity_score: Optional[float]) -> bool:
    spread_ok = option_spread_percent is None or float(option_spread_percent) <= 0.08
    liquidity_ok = option_liquidity_score is None or float(option_liquidity_score) >= 0.45
    return spread_ok and liquidity_ok


def _is_time_between(current_time_et: Optional[datetime], start: time, end: time) -> bool:
    if current_time_et is None:
        return False
    current_time = current_time_et.time() if hasattr(current_time_et, "time") else current_time_et
    if not isinstance(current_time, time):
        return False
    return start <= current_time <= end


def _route(
    strategy_name: str,
    direction: str,
    confidence: float,
    reason: str,
    required_exit_profile: str,
    recommended_expiry_type: str,
    risk_multiplier: float,
    max_hold_minutes: int,
) -> StrategyRoute:
    return StrategyRoute(
        strategy_name=strategy_name,
        direction=direction,
        confidence=max(0.0, min(float(confidence), 1.0)),
        reason=reason,
        required_exit_profile=required_exit_profile,
        recommended_expiry_type=recommended_expiry_type,
        risk_multiplier=risk_multiplier,
        max_hold_minutes=max_hold_minutes,
    )


def route_strategy(
    *,
    regime_result: Optional[dict],
    master_score: Optional[dict],
    vwap_distance_percent: Optional[float] = None,
    ema_9: Optional[float] = None,
    ema_20: Optional[float] = None,
    latest_close: Optional[float] = None,
    opening_high: Optional[float] = None,
    opening_low: Optional[float] = None,
    prev_day_high: Optional[float] = None,
    prev_day_low: Optional[float] = None,
    support_level: Optional[float] = None,
    resistance_level: Optional[float] = None,
    atr_percent: Optional[float] = None,
    rvol: Optional[float] = None,
    candle_body_percent: Optional[float] = None,
    momentum_direction: Optional[str] = None,
    gap_direction: Optional[str] = None,
    opening_range_result: Optional[dict] = None,
    trend_result: Optional[dict] = None,
    volume_result: Optional[dict] = None,
    candle_result: Optional[dict] = None,
    support_resistance_result: Optional[dict] = None,
    current_time_et: Optional[datetime] = None,
    option_spread_percent: Optional[float] = None,
    option_liquidity_score: Optional[float] = None,
    option_premium: Optional[float] = None,
    gap_percent: Optional[float] = None,
    gap_fill_direction: Optional[str] = None,
    price_near_support: Optional[bool] = None,
    price_near_resistance: Optional[bool] = None,
    entry_quality_score: Optional[float] = None,
) -> dict[str, Any]:
    score = _get_score(master_score)
    regime_name = _get_regime_name(regime_result)
    trend_direction = _get_direction_result(trend_result)
    volume_direction = _get_direction_result(volume_result)
    candle_direction = _get_direction_result(candle_result)
    opening_range_direction = _get_direction_result(opening_range_result)
    support_resistance_direction = _get_direction_result(support_resistance_result)
    momentum_direction = str(momentum_direction or "neutral")
    gap_direction = str(gap_direction or "neutral")
    gap_fill_direction = str(gap_fill_direction or "neutral")
    close_to_open_range_high = _near(latest_close, opening_high)
    close_to_open_range_low = _near(latest_close, opening_low)
    ema_bullish = ema_9 is not None and ema_20 is not None and float(ema_9) > float(ema_20)
    ema_bearish = ema_9 is not None and ema_20 is not None and float(ema_9) < float(ema_20)
    spread_liquidity_ok = _liquidity_ok(option_spread_percent, option_liquidity_score)
    very_tight_spread = option_spread_percent is None or float(option_spread_percent) <= 0.04
    resolved_entry_quality = _to_float(entry_quality_score)

    if not spread_liquidity_ok:
        return _route(
            "NO_TRADE",
            "NO_TRADE",
            confidence=0.0,
            reason="Option spread or liquidity failed router gate",
            required_exit_profile="baseline",
            recommended_expiry_type="none",
            risk_multiplier=0.0,
            max_hold_minutes=0,
        ).to_dict()

    if score < 50:
        return _route(
            "NO_TRADE",
            "NO_TRADE",
            confidence=min(score / 100.0, 0.5),
            reason="Master score below routing threshold",
            required_exit_profile="baseline",
            recommended_expiry_type="none",
            risk_multiplier=0.0,
            max_hold_minutes=0,
        ).to_dict()

    if regime_name == "LOW_VOLATILITY":
        low_vol_threshold = float(get_entry_quality_threshold("LOW_VOLATILITY"))
        if resolved_entry_quality is None or resolved_entry_quality < low_vol_threshold or not very_tight_spread:
            return _route(
                "NO_TRADE",
                "NO_TRADE",
                confidence=min(score / 100.0, 0.5),
                reason="LOW_VOLATILITY requires entry_quality >= 80 and very tight spread",
                required_exit_profile="baseline",
                recommended_expiry_type="none",
                risk_multiplier=0.0,
                max_hold_minutes=0,
            ).to_dict()

    if regime_name == "CHOPPY":
        if ENABLE_RANGE_SCALP_0DTE and _is_time_between(current_time_et, time(12, 45), time(14, 30)) and option_premium is not None and 0.30 <= float(option_premium) <= 1.50:
            if price_near_support and candle_direction in ["bullish", "neutral"] and momentum_direction in ["bullish", "neutral"]:
                return _route(
                    "RANGE_SCALP_0DTE",
                    "CALL",
                    confidence=min(0.84, 0.48 + float(score) / 260.0),
                    reason="CHOPPY regime routed to RANGE_SCALP_0DTE",
                    required_exit_profile="scalp",
                    recommended_expiry_type="0DTE",
                    risk_multiplier=0.6,
                    max_hold_minutes=RANGE_SCALP_MAX_HOLD_MINUTES,
                ).to_dict()
            if price_near_resistance and candle_direction in ["bearish", "neutral"] and momentum_direction in ["bearish", "neutral"]:
                return _route(
                    "RANGE_SCALP_0DTE",
                    "PUT",
                    confidence=min(0.84, 0.48 + float(score) / 260.0),
                    reason="CHOPPY regime routed to RANGE_SCALP_0DTE",
                    required_exit_profile="scalp",
                    recommended_expiry_type="0DTE",
                    risk_multiplier=0.6,
                    max_hold_minutes=RANGE_SCALP_MAX_HOLD_MINUTES,
                ).to_dict()

        if ENABLE_MEAN_REVERSION_0DTE and option_premium is not None and float(option_premium) >= 0.50:
            if vwap_distance_percent is not None and float(vwap_distance_percent) <= -0.008 and momentum_direction in ["bearish", "neutral"]:
                return _route(
                    "MEAN_REVERSION_0DTE",
                    "CALL",
                    confidence=min(0.8, 0.42 + abs(float(vwap_distance_percent)) * 14.0),
                    reason="CHOPPY regime routed to MEAN_REVERSION_0DTE",
                    required_exit_profile="scalp",
                    recommended_expiry_type="0DTE",
                    risk_multiplier=0.6,
                    max_hold_minutes=MEAN_REVERSION_MAX_HOLD_MINUTES,
                ).to_dict()
            if vwap_distance_percent is not None and float(vwap_distance_percent) >= 0.008 and momentum_direction in ["bullish", "neutral"]:
                return _route(
                    "MEAN_REVERSION_0DTE",
                    "PUT",
                    confidence=min(0.8, 0.42 + abs(float(vwap_distance_percent)) * 14.0),
                    reason="CHOPPY regime routed to MEAN_REVERSION_0DTE",
                    required_exit_profile="scalp",
                    recommended_expiry_type="0DTE",
                    risk_multiplier=0.6,
                    max_hold_minutes=MEAN_REVERSION_MAX_HOLD_MINUTES,
                ).to_dict()

        if ENABLE_VWAP_BOUNCE and _flat(vwap_distance_percent) and float(rvol or 0.0) >= 1.2 and float(candle_body_percent or 0.0) >= 0.4:
            if float(vwap_distance_percent or 0.0) >= 0 and momentum_direction in ["bullish", "neutral"]:
                return _route(
                    "VWAP_BOUNCE",
                    "CALL",
                    confidence=min(0.86, 0.5 + float(score) / 260.0),
                    reason="CHOPPY regime routed to high-confidence VWAP_BOUNCE",
                    required_exit_profile="scalp",
                    recommended_expiry_type="same_day_or_next",
                    risk_multiplier=0.6,
                    max_hold_minutes=VWAP_BOUNCE_MAX_HOLD_MINUTES,
                ).to_dict()
            if float(vwap_distance_percent or 0.0) <= 0 and momentum_direction in ["bearish", "neutral"]:
                return _route(
                    "VWAP_BOUNCE",
                    "PUT",
                    confidence=min(0.86, 0.5 + float(score) / 260.0),
                    reason="CHOPPY regime routed to high-confidence VWAP_BOUNCE",
                    required_exit_profile="scalp",
                    recommended_expiry_type="same_day_or_next",
                    risk_multiplier=0.6,
                    max_hold_minutes=VWAP_BOUNCE_MAX_HOLD_MINUTES,
                ).to_dict()

        return _route(
            "NO_TRADE",
            "NO_TRADE",
            confidence=min(0.45, max(0.0, float(score) / 200.0)),
            reason="CHOPPY regime requires range/mean-reversion strategy, none enabled",
            required_exit_profile="baseline",
            recommended_expiry_type="none",
            risk_multiplier=0.0,
            max_hold_minutes=0,
        ).to_dict()

    bullish = latest_close is not None and vwap_distance_percent is not None and float(latest_close) >= float(opening_high or latest_close)
    bearish = latest_close is not None and vwap_distance_percent is not None and float(latest_close) <= float(opening_low or latest_close)

    if ENABLE_MOMENTUM_BREAKOUT and rvol is not None and candle_body_percent is not None:
        if (
            float(rvol) >= 1.8
            and float(candle_body_percent) >= 0.55
            and regime_name in ["TREND_UP", "TREND_DOWN", "HIGH_VOLATILITY"]
            and latest_close is not None
            and opening_high is not None
            and opening_low is not None
        ):
            if (
                float(latest_close) > float(opening_high)
                and ema_bullish
                and vwap_distance_percent is not None
                and float(vwap_distance_percent) >= 0
                and momentum_direction in ["bullish", "neutral"]
                and volume_direction in ["bullish", "neutral"]
            ):
                hold_minutes = MOMENTUM_BREAKOUT_MAX_HOLD_MINUTES
                if ENABLE_MOMENTUM_RUNNER and float(rvol) >= 2.0 and regime_name == "TREND_UP":
                    hold_minutes = max(hold_minutes, 60)
                return _route(
                    "MOMENTUM_BREAKOUT",
                    "CALL",
                    confidence=min(0.95, 0.55 + (float(rvol) - 1.8) * 0.12 + (float(candle_body_percent) - 0.55) * 0.4),
                    reason="Breakout above opening range with strong volume and trend alignment",
                    required_exit_profile="runner",
                    recommended_expiry_type="same_day_or_next",
                    risk_multiplier=1.15 if float(rvol) < 2.0 else 1.35,
                    max_hold_minutes=hold_minutes,
                ).to_dict()
            if (
                float(latest_close) < float(opening_low)
                and ema_bearish
                and vwap_distance_percent is not None
                and float(vwap_distance_percent) <= 0
                and momentum_direction in ["bearish", "neutral"]
                and volume_direction in ["bearish", "neutral"]
            ):
                hold_minutes = MOMENTUM_BREAKOUT_MAX_HOLD_MINUTES
                if ENABLE_MOMENTUM_RUNNER and float(rvol) >= 2.0 and regime_name == "TREND_DOWN":
                    hold_minutes = max(hold_minutes, 60)
                return _route(
                    "MOMENTUM_BREAKOUT",
                    "PUT",
                    confidence=min(0.95, 0.55 + (float(rvol) - 1.8) * 0.12 + (float(candle_body_percent) - 0.55) * 0.4),
                    reason="Breakdown below opening range with strong volume and trend alignment",
                    required_exit_profile="runner",
                    recommended_expiry_type="same_day_or_next",
                    risk_multiplier=1.15 if float(rvol) < 2.0 else 1.35,
                    max_hold_minutes=hold_minutes,
                ).to_dict()

    if ENABLE_OPENING_RANGE_BREAKOUT and current_time_et is not None:
        if _is_time_between(current_time_et, time(9, 45), time(11, 0)) and float(rvol or 0.0) >= 1.5:
            if latest_close is not None and opening_high is not None and float(latest_close) > float(opening_high):
                if resistance_level is None or (latest_close is not None and not _near(latest_close, resistance_level, 0.003)):
                    return _route(
                        "OPENING_RANGE_BREAKOUT",
                        "CALL",
                        confidence=min(0.92, 0.5 + (float(rvol) - 1.5) * 0.15 + (float(score) / 200.0)),
                        reason="Opening range break with sufficient volume and limited nearby resistance",
                        required_exit_profile="runner" if float(rvol) >= 1.8 else "scalp",
                        recommended_expiry_type="same_day_or_next",
                        risk_multiplier=1.1,
                        max_hold_minutes=45,
                    ).to_dict()
            if latest_close is not None and opening_low is not None and float(latest_close) < float(opening_low):
                if support_level is None or (latest_close is not None and not _near(latest_close, support_level, 0.003)):
                    return _route(
                        "OPENING_RANGE_BREAKOUT",
                        "PUT",
                        confidence=min(0.92, 0.5 + (float(rvol) - 1.5) * 0.15 + (float(score) / 200.0)),
                        reason="Opening range breakdown with sufficient volume and limited nearby support",
                        required_exit_profile="runner" if float(rvol) >= 1.8 else "scalp",
                        recommended_expiry_type="same_day_or_next",
                        risk_multiplier=1.1,
                        max_hold_minutes=45,
                    ).to_dict()

    if ENABLE_GAP_AND_GO and gap_direction in ["bullish", "bearish"] and opening_range_direction in ["bullish", "bearish"]:
        if gap_direction == "bullish" and bullish and float(rvol or 0.0) >= 1.4 and opening_range_direction == "bullish":
            return _route(
                "GAP_AND_GO",
                "CALL",
                confidence=min(0.9, 0.48 + float(rvol or 0.0) * 0.1 + float(score) / 250.0),
                reason="Gap up held and opening range confirmed continuation",
                required_exit_profile="runner",
                recommended_expiry_type="same_day_or_next",
                risk_multiplier=1.2,
                max_hold_minutes=90,
            ).to_dict()
        if gap_direction == "bearish" and bearish and float(rvol or 0.0) >= 1.4 and opening_range_direction == "bearish":
            return _route(
                "GAP_AND_GO",
                "PUT",
                confidence=min(0.9, 0.48 + float(rvol or 0.0) * 0.1 + float(score) / 250.0),
                reason="Gap down held and opening range confirmed continuation",
                required_exit_profile="runner",
                recommended_expiry_type="same_day_or_next",
                risk_multiplier=1.2,
                max_hold_minutes=90,
            ).to_dict()

    if ENABLE_GAP_FILL_REVERSAL and gap_fill_direction in ["bullish", "bearish"]:
        if gap_fill_direction == "bullish" and regime_name in ["RANGE", "CHOPPY", "TREND_UP"] and vwap_distance_percent is not None and float(vwap_distance_percent) >= 0:
            return _route(
                "GAP_FILL_REVERSAL",
                "CALL",
                confidence=min(0.88, 0.45 + abs(float(vwap_distance_percent)) * 10.0 + float(score) / 300.0),
                reason="Gap down started reversing and reclaimed VWAP",
                required_exit_profile="balanced",
                recommended_expiry_type="same_day_or_next",
                risk_multiplier=0.95,
                max_hold_minutes=30,
            ).to_dict()

    if regime_name == "REVERSAL":
        if ENABLE_MEAN_REVERSION_0DTE and _is_time_between(current_time_et, time(12, 45), time(14, 30)) and option_premium is not None and float(option_premium) >= 0.50:
            if vwap_distance_percent is not None and float(vwap_distance_percent) <= -0.008:
                return _route(
                    "MEAN_REVERSION_0DTE",
                    "CALL",
                    confidence=min(0.84, 0.45 + abs(float(vwap_distance_percent)) * 12.0),
                    reason="REVERSAL regime routed to MEAN_REVERSION_0DTE in midday session",
                    required_exit_profile="scalp",
                    recommended_expiry_type="0DTE",
                    risk_multiplier=0.7,
                    max_hold_minutes=MEAN_REVERSION_MAX_HOLD_MINUTES,
                ).to_dict()
            if vwap_distance_percent is not None and float(vwap_distance_percent) >= 0.008:
                return _route(
                    "MEAN_REVERSION_0DTE",
                    "PUT",
                    confidence=min(0.84, 0.45 + abs(float(vwap_distance_percent)) * 12.0),
                    reason="REVERSAL regime routed to MEAN_REVERSION_0DTE in midday session",
                    required_exit_profile="scalp",
                    recommended_expiry_type="0DTE",
                    risk_multiplier=0.7,
                    max_hold_minutes=MEAN_REVERSION_MAX_HOLD_MINUTES,
                ).to_dict()

        if vwap_distance_percent is not None and float(vwap_distance_percent) <= 0 and momentum_direction in ["bullish", "neutral"]:
            return _route(
                "GAP_FILL_REVERSAL",
                "CALL",
                confidence=min(0.86, 0.45 + abs(float(vwap_distance_percent)) * 10.0 + float(score) / 280.0),
                reason="Reversal regime mapped to bullish gap-fill continuation",
                required_exit_profile="balanced",
                recommended_expiry_type="same_day_or_next",
                risk_multiplier=0.9,
                max_hold_minutes=35,
            ).to_dict()
        if vwap_distance_percent is not None and float(vwap_distance_percent) >= 0 and momentum_direction in ["bearish", "neutral"]:
            return _route(
                "GAP_FILL_REVERSAL",
                "PUT",
                confidence=min(0.86, 0.45 + abs(float(vwap_distance_percent)) * 10.0 + float(score) / 280.0),
                reason="Reversal regime mapped to bearish gap-fill continuation",
                required_exit_profile="balanced",
                recommended_expiry_type="same_day_or_next",
                risk_multiplier=0.9,
                max_hold_minutes=35,
            ).to_dict()
        if gap_fill_direction == "bearish" and regime_name in ["RANGE", "CHOPPY", "TREND_DOWN"] and vwap_distance_percent is not None and float(vwap_distance_percent) <= 0:
            return _route(
                "GAP_FILL_REVERSAL",
                "PUT",
                confidence=min(0.88, 0.45 + abs(float(vwap_distance_percent)) * 10.0 + float(score) / 300.0),
                reason="Gap up started reversing and lost VWAP",
                required_exit_profile="balanced",
                recommended_expiry_type="same_day_or_next",
                risk_multiplier=0.95,
                max_hold_minutes=30,
            ).to_dict()

    if ENABLE_TREND_PULLBACK and regime_name in ["TREND_UP", "TREND_DOWN"]:
        near_vwap_or_ema20 = False
        if latest_close is not None and vwap_distance_percent is not None:
            near_vwap_or_ema20 = abs(float(vwap_distance_percent)) <= 0.004
        if latest_close is not None and ema_20 is not None:
            ema_gap = abs(float(latest_close) - float(ema_20)) / max(abs(float(ema_20)), 1.0)
            near_vwap_or_ema20 = near_vwap_or_ema20 or ema_gap <= 0.003

        rejection_bullish = candle_direction in ["bullish", "neutral"] and momentum_direction in ["bullish", "neutral"]
        rejection_bearish = candle_direction in ["bearish", "neutral"] and momentum_direction in ["bearish", "neutral"]

        if regime_name == "TREND_UP" and near_vwap_or_ema20 and rejection_bullish:
            return _route(
                "TREND_PULLBACK",
                "CALL",
                confidence=min(0.9, 0.5 + float(score) / 220.0 + (0.005 - abs(float(vwap_distance_percent or 0.0))) * 20.0),
                reason="Trend up pullback into VWAP/EMA20 with bullish rejection",
                required_exit_profile="balanced",
                recommended_expiry_type="same_day_or_next",
                risk_multiplier=1.0,
                max_hold_minutes=60,
            ).to_dict()
        if regime_name == "TREND_DOWN" and near_vwap_or_ema20 and rejection_bearish:
            return _route(
                "TREND_PULLBACK",
                "PUT",
                confidence=min(0.9, 0.5 + float(score) / 220.0 + (0.005 - abs(float(vwap_distance_percent or 0.0))) * 20.0),
                reason="Trend down pullback into VWAP/EMA20 with bearish rejection",
                required_exit_profile="balanced",
                recommended_expiry_type="same_day_or_next",
                risk_multiplier=1.0,
                max_hold_minutes=60,
            ).to_dict()

    if ENABLE_VWAP_BOUNCE and regime_name in ["TREND_UP", "TREND_DOWN", "RANGE"] and _flat(vwap_distance_percent):
        if latest_close is not None and candle_body_percent is not None and float(candle_body_percent) >= 0.4 and float(rvol or 0.0) >= 1.2:
            vwap_bias_bullish = float(vwap_distance_percent or 0.0) >= 0
            vwap_bias_bearish = float(vwap_distance_percent or 0.0) <= 0
            if vwap_bias_bullish and momentum_direction in ["bullish", "neutral"] and trend_direction in ["bullish", "neutral"]:
                return _route(
                    "VWAP_BOUNCE",
                    "CALL",
                    confidence=min(0.84, 0.42 + float(score) / 260.0 + float(rvol or 0.0) * 0.05),
                    reason="VWAP held from above with strong rejection",
                    required_exit_profile="scalp",
                    recommended_expiry_type="same_day_or_next",
                    risk_multiplier=0.8,
                    max_hold_minutes=VWAP_BOUNCE_MAX_HOLD_MINUTES,
                ).to_dict()
            if vwap_bias_bearish and momentum_direction in ["bearish", "neutral"] and trend_direction in ["bearish", "neutral"]:
                return _route(
                    "VWAP_BOUNCE",
                    "PUT",
                    confidence=min(0.84, 0.42 + float(score) / 260.0 + float(rvol or 0.0) * 0.05),
                    reason="VWAP rejected from below with strong follow-through",
                    required_exit_profile="scalp",
                    recommended_expiry_type="same_day_or_next",
                    risk_multiplier=0.8,
                    max_hold_minutes=VWAP_BOUNCE_MAX_HOLD_MINUTES,
                ).to_dict()

    if ENABLE_RANGE_SCALP_0DTE and regime_name in ["RANGE", "CHOPPY"] and _is_time_between(current_time_et, time(12, 45), time(14, 30)):
        if not ALLOW_0DTE_FOR_RANGE_SCALP:
            return _route(
                "NO_TRADE",
                "NO_TRADE",
                confidence=0.0,
                reason="0DTE blocked for range scalp",
                required_exit_profile="baseline",
                recommended_expiry_type="none",
                risk_multiplier=0.0,
                max_hold_minutes=0,
            ).to_dict()
        if option_premium is not None and 0.30 <= float(option_premium) <= 1.50 and spread_liquidity_ok and float(rvol or 0.0) >= 1.0:
            if price_near_support and candle_direction in ["bullish", "neutral"] and momentum_direction in ["bullish", "neutral"]:
                return _route(
                    "RANGE_SCALP_0DTE",
                    "CALL",
                    confidence=min(0.86, 0.5 + float(score) / 250.0),
                    reason="Range support rejection during midday sideways window",
                    required_exit_profile="scalp",
                    recommended_expiry_type="0DTE",
                    risk_multiplier=0.6,
                    max_hold_minutes=RANGE_SCALP_MAX_HOLD_MINUTES,
                ).to_dict()
            if price_near_resistance and candle_direction in ["bearish", "neutral"] and momentum_direction in ["bearish", "neutral"]:
                return _route(
                    "RANGE_SCALP_0DTE",
                    "PUT",
                    confidence=min(0.86, 0.5 + float(score) / 250.0),
                    reason="Range resistance rejection during midday sideways window",
                    required_exit_profile="scalp",
                    recommended_expiry_type="0DTE",
                    risk_multiplier=0.6,
                    max_hold_minutes=RANGE_SCALP_MAX_HOLD_MINUTES,
                ).to_dict()

    if ENABLE_MEAN_REVERSION_0DTE and regime_name in ["RANGE", "CHOPPY"]:
        if option_premium is not None and float(option_premium) >= 0.50:
            if vwap_distance_percent is not None and float(vwap_distance_percent) <= -0.008 and price_near_support and momentum_direction in ["bearish", "neutral"]:
                return _route(
                    "MEAN_REVERSION_0DTE",
                    "CALL",
                    confidence=min(0.8, 0.4 + abs(float(vwap_distance_percent)) * 15.0 + float(score) / 300.0),
                    reason="Extended below VWAP with exhaustion and support reclaim setup",
                    required_exit_profile="scalp",
                    recommended_expiry_type="0DTE",
                    risk_multiplier=0.65,
                    max_hold_minutes=MEAN_REVERSION_MAX_HOLD_MINUTES,
                ).to_dict()
            if vwap_distance_percent is not None and float(vwap_distance_percent) >= 0.008 and price_near_resistance and momentum_direction in ["bullish", "neutral"]:
                return _route(
                    "MEAN_REVERSION_0DTE",
                    "PUT",
                    confidence=min(0.8, 0.4 + abs(float(vwap_distance_percent)) * 15.0 + float(score) / 300.0),
                    reason="Extended above VWAP with exhaustion and resistance fade setup",
                    required_exit_profile="scalp",
                    recommended_expiry_type="0DTE",
                    risk_multiplier=0.65,
                    max_hold_minutes=MEAN_REVERSION_MAX_HOLD_MINUTES,
                ).to_dict()

    if latest_close is not None and opening_high is not None and opening_low is not None:
        if float(latest_close) > float(opening_high) and ema_bullish and volume_direction in ["bullish", "neutral"]:
            return _route(
                "MOMENTUM_BREAKOUT",
                "CALL",
                confidence=min(0.75, 0.35 + float(score) / 200.0),
                reason="Fallback bullish momentum breakout",
                required_exit_profile="runner",
                recommended_expiry_type="same_day_or_next",
                risk_multiplier=1.0,
                max_hold_minutes=MOMENTUM_BREAKOUT_MAX_HOLD_MINUTES,
            ).to_dict()
        if float(latest_close) < float(opening_low) and ema_bearish and volume_direction in ["bearish", "neutral"]:
            return _route(
                "MOMENTUM_BREAKOUT",
                "PUT",
                confidence=min(0.75, 0.35 + float(score) / 200.0),
                reason="Fallback bearish momentum breakout",
                required_exit_profile="runner",
                recommended_expiry_type="same_day_or_next",
                risk_multiplier=1.0,
                max_hold_minutes=MOMENTUM_BREAKOUT_MAX_HOLD_MINUTES,
            ).to_dict()

    return _route(
        "NO_TRADE",
        "NO_TRADE",
        confidence=min(0.45, max(0.0, float(score) / 200.0)),
        reason=f"No route matched for regime={regime_name}",
        required_exit_profile="baseline",
        recommended_expiry_type="none",
        risk_multiplier=0.0,
        max_hold_minutes=0,
    ).to_dict()