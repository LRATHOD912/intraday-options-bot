from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

from app.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_DECISION_ENABLED,
    CLAUDE_LOG_PROMPTS,
    CLAUDE_MAX_POSITION_PERCENT,
    CLAUDE_MAX_RETRIES,
    CLAUDE_MIN_CONFIDENCE,
    CLAUDE_MIN_POSITION_PERCENT,
    CLAUDE_MODEL,
    CLAUDE_PAPER_ONLY,
    CLAUDE_REQUIRE_EXISTING_SIGNAL,
    CLAUDE_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)
STATUS_PATH = Path("logs/claude_status.json")

Decision = Literal["CALL", "PUT", "NO_TRADE"]

SUPPORTED_STRATEGIES = {
    "MOMENTUM_BREAKOUT",
    "TREND_PULLBACK",
    "VWAP_BOUNCE",
    "OPENING_RANGE_BREAKOUT",
    "GAP_AND_GO",
    "GAP_FILL_REVERSAL",
    "RANGE_SCALP_0DTE",
    "MEAN_REVERSION_0DTE",
    "MOMENTUM_RUNNER",
    "LATE_DAY_TREND",
    "POWER_HOUR_BREAKOUT",
    "OPENING_REVERSAL",
    "FAILED_BREAKOUT",
    "LIQUIDITY_SWEEP",
    "EXHAUSTION_REVERSAL",
    "TREND_CONTINUATION",
    "CLAUDE_NO_TRADE",
}


@dataclass
class ClaudeTradeDecision:
    decision: Decision
    confidence: float
    strategy: str
    reason: str
    supporting_factors: list[str]
    conflicting_factors: list[str]
    position_size_percent: float
    exit_profile: str
    max_hold_minutes: int
    require_tighter_spread: bool
    risk_notes: list[str]
    model: str
    decided_at: str
    raw_response_id: str | None = None


def no_trade_decision(reason: str) -> ClaudeTradeDecision:
    return ClaudeTradeDecision(
        decision="NO_TRADE",
        confidence=0.0,
        strategy="CLAUDE_NO_TRADE",
        reason=reason,
        supporting_factors=[],
        conflicting_factors=[],
        position_size_percent=0.0,
        exit_profile="baseline",
        max_hold_minutes=0,
        require_tighter_spread=False,
        risk_notes=[reason],
        model=CLAUDE_MODEL,
        decided_at=datetime.now(timezone.utc).isoformat(),
    )


def _default_status() -> dict[str, Any]:
    return {
        "enabled": bool(CLAUDE_DECISION_ENABLED),
        "model": CLAUDE_MODEL,
        "api_status": "disabled" if not CLAUDE_DECISION_ENABLED else "unknown",
        "last_request_at": None,
        "last_success_at": None,
        "last_latency_ms": None,
        "last_error": None,
        "last_decision": None,
    }


def _load_status() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return _default_status()
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _default_status()
    if not isinstance(data, dict):
        return _default_status()
    status = _default_status()
    status.update(data)
    status["enabled"] = bool(CLAUDE_DECISION_ENABLED)
    status["model"] = CLAUDE_MODEL
    return status


