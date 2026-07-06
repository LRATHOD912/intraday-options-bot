import json
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


LOG_PATH = Path("logs/paper_orders.jsonl")
_ORDERS = {}


def _timestamp_et() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat()


def _append_order_event(order: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(order) + "\n")


def _load_orders_from_log() -> None:
    _ORDERS.clear()
    if not LOG_PATH.exists():
        return

    with LOG_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            order_id = record.get("order_id")
            if order_id:
                _ORDERS[order_id] = record


def _create_filled_order(symbol: str, qty: int, side: str, price=None) -> dict:
    order = {
        "order_id": str(uuid.uuid4()),
        "symbol": symbol,
        "qty": int(qty),
        "side": side,
        "price": float(price) if price is not None else None,
        "status": "FILLED",
        "timestamp": _timestamp_et(),
    }
    _ORDERS[order["order_id"]] = order
    _append_order_event(order)
    return dict(order)


def submit_buy_order(symbol, qty, price=None):
    return _create_filled_order(symbol=symbol, qty=qty, side="BUY", price=price)


def submit_sell_order(symbol, qty, price=None):
    return _create_filled_order(symbol=symbol, qty=qty, side="SELL", price=price)


def get_order_status(order_id):
    order = _ORDERS.get(order_id)
    if order is None:
        return None
    return dict(order)


def cancel_order(order_id):
    order = _ORDERS.get(order_id)
    if order is None:
        return None

    if order.get("status") != "FILLED":
        order["status"] = "CANCELLED"
        order["timestamp"] = _timestamp_et()
        _append_order_event(order)

    return dict(order)


_load_orders_from_log()
