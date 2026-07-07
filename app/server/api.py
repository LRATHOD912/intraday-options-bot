import json
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.analytics.performance_tracker import get_summary
from app.analytics.strategy_performance import get_strategy_summary
from app.config import ALPACA_PAPER, API_TOKEN, ENABLE_TRADING, EXIT_PROFILE, MIN_ENTRY_QUALITY_SCORE, POSITION_QUANTITY, USE_ALPACA_PAPER_EXECUTION, USE_DYNAMIC_POSITION_SIZE, USE_REGIME_FILTER, USE_TUNED_STAGED_EXITS
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

        return {
                "status": {
                        "running": runner.get("running"),
                        "thread_alive": runner.get("thread_alive"),
                        "started_at": runner.get("started_at"),
                        "last_scan_at": runner.get("last_scan_at"),
                        "last_error": runner.get("last_error"),
                        "open_positions_count": len(positions),
                },
                "positions": positions,
                "risk": risk_state,
                "orders": _read_jsonl(Path("logs/paper_orders.jsonl"), limit=20),
                "journal": _read_jsonl(Path("logs/trade_journal.jsonl"), limit=20),
                "performance": get_summary(limit_last=20),
                "strategy_performance": get_strategy_summary(limit=20),
                "strategy_status": strategy_status(),
                "config_summary": config_summary,
                "last_scan_decision": latest_decision,
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
    <title>QQQ Intraday Options Bot</title>
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
                <h1>QQQ Intraday Options Bot</h1>
                <div class=\"muted\">Paper-first live control dashboard</div>
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


@app.get("/ui")
def ui(api_token: str = Query(...)):
    if API_TOKEN and api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return HTMLResponse(_build_ui_html(api_token))