def _save_status(status: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_status(**fields: Any) -> dict[str, Any]:
    status = _load_status()
    status.update(fields)
    status["enabled"] = bool(CLAUDE_DECISION_ENABLED)
    status["model"] = CLAUDE_MODEL
    _save_status(status)
    return status


def get_claude_status() -> dict[str, Any]:
    return _load_status()


SYSTEM_PROMPT = """
You are the final decision engine for an intraday QQQ options PAPER
TRADING research bot.

You receive only structured, current market data calculated by the bot.
You have no independent live market-data access. Never invent missing
prices, indicators, news, contracts, or account values.

Your task is to return exactly one decision:

CALL
PUT
NO_TRADE

You are responsible for combining conflicting SOFT signals intelligently.
You must not reject a setup only because one soft score narrowly misses a
threshold when the total evidence is strong.

However, you must be conservative when data is missing, stale, internally
contradictory, or the market is directionless.

BOT CAPABILITIES ALREADY IMPLEMENTED:

Market analysis:
- QQQ/SPY/IWM latest prices
- VWAP
- EMA 9 and EMA 20
- market structure
- previous high/low/close
- opening range
- gap direction and gap-fill status
- support and resistance
- RSI
- rate of change
- volume and relative volume
- ATR and volatility
- candle pattern
- regime classification
- market internals
- news-risk placeholder
- strategy router
- entry-quality score
- confidence score

Strategies:
- MOMENTUM_BREAKOUT
- TREND_PULLBACK
- VWAP_BOUNCE
- OPENING_RANGE_BREAKOUT
- GAP_AND_GO
- GAP_FILL_REVERSAL
- RANGE_SCALP_0DTE
- MEAN_REVERSION_0DTE
- MOMENTUM_RUNNER
- LATE_DAY_TREND
- POWER_HOUR_BREAKOUT
- OPENING_REVERSAL
- FAILED_BREAKOUT
- LIQUIDITY_SWEEP
- EXHAUSTION_REVERSAL
- TREND_CONTINUATION

Execution and risk:
- Alpaca Paper execution
- actual options-contract selection
- multiple positions
- position sizing
- duplicate-position protection
- daily loss control
- max-open-risk control
- partial exits
- breakeven movement
- trailing stops
- trade journal
- dashboard

DECISION PRINCIPLES:

1. Strong directional alignment:
   Prefer a directional trade when structure, VWAP position, opening range,
   gap behavior, and broader scoring agree.

2. Conflicting short-term signals:
   A bullish candle or short-term bounce does not automatically invalidate a
   larger bearish structure. Determine whether it is:
   - continuation,
   - pullback,
   - reversal,
   - or noise.

3. Reversal:
   Require evidence of rejection/exhaustion and confirmation. Do not call a
   simple intraday bounce a reversal without support.

4. Choppy market:
   Prefer NO_TRADE unless a clearly defined range scalp, mean-reversion, or
   VWAP-bounce setup exists.

5. Low-volume market:
   Reduce size or return NO_TRADE unless the structure is unusually clear.

6. High-confidence borderline entry:
   If confidence is strong and entry quality is only slightly below the bot's
   normal threshold, you may approve a reduced-size trade.

7. Direction consistency:
   The returned direction must be consistent with the selected strategy.
   Never return a bullish strategy with PUT or a bearish strategy with CALL.

8. Position size:
   Return a percentage from 0.10 through 0.40 for approved trades.
   Lower quality/conflict means lower size.
   Never return more than 0.40.

9. Hard safety:
   You do not have authority to override:
   - market closed
   - outside trading window
   - invalid/missing contract
   - missing bid/ask
   - excessive spread
   - inadequate liquidity
   - insufficient buying power
   - daily loss block
   - max-risk block
   - duplicate position
   - Alpaca API errors
   - live-trading restrictions

10. Missing or stale data:
    Return NO_TRADE.

11. Do not promise profit.
    Evaluate only the supplied setup.

Return only the required structured decision.
"""


DECISION_TOOL = {
    "name": "submit_trade_decision",
    "description": (
        "Return the final structured paper-trading decision. "
        "Use CALL or PUT only when the supplied evidence supports an "
        "actionable setup. Otherwise return NO_TRADE. This tool never "
        "submits an order and cannot override Python hard-safety checks."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["CALL", "PUT", "NO_TRADE"],
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "strategy": {"type": "string"},
            "reason": {"type": "string"},
            "supporting_factors": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 10,
            },
            "conflicting_factors": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 10,
            },
            "position_size_percent": {
                "type": "number",
                "minimum": 0,
                "maximum": 0.40,
            },
            "exit_profile": {
                "type": "string",
                "enum": [
                    "baseline",
                    "scalp",
                    "balanced",
                    "runner",
                    "adaptive",
                ],
            },
            "max_hold_minutes": {
                "type": "integer",
                "minimum": 0,
                "maximum": 180,
            },
            "require_tighter_spread": {"type": "boolean"},
            "risk_notes": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 10,
            },
        },
        "required": [
            "decision",
            "confidence",
            "strategy",
            "reason",
            "supporting_factors",
            "conflicting_factors",
            "position_size_percent",
            "exit_profile",
            "max_hold_minutes",
            "require_tighter_spread",
            "risk_notes",
        ],
        "additionalProperties": False,
    },
}


def _extract_tool_input(message: Any) -> dict[str, Any] | None:
    for block in getattr(message, "content", []):
        if getattr(block, "type", None) == "tool_use":
            if getattr(block, "name", None) == "submit_trade_decision":
                return dict(getattr(block, "input", {}) or {})
    return None


