import json
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from app.config import API_TOKEN
from app.execution.position_manager import get_open_position, has_open_position
from app.main import run_bot_scan
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
    return {
        "runner": get_runner_status(),
        "has_open_position": has_open_position(),
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
    return {
        "has_open_position": has_open_position(),
        "position": get_open_position(),
    }


@app.get("/risk")
def risk(_: bool = Depends(require_api_token)):
    state = _read_json_file(Path("logs/daily_risk_state.json"))
    return state or {
        "date": None,
        "trades_today": 0,
        "losses_today": 0,
        "realized_pnl": 0.0,
    }


@app.get("/journal")
def journal(limit: int = 100, _: bool = Depends(require_api_token)):
    return {"events": _read_jsonl(Path("logs/trade_journal.jsonl"), limit=limit)}


@app.get("/orders")
def orders(limit: int = 100, _: bool = Depends(require_api_token)):
    return {"orders": _read_jsonl(Path("logs/paper_orders.jsonl"), limit=limit)}


@app.post("/scan-once")
def scan_once(_: bool = Depends(require_api_token)):
    if get_runner_status().get("running"):
        return run_scan_once()

    try:
        run_bot_scan()
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
