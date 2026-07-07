from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo


STRATEGY_PERF_PATH = Path("logs/strategy_performance.json")


def _load_state() -> dict[str, Any]:
    if not STRATEGY_PERF_PATH.exists():
        return {"strategies": {}, "updated_at": None}
    try:
        data = json.loads(STRATEGY_PERF_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("strategies", {})
            return data
    except json.JSONDecodeError:
        pass
    return {"strategies": {}, "updated_at": None}


def _save_state(state: dict[str, Any]) -> None:
    STRATEGY_PERF_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(ZoneInfo("America/New_York")).isoformat()
    STRATEGY_PERF_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def _strategy_bucket(state: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    strategies = state.setdefault("strategies", {})
    bucket = strategies.setdefault(
        strategy_name,
        {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "sum_r": 0.0,
            "sum_hold_minutes": 0.0,
            "max_drawdown": 0.0,
            "equity_curve": [],
            "last_20_r": [],
            "consecutive_losses": 0,
            "disabled": False,
            "disabled_reason": None,
            "disabled_until": None,
            "manual_enabled": True,
            "time_windows": {},
            "best_time_window": None,
            "worst_time_window": None,
            "spread_slippage_issues": 0,
            "last_event_at": None,
        },
    )
    return bucket


def _update_drawdown(bucket: dict[str, Any], realized_pnl: float) -> None:
    equity_curve = bucket.setdefault("equity_curve", [])
    equity_curve.append(float(realized_pnl))
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in equity_curve:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    bucket["max_drawdown"] = float(max_drawdown)


def _update_window_stats(bucket: dict[str, Any], time_window: Optional[str], pnl: float) -> None:
    if not time_window:
        return
    windows = bucket.setdefault("time_windows", {})
    window = windows.setdefault(time_window, {"trades": 0, "net_pnl": 0.0})
    window["trades"] += 1
    window["net_pnl"] += float(pnl)
    ranked = sorted(windows.items(), key=lambda item: (item[1]["net_pnl"], item[1]["trades"]), reverse=True)
    if ranked:
        bucket["best_time_window"] = ranked[0][0]
        bucket["worst_time_window"] = ranked[-1][0]


def _should_disable(bucket: dict[str, Any]) -> tuple[bool, Optional[str]]:
    last_20 = bucket.get("last_20_r", [])
    if len(last_20) >= 20:
        recent = last_20[-20:]
        expectancy = sum(recent) / len(recent)
        if expectancy < 0:
            return True, "last_20_expectancy_below_zero"

    if int(bucket.get("consecutive_losses", 0)) >= 3:
        return True, "three_consecutive_losses"

    if int(bucket.get("spread_slippage_issues", 0)) >= 3:
        return True, "repeated_spread_or_slippage_issues"

    return False, None


def record_strategy_trade(
    strategy_name: Optional[str],
    *,
    pnl: float,
    r_multiple: Optional[float] = None,
    hold_minutes: Optional[float] = None,
    time_window: Optional[str] = None,
    regime: Optional[str] = None,
    spread_slippage_issue: bool = False,
) -> dict[str, Any]:
    if not strategy_name:
        return {"strategy_name": None, "recorded": False}

    state = _load_state()
    bucket = _strategy_bucket(state, strategy_name)
    pnl_value = float(pnl)
    r_value = float(r_multiple) if r_multiple is not None else (pnl_value if pnl_value else 0.0)

    bucket["trades"] += 1
    if pnl_value > 0:
        bucket["wins"] += 1
        bucket["consecutive_losses"] = 0
        bucket["gross_profit"] += pnl_value
    elif pnl_value < 0:
        bucket["losses"] += 1
        bucket["gross_loss"] += abs(pnl_value)
        bucket["consecutive_losses"] += 1
    else:
        bucket["consecutive_losses"] = 0

    bucket["sum_r"] += r_value
    if hold_minutes is not None:
        bucket["sum_hold_minutes"] += float(hold_minutes)
    bucket["last_20_r"] = (bucket.get("last_20_r", []) + [r_value])[-20:]
    bucket["last_event_at"] = datetime.now(ZoneInfo("America/New_York")).isoformat()
    if spread_slippage_issue:
        bucket["spread_slippage_issues"] = int(bucket.get("spread_slippage_issues", 0)) + 1

    _update_drawdown(bucket, pnl_value)
    _update_window_stats(bucket, time_window, pnl_value)

    should_disable, reason = _should_disable(bucket)
    if should_disable:
        bucket["disabled"] = True
        bucket["disabled_reason"] = reason
        bucket["disabled_until"] = datetime.now(ZoneInfo("America/New_York")).date().isoformat()

    _save_state(state)
    return {"strategy_name": strategy_name, "recorded": True, "disabled": bool(bucket.get("disabled")), "disabled_reason": bucket.get("disabled_reason")}


def enable_strategy(strategy_name: str) -> dict[str, Any]:
    state = _load_state()
    bucket = _strategy_bucket(state, strategy_name)
    bucket["disabled"] = False
    bucket["disabled_reason"] = None
    bucket["disabled_until"] = None
    bucket["manual_enabled"] = True
    bucket["consecutive_losses"] = 0
    bucket["spread_slippage_issues"] = 0
    _save_state(state)
    return {"strategy_name": strategy_name, "enabled": True}


def disable_strategy(strategy_name: str, reason: str = "manual_disable") -> dict[str, Any]:
    state = _load_state()
    bucket = _strategy_bucket(state, strategy_name)
    bucket["disabled"] = True
    bucket["disabled_reason"] = reason
    bucket["disabled_until"] = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    bucket["manual_enabled"] = False
    _save_state(state)
    return {"strategy_name": strategy_name, "enabled": False, "reason": reason}


def get_strategy_status() -> dict[str, Any]:
    state = _load_state()
    strategies = state.get("strategies", {})
    disabled = []
    enabled = []
    for name, bucket in strategies.items():
        if bucket.get("disabled") and not bucket.get("manual_enabled", True):
            disabled.append(name)
        elif bucket.get("disabled"):
            disabled.append(name)
        else:
            enabled.append(name)
    return {
        "strategies": strategies,
        "disabled_strategies": sorted(disabled),
        "enabled_strategies": sorted(enabled),
        "updated_at": state.get("updated_at"),
    }


def is_strategy_enabled(strategy_name: Optional[str]) -> bool:
    if not strategy_name:
        return False
    state = _load_state()
    bucket = state.get("strategies", {}).get(strategy_name)
    if not bucket:
        return True
    if not bucket.get("manual_enabled", True):
        return False
    return not bool(bucket.get("disabled", False))


def get_strategy_summary(limit: int = 10) -> dict[str, Any]:
    state = _load_state()
    strategies = {}
    for name, bucket in state.get("strategies", {}).items():
        trades = int(bucket.get("trades", 0))
        wins = int(bucket.get("wins", 0))
        losses = int(bucket.get("losses", 0))
        gross_profit = float(bucket.get("gross_profit", 0.0))
        gross_loss = float(bucket.get("gross_loss", 0.0))
        expectancy = (gross_profit - gross_loss) / trades if trades else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (9999.0 if gross_profit > 0 else 0.0)
        avg_hold = (float(bucket.get("sum_hold_minutes", 0.0)) / trades) if trades else 0.0
        strategies[name] = {
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / trades) if trades else 0.0,
            "average_r": (float(bucket.get("sum_r", 0.0)) / trades) if trades else 0.0,
            "average_hold_minutes": avg_hold,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "max_drawdown": float(bucket.get("max_drawdown", 0.0)),
            "best_time_window": bucket.get("best_time_window"),
            "worst_time_window": bucket.get("worst_time_window"),
            "disabled": bool(bucket.get("disabled", False)),
            "disabled_reason": bucket.get("disabled_reason"),
            "last_20_r": list(bucket.get("last_20_r", [])[-limit:]),
        }
    return {"updated_at": state.get("updated_at"), "strategies": strategies}