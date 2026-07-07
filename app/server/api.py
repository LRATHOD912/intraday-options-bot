import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.analytics.performance_tracker import get_summary
from app.analytics.strategy_performance import get_strategy_summary
from app.config import ALPACA_PAPER, API_TOKEN, BOT_END_TIME, BOT_START_TIME, ENABLE_TRADING, EXIT_PROFILE, MIN_ENTRY_QUALITY_SCORE, POSITION_QUANTITY, USE_ALPACA_PAPER_EXECUTION, USE_DYNAMIC_POSITION_SIZE, USE_REGIME_FILTER, USE_TUNED_STAGED_EXITS, VIEW_TOKEN
from app.execution.position_manager import get_open_position, get_open_positions, get_total_open_risk, has_open_position
from app.logs.trade_journal import log_trade_event
from app.main import run_bot_scan
from app.risk.auto_pause import get_pause_status, resume_risk_if_allowed
from app.risk.strategy_control import disable_strategy_for_user, enable_strategy_for_user, strategy_status
from app.market.option_quote import get_option_market_price
from app.runner.bot_runner import get_runner_status, run_scan_once, start_runner, stop_runner

app = FastAPI(title="Intraday Options Bot Control API")


def _read_json_file(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_jsonl(path: Path, limit: int = 100):
    if not path.exists():
        return []

    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if limit <= 0:
        return rows
    return rows[-limit:]


def _friendly_error_text(raw_error):
    text = str(raw_error or "").lower()
    if not text:
        return None
    if "timeout" in text:
        return "API timeout"
    if "rate" in text and "limit" in text:
        return "Rate limit"
    if "closed" in text:
        return "Market closed"
    if "buying power" in text:
        return "Buying power insufficient"
    if "quote" in text:
        return "Quote unavailable"
    if "option" in text and "found" in text:
        return "Option contract not found"
    if "alpaca" in text and "reject" in text:
        return "Alpaca rejected order"
    return "Execution error"


def _build_decision_history(limit: int = 100):
    snapshot = _read_json_file(Path("logs/decision_history_last_100.json"))
    rows = snapshot if isinstance(snapshot, list) else _read_jsonl(Path("logs/decisions.jsonl"), limit=limit)
    rows = rows[-limit:]
    output = []
    for row in rows:
        trace = row.get("trace") or {}
        output.append(
            {
                "timestamp": row.get("timestamp"),
                "symbol": trace.get("symbol") or "QQQ",
                "regime": trace.get("market_regime") or row.get("regime"),
                "trend": trace.get("trend"),
                "vwap_status": trace.get("vwap_status"),
                "ema_status": trace.get("ema_status"),
                "adx": trace.get("adx"),
                "atr": trace.get("atr"),
                "volume_score": trace.get("volume_score"),
                "rsi": trace.get("rsi"),
                "macd": trace.get("macd"),
                "spread": trace.get("option_spread"),
                "delta": trace.get("option_delta"),
                "strategy": trace.get("selected_strategy") or (row.get("strategy_route") or {}).get("strategy_name") or "No strategy",
                "decision": (row.get("master_decision") or {}).get("decision") or "NO_TRADE",
                "confidence": trace.get("confidence"),
                "entry_quality": trace.get("entry_quality") or row.get("entry_quality_score"),
                "entry_quality_score": trace.get("entry_quality") or row.get("entry_quality_score"),
                "adaptive_entry_threshold": trace.get("adaptive_entry_threshold") or row.get("adaptive_entry_threshold"),
                "static_entry_threshold": trace.get("static_entry_threshold") or row.get("static_entry_threshold") or MIN_ENTRY_QUALITY_SCORE,
                "entry_quality_passed": trace.get("entry_quality_passed") if trace.get("entry_quality_passed") is not None else row.get("entry_quality_passed"),
                "entry_quality_gap": trace.get("entry_quality_gap") if trace.get("entry_quality_gap") is not None else row.get("entry_quality_gap"),
                "regime_risk_multiplier": trace.get("regime_risk_multiplier") or row.get("regime_risk_multiplier"),
                "regime_note": trace.get("regime_note") or row.get("regime_note"),
                "accepted": bool(trace.get("accepted", (row.get("gate_result") or {}).get("allowed"))),
                "reason": trace.get("reason") or (row.get("gate_result") or {}).get("reason"),
                "reason_exact": trace.get("reason_exact") or row.get("rejection_reason") or trace.get("reason") or (row.get("gate_result") or {}).get("reason"),
                "reason_raw": trace.get("reason_raw") or (row.get("gate_result") or {}).get("reason"),
                "contract": trace.get("selected_option_contract"),
                "rejected_by_gate": trace.get("rejected_by_gate") or row.get("rejected_by_gate") or (row.get("gate_result") or {}).get("gate"),
                "next_retry_at": row.get("next_retry_at"),
            }
        )
    return output


def _read_latest_decision():
        return (_read_jsonl(Path("logs/decisions.jsonl"), limit=1) or [None])[0]


def _read_risk_state():
        return _read_json_file(Path("logs/daily_risk_state.json")) or {
                "date": None,
                "trades_today": 0,
                "losses_today": 0,
                "realized_pnl": 0.0,
        }


def _enrich_positions(positions):
        enriched = []
        for position in positions:
                current_price = None
                quote = None
                try:
                        quote = get_option_market_price(position.get("option_symbol"))
                except Exception:
                        quote = None
                if quote is not None:
                        current_price = quote.get("price")
                enriched.append(
                        {
                                **position,
                                "current_price": current_price,
                                "quote": quote,
                        }
                )
        return enriched


def _build_dashboard_payload():
        runner = get_runner_status()
        positions = _enrich_positions(get_open_positions())
        latest_decision = _read_latest_decision()
        risk_state = _read_risk_state()
        risk_state["total_open_risk"] = round(get_total_open_risk(), 2)

        config_summary = {
                "enable_trading": ENABLE_TRADING,
                "alpaca_paper": ALPACA_PAPER,
                "use_alpaca_paper_execution": USE_ALPACA_PAPER_EXECUTION,
                "use_regime_filter": USE_REGIME_FILTER,
                "min_entry_quality_score": MIN_ENTRY_QUALITY_SCORE,
                "use_dynamic_position_size": USE_DYNAMIC_POSITION_SIZE,
                "position_quantity": POSITION_QUANTITY,
                "exit_profile": EXIT_PROFILE,
                "use_tuned_staged_exits": USE_TUNED_STAGED_EXITS,
        }

        latest_trace = (latest_decision or {}).get("trace") if isinstance(latest_decision, dict) else {}
        if not isinstance(latest_trace, dict):
            latest_trace = {}
        last_scan_at_raw = runner.get("last_scan_at")
        next_retry_time = None
        if isinstance(last_scan_at_raw, str):
            try:
                next_retry_time = (datetime.fromisoformat(last_scan_at_raw) + timedelta(seconds=60)).isoformat()
            except ValueError:
                next_retry_time = None

        trade_found = bool((latest_decision or {}).get("trade_found", (latest_decision or {}).get("master_decision", {}).get("decision") in ["CALL", "PUT"]))
        trade_rejected = bool((latest_decision or {}).get("trade_rejected", not bool((latest_decision or {}).get("gate_result", {}).get("allowed", True))))
        exact_rejection_reason = (
            (latest_decision or {}).get("rejection_reason")
            or latest_trace.get("reason_exact")
            or latest_trace.get("reason")
            or (latest_decision or {}).get("gate_result", {}).get("reason")
            or "No rejection"
        )
        rejected_by_gate = (
            (latest_decision or {}).get("rejected_by_gate")
            or latest_trace.get("rejected_by_gate")
            or (latest_decision or {}).get("gate_result", {}).get("gate")
            or "none"
        )
        adaptive_entry_threshold = (latest_decision or {}).get("adaptive_entry_threshold") or latest_trace.get("adaptive_entry_threshold")
        static_entry_threshold = (latest_decision or {}).get("static_entry_threshold") or latest_trace.get("static_entry_threshold") or MIN_ENTRY_QUALITY_SCORE
        entry_quality_value = latest_trace.get("entry_quality") or (latest_decision or {}).get("entry_quality_score")
        entry_quality_passed = (latest_decision or {}).get("entry_quality_passed")
        if entry_quality_passed is None and entry_quality_value is not None and adaptive_entry_threshold is not None:
            try:
                entry_quality_passed = float(entry_quality_value) >= float(adaptive_entry_threshold)
            except (TypeError, ValueError):
                entry_quality_passed = None
        entry_quality_gap = (latest_decision or {}).get("entry_quality_gap")
        if entry_quality_gap is None and entry_quality_value is not None and adaptive_entry_threshold is not None:
            try:
                entry_quality_gap = float(entry_quality_value) - float(adaptive_entry_threshold)
            except (TypeError, ValueError):
                entry_quality_gap = None
        regime_risk_multiplier = (latest_decision or {}).get("regime_risk_multiplier") or latest_trace.get("regime_risk_multiplier")
        regime_note = (latest_decision or {}).get("regime_note") or latest_trace.get("regime_note")

        strategy_state = strategy_status()
        strategy_perf = get_strategy_summary(limit=20)
        disabled_details = []
        for name in (strategy_state.get("disabled_strategies") or []):
            bucket = (strategy_perf.get("strategies") or {}).get(name, {})
            disabled_details.append(
                {
                    "name": name,
                    "status": "Disabled",
                    "disabled_at": bucket.get("disabled_until"),
                    "reason": bucket.get("disabled_reason") or "Unknown",
                }
            )
        decision_history = _build_decision_history(limit=100)

        account_snapshot = _read_json_file(Path("logs/account_snapshot.json")) or {}
        call_exposure = 0.0
        put_exposure = 0.0
        for position in positions:
            qty = float(position.get("remaining_quantity") or position.get("quantity") or 0)
            price = float(position.get("current_price") or position.get("entry_price") or 0)
            exposure = qty * price * 100.0
            if str(position.get("direction", "")).upper() == "CALL":
                call_exposure += exposure
            elif str(position.get("direction", "")).upper() == "PUT":
                put_exposure += exposure

        today_perf = (get_summary(limit_last=20) or {}).get("today", {})
        overall_perf = (get_summary(limit_last=20) or {}).get("overall", {})

        return {
                "status": {
                        "running": runner.get("running"),
                        "thread_alive": runner.get("thread_alive"),
                        "started_at": runner.get("started_at"),
                        "last_scan_at": runner.get("last_scan_at"),
                        "last_error": runner.get("last_error"),
                        "open_positions_count": len(positions),
                        "current_regime": latest_trace.get("market_regime") or (latest_decision or {}).get("regime"),
                        "current_strategy": latest_trace.get("selected_strategy") or ((latest_decision or {}).get("strategy_route") or {}).get("strategy_name"),
                        "current_confidence": latest_trace.get("confidence") or ((latest_decision or {}).get("strategy_route") or {}).get("confidence"),
                        "current_entry_quality": latest_trace.get("entry_quality") or (latest_decision or {}).get("entry_quality_score"),
                        "friendly_last_error": _friendly_error_text(runner.get("last_error")),
                        "trade_found": trade_found,
                        "trade_rejected": trade_rejected,
                        "exact_rejection_reason": exact_rejection_reason,
                        "rejected_by_gate": rejected_by_gate,
                        "next_retry_time": (latest_decision or {}).get("next_retry_at") or next_retry_time,
                        "adaptive_entry_threshold": adaptive_entry_threshold,
                        "static_entry_threshold": static_entry_threshold,
                        "regime_risk_multiplier": regime_risk_multiplier,
                        "regime_note": regime_note,
                        "entry_quality_passed": entry_quality_passed,
                        "entry_quality_gap": entry_quality_gap,
                },
                "positions": positions,
                "risk": risk_state,
                "orders": _read_jsonl(Path("logs/paper_orders.jsonl"), limit=20),
                "journal": _read_jsonl(Path("logs/trade_journal.jsonl"), limit=20),
                "performance": get_summary(limit_last=20),
                "strategy_performance": get_strategy_summary(limit=20),
                    "strategy_status": strategy_state,
                    "strategy_disabled_details": disabled_details,
                "config_summary": config_summary,
                "last_scan_decision": latest_decision,
                    "decision_history": decision_history,
                    "health": {
                        "scanner_running": bool(runner.get("running")),
                        "monitor_running": bool(runner.get("thread_alive")),
                        "scheduler_running": bool(runner.get("running")),
                        "broker_connected": True,
                        "alpaca_connected": bool(USE_ALPACA_PAPER_EXECUTION),
                        "market_data_connected": True,
                        "options_feed_connected": True,
                        "last_successful_scan": runner.get("last_scan_at"),
                        "last_successful_order": (_read_jsonl(Path("logs/paper_orders.jsonl"), limit=1) or [{}])[-1].get("timestamp"),
                        "last_successful_exit": (_read_jsonl(Path("logs/trade_journal.jsonl"), limit=20) or [{}])[-1].get("timestamp"),
                        "heartbeat": datetime.now().isoformat(),
                    },
                    "metrics": {
                        "today_pnl": today_perf.get("realized_pnl", 0.0),
                        "weekly_pnl": overall_perf.get("last_5_days_realized_pnl", 0.0),
                        "monthly_pnl": overall_perf.get("last_20_days_realized_pnl", 0.0),
                        "profit_factor": overall_perf.get("profit_factor", 0.0),
                        "win_rate": overall_perf.get("win_rate", 0.0),
                        "average_r": overall_perf.get("average_r", 0.0),
                        "expectancy": overall_perf.get("expectancy", 0.0),
                        "largest_winner": overall_perf.get("largest_win", 0.0),
                        "largest_loser": overall_perf.get("largest_loss", 0.0),
                        "consecutive_wins": overall_perf.get("consecutive_wins", 0),
                        "consecutive_losses": overall_perf.get("consecutive_losses", 0),
                        "max_drawdown": overall_perf.get("max_drawdown", 0.0),
                        "current_exposure": call_exposure + put_exposure,
                        "call_exposure": call_exposure,
                        "put_exposure": put_exposure,
                        "buying_power": account_snapshot.get("buying_power"),
                        "used_buying_power": account_snapshot.get("used_buying_power"),
                    },
                # Backward-compatible fields.
                "bot": {
                        "running": runner.get("running"),
                        "thread_alive": runner.get("thread_alive"),
                        "started_at": runner.get("started_at"),
                        "last_scan_at": runner.get("last_scan_at"),
                        "last_error": runner.get("last_error"),
                },
                "position": positions[0] if positions else None,
                "risk_today": risk_state,
                "pause_status": get_pause_status(),
                "journal_last_10": _read_jsonl(Path("logs/trade_journal.jsonl"), limit=10),
                "orders_last_10": _read_jsonl(Path("logs/paper_orders.jsonl"), limit=10),
                "active_strategy": (positions[0] or {}).get("strategy_name") if positions else ((latest_decision or {}).get("strategy_route") or {}).get("strategy_name"),
                "last_strategy_decision": (latest_decision or {}).get("strategy_route"),
                "current_qqq_price": (latest_decision or {}).get("market_price"),
                "current_option_contract": (positions[0] or {}).get("option_symbol") if positions else None,
        }


def _build_ui_html(api_token: str) -> str:
        token_js = json.dumps(api_token)
        return f"""<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Intraday Options Bot</title>
    <style>
        :root {{
            color-scheme: light;
            --bg: #08111f;
            --panel: rgba(255, 255, 255, 0.92);
            --ink: #0f172a;
            --muted: #64748b;
            --line: rgba(148, 163, 184, 0.28);
            --accent: #0f766e;
            --accent-2: #2563eb;
            --danger: #b42318;
            --shadow: 0 18px 45px rgba(2, 8, 23, 0.22);
        }}
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif; min-height: 100vh; color: var(--ink); background:
            radial-gradient(circle at top left, rgba(37, 99, 235, 0.32), transparent 28%),
            radial-gradient(circle at top right, rgba(124, 58, 237, 0.28), transparent 24%),
            radial-gradient(circle at 30% 100%, rgba(15, 118, 110, 0.18), transparent 24%),
            linear-gradient(180deg, #06101d 0%, #0f172a 34%, #111c34 100%); }}
        body::before {{ content: ''; position: fixed; inset: 0; pointer-events: none; background-image: linear-gradient(rgba(148, 163, 184, 0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(148, 163, 184, 0.08) 1px, transparent 1px); background-size: 36px 36px; mask-image: linear-gradient(180deg, rgba(0,0,0,0.85), transparent 88%); }}
        .wrap {{ max-width: 1280px; margin: 0 auto; padding: 16px; }}
        .hero {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; margin-bottom: 14px; padding: 18px; border-radius: 24px; background: linear-gradient(135deg, rgba(15, 23, 42, 0.9), rgba(30, 41, 59, 0.82), rgba(12, 74, 110, 0.72)); border: 1px solid rgba(255,255,255,0.12); box-shadow: var(--shadow); color: white; position: relative; overflow: hidden; }}
        .hero::after {{ content: ''; position: absolute; inset: auto -80px -70px auto; width: 220px; height: 220px; border-radius: 50%; background: radial-gradient(circle, rgba(34, 211, 238, 0.35), rgba(34, 211, 238, 0)); }}
        .hero h1 {{ margin: 0; font-size: 1.2rem; letter-spacing: -0.02em; }}
        .hero .muted {{ color: rgba(226, 232, 240, 0.8); }}
        .pill {{ display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 999px; background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.18); box-shadow: var(--shadow); font-size: 0.88rem; color: white; backdrop-filter: blur(10px); }}
        .grid {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 12px; }}
        .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 14px; box-shadow: var(--shadow); min-width: 0; position: relative; overflow: hidden; backdrop-filter: blur(10px); }}
        .card::before {{ content: ''; position: absolute; inset: 0 auto auto 0; width: 100%; height: 4px; background: linear-gradient(90deg, #2563eb, #7c3aed, #ea580c); }}
        .card-controls::before {{ background: linear-gradient(90deg, #22c55e, #14b8a6, #0ea5e9); }}
        .card-status::before {{ background: linear-gradient(90deg, #2563eb, #38bdf8, #14b8a6); }}
        .card-risk::before {{ background: linear-gradient(90deg, #f59e0b, #f97316, #ef4444); }}
        .card-decision::before {{ background: linear-gradient(90deg, #7c3aed, #a855f7, #ec4899); }}
        .card-positions::before {{ background: linear-gradient(90deg, #06b6d4, #0ea5e9, #3b82f6); }}
        .card-orders::before {{ background: linear-gradient(90deg, #ea580c, #f59e0b, #f43f5e); }}
        .card-journal::before {{ background: linear-gradient(90deg, #db2777, #f472b6, #8b5cf6); }}
        .card-strategy::before {{ background: linear-gradient(90deg, #14b8a6, #0f766e, #2563eb); }}
        .span-12 {{ grid-column: span 12; }}
        .span-8 {{ grid-column: span 8; }}
        .span-6 {{ grid-column: span 6; }}
        .span-4 {{ grid-column: span 4; }}
        .span-3 {{ grid-column: span 3; }}
        h2 {{ font-size: 0.95rem; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 0.08em; color: #0f172a; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
        .stat {{ padding: 10px 12px; border-radius: 14px; background: linear-gradient(180deg, rgba(248, 250, 252, 0.96), rgba(241, 245, 249, 0.98)); border: 1px solid rgba(148, 163, 184, 0.22); box-shadow: inset 0 1px 0 rgba(255,255,255,0.75); }}
        .stat .label {{ display: block; color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px; }}
        .stat .value {{ font-size: 1rem; font-weight: 700; word-break: break-word; color: #0f172a; }}
        .actions {{ display: flex; flex-wrap: wrap; gap: 8px; }}
        button, .btn {{ border: 0; border-radius: 12px; padding: 10px 14px; cursor: pointer; font-weight: 700; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; }}
        .btn-primary {{ background: linear-gradient(135deg, #2563eb, #7c3aed); color: white; box-shadow: 0 10px 22px rgba(37, 99, 235, 0.28); }}
        .btn-secondary {{ background: linear-gradient(135deg, #e0f2fe, #dbeafe); color: #0f2d66; }}
        .btn-danger {{ background: linear-gradient(135deg, #fee2e2, #fecaca); color: var(--danger); }}
        .btn-dark {{ background: linear-gradient(135deg, #0f172a, #1f2937); color: white; }}
        .table-wrap {{ overflow-x: auto; border-radius: 14px; border: 1px solid rgba(148, 163, 184, 0.24); box-shadow: inset 0 1px 0 rgba(255,255,255,0.7); }}
        table {{ width: 100%; border-collapse: collapse; min-width: 860px; background: rgba(255,255,255,0.96); }}
        th, td {{ padding: 10px 12px; border-bottom: 1px solid rgba(148, 163, 184, 0.18); text-align: left; vertical-align: top; font-size: 0.9rem; }}
        th {{ background: linear-gradient(180deg, #f8fafc, #eef2ff); color: #475569; position: sticky; top: 0; }}
        tbody tr:nth-child(even) {{ background: rgba(248, 250, 252, 0.8); }}
        tbody tr:hover {{ background: rgba(219, 234, 254, 0.45); }}
        .footer-mark {{
            margin: 18px 4px 0;
            padding: 12px 16px;
            border-radius: 999px;
            display: inline-flex;
            align-items: center;
            gap: 10px;
            color: rgba(226, 232, 240, 0.9);
            background: rgba(15, 23, 42, 0.72);
            border: 1px solid rgba(255, 255, 255, 0.12);
            box-shadow: var(--shadow);
            backdrop-filter: blur(10px);
            letter-spacing: 0.02em;
            font-size: 0.86rem;
        }}
        .footer-mark strong {{
            color: #ffffff;
            font-weight: 800;
        }}
        .muted {{ color: var(--muted); }}
        .mono {{ font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
        @media (max-width: 960px) {{
            .span-8, .span-6, .span-4, .span-3 {{ grid-column: span 12; }}
            .wrap {{ padding: 12px; }}
            .hero h1 {{ font-size: 1.05rem; }}
        }}
    </style>
</head>
<body>
    <div class=\"wrap\">
        <div class=\"hero\">
            <div>
                <h1>Intraday Options Bot</h1>
                        <div class="muted">Command deck for market structure, flow, and volatility</div>
            </div>
            <div class=\"pill mono\" id=\"last-refresh\">Loading...</div>
        </div>

        <div class=\"grid\">
            <div class=\"card card-controls span-12\">
                <h2>Bot Controls</h2>
                <div class=\"actions\">
                    <button class=\"btn btn-primary\" onclick=\"callEndpoint('/start', 'POST')\">Start</button>
                    <button class=\"btn btn-danger\" onclick=\"callEndpoint('/stop', 'POST')\">Stop</button>
                    <button class=\"btn btn-secondary\" onclick=\"callEndpoint('/scan-once', 'POST')\">Scan Once</button>
                    <button class=\"btn btn-dark\" onclick=\"refreshDashboard()\">Refresh</button>
                </div>
            </div>

            <div class=\"card card-status span-4\">
                <h2>Status</h2>
                <div class=\"stats\" id=\"status-card\"></div>
            </div>

            <div class=\"card card-risk span-4\">
                <h2>Daily Risk</h2>
                <div class=\"stats\" id=\"risk-card\"></div>
            </div>

            <div class=\"card card-decision span-4\">
                <h2>Strategy / Decision</h2>
                <div class=\"stats\" id=\"decision-card\"></div>
            </div>

            <div class=\"card card-positions span-12\">
                <h2>Positions</h2>
                <div class=\"table-wrap\"><table id=\"positions-table\"></table></div>
            </div>

            <div class=\"card card-orders span-6\">
                <h2>Orders</h2>
                <div class=\"table-wrap\"><table id=\"orders-table\"></table></div>
            </div>

            <div class=\"card card-journal span-6\">
                <h2>Journal</h2>
                <div class=\"table-wrap\"><table id=\"journal-table\"></table></div>
            </div>

            <div class=\"card card-strategy span-12\">
                <h2>Strategy Summary</h2>
                <div class=\"stats\" id=\"strategy-card\"></div>
            </div>
        </div>
        <div class="footer-mark">Designed by <strong>Lolla</strong> for the tape</div>
    </div>

    <script>
        const API_TOKEN = {token_js};
        async function callEndpoint(path, method='GET') {{
            const response = await fetch(`${{path}}?api_token=${{encodeURIComponent(API_TOKEN)}}`, {{ method }});
            await refreshDashboard();
            return response;
        }}

        function statCard(label, value) {{
            return `<div class=\"stat\"><span class=\"label\">${{label}}</span><span class=\"value mono\">${{value ?? 'ΓÇö'}}</span></div>`;
        }}

        function tableFromRows(tableId, rows, columns) {{
            const table = document.getElementById(tableId);
            if (!rows || rows.length === 0) {{
                table.innerHTML = '<thead><tr>' + columns.map(c => `<th>${{c.label}}</th>`).join('') + '</tr></thead><tbody><tr><td colspan="' + columns.length + '" class="muted">No data</td></tr></tbody>';
                return;
            }}
            const head = '<thead><tr>' + columns.map(c => `<th>${{c.label}}</th>`).join('') + '</tr></thead>';
            const body = '<tbody>' + rows.map(row => '<tr>' + columns.map(c => `<td>${{row[c.key] ?? 'ΓÇö'}}</td>`).join('') + '</tr>').join('') + '</tbody>';
            table.innerHTML = head + body;
        }}

        async function refreshDashboard() {{
            const response = await fetch(`/dashboard?api_token=${{encodeURIComponent(API_TOKEN)}}`);
            const data = await response.json();
            document.getElementById('last-refresh').textContent = 'Last refresh: ' + new Date().toLocaleTimeString();

            const status = data.status || {{}};
            document.getElementById('status-card').innerHTML = [
                statCard('running', status.running),
                statCard('thread_alive', status.thread_alive),
                statCard('last_scan_at', status.last_scan_at),
                statCard('last_error', status.last_error || 'none'),
            ].join('');

            const risk = data.risk || {{}};
            document.getElementById('risk-card').innerHTML = [
                statCard('trades_today', risk.trades_today),
                statCard('losses_today', risk.losses_today),
                statCard('realized_pnl', risk.realized_pnl),
                statCard('total_open_risk', risk.total_open_risk),
            ].join('');

            const decision = data.last_scan_decision || {{}};
            const route = decision.strategy_route || {{}};
            document.getElementById('decision-card').innerHTML = [
                statCard('strategy', route.strategy_name || 'ΓÇö'),
                statCard('confidence', route.confidence ?? 'ΓÇö'),
                statCard('regime', decision.regime || 'ΓÇö'),
                statCard('entry_quality', decision.entry_quality_score ?? 'ΓÇö'),
                statCard('adaptive_threshold', status.adaptive_entry_threshold ?? 'ΓÇö'),
                statCard('static_threshold', status.static_entry_threshold ?? 'ΓÇö'),
                statCard('regime_risk_multiplier', status.regime_risk_multiplier ?? 'ΓÇö'),
                statCard('regime_note', status.regime_note || 'ΓÇö'),
                statCard('entry_quality_passed', status.entry_quality_passed ? 'PASS' : 'FAIL'),
                statCard('entry_quality_gap', status.entry_quality_gap ?? 'ΓÇö'),
                statCard('trade_found', status.trade_found ? 'YES' : 'NO'),
                statCard('trade_rejected', status.trade_rejected ? 'YES' : 'NO'),
                statCard('rejected_by_gate', status.rejected_by_gate || 'none'),
                statCard('exact_rejection_reason', status.exact_rejection_reason || 'none'),
                statCard('next_retry_time', status.next_retry_time || 'unknown'),
            ].join('');

            const positions = (data.positions || []).map(p => ({{
                position_id: p.position_id,
                option_symbol: p.option_symbol,
                direction: p.direction,
                quantity: p.quantity,
                remaining_quantity: p.remaining_quantity,
                entry_price: p.entry_price,
                current_price: p.current_price,
                stop_price: p.stop_price,
                target_1x: p.target_1x,
                target_2x: p.target_2x,
                target_3x: p.target_3x,
                target_4x: p.target_4x,
                realized_pnl: p.realized_pnl,
                status: p.status,
            }}));
            tableFromRows('positions-table', positions, [
                {{ key: 'position_id', label: 'position_id' }},
                {{ key: 'option_symbol', label: 'option_symbol' }},
                {{ key: 'direction', label: 'direction' }},
                {{ key: 'quantity', label: 'quantity' }},
                {{ key: 'remaining_quantity', label: 'remaining' }},
                {{ key: 'entry_price', label: 'entry' }},
                {{ key: 'current_price', label: 'current' }},
                {{ key: 'stop_price', label: 'stop' }},
                {{ key: 'target_1x', label: '1x' }},
                {{ key: 'target_2x', label: '2x' }},
                {{ key: 'target_3x', label: '3x' }},
                {{ key: 'target_4x', label: '4x' }},
                {{ key: 'realized_pnl', label: 'pnl' }},
                {{ key: 'status', label: 'status' }},
            ]);

            tableFromRows('orders-table', data.orders || [], [
                {{ key: 'timestamp', label: 'timestamp' }},
                {{ key: 'symbol', label: 'symbol' }},
                {{ key: 'side', label: 'side' }},
                {{ key: 'qty', label: 'qty' }},
                {{ key: 'status', label: 'status' }},
                {{ key: 'broker', label: 'broker' }},
            ]);

            tableFromRows('journal-table', data.journal || [], [
                {{ key: 'timestamp', label: 'timestamp' }},
                {{ key: 'event_type', label: 'event' }},
                {{ key: 'payload', label: 'payload' }},
            ]);

            const strategyPerformance = data.strategy_performance?.strategies || {{}};
            const strategyRows = Object.entries(strategyPerformance).map(([name, row]) => ({{
                name,
                trades: row.trades,
                win_rate: row.win_rate,
                avg_R: row.average_r,
                expectancy: row.expectancy,
                profit_factor: row.profit_factor,
                max_drawdown: row.max_drawdown,
                disabled: row.disabled,
            }}));
            document.getElementById('strategy-card').innerHTML = strategyRows.length
                ? strategyRows.map(row => statCard(row.name, `trades ${{row.trades}} | PF ${{Number(row.profit_factor).toFixed(2)}} | exp ${{Number(row.expectancy).toFixed(2)}} | disabled ${{row.disabled}}`)).join('')
                : '<div class="muted">No strategy performance yet</div>';
        }}

        refreshDashboard();
        setInterval(refreshDashboard, 15000);
    </script>
</body>
</html>"""


def require_api_token(
    x_api_token: str = Header(default=None, alias="X-API-Token"),
    api_token: str = Query(default=None),
):
    if not API_TOKEN:
        raise HTTPException(status_code=500, detail="API_TOKEN is not configured")
    provided = x_api_token or api_token
    if provided != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def require_view_token(token: str = Query(default=None)):
    if not VIEW_TOKEN or token != VIEW_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def _build_public_dashboard_payload():
    payload = _build_dashboard_payload()
    status = payload.get("status", {})
    risk = payload.get("risk", {})
    decision = payload.get("last_scan_decision") or {}
    performance = payload.get("performance") or {}
    pause_status = payload.get("pause_status") or {}

    now = datetime.now()
    try:
        start_h, start_m = [int(v) for v in BOT_START_TIME.split(":", 1)]
        end_h, end_m = [int(v) for v in BOT_END_TIME.split(":", 1)]
        start_minutes = (start_h * 60) + start_m
        end_minutes = (end_h * 60) + end_m
    except Exception:
        start_minutes = 9 * 60 + 45
        end_minutes = 12 * 60
    now_minutes = now.hour * 60 + now.minute

    if now_minutes < 9 * 60 + 30:
        market_session = "Pre-market"
    elif now_minutes < start_minutes:
        market_session = "Waiting for strategy window"
    elif now_minutes <= end_minutes:
        market_session = "Strategy window active"
    elif now_minutes <= 16 * 60:
        market_session = "After hours"
    else:
        market_session = "After hours"

    strategy_route = decision.get("strategy_route") if isinstance(decision, dict) else {}
    if not isinstance(strategy_route, dict):
        strategy_route = {}

    strategy_state = payload.get("strategy_status") or {}
    enabled_strategies = strategy_state.get("enabled_strategies") or strategy_state.get("enabled") or []
    disabled_strategies = strategy_state.get("disabled_strategies") or strategy_state.get("disabled") or []

    reason = decision.get("reason") or decision.get("skip_reason") or decision.get("rejection_reason") or status.get("last_error") or "No reason recorded yet"
    trace_reason = ((decision.get("trace") or {}).get("reason") if isinstance(decision, dict) else None)
    if trace_reason:
        reason = trace_reason
    last_decision = strategy_route.get("decision") or strategy_route.get("strategy_name") or decision.get("signal") or "No decision yet"
    active_strategy = strategy_route.get("strategy_name") or payload.get("active_strategy") or "No strategy selected yet"

    explanation_reasons = []
    if not status.get("last_scan_at"):
        explanation_reasons.append("Bot has not scanned yet")
    if not status.get("running"):
        explanation_reasons.append("Bot is currently stopped")
    if market_session in ("Pre-market", "After hours"):
        explanation_reasons.append("Market closed")
    elif market_session == "Waiting for strategy window":
        explanation_reasons.append("Outside strategy window")
    if pause_status.get("paused"):
        explanation_reasons.append("Risk blocked")
    if not explanation_reasons:
        explanation_reasons.append("No valid setup")

    positions = payload.get("positions") or []
    position_cards = []
    for p in positions:
        entry = p.get("entry_price") or 0
        current = p.get("current_price") if p.get("current_price") is not None else entry
        qty = p.get("quantity") or 0
        remaining_qty = p.get("remaining_quantity") if p.get("remaining_quantity") is not None else qty
        pnl_value = p.get("realized_pnl")
        if pnl_value is None:
            try:
                pnl_value = (float(current) - float(entry)) * float(remaining_qty) * 100
                if str(p.get("direction", "")).upper() == "PUT":
                    pnl_value = (float(entry) - float(current)) * float(remaining_qty) * 100
            except Exception:
                pnl_value = 0
        try:
            pnl_pct = ((float(current) - float(entry)) / float(entry) * 100) if float(entry) else 0
            if str(p.get("direction", "")).upper() == "PUT":
                pnl_pct = ((float(entry) - float(current)) / float(entry) * 100) if float(entry) else 0
        except Exception:
            pnl_pct = 0
        position_cards.append(
            {
                "option_symbol": p.get("option_symbol"),
                "direction": p.get("direction"),
                "quantity": qty,
                "remaining_quantity": remaining_qty,
                "entry": entry,
                "current_price": current,
                "pnl_dollar": round(float(pnl_value or 0), 2),
                "pnl_percent": round(float(pnl_pct or 0), 2),
                "stop": p.get("stop_price"),
                "targets": [p.get("target_1x"), p.get("target_2x"), p.get("target_3x"), p.get("target_4x")],
                "holding_time": p.get("holding_time") or "N/A",
                "broker": p.get("broker") or "paper",
            }
        )

    today = performance.get("today") or {}
    overall = performance.get("overall") or {}
    trades_today = today.get("trades", risk.get("trades_today", 0))
    wins_today = today.get("wins", max(int(trades_today or 0) - int(risk.get("losses_today", 0) or 0), 0))
    losses_today = today.get("losses", risk.get("losses_today", 0))
    win_rate_today = today.get("win_rate")
    if win_rate_today is None:
        try:
            win_rate_today = (float(wins_today) / float(trades_today)) if trades_today else 0.0
        except Exception:
            win_rate_today = 0.0

    account_snapshot = _read_json_file(Path("logs/account_snapshot.json")) or {}
    buying_power = account_snapshot.get("buying_power")

    return {
        "status": {
            "running": bool(status.get("running")),
            "bot_state": "BOT RUNNING" if status.get("running") else "BOT STOPPED",
            "market_session": market_session,
            "last_scan_at": status.get("last_scan_at"),
            "last_scan_age_seconds": None,
            "last_decision": last_decision,
            "last_reason": reason,
            "active_strategy": active_strategy,
            "current_regime": decision.get("regime") or "Unknown",
            "strategy_confidence": strategy_route.get("confidence"),
            "entry_quality_score": decision.get("entry_quality_score"),
            "adaptive_entry_threshold": status.get("adaptive_entry_threshold"),
            "static_entry_threshold": status.get("static_entry_threshold"),
            "regime_risk_multiplier": status.get("regime_risk_multiplier"),
            "regime_note": status.get("regime_note"),
            "entry_quality_passed": status.get("entry_quality_passed"),
            "entry_quality_gap": status.get("entry_quality_gap"),
            "open_positions_count": status.get("open_positions_count", 0),
            "trade_found": status.get("trade_found"),
            "trade_rejected": status.get("trade_rejected"),
            "exact_rejection_reason": status.get("exact_rejection_reason"),
            "rejected_by_gate": status.get("rejected_by_gate"),
            "next_retry_time": status.get("next_retry_time"),
        },
        "performance": {
            "today_pnl": today.get("realized_pnl", risk.get("realized_pnl", 0.0)),
            "realized_pnl": today.get("realized_pnl", risk.get("realized_pnl", 0.0)),
            "trades_today": trades_today,
            "wins": wins_today,
            "losses": losses_today,
            "win_rate": win_rate_today,
            "open_positions": status.get("open_positions_count", 0),
            "profit_factor": overall.get("profit_factor"),
            "buying_power": buying_power,
            "bot_running": bool(status.get("running")),
        },
        "risk": risk,
        "orders": payload.get("orders_last_10") or payload.get("orders", [])[:10],
        "journal": payload.get("journal_last_10") or payload.get("journal", [])[:10],
        "decision_history": payload.get("decision_history", [])[-20:],
        "last_scan_decision": decision,
        "last_skipped_reason": decision.get("skip_reason") or decision.get("rejection_reason") or reason,
        "strategy": {
            "regime": decision.get("regime") or "Unknown",
            "current_strategy": active_strategy,
            "strategy_confidence": strategy_route.get("confidence"),
            "entry_quality_score": decision.get("entry_quality_score"),
            "enabled_strategies": enabled_strategies,
            "disabled_strategies": disabled_strategies,
        },
        "positions": position_cards,
        "position_explanations": explanation_reasons,
    }


def _build_public_dashboard_html(view_token: str) -> str:
    token_js = json.dumps(view_token)
    return """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Intraday Options Bot | Public View</title>
    <style>
        :root { color-scheme: dark; --bg: #07111f; --panel: rgba(15, 23, 42, 0.92); --ink: #e5eefc; --muted: #93a4be; --line: rgba(148, 163, 184, 0.18); --good: #4ade80; --bad: #f87171; }
        * { box-sizing: border-box; }
        body { margin: 0; min-height: 100vh; font-family: Inter, system-ui, sans-serif; background: radial-gradient(circle at top left, rgba(37,99,235,.25), transparent 28%), linear-gradient(180deg, #050a12, var(--bg)); color: var(--ink); }
        .wrap { max-width: 1120px; margin: 0 auto; padding: 16px; }
        .hero, .panel, .card { background: var(--panel); border: 1px solid var(--line); border-radius: 20px; box-shadow: 0 18px 45px rgba(0,0,0,.28); }
        .hero { padding: 16px; margin-bottom: 12px; }
        .hero h1 { margin: 0; font-size: 1.32rem; letter-spacing: -0.02em; }
        .hero p, .hint { margin: 6px 0 0; color: var(--muted); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 12px; }
        .grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 12px; }
        .card { padding: 12px; }
        .label { display: block; color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: .08em; }
        .value { display: block; margin-top: 6px; font-size: 1.1rem; font-weight: 800; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--line); font-size: 0.75rem; color: var(--ink); background: rgba(255,255,255,.06); }
        .positions { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
        .position { padding: 12px; border-radius: 16px; background: rgba(255,255,255,.04); }
        .status { display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 999px; background: rgba(255,255,255,.08); margin-top: 12px; }
        .dot { width: 10px; height: 10px; border-radius: 999px; background: #4ade80; }
        .dot.off { background: #f87171; }
        .section-title { margin: 0 0 10px; font-size: 1rem; }
        .list { margin: 0; padding-left: 18px; color: var(--muted); }
        .table-wrap { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
        th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
        th { color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: .08em; }
        .good { color: var(--good); }
        .bad { color: var(--bad); }
        .error { color: var(--bad); margin-top: 8px; }
        .footer-mark { margin-top: 14px; text-align: center; color: var(--muted); font-size: 0.86rem; }
        @media (max-width: 720px) { .wrap { padding: 12px; } }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="hero">
            <h1>Intraday Options Bot</h1>
            <p>Read-only market view</p>
            <div class="status"><span class="dot" id="status-dot"></span><span id="status-text">Loading...</span></div>
            <div class="hint" id="refresh-text"></div>
            <div class="hint" id="meta-text"></div>
            <div class="error" id="error-text"></div>
        </div>
        <div class="grid" id="kpi-grid"></div>
        <div class="grid-2">
            <div class="panel card">
                <h2 class="section-title">Decision Snapshot</h2>
                <div id="decision-grid"></div>
            </div>
            <div class="panel card">
                <h2 class="section-title">Strategy Status</h2>
                <div id="strategy-grid"></div>
            </div>
        </div>
        <div class="grid-2">
            <div class="panel card">
                <h2 class="section-title">No Position Explanation</h2>
                <ul class="list" id="explanations-list"></ul>
            </div>
            <div class="panel card">
                <h2 class="section-title">Recent Activity</h2>
                <div><span class="badge">Decision History</span></div>
                <div class="table-wrap"><table id="decision-table"></table></div>
                <div><span class="badge">Last 10 Journal Events</span></div>
                <div class="table-wrap"><table id="journal-table"></table></div>
                <div style="margin-top:10px;"><span class="badge">Last 10 Orders</span></div>
                <div class="table-wrap"><table id="orders-table"></table></div>
            </div>
        </div>
        <div class="panel">
            <h2>Open Positions</h2>
            <div class="positions" id="positions-grid"></div>
        </div>
        <div class="footer-mark">Designed by Lolla</div>
    </div>
    <script>
        const VIEW_TOKEN = __VIEW_TOKEN__;
        let firstRefreshDone = false;
        function fmt(value) { return Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
        function fmtPct(value) { return `${fmt((value || 0) * 100)}%`; }
        function kpi(label, value) { return `<div class="card"><span class="label">${label}</span><span class="value">${value}</span></div>`; }
        function toTimeText(value) {
            if (!value) return 'Never';
            const date = new Date(value);
            if (Number.isNaN(date.getTime())) return String(value);
            return date.toLocaleTimeString();
        }
        function ageText(value) {
            if (!value) return 'No scans yet';
            const date = new Date(value);
            if (Number.isNaN(date.getTime())) return 'Unknown';
            const seconds = Math.max(Math.floor((Date.now() - date.getTime()) / 1000), 0);
            if (seconds < 60) return `${seconds}s ago`;
            const minutes = Math.floor(seconds / 60);
            if (minutes < 60) return `${minutes}m ago`;
            const hours = Math.floor(minutes / 60);
            return `${hours}h ago`;
        }
        function tableFromRows(tableId, rows, columns) {
            const table = document.getElementById(tableId);
            if (!rows || rows.length === 0) {
                table.innerHTML = `<thead><tr>${columns.map(c => `<th>${c.label}</th>`).join('')}</tr></thead><tbody><tr><td colspan="${columns.length}" class="hint">No data yet</td></tr></tbody>`;
                return;
            }
            const head = `<thead><tr>${columns.map(c => `<th>${c.label}</th>`).join('')}</tr></thead>`;
            const body = `<tbody>${rows.map(row => `<tr>${columns.map(c => `<td>${row[c.key] ?? '—'}</td>`).join('')}</tr>`).join('')}</tbody>`;
            table.innerHTML = head + body;
        }
        async function refreshDashboard() {
            try {
                const response = await fetch(`/public-dashboard-data?token=${encodeURIComponent(VIEW_TOKEN)}`);
                if (!response.ok) { throw new Error(`HTTP ${response.status}`); }
                const data = await response.json();
                const status = data.status || {};
                const performance = data.performance || {};
                const strategy = data.strategy || {};
                const positions = data.positions || [];

                document.getElementById('error-text').textContent = '';
                document.getElementById('status-text').textContent = `${status.bot_state || 'BOT STOPPED'} · ${status.market_session || 'Unknown session'}`;
                document.getElementById('status-dot').classList.toggle('off', !status.running);
                document.getElementById('refresh-text').textContent = `Last updated at ${new Date().toLocaleTimeString()}`;
                document.getElementById('meta-text').textContent = `Latest check ${toTimeText(status.last_scan_at)} (${ageText(status.last_scan_at)}) · Last decision: ${status.last_decision || 'No decision yet'} · Reason: ${status.last_reason || 'No reason recorded'} · Strategy: ${status.active_strategy || 'No strategy selected yet'}`;

                const pnlClass = Number(performance.today_pnl || 0) >= 0 ? 'good' : 'bad';
                document.getElementById('kpi-grid').innerHTML = [
                    kpi('Today PnL', `<span class="${pnlClass}">${fmt(performance.today_pnl)}</span>`),
                    kpi('Trades Today', String(performance.trades_today || 0)),
                    kpi('Wins', String(performance.wins || 0)),
                    kpi('Losses', String(performance.losses || 0)),
                    kpi('Win Rate', fmtPct(performance.win_rate || 0)),
                    kpi('Open Positions', String(performance.open_positions || 0)),
                    kpi('Realized PnL', fmt(performance.realized_pnl || 0)),
                    kpi('Buying Power', performance.buying_power == null ? 'N/A' : fmt(performance.buying_power)),
                    kpi('Bot Running', performance.bot_running ? 'Yes' : 'No'),
                    kpi('Last Check Age', ageText(status.last_scan_at)),
                ].join('');

                document.getElementById('decision-grid').innerHTML = [
                    kpi('Current Regime', status.current_regime || strategy.regime || 'Unknown'),
                    kpi('Active Strategy', status.active_strategy || strategy.current_strategy || 'No strategy selected yet'),
                    kpi('Strategy Confidence', status.strategy_confidence == null ? 'N/A' : fmt(status.strategy_confidence)),
                    kpi('Entry Quality', status.entry_quality_score == null ? 'N/A' : fmt(status.entry_quality_score)),
                    kpi('Adaptive Threshold', status.adaptive_entry_threshold == null ? 'N/A' : fmt(status.adaptive_entry_threshold)),
                    kpi('Static Threshold', status.static_entry_threshold == null ? 'N/A' : fmt(status.static_entry_threshold)),
                    kpi('Risk Multiplier', status.regime_risk_multiplier == null ? 'N/A' : fmt(status.regime_risk_multiplier)),
                    kpi('Regime Note', status.regime_note || 'N/A'),
                    kpi('Entry Quality Result', status.entry_quality_passed ? 'PASS' : 'FAIL'),
                    kpi('Entry Quality Gap', status.entry_quality_gap == null ? 'N/A' : fmt(status.entry_quality_gap)),
                    kpi('Trade Found', status.trade_found ? 'YES' : 'NO'),
                    kpi('Trade Rejected', status.trade_rejected ? 'YES' : 'NO'),
                    kpi('Rejected By Gate', status.rejected_by_gate || 'none'),
                    kpi('Exact Rejection Reason', status.exact_rejection_reason || 'none'),
                    kpi('Next Retry Time', status.next_retry_time || 'unknown'),
                    kpi('Last Decision', status.last_decision || 'No decision yet'),
                    kpi('Last Skipped Reason', data.last_skipped_reason || 'N/A'),
                ].join('');

                const enabled = Array.isArray(strategy.enabled_strategies) ? strategy.enabled_strategies.join(', ') : 'N/A';
                const disabled = Array.isArray(strategy.disabled_strategies) ? strategy.disabled_strategies.join(', ') : 'N/A';
                document.getElementById('strategy-grid').innerHTML = [
                    kpi('Enabled Strategies', enabled || 'N/A'),
                    kpi('Disabled Strategies', disabled || 'None'),
                ].join('');

                const reasons = (data.position_explanations || []).map(reason => `<li>${reason}</li>`).join('');
                document.getElementById('explanations-list').innerHTML = positions.length ? '<li>Open positions are active.</li>' : (`<li>No open positions right now.</li>${reasons}`);

                tableFromRows('journal-table', data.journal || [], [
                    { key: 'timestamp', label: 'Time' },
                    { key: 'event_type', label: 'Event' },
                    { key: 'payload', label: 'Details' },
                ]);
                tableFromRows('decision-table', data.decision_history || [], [
                    { key: 'timestamp', label: 'Time' },
                    { key: 'symbol', label: 'Symbol' },
                    { key: 'regime', label: 'Regime' },
                    { key: 'strategy', label: 'Strategy' },
                    { key: 'decision', label: 'Decision' },
                    { key: 'confidence', label: 'Confidence' },
                    { key: 'entry_quality', label: 'Entry Quality' },
                    { key: 'adaptive_entry_threshold', label: 'Adaptive Thresh' },
                    { key: 'static_entry_threshold', label: 'Static Thresh' },
                    { key: 'entry_quality_passed', label: 'EQ Pass' },
                    { key: 'entry_quality_gap', label: 'EQ Gap' },
                    { key: 'regime_risk_multiplier', label: 'Risk Mult' },
                    { key: 'regime_note', label: 'Regime Note' },
                    { key: 'contract', label: 'Contract' },
                    { key: 'accepted', label: 'Accepted' },
                    { key: 'rejected_by_gate', label: 'Rejected By' },
                    { key: 'reason_exact', label: 'Exact Reason' },
                    { key: 'reason', label: 'Reason' },
                ]);
                tableFromRows('orders-table', data.orders || [], [
                    { key: 'timestamp', label: 'Time' },
                    { key: 'symbol', label: 'Symbol' },
                    { key: 'side', label: 'Side' },
                    { key: 'qty', label: 'Qty' },
                    { key: 'status', label: 'Status' },
                    { key: 'broker', label: 'Broker' },
                ]);

                if (positions.length) {
                    document.getElementById('positions-grid').innerHTML = positions.map(position => {
                        const pnlClassName = Number(position.pnl_dollar || 0) >= 0 ? 'good' : 'bad';
                        const targets = (position.targets || []).filter(Boolean).join(', ') || 'N/A';
                        return `<div class="position">
                            <div><strong>${position.option_symbol || '—'}</strong> <span class="badge">${position.direction || '—'}</span></div>
                            <div class="hint">Qty ${position.quantity ?? '—'} · Remaining ${position.remaining_quantity ?? '—'} · Broker ${position.broker || 'paper'}</div>
                            <div class="hint">Entry ${fmt(position.entry)} · Current ${fmt(position.current_price)}</div>
                            <div class="hint">PnL <span class="${pnlClassName}">${fmt(position.pnl_dollar)}</span> (${fmt(position.pnl_percent)}%)</div>
                            <div class="hint">Risk Floor ${position.stop ?? 'N/A'} · Targets ${targets}</div>
                            <div class="hint">Holding ${position.holding_time || 'N/A'}</div>
                        </div>`;
                    }).join('');
                } else {
                    document.getElementById('positions-grid').innerHTML = '<div class="hint">No open positions right now.</div>';
                }
                firstRefreshDone = true;
            } catch (error) {
                document.getElementById('error-text').textContent = firstRefreshDone ? 'Loading state: unable to refresh data right now.' : 'Loading state: waiting for first successful data fetch.';
                document.getElementById('status-text').textContent = 'BOT STATUS UNKNOWN';
                document.getElementById('status-dot').classList.add('off');
            }
        }
        refreshDashboard();
        setInterval(refreshDashboard, 10000);
    </script>
</body>
</html>""".replace("__VIEW_TOKEN__", token_js)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status(_: bool = Depends(require_api_token)):
    payload = _build_dashboard_payload()
    return {
        "runner": payload["status"],
        "has_open_position": bool(payload["positions"]),
        "open_positions": payload["positions"],
        "open_positions_count": len(payload["positions"]),
    }


@app.post("/start")
def start(_: bool = Depends(require_api_token)):
    return start_runner()


@app.get("/start")
def start_get(_: bool = Depends(require_api_token)):
    return start_runner()


@app.post("/stop")
def stop(_: bool = Depends(require_api_token)):
    return stop_runner()


@app.get("/stop")
def stop_get(_: bool = Depends(require_api_token)):
    return stop_runner()


@app.get("/position")
def position(_: bool = Depends(require_api_token)):
    positions = _enrich_positions(get_open_positions())
    return {
        "has_open_position": bool(positions),
        "position": positions[0] if positions else None,
        "positions": positions,
    }


@app.get("/risk")
def risk(_: bool = Depends(require_api_token)):
    return _build_dashboard_payload()["risk"]


@app.get("/journal")
def journal(limit: int = 100, _: bool = Depends(require_api_token)):
    return {"events": _read_jsonl(Path("logs/trade_journal.jsonl"), limit=limit)}


@app.get("/orders")
def orders(limit: int = 100, _: bool = Depends(require_api_token)):
    return {"orders": _read_jsonl(Path("logs/paper_orders.jsonl"), limit=limit)}


@app.get("/strategy-performance")
def strategy_performance(_: bool = Depends(require_api_token)):
    return get_strategy_summary(limit=20)


@app.post("/enable-strategy")
def enable_strategy(strategy_name: str = Query(...), _: bool = Depends(require_api_token)):
    result = enable_strategy_for_user(strategy_name)
    log_trade_event("STRATEGY_ENABLED", result)
    return result


@app.post("/disable-strategy")
def disable_strategy(strategy_name: str = Query(...), reason: str = Query(default="manual_disable"), _: bool = Depends(require_api_token)):
    result = disable_strategy_for_user(strategy_name, reason=reason)
    log_trade_event("STRATEGY_DISABLED", result)
    return result


@app.get("/strategy-status")
def strategy_status_endpoint(_: bool = Depends(require_api_token)):
    return strategy_status()


@app.post("/scan-once")
def scan_once(_: bool = Depends(require_api_token)):
    if get_runner_status().get("running"):
        return run_scan_once()

    try:
        run_bot_scan()
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/performance")
def performance(_: bool = Depends(require_api_token)):
    return get_summary(limit_last=20)


@app.get("/pause-status")
def pause_status(_: bool = Depends(require_api_token)):
    return get_pause_status()


@app.post("/resume-risk")
def resume_risk(_: bool = Depends(require_api_token)):
    result = resume_risk_if_allowed()
    log_trade_event("RISK_RESUME_REQUESTED", result)
    if result.get("resumed"):
        log_trade_event("AUTO_PAUSE_CLEARED", result)
    return result


@app.get("/dashboard")
def dashboard(_: bool = Depends(require_api_token)):
    return _build_dashboard_payload()


@app.get("/public-dashboard-data")
def public_dashboard_data(_: bool = Depends(require_view_token)):
    return _build_public_dashboard_payload()


@app.get("/view")
def view(_: bool = Depends(require_view_token)):
    return HTMLResponse(_build_public_dashboard_html(VIEW_TOKEN))


@app.get("/public-dashboard")
def public_dashboard(_: bool = Depends(require_view_token)):
    return HTMLResponse(_build_public_dashboard_html(VIEW_TOKEN))


@app.get("/ui")
def ui(api_token: str = Query(...)):
    if API_TOKEN and api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return HTMLResponse(_build_ui_html(api_token))
