import time
from typing import Optional

from app.broker.orders import submit_option_sell_order
from app.broker.paper_broker import submit_sell_order as submit_paper_sell_order
from app.config import ENABLE_TRADING, SIMULATE_POSITIONS
from app.execution.position_manager import close_position, get_open_position, has_open_position
from app.logs.trade_journal import log_trade_event
from app.market.option_quote import get_option_market_price
from app.risk.daily_risk_manager import record_trade_result


def monitor_open_position_once() -> dict:
    if not has_open_position():
        return {"status": "NO_POSITION", "message": "No open position"}

    open_pos = get_open_position()
    option_symbol = open_pos.get("option_symbol")
    quantity = int(open_pos.get("quantity", 1))

    if not option_symbol:
        return {
            "status": "HOLD",
            "message": "Open position missing option symbol",
            "position": open_pos,
        }

    option_quote = get_option_market_price(option_symbol)
    if option_quote is None:
        return {
            "status": "HOLD",
            "message": "Option quote unavailable",
            "position": open_pos,
        }

    if not option_quote.get("quote_valid", False):
        return {
            "status": "HOLD",
            "message": "Option quote invalid or spread too wide",
            "position": open_pos,
            "quote": option_quote,
        }

    current_option_price = float(option_quote["price"])
    stop_price = open_pos.get("stop_price")
    target_0 = open_pos.get("target_0")
    target_1 = open_pos.get("target_1")

    exit_reason: Optional[str] = None
    if stop_price is not None and current_option_price <= float(stop_price):
        exit_reason = "stop_loss"
    elif target_1 is not None and current_option_price >= float(target_1):
        exit_reason = "target_1"
    elif target_0 is not None and current_option_price >= float(target_0):
        exit_reason = "target_0"

    if exit_reason is None:
        return {
            "status": "HOLD",
            "message": "Exit conditions not met",
            "position": open_pos,
            "quote": option_quote,
        }

    if ENABLE_TRADING:
        sell_order_result = submit_option_sell_order(option_symbol, qty=quantity)
    elif SIMULATE_POSITIONS:
        paper_sell_order = submit_paper_sell_order(
            symbol=option_symbol,
            qty=quantity,
            price=current_option_price,
        )
        sell_order_result = {
            "submitted": True,
            "order_id": paper_sell_order.get("order_id"),
            "status": paper_sell_order.get("status", "FILLED"),
            "broker": "PAPER_SIM",
            "symbol": option_symbol,
            "qty": quantity,
        }
    else:
        sell_order_result = {
            "submitted": False,
            "reason": "ENABLE_TRADING=false and SIMULATE_POSITIONS=false",
            "symbol": option_symbol,
            "qty": quantity,
        }

    if not sell_order_result.get("submitted"):
        return {
            "status": "HOLD",
            "message": "Exit order not submitted",
            "position": open_pos,
            "quote": option_quote,
            "order_result": sell_order_result,
        }

    closed_position = close_position(exit_price=current_option_price)
    if closed_position is not None:
        entry_price = float(open_pos.get("entry_price", 0.0))
        pnl = (current_option_price - entry_price) * quantity * 100
        was_loss = pnl < 0
        record_trade_result(pnl=pnl, was_loss=was_loss)
        log_trade_event(
            "EXIT",
            {
                "symbol": open_pos.get("symbol"),
                "option_symbol": option_symbol,
                "direction": open_pos.get("direction"),
                "quantity": quantity,
                "entry_price": entry_price,
                "exit_price": current_option_price,
                "pnl": round(pnl, 2),
                "was_loss": was_loss,
                "exit_reason": exit_reason,
                "order_id": sell_order_result.get("order_id"),
                "broker": sell_order_result.get("broker", "ALPACA"),
            },
        )

    return {
        "status": "EXITED",
        "message": "Position exited",
        "position": closed_position,
        "quote": option_quote,
        "order_result": sell_order_result,
        "exit_reason": exit_reason,
    }


def run_continuous_position_monitor(stop_event=None, poll_seconds: int = 5) -> dict:
    last_result = {"status": "NO_POSITION", "message": "No open position"}
    interval = max(int(poll_seconds), 1)

    while has_open_position():
        if stop_event is not None and stop_event.is_set():
            return {"status": "STOPPED", "message": "Monitor stopped by request"}

        last_result = monitor_open_position_once()
        if last_result.get("status") == "EXITED":
            return last_result

        time.sleep(interval)

    return last_result
