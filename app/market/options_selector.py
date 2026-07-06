from app.market.options_data import get_option_contracts, get_option_snapshot
from app.market.market_data import get_latest_price

MIN_DELTA = 0.30
MAX_DELTA = 0.50
MAX_SPREAD_PERCENT = 0.10
MIN_VOLUME = 100
MIN_OPEN_INTEREST = 500


def calculate_spread_percent(bid, ask):
    if ask <= 0:
        return 999
    return (ask - bid) / ask


def choose_best_contract(underlying_symbol, direction, underlying_price):
    contracts = get_option_contracts(underlying_symbol, direction)
    if not contracts:
        return None, "No option contracts found"

    preferred_candidates = []
    fallback_candidates = []

    contracts = sorted(contracts, key=lambda c: (str(c.expiration_date), abs(float(c.strike_price) - underlying_price)))

    for contract in contracts:
        snapshot = get_option_snapshot(contract.symbol)
        if snapshot is None:
            continue

        quote = snapshot.latest_quote
        greeks = snapshot.greeks
        if quote is None:
            continue

        bid = float(quote.bid_price or 0)
        ask = float(quote.ask_price or 0)
        strike = float(contract.strike_price)
        distance_from_price = abs(strike - underlying_price)

        if bid <= 0 or ask <= 0:
            continue

        spread_percent = calculate_spread_percent(bid, ask)
        if spread_percent > MAX_SPREAD_PERCENT:
            continue

        daily_bar = getattr(snapshot, "daily_bar", None)
        volume = getattr(daily_bar, "volume", None)
        if volume is not None and float(volume) < MIN_VOLUME:
            continue

        open_interest = getattr(snapshot, "open_interest", None)
        if open_interest is None:
            open_interest = getattr(contract, "open_interest", None)
        if open_interest is not None and float(open_interest) < MIN_OPEN_INTEREST:
            continue

        candidate = {
            "symbol": contract.symbol,
            "strike": strike,
            "expiration": contract.expiration_date,
            "bid": bid,
            "ask": ask,
            "mid": round((bid + ask) / 2, 2),
            "spread_percent": round(spread_percent, 4),
            "distance_from_price": distance_from_price,
            "volume": int(volume) if volume is not None else None,
            "open_interest": int(open_interest) if open_interest is not None else None,
        }

        if greeks is not None and getattr(greeks, "delta", None) is not None:
            delta = abs(float(greeks.delta))
            candidate["delta"] = round(delta, 4)
            candidate["delta_gap"] = abs(delta - 0.40)
            if MIN_DELTA <= delta <= MAX_DELTA:
                preferred_candidates.append(candidate)
            else:
                fallback_candidates.append(candidate)
        else:
            # Greeks unavailable: fall back to nearest ATM with tight spread.
            fallback_candidates.append(candidate)

    if preferred_candidates:
        preferred_candidates.sort(
            key=lambda x: (str(x["expiration"]), x.get("delta_gap", 999), x["distance_from_price"], x["spread_percent"])
        )
        return preferred_candidates[0], "Best contract selected (preferred delta/liquidity)"

    if not fallback_candidates:
        return None, "No valid contracts after filters"

    fallback_candidates.sort(key=lambda x: (str(x["expiration"]), x["distance_from_price"], x["spread_percent"]))
    return fallback_candidates[0], "Best contract selected (fallback without preferred delta)"


def select_option_contract(symbol, direction):
    """Compatibility wrapper for older call-sites.

    Uses latest underlying stock price and delegates to choose_best_contract.
    """
    underlying_price = get_latest_price(symbol)
    if underlying_price is None:
        return None, f"Unable to fetch latest price for {symbol}"
    return choose_best_contract(symbol, direction, float(underlying_price))
