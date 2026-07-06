from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from app.broker.alpaca_client import get_trading_client
from app.config import ENABLE_TRADING


def submit_option_buy_order(option_symbol, qty=1):
    if not ENABLE_TRADING:
        return {
            "submitted": False,
            "reason": "ENABLE_TRADING=false, order not submitted",
            "symbol": option_symbol,
            "qty": qty,
        }

    client = get_trading_client()
    order_request = MarketOrderRequest(
        symbol=option_symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(order_request)
    return {
        "submitted": True,
        "order_id": order.id,
        "symbol": option_symbol,
        "qty": qty,
        "status": order.status,
    }


def submit_option_sell_order(option_symbol, qty=1):
    if not ENABLE_TRADING:
        return {
            "submitted": False,
            "reason": "ENABLE_TRADING=false, sell order not submitted",
            "symbol": option_symbol,
            "qty": qty,
        }

    client = get_trading_client()
    order_request = MarketOrderRequest(
        symbol=option_symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(order_request)
    return {
        "submitted": True,
        "order_id": order.id,
        "symbol": option_symbol,
        "qty": qty,
        "status": order.status,
    }
