from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from app.broker.alpaca_client import get_trading_client
from app.config import ALPACA_PAPER, ENABLE_TRADING, USE_ALPACA_PAPER_EXECUTION


def _alpaca_paper_enabled() -> bool:
    return str(ALPACA_PAPER).lower() == "true"


def _resolve_alpaca_route() -> tuple[bool, str, str]:
    paper_enabled = _alpaca_paper_enabled()

    if ENABLE_TRADING:
        broker = "ALPACA_PAPER" if paper_enabled else "ALPACA_LIVE"
        return True, broker, "ENABLE_TRADING=true"

    if USE_ALPACA_PAPER_EXECUTION and paper_enabled:
        return True, "ALPACA_PAPER", "ENABLE_TRADING=false and USE_ALPACA_PAPER_EXECUTION=true and ALPACA_PAPER=true"

    if USE_ALPACA_PAPER_EXECUTION and not paper_enabled:
        return False, "NONE", "Refused: USE_ALPACA_PAPER_EXECUTION=true requires ALPACA_PAPER=true while ENABLE_TRADING=false"

    return False, "NONE", "ENABLE_TRADING=false and Alpaca paper routing disabled"


def _submit_alpaca_order(option_symbol, qty, side):
    can_submit, broker, route_reason = _resolve_alpaca_route()
    if not can_submit:
        return {
            "submitted": False,
            "reason": route_reason,
            "symbol": option_symbol,
            "qty": qty,
            "broker": "NONE",
        }

    client = get_trading_client()
    order_request = MarketOrderRequest(
        symbol=option_symbol,
        qty=qty,
        side=side,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(order_request)
    return {
        "submitted": True,
        "order_id": order.id,
        "symbol": option_symbol,
        "qty": qty,
        "status": order.status,
        "broker": broker,
        "route_reason": route_reason,
    }


def submit_option_buy_order(option_symbol, qty=1):
    return _submit_alpaca_order(option_symbol=option_symbol, qty=qty, side=OrderSide.BUY)


def submit_option_sell_order(option_symbol, qty=1):
    return _submit_alpaca_order(option_symbol=option_symbol, qty=qty, side=OrderSide.SELL)
