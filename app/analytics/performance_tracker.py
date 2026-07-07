import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PERF_PATH = Path("logs/performance_summary.json")


def _safe_div(a, b):
    return (a / b) if b else 0.0


def _load():
    if not PERF_PATH.exists():
        return {
            "updated_at": None,
            "daily": {},
            "trades": [],
            "consecutive_losses": 0,
            "max_drawdown": 0.0,
        }
    try:
        return json.loads(PERF_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "updated_at": None,
            "daily": {},
            "trades": [],
            "consecutive_losses": 0,
            "max_drawdown": 0.0,
        }


def _save(state):
    PERF_PATH.parent.mkdir(parents=True, exist_ok=True)
    PERF_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def record_trade_event(pnl, r_multiple=None, regime=None, hour=None, setup_type=None):
    state = _load()
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    daily = state["daily"].setdefault(
        today,
        {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "realized_pnl": 0.0,
            "r_values": [],
            "regime": {},
            "hour": {},
            "setup": {},
        },
    )

    pnl = float(pnl)
    daily["trades"] += 1
    if pnl > 0:
        daily["wins"] += 1
        state["consecutive_losses"] = 0
    elif pnl < 0:
        daily["losses"] += 1
        state["consecutive_losses"] = int(state.get("consecutive_losses", 0)) + 1
    daily["realized_pnl"] = round(float(daily.get("realized_pnl", 0.0)) + pnl, 2)

    if r_multiple is not None:
        daily["r_values"].append(float(r_multiple))

    if regime:
        daily["regime"][str(regime)] = int(daily["regime"].get(str(regime), 0)) + 1
    if hour is not None:
        key = str(hour)
        daily["hour"][key] = int(daily["hour"].get(key, 0)) + 1
    if setup_type:
        daily["setup"][str(setup_type)] = int(daily["setup"].get(str(setup_type), 0)) + 1

    trade_record = {
        "timestamp": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "pnl": pnl,
        "r_multiple": float(r_multiple) if r_multiple is not None else None,
        "regime": regime,
        "hour": hour,
        "setup_type": setup_type,
    }
    state["trades"].append(trade_record)
    state["trades"] = state["trades"][-500:]

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in state["trades"]:
        equity += float(t.get("pnl", 0.0))
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    state["max_drawdown"] = round(max_dd, 2)

    state["updated_at"] = datetime.now(ZoneInfo("America/New_York")).isoformat()
    _save(state)
    return state


def get_summary(limit_last=20):
    state = _load()
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    daily = state.get("daily", {}).get(
        today,
        {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "realized_pnl": 0.0,
            "r_values": [],
            "regime": {},
            "hour": {},
            "setup": {},
        },
    )

    trades = state.get("trades", [])
    pnls = [float(t.get("pnl", 0.0)) for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    r_vals = [float(t.get("r_multiple")) for t in trades if t.get("r_multiple") is not None]

    last_n = trades[-max(int(limit_last), 1):]
    last_n_expectancy = _safe_div(sum(float(t.get("pnl", 0.0)) for t in last_n), len(last_n)) if last_n else 0.0

    return {
        "updated_at": state.get("updated_at"),
        "today": {
            "trades": int(daily.get("trades", 0)),
            "wins": int(daily.get("wins", 0)),
            "losses": int(daily.get("losses", 0)),
            "realized_pnl": round(float(daily.get("realized_pnl", 0.0)), 2),
            "win_rate": round(_safe_div(int(daily.get("wins", 0)), int(daily.get("trades", 0))), 4),
            "average_r": round(_safe_div(sum(daily.get("r_values", [])), len(daily.get("r_values", []))), 4) if daily.get("r_values") else 0.0,
            "regime_performance": daily.get("regime", {}),
            "hour_of_day_performance": daily.get("hour", {}),
            "setup_performance": daily.get("setup", {}),
        },
        "overall": {
            "expectancy": round(_safe_div(sum(pnls), len(pnls)), 4) if pnls else 0.0,
            "profit_factor": round(_safe_div(sum(wins), abs(sum(losses))), 4) if losses else (9999.0 if wins else 0.0),
            "max_drawdown": round(float(state.get("max_drawdown", 0.0)), 2),
            "consecutive_losses": int(state.get("consecutive_losses", 0)),
            "last_20_expectancy": round(last_n_expectancy, 4),
            "trades_count": len(trades),
        },
    }
