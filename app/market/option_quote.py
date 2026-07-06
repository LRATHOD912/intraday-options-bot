from app.market.options_data import get_option_snapshot


def get_option_market_price(option_symbol):
    try:
        snapshot = get_option_snapshot(option_symbol)
    except Exception:
        return None

    if snapshot is None:
        return None

    quote = getattr(snapshot, "latest_quote", None)
    trade = getattr(snapshot, "latest_trade", None)

    bid = None
    ask = None
    last = None

    if quote is not None:
        raw_bid = getattr(quote, "bid_price", None)
        raw_ask = getattr(quote, "ask_price", None)
        bid = float(raw_bid) if raw_bid is not None else None
        ask = float(raw_ask) if raw_ask is not None else None

    if trade is not None:
        raw_last = getattr(trade, "price", None)
        last = float(raw_last) if raw_last is not None else None

    mid = None
    spread_percent = None
    if bid is not None and ask is not None:
        mid = round((bid + ask) / 2, 4)
        if ask > 0:
            spread_percent = round((ask - bid) / ask, 4)

    if bid is not None and ask is not None:
        price = mid
    elif last is not None:
        price = last
    else:
        return None

    quote_valid = (
        price is not None
        and bid is not None
        and ask is not None
        and bid > 0
        and ask > 0
        and spread_percent is not None
        and spread_percent <= 0.15
    )

    return {
        "symbol": option_symbol,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "last": last,
        "price": price,
        "spread_percent": spread_percent,
        "quote_valid": quote_valid,
    }