def _validate_decision(payload: dict[str, Any], market_snapshot: dict[str, Any]) -> ClaudeTradeDecision:
    decision = str(payload.get("decision", "NO_TRADE")).upper()
    if decision not in {"CALL", "PUT", "NO_TRADE"}:
        return no_trade_decision("Claude returned invalid direction")

    confidence = float(payload.get("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(confidence, 1.0))

    size = float(payload.get("position_size_percent", 0.0) or 0.0)
    strategy = str(payload.get("strategy", "CLAUDE_DECISION") or "CLAUDE_DECISION").strip().upper()

    if decision == "NO_TRADE":
        size = 0.0
        strategy = "CLAUDE_NO_TRADE"
    else:
        if confidence < CLAUDE_MIN_CONFIDENCE:
            return no_trade_decision(
                f"Claude confidence {confidence:.2f} below minimum {CLAUDE_MIN_CONFIDENCE:.2f}"
            )
        if strategy not in SUPPORTED_STRATEGIES:
            return no_trade_decision("Claude returned unsupported strategy")
        size = max(CLAUDE_MIN_POSITION_PERCENT, min(size, CLAUDE_MAX_POSITION_PERCENT))

    existing_direction = str(market_snapshot.get("existing_signal", "NO_TRADE")).upper()
    if CLAUDE_REQUIRE_EXISTING_SIGNAL and decision in {"CALL", "PUT"} and existing_direction not in {decision, "NO_TRADE"}:
        return no_trade_decision("Claude direction conflicts with existing signal engine")

    return ClaudeTradeDecision(
        decision=decision,
        confidence=confidence,
        strategy=strategy,
        reason=str(payload.get("reason", "")).strip(),
        supporting_factors=[str(x) for x in payload.get("supporting_factors", [])],
        conflicting_factors=[str(x) for x in payload.get("conflicting_factors", [])],
        position_size_percent=size,
        exit_profile=str(payload.get("exit_profile", "balanced")),
        max_hold_minutes=int(payload.get("max_hold_minutes", 30) or 0),
        require_tighter_spread=bool(payload.get("require_tighter_spread", False)),
        risk_notes=[str(x) for x in payload.get("risk_notes", [])],
        model=CLAUDE_MODEL,
        decided_at=datetime.now(timezone.utc).isoformat(),
    )


def get_claude_trade_decision(market_snapshot: dict[str, Any]) -> ClaudeTradeDecision:
    if not CLAUDE_DECISION_ENABLED:
        decision = no_trade_decision("Claude decision engine disabled")
        _record_status(api_status="disabled", last_error=decision.reason, last_decision=decision_to_dict(decision))
        return decision

    if CLAUDE_PAPER_ONLY and not market_snapshot.get("paper_trading_confirmed", False):
        decision = no_trade_decision("Claude decision engine requires confirmed paper mode")
        _record_status(api_status="paper_only_blocked", last_error=decision.reason, last_decision=decision_to_dict(decision))
        return decision

    if not ANTHROPIC_API_KEY:
        decision = no_trade_decision("ANTHROPIC_API_KEY is missing")
        _record_status(api_status="missing_api_key", last_error=decision.reason, last_decision=decision_to_dict(decision))
        return decision

    if Anthropic is None:
        decision = no_trade_decision("Anthropic SDK is not installed")
        _record_status(api_status="sdk_not_installed", last_error=decision.reason, last_decision=decision_to_dict(decision))
        return decision

    if not market_snapshot:
        decision = no_trade_decision("Market snapshot is empty")
        _record_status(api_status="missing_snapshot", last_error=decision.reason, last_decision=decision_to_dict(decision))
        return decision

    try:
        started_at = datetime.now(timezone.utc).isoformat()
        start = perf_counter()
        _record_status(api_status="requesting", last_request_at=started_at, last_error=None)
        client = Anthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=CLAUDE_TIMEOUT_SECONDS,
            max_retries=CLAUDE_MAX_RETRIES,
        )

        safe_snapshot = json.loads(json.dumps(market_snapshot, default=str))
        if CLAUDE_LOG_PROMPTS:
            logger.info("Claude market snapshot: %s", json.dumps(safe_snapshot))

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1400,
            temperature=0,
            system=SYSTEM_PROMPT,
            tools=[DECISION_TOOL],
            tool_choice={"type": "tool", "name": "submit_trade_decision"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Analyze this current market snapshot and issue the final paper-trading decision.\n\n"
                        + json.dumps(safe_snapshot, separators=(",", ":"))
                    ),
                }
            ],
        )

        tool_payload = _extract_tool_input(response)
        if tool_payload is None:
            decision = no_trade_decision("Claude did not return structured decision")
            latency_ms = round((perf_counter() - start) * 1000, 2)
            _record_status(
                api_status="invalid_response",
                last_success_at=started_at,
                last_latency_ms=latency_ms,
                last_error=decision.reason,
                last_decision=decision_to_dict(decision),
            )
            return decision

        decision = _validate_decision(tool_payload, safe_snapshot)
        decision.raw_response_id = getattr(response, "id", None)
        latency_ms = round((perf_counter() - start) * 1000, 2)
        _record_status(
            api_status="ok",
            last_success_at=decision.decided_at,
            last_latency_ms=latency_ms,
            last_error=None,
            last_decision=decision_to_dict(decision),
        )
        return decision
    except Exception as exc:
        logger.exception("Claude decision request failed")
        decision = no_trade_decision(f"Claude API failure: {type(exc).__name__}")
        _record_status(api_status="error", last_error=decision.reason, last_decision=decision_to_dict(decision))
        return decision


def decision_to_dict(decision: ClaudeTradeDecision) -> dict[str, Any]:
    return asdict(decision)