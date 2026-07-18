from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.ai.market_snapshot import get_snapshot_age_seconds, normalize_decision_label, snapshot_has_required_data


PLACEHOLDER_SYMBOL_MARKERS = ("TEST", "DUMMY", "PLACEHOLDER")


@dataclass
class ClaudeSafetyGateResult:
    allowed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _allow(details: dict[str, Any] | None = None) -> ClaudeSafetyGateResult:
    return ClaudeSafetyGateResult(True, "ok", details or {})


def _block(reason: str, details: dict[str, Any] | None = None) -> ClaudeSafetyGateResult:
    return ClaudeSafetyGateResult(False, reason, details or {})


def infer_contract_direction(contract: dict[str, Any] | None) -> str:
    if not isinstance(contract, dict):
        return "NO_TRADE"
    option_type = str(contract.get("option_type") or "").upper().strip()
    if option_type in {"CALL", "PUT"}:
        return option_type
    symbol = str(contract.get("symbol") or "").upper()
    if "C" in symbol and "P" not in symbol:
        return "CALL"
    if "P" in symbol and "C" not in symbol:
        return "PUT"
    if len(symbol) >= 9:
        if "C" in symbol[-9:]:
            return "CALL"
        if "P" in symbol[-9:]:
            return "PUT"
    return "NO_TRADE"


def is_real_option_symbol(symbol: str | None) -> bool:
    text = str(symbol or "").upper().strip()
    if not text:
        return False
    return not any(marker in text for marker in PLACEHOLDER_SYMBOL_MARKERS)


def evaluate_claude_call_control(
    *,
    enabled: bool,
    paper_trading_confirmed: bool,
    market_open: bool,
    within_strategy_window: bool,
    risk_allowed: bool,
    market_snapshot: dict[str, Any] | None,
    last_called_at: str | None,
    min_seconds_between_calls: int,
    now: datetime | None = None,
) -> ClaudeSafetyGateResult:
    current_time = now or datetime.now(timezone.utc)
    if not enabled:
        return _block("claude_disabled")
    if not paper_trading_confirmed:
        return _block("paper_mode_unconfirmed")
    if not market_open:
        return _block("market_closed")
    if not within_strategy_window:
        return _block("outside_strategy_window")
    if not risk_allowed:
        return _block("daily_risk_limit_reached")
    if not snapshot_has_required_data(market_snapshot or {}):
        return _block("missing_market_data")
    snapshot_age = get_snapshot_age_seconds(market_snapshot or {}, now=current_time)
    if snapshot_age is None or snapshot_age > 45:
        return _block("stale_market_snapshot", {"snapshot_age_seconds": snapshot_age})
    if last_called_at:
        try:
            parsed = datetime.fromisoformat(str(last_called_at).replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            elapsed = (current_time - parsed.astimezone(timezone.utc)).total_seconds()
            if elapsed < int(min_seconds_between_calls):
                return _block(
                    "claude_rate_limited",
                    {
                        "seconds_since_last_call": max(elapsed, 0.0),
                        "required_seconds": int(min_seconds_between_calls),
                    },
                )
    return _allow({"snapshot_age_seconds": snapshot_age})


def evaluate_claude_execution_gate(
    *,
    paper_trading_confirmed: bool,
    market_open: bool,
    within_strategy_window: bool,
    market_snapshot: dict[str, Any] | None,
    claude_decided_at: str | None,
    decision_direction: str,
    trade_plan_direction: str | None,
    selector_direction: str | None,
    contract: dict[str, Any] | None,
    option_quote: dict[str, Any] | None,
    spread_percent: float | None,
    spread_limit: float,
    entry_price: float | None,
    trade_quantity: int,
    allow_0dte: bool,
    preferred_delta_min: float,
    preferred_delta_max: float,
    min_option_volume: float,
    min_option_open_interest: float,
    min_option_price: float,
    max_option_price: float,
    buying_power: float | None,
    daily_risk_ok: bool,
    total_open_risk: float,
    new_trade_risk: float,
    max_total_open_risk: float,
    total_open_positions: int,
    max_open_positions: int,
    duplicate_position: bool,
    conflicting_position: bool,
    now: datetime | None = None,
) -> ClaudeSafetyGateResult:
    current_time = now or datetime.now(timezone.utc)
    if not paper_trading_confirmed:
        return _block("paper_mode_unconfirmed")
    if not market_open:
        return _block("market_closed")
    if not within_strategy_window:
        return _block("outside_strategy_window")
    snapshot_age = get_snapshot_age_seconds(market_snapshot or {}, now=current_time)
    if snapshot_age is None or snapshot_age > 45:
        return _block("stale_market_snapshot", {"snapshot_age_seconds": snapshot_age})
    if claude_decided_at:
        try:
            parsed = datetime.fromisoformat(str(claude_decided_at).replace("Z", "+00:00"))
        except ValueError:
            return _block("stale_claude_decision")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if (current_time - parsed.astimezone(timezone.utc)).total_seconds() > 45:
            return _block("stale_claude_decision")
    if not daily_risk_ok:
        return _block("daily_risk_limit_reached")
    if total_open_positions >= int(max_open_positions):
        return _block("max_open_positions_reached")
    if duplicate_position:
        return _block("duplicate_position")
    if conflicting_position:
        return _block("opposite_direction_position_exists")
    if not isinstance(contract, dict) or not contract.get("symbol"):
        return _block("missing_option_symbol")
    if not is_real_option_symbol(contract.get("symbol")):
        return _block("placeholder_option_symbol")

    normalized_decision = normalize_decision_label(decision_direction)
    normalized_trade_plan = normalize_decision_label(trade_plan_direction)
    normalized_selector = normalize_decision_label(selector_direction)
    contract_direction = infer_contract_direction(contract)
    if normalized_decision not in {"CALL", "PUT"}:
        return _block("direction_mismatch")
    if normalized_trade_plan not in {normalized_decision, "NO_TRADE"}:
        return _block("direction_mismatch")
    if normalized_selector not in {normalized_decision, "NO_TRADE"}:
        return _block("direction_mismatch")
    if contract_direction != normalized_decision:
        return _block("direction_mismatch", {"contract_direction": contract_direction})

    expiry_days = contract.get("expiry_days")
    if expiry_days is None:
        return _block("invalid_expiry")
    if int(expiry_days) == 0 and not allow_0dte:
        return _block("zero_dte_not_allowed")

    delta = contract.get("delta")
    if delta is None:
        return _block("delta_out_of_range")
    abs_delta = abs(float(delta))
    if abs_delta < float(preferred_delta_min) or abs_delta > float(preferred_delta_max):
        return _block("delta_out_of_range")

    volume = contract.get("volume")
    if volume is None or float(volume) < float(min_option_volume):
        return _block("option_volume_too_low")
    open_interest = contract.get("open_interest")
    if open_interest is None or float(open_interest) < float(min_option_open_interest):
        return _block("option_open_interest_too_low")

    if option_quote is None or not option_quote.get("quote_valid", False):
        return _block("invalid_option_quote")
    if option_quote.get("bid") is None or option_quote.get("ask") is None:
        return _block("missing_bid_ask")
    if spread_percent is not None and float(spread_percent) > float(spread_limit):
        return _block("spread_too_wide")
    if entry_price is None or float(entry_price) < float(min_option_price) or float(entry_price) > float(max_option_price):
        return _block("option_price_out_of_bounds")

    estimated_cost = float(entry_price) * float(max(int(trade_quantity), 1)) * 100.0
    if buying_power is not None and float(buying_power) < estimated_cost:
        return _block("buying_power_insufficient")
    if float(total_open_risk) + float(new_trade_risk) > float(max_total_open_risk):
        return _block("total_open_risk_exceeded")

    return _allow({"estimated_cost": estimated_cost, "contract_direction": contract_direction})