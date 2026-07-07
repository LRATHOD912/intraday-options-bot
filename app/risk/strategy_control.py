from __future__ import annotations

from typing import Any, Optional

from app.analytics.strategy_performance import (
    disable_strategy,
    enable_strategy,
    get_strategy_status,
    is_strategy_enabled,
    record_strategy_trade,
)


def record_strategy_event(
    strategy_name: Optional[str],
    *,
    pnl: float = 0.0,
    r_multiple: Optional[float] = None,
    hold_minutes: Optional[float] = None,
    time_window: Optional[str] = None,
    regime: Optional[str] = None,
    spread_slippage_issue: bool = False,
) -> dict[str, Any]:
    return record_strategy_trade(
        strategy_name,
        pnl=pnl,
        r_multiple=r_multiple,
        hold_minutes=hold_minutes,
        time_window=time_window,
        regime=regime,
        spread_slippage_issue=spread_slippage_issue,
    )


def strategy_enabled(strategy_name: Optional[str]) -> bool:
    return is_strategy_enabled(strategy_name)


def enable_strategy_for_user(strategy_name: str) -> dict[str, Any]:
    return enable_strategy(strategy_name)


def disable_strategy_for_user(strategy_name: str, reason: str = "manual_disable") -> dict[str, Any]:
    return disable_strategy(strategy_name, reason=reason)


def strategy_status() -> dict[str, Any]:
    return get_strategy_status()