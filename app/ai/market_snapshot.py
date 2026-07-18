from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.logs.decision_logger import _to_jsonable
from app.planning.trade_plan import build_trade_plan


LAST_SNAPSHOT_PATH = Path("logs/claude_last_snapshot.json")
REQUIRED_LATEST_BAR_KEYS = {
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "ema_9",
    "ema_20",
    "avg_volume",
}


def normalize_decision_label(value: Any) -> str:
    text = str(value or "NO_TRADE").upper().replace(" ", "_")
    return text if text in {"CALL", "PUT", "NO_TRADE"} else "NO_TRADE"


def build_trade_plan_for_decision(
    decision: str,
    latest_close: float,
    latest_vwap: float,
    atr_value: float | None,
    swing_low: float | None,
    swing_high: float | None,
):
    if normalize_decision_label(decision) not in {"CALL", "PUT"}:
        return None
    return build_trade_plan(
        normalize_decision_label(decision),
        latest_close,
        latest_vwap,
        atr=atr_value,
        swing_low=swing_low,
        swing_high=swing_high,
    )


def build_claude_market_snapshot(
    *,
    symbol: str,
    paper_trading_confirmed: bool,
    prices: dict[str, Any],
    latest: Any,
    premarket_high: Any,
    premarket_low: Any,
    opening_high: Any,
    opening_low: Any,
    prev_high: Any,
    prev_low: Any,
    prev_close: Any,
    analysis_results: list[dict[str, Any]],
    signal_master_decision: dict[str, Any],
    strategy_route: dict[str, Any],
    entry_quality: dict[str, Any],
    entry_quality_score: int,
    adaptive_threshold: int,
    static_threshold: int,
    regime_name: str,
    regime_note: str,
    call_decision: dict[str, Any],
    put_decision: dict[str, Any],
    final_decision: dict[str, Any],
    trade_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    route_direction = normalize_decision_label(strategy_route.get("direction")) if isinstance(strategy_route, dict) else "NO_TRADE"
    signal_direction = normalize_decision_label(signal_master_decision.get("decision"))
    simple_signal = normalize_decision_label(final_decision.get("decision"))
    existing_signal = next(
        (
            direction
            for direction in [route_direction, signal_direction, simple_signal]
            if direction in {"CALL", "PUT"}
        ),
        "NO_TRADE",
    )
    snapshot = {
        "symbol": symbol,
        "paper_trading_confirmed": bool(paper_trading_confirmed),
        "existing_signal": existing_signal,
        "latest_prices": prices,
        "latest_bar": {
            "timestamp": latest["timestamp"],
            "open": float(latest["open"]),
            "high": float(latest["high"]),
            "low": float(latest["low"]),
            "close": float(latest["close"]),
            "volume": float(latest["volume"]),
            "vwap": float(latest["vwap"]),
            "ema_9": float(latest["ema_9"]),
            "ema_20": float(latest["ema_20"]),
            "avg_volume": float(latest["avg_volume"]),
        },
        "reference_levels": {
            "premarket_high": premarket_high,
            "premarket_low": premarket_low,
            "opening_high": opening_high,
            "opening_low": opening_low,
            "prev_high": prev_high,
            "prev_low": prev_low,
            "prev_close": prev_close,
        },
        "analysis_results": analysis_results,
        "signal_master_decision": signal_master_decision,
        "strategy_route": strategy_route,
        "entry_quality": entry_quality,
        "entry_quality_score": int(entry_quality_score),
        "adaptive_entry_threshold": int(adaptive_threshold),
        "static_entry_threshold": int(static_threshold),
        "regime": regime_name,
        "regime_note": regime_note,
        "call_signal": call_decision,
        "put_signal": put_decision,
        "simple_final_signal": {"decision": simple_signal, "details": final_decision},
        "trade_plan": trade_plan,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.loads(json.dumps(snapshot, default=str))


def persist_market_snapshot(snapshot: dict[str, Any]) -> Path:
    LAST_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = _to_jsonable(snapshot)
    LAST_SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return LAST_SNAPSHOT_PATH


def load_market_snapshot() -> dict[str, Any] | None:
    if not LAST_SNAPSHOT_PATH.exists():
        return None
    try:
        data = json.loads(LAST_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def get_snapshot_age_seconds(snapshot: dict[str, Any], now: datetime | None = None) -> float | None:
    latest_bar = snapshot.get("latest_bar") if isinstance(snapshot, dict) else None
    if not isinstance(latest_bar, dict):
        return None
    raw_timestamp = latest_bar.get("timestamp")
    if raw_timestamp is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    return max((current_time - parsed.astimezone(timezone.utc)).total_seconds(), 0.0)


def snapshot_has_required_data(snapshot: dict[str, Any]) -> bool:
    if not isinstance(snapshot, dict):
        return False
    latest_prices = snapshot.get("latest_prices")
    latest_bar = snapshot.get("latest_bar")
    if not isinstance(latest_prices, dict) or not latest_prices.get("QQQ"):
        return False
    if not isinstance(latest_bar, dict) or not REQUIRED_LATEST_BAR_KEYS.issubset(set(latest_bar.keys())):
        return False
    if not isinstance(snapshot.get("analysis_results"), list) or not snapshot.get("analysis_results"):
        return False
    return True