from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from app.broker.alpaca_client import get_trading_client
from app.config import ALPACA_PAPER, ENABLE_TRADING, USE_ALPACA_PAPER_EXECUTION, USE_LIMIT_ORDERS


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


def _submit_alpaca_order(option_symbol, qty, side, limit_price=None, timeout_seconds=0):
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
    use_limit = bool(USE_LIMIT_ORDERS and broker == "ALPACA_PAPER" and limit_price is not None)
    if use_limit:
        order_request = LimitOrderRequest(
            symbol=option_symbol,
            qty=qty,
            side=side,
            limit_price=float(limit_price),
            time_in_force=TimeInForce.DAY,
        )
    else:
        order_request = MarketOrderRequest(
            symbol=option_symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )

    order = client.submit_order(order_request)
    status_value = str(order.status)

    if timeout_seconds and use_limit and status_value.lower() not in ["filled", "accepted", "new"]:
        try:
            client.cancel_order_by_id(order.id)
            return {
                "submitted": False,
                "reason": "Limit order timeout/cancelled",
                "order_id": order.id,
                "symbol": option_symbol,
                "qty": qty,
                "broker": broker,
                "route_reason": route_reason,
            }
        except Exception:
            pass

    return {
        "submitted": True,
        "order_id": order.id,
        "symbol": option_symbol,
        "qty": qty,
        "status": status_value,
        "broker": broker,
        "route_reason": route_reason,
        "order_type": "LIMIT" if use_limit else "MARKET",
    }


def submit_option_buy_order(option_symbol, qty=1, limit_price=None, timeout_seconds=0):
    return _submit_alpaca_order(
        option_symbol=option_symbol,
        qty=qty,
        side=OrderSide.BUY,
        limit_price=limit_price,
        timeout_seconds=timeout_seconds,
    )


def submit_option_sell_order(option_symbol, qty=1, limit_price=None, timeout_seconds=0):
    return _submit_alpaca_order(
        option_symbol=option_symbol,
        qty=qty,
        side=OrderSide.SELL,
        limit_price=limit_price,
        timeout_seconds=timeout_seconds,
    )
