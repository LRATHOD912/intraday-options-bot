import time
from typing import Optional

from app.broker.orders import submit_option_sell_order
from app.broker.paper_broker import submit_sell_order as submit_paper_sell_order
from app.config import SIMULATE_POSITIONS
from app.execution.position_manager import close_position, get_open_position, has_open_position, update_open_position
from app.logs.trade_journal import log_trade_event
from app.market.option_quote import get_option_market_price
from app.risk.daily_risk_manager import record_realized_pnl


def _target_hit(direction: str, current_price: float, target_price: Optional[float]) -> bool:
    if target_price is None:
        return False
    if direction == "PUT":
        return current_price <= float(target_price)
    return current_price >= float(target_price)


def _stop_hit(direction: str, current_price: float, stop_price: Optional[float]) -> bool:
    if stop_price is None:
        return False
    if direction == "PUT":
        return current_price >= float(stop_price)
    return current_price <= float(stop_price)


def _submit_exit_order(option_symbol: str, quantity: int, current_option_price: float) -> dict:
    if quantity <= 0:
        return {
            "submitted": False,
            "reason": "invalid_exit_quantity",
            "symbol": option_symbol,
            "qty": quantity,
        }

    alpaca_result = submit_option_sell_order(option_symbol, qty=quantity)
    if alpaca_result.get("submitted"):
        return alpaca_result

    if SIMULATE_POSITIONS:
        paper_sell_order = submit_paper_sell_order(
            symbol=option_symbol,
            qty=quantity,
            price=current_option_price,
        )
        return {
            "submitted": True,
            "order_id": paper_sell_order.get("order_id"),
            "status": paper_sell_order.get("status", "FILLED"),
            "broker": "INTERNAL_SIM",
            "symbol": option_symbol,
            "qty": quantity,
            "route_reason": "SIMULATE_POSITIONS=true fallback",
        }

    return alpaca_result


def _record_exit_leg(event_type: str, open_pos: dict, quantity: int, exit_price: float, order_result: dict, exit_reason: str) -> dict:
    entry_price = float(open_pos.get("entry_price", 0.0))
    pnl = (exit_price - entry_price) * quantity * 100
    was_loss = pnl < 0
    record_realized_pnl(pnl=pnl, was_loss=was_loss)
    payload = {
        "symbol": open_pos.get("symbol"),
        "option_symbol": open_pos.get("option_symbol"),
        "direction": open_pos.get("direction"),
        "quantity": int(quantity),
        "entry_price": entry_price,
        "exit_price": float(exit_price),
        "pnl": round(pnl, 2),
        "was_loss": was_loss,
        "exit_reason": exit_reason,
        "order_id": order_result.get("order_id"),
        "broker": order_result.get("broker", "ALPACA"),
    }
    log_trade_event(event_type, payload)
    return payload


