from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def _coerce_to_new_york_timestamp(value):
    if value is None:
        return None

    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=ZoneInfo("America/New_York"))
        return value.astimezone(ZoneInfo("America/New_York"))

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=ZoneInfo("America/New_York"))
        return parsed.astimezone(ZoneInfo("America/New_York"))

    return None


def final_trade_gate(master_decision, risk_allowed, risk_reason, news_result=None, latest_bar_timestamp=None, trade_plan=None, skip_soft_checks=False):
    if latest_bar_timestamp is not None:
        latest_bar_et = _coerce_to_new_york_timestamp(latest_bar_timestamp)
        if latest_bar_et is not None:
            now_et = datetime.now(ZoneInfo("America/New_York"))
            if now_et - latest_bar_et > timedelta(minutes=20):
                return {"allowed": False, "reason": "Latest market data is stale"}

    if trade_plan is not None and trade_plan.get("valid_rr") is False:
        return {"allowed": False, "reason": "Poor risk/reward"}

    if not risk_allowed:
        return {"allowed": False, "reason": f"Risk block: {risk_reason}"}

    if news_result is not None:
        news_data = news_result.get("data", {}) or {}
        if news_data.get("can_trade") is False:
            return {"allowed": False, "reason": "News block: high-impact event nearby"}

    if not skip_soft_checks:
        if master_decision.get("decision") == "NO TRADE":
            return {"allowed": False, "reason": "Decision is NO TRADE"}

        if master_decision.get("total_score", 0) < 80:
            return {"allowed": False, "reason": f"Score below minimum threshold: {master_decision.get('total_score', 0)}"}

        if master_decision.get("quality") == "NO TRADE":
            return {"allowed": False, "reason": "Quality is NO TRADE"}

    return {"allowed": True, "reason": "Trade allowed by final gate"}
