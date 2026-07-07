import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.analytics.performance_tracker import get_summary
from app.config import MAX_CONSECUTIVE_LOSSES, MAX_DRAWDOWN_DAY, MIN_EXPECTANCY_LAST_20_TRADES, USE_AUTO_PAUSE


STATE_PATH = Path("logs/auto_pause_state.json")


def _load():
    if not STATE_PATH.exists():
        return {"paused": False, "reason": None, "updated_at": None}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"paused": False, "reason": None, "updated_at": None}


def _save(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(ZoneInfo("America/New_York")).isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def evaluate_pause_rules():
    if not USE_AUTO_PAUSE:
        state = {"paused": False, "reason": "auto_pause_disabled"}
        _save(state)
        return state

    perf = get_summary(limit_last=20)
    today = perf.get("today", {})
    overall = perf.get("overall", {})

    paused = False
    reason = None

    if int(overall.get("consecutive_losses", 0)) >= int(MAX_CONSECUTIVE_LOSSES):
        paused = True
        reason = "max_consecutive_losses"
    elif float(overall.get("last_20_expectancy", 0.0)) < float(MIN_EXPECTANCY_LAST_20_TRADES):
        paused = True
        reason = "negative_expectancy_last_20"
    elif float(today.get("realized_pnl", 0.0)) <= float(MAX_DRAWDOWN_DAY):
        paused = True
        reason = "max_daily_drawdown"

    state = _load()
    state["paused"] = paused
    state["reason"] = reason
    _save(state)
    return state


def can_open_new_trade():
    state = evaluate_pause_rules()
    if state.get("paused"):
        return False, state.get("reason")
    return True, "auto_pause_clear"


def resume_risk_if_allowed():
    state = evaluate_pause_rules()
    if state.get("paused"):
        return {"resumed": False, "reason": state.get("reason")}
    state["paused"] = False
    state["reason"] = None
    _save(state)
    return {"resumed": True, "reason": "risk_resumed"}


def get_pause_status():
    return evaluate_pause_rules()