def monitor_open_position_once() -> dict:
    if not has_open_position():
        return {"status": "NO_POSITION", "message": "No open position"}

    open_pos = get_open_position()
    option_symbol = open_pos.get("option_symbol")
    direction = str(open_pos.get("direction", "CALL"))
    original_quantity = int(open_pos.get("original_quantity", open_pos.get("quantity", 1)))
    remaining_quantity = int(open_pos.get("remaining_quantity", open_pos.get("quantity", original_quantity)))

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
    if remaining_quantity <= 0:
        closed_position = close_position(exit_price=current_option_price)
        return {
            "status": "EXITED",
            "message": "Position already fully scaled out",
            "position": closed_position,
            "quote": option_quote,
            "exit_reason": "position_depleted",
        }

    entry_price = float(open_pos.get("entry_price", current_option_price))
    stop_price = float(open_pos.get("stop_price", entry_price))
    risk_per_contract = float(open_pos.get("risk_per_contract", abs(entry_price - stop_price)))
    target_1x = open_pos.get("target_1x", open_pos.get("target_0"))
    target_2x = open_pos.get("target_2x", open_pos.get("target_1"))
    target_3x = open_pos.get("target_3x", open_pos.get("target_2"))
    target_4x = open_pos.get("target_4x")
    target_5x = float(entry_price + (5.0 * risk_per_contract)) if direction == "CALL" else float(entry_price - (5.0 * risk_per_contract))

    took_1x_profit = bool(open_pos.get("took_1x_profit", False))
    took_2x_profit = bool(open_pos.get("took_2x_profit", False))
    took_3x_profit = bool(open_pos.get("took_3x_profit", False))
    stop_moved_to_breakeven = bool(open_pos.get("stop_moved_to_breakeven", False))
    trailing_stop_price = open_pos.get("trailing_stop_price")
    highest_price_seen = open_pos.get("highest_price_seen")
    lowest_price_seen = open_pos.get("lowest_price_seen")

    updates = {}
    leg_events = []

    qty_1x = 1
    qty_2x = 1
    qty_3x = 1

    if _target_hit(direction, current_option_price, target_1x):
        if not stop_moved_to_breakeven:
            stop_moved_to_breakeven = True
            updates["stop_moved_to_breakeven"] = True
            updates["stop_price"] = entry_price

        if direction == "CALL":
            highest_price_seen = max(float(highest_price_seen or entry_price), current_option_price)
            updates["highest_price_seen"] = highest_price_seen
            trailing_stop_price = max(entry_price, highest_price_seen - (1.5 * risk_per_contract))
            updates["trailing_stop_price"] = trailing_stop_price
        else:
            lowest_price_seen = min(float(lowest_price_seen or entry_price), current_option_price)
            updates["lowest_price_seen"] = lowest_price_seen
            trailing_stop_price = min(entry_price, lowest_price_seen + (1.5 * risk_per_contract))
            updates["trailing_stop_price"] = trailing_stop_price

        if not took_1x_profit:
            sell_qty_1x = min(remaining_quantity, qty_1x)
            if sell_qty_1x >= 1:
                order_1x = _submit_exit_order(option_symbol, sell_qty_1x, current_option_price)
                if not order_1x.get("submitted"):
                    return {
                        "status": "HOLD",
                        "message": "1R partial exit order not submitted",
                        "position": open_pos,
                        "quote": option_quote,
                        "order_result": order_1x,
                    }
                leg_payload = _record_exit_leg("PARTIAL_EXIT_1X", open_pos, sell_qty_1x, current_option_price, order_1x, "target_1x")
                remaining_quantity -= sell_qty_1x
                leg_events.append(leg_payload)
                took_1x_profit = True
                updates["took_1x_profit"] = True
            elif original_quantity == 1:
                # Quantity=1 cannot scale out at 1R; activate BE/trailing only.
                took_1x_profit = True
                updates["took_1x_profit"] = True

    if stop_moved_to_breakeven and remaining_quantity > 0:
        if direction == "CALL":
            highest_price_seen = max(float(highest_price_seen or entry_price), current_option_price)
            updates["highest_price_seen"] = highest_price_seen
            trailing_stop_price = max(entry_price, highest_price_seen - (1.5 * risk_per_contract))
            updates["trailing_stop_price"] = trailing_stop_price
        else:
            lowest_price_seen = min(float(lowest_price_seen or entry_price), current_option_price)
            updates["lowest_price_seen"] = lowest_price_seen
            trailing_stop_price = min(entry_price, lowest_price_seen + (1.5 * risk_per_contract))
            updates["trailing_stop_price"] = trailing_stop_price

    if stop_moved_to_breakeven and _target_hit(direction, current_option_price, target_2x) and not took_2x_profit and remaining_quantity > 0:
        sell_qty_2x = min(remaining_quantity, qty_2x)
        if sell_qty_2x >= 1:
            order_2x = _submit_exit_order(option_symbol, sell_qty_2x, current_option_price)
            if not order_2x.get("submitted"):
                return {
                    "status": "HOLD",
                    "message": "2R partial exit order not submitted",
                    "position": open_pos,
                    "quote": option_quote,
                    "order_result": order_2x,
                }
            leg_payload = _record_exit_leg("PARTIAL_EXIT_2X", open_pos, sell_qty_2x, current_option_price, order_2x, "target_2x")
            remaining_quantity -= sell_qty_2x
            leg_events.append(leg_payload)
        took_2x_profit = True
        updates["took_2x_profit"] = True

    if stop_moved_to_breakeven and _target_hit(direction, current_option_price, target_3x) and not took_3x_profit and remaining_quantity > 0:
        sell_qty_3x = min(remaining_quantity, qty_3x)
        if sell_qty_3x >= 1:
            order_3x = _submit_exit_order(option_symbol, sell_qty_3x, current_option_price)
            if not order_3x.get("submitted"):
                return {
                    "status": "HOLD",
                    "message": "3R partial exit order not submitted",
                    "position": open_pos,
                    "quote": option_quote,
                    "order_result": order_3x,
                }
            leg_payload = _record_exit_leg("PARTIAL_EXIT_3X", open_pos, sell_qty_3x, current_option_price, order_3x, "target_3x")
            remaining_quantity -= sell_qty_3x
            leg_events.append(leg_payload)
        took_3x_profit = True
        updates["took_3x_profit"] = True

    final_target_hit = _target_hit(direction, current_option_price, target_5x)
    if target_4x is not None and not final_target_hit:
        final_target_hit = _target_hit(direction, current_option_price, target_4x) and remaining_quantity <= 1

    if not stop_moved_to_breakeven and _stop_hit(direction, current_option_price, stop_price):
        order_stop = _submit_exit_order(option_symbol, remaining_quantity, current_option_price)
        if not order_stop.get("submitted"):
            return {
                "status": "HOLD",
                "message": "Stop-loss order not submitted",
                "position": open_pos,
                "quote": option_quote,
                "order_result": order_stop,
            }
        final_payload = _record_exit_leg("STOP_LOSS_EXIT", open_pos, remaining_quantity, current_option_price, order_stop, "stop_loss")
        leg_events.append(final_payload)
        closed_position = close_position(exit_price=current_option_price)
        return {
            "status": "EXITED",
            "message": "Position closed at stop",
            "position": closed_position,
            "quote": option_quote,
            "order_result": order_stop,
            "events": leg_events,
            "exit_reason": "stop_loss",
        }

    if remaining_quantity > 0 and final_target_hit:
        order_final = _submit_exit_order(option_symbol, remaining_quantity, current_option_price)
        if not order_final.get("submitted"):
            return {
                "status": "HOLD",
                "message": "Final target exit order not submitted",
                "position": open_pos,
                "quote": option_quote,
                "order_result": order_final,
            }
        final_payload = _record_exit_leg("FINAL_EXIT", open_pos, remaining_quantity, current_option_price, order_final, "target_5x_or_trail")
        leg_events.append(final_payload)
        closed_position = close_position(exit_price=current_option_price)
        return {
            "status": "EXITED",
            "message": "Position fully exited at final target",
            "position": closed_position,
            "quote": option_quote,
            "order_result": order_final,
            "events": leg_events,
            "exit_reason": "final_target",
        }

    if remaining_quantity > 0 and stop_moved_to_breakeven:
        trail_stop = float(trailing_stop_price) if trailing_stop_price is not None else entry_price
        if _stop_hit(direction, current_option_price, trail_stop):
            event_type = "BREAKEVEN_EXIT" if abs(trail_stop - entry_price) < 1e-9 else "TRAILING_STOP_EXIT"
            order_trail = _submit_exit_order(option_symbol, remaining_quantity, current_option_price)
            if not order_trail.get("submitted"):
                return {
                    "status": "HOLD",
                    "message": "Trailing/breakeven exit order not submitted",
                    "position": open_pos,
                    "quote": option_quote,
                    "order_result": order_trail,
                }
            final_payload = _record_exit_leg(event_type, open_pos, remaining_quantity, current_option_price, order_trail, "trail_or_breakeven")
            leg_events.append(final_payload)
            closed_position = close_position(exit_price=current_option_price)
            return {
                "status": "EXITED",
                "message": "Position fully exited by trailing/breakeven stop",
                "position": closed_position,
                "quote": option_quote,
                "order_result": order_trail,
                "events": leg_events,
                "exit_reason": event_type.lower(),
            }

    updates["remaining_quantity"] = int(remaining_quantity)
    updates["quantity"] = int(remaining_quantity)
    updates["stop_price"] = float(entry_price) if stop_moved_to_breakeven else stop_price
    updates["took_1x_profit"] = bool(took_1x_profit)
    updates["took_2x_profit"] = bool(took_2x_profit)
    updates["took_3x_profit"] = bool(took_3x_profit)

    updated_position = update_open_position(updates) if updates else open_pos

    if leg_events:
        return {
            "status": "PARTIAL_EXIT",
            "message": "Partial exits executed and position updated",
            "position": updated_position,
            "quote": option_quote,
            "events": leg_events,
        }

    return {
        "status": "HOLD",
        "message": "Exit conditions not met",
        "position": updated_position,
        "quote": option_quote,
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
