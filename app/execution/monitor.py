from app.broker.orders import submit_option_sell_order

STOP_LOSS_PERCENT = 0.20
TAKE_PROFIT_PERCENT = 0.25


def calculate_pnl_percent(entry_price, current_price):
    if entry_price <= 0:
        return 0
    return (current_price - entry_price) / entry_price


def check_exit_rules(option_symbol, entry_price, current_price, qty=1):
    pnl_percent = calculate_pnl_percent(entry_price, current_price)

    if pnl_percent <= -STOP_LOSS_PERCENT:
        order_result = submit_option_sell_order(option_symbol, qty)
        return {
            "exit": True,
            "reason": "Stop loss hit",
            "pnl_percent": round(pnl_percent * 100, 2),
            "order": order_result,
        }

    if pnl_percent >= TAKE_PROFIT_PERCENT:
        order_result = submit_option_sell_order(option_symbol, qty)
        return {
            "exit": True,
            "reason": "Take profit hit",
            "pnl_percent": round(pnl_percent * 100, 2),
            "order": order_result,
        }

    return {
        "exit": False,
        "reason": "Hold position",
        "pnl_percent": round(pnl_percent * 100, 2),
        "order": None,
    }
