from datetime import date

from app.config import (
    ALLOW_0DTE,
    MAX_OPTION_SPREAD_PERCENT,
    MIN_OPTION_OPEN_INTEREST,
    MIN_OPTION_VOLUME,
    MEAN_REVERSION_MAX_PREMIUM,
    MEAN_REVERSION_MAX_DELTA,
    MEAN_REVERSION_MIN_PREMIUM,
    MEAN_REVERSION_MIN_DELTA,
    MOMENTUM_MAX_DELTA,
    MOMENTUM_MIN_DELTA,
    PREFERRED_DELTA_MAX,
    PREFERRED_DELTA_MIN,
    RANGE_SCALP_MAX_PREMIUM,
    RANGE_SCALP_MIN_PREMIUM,
)
from app.market.options_data import get_option_contracts, get_option_contracts_after_today, get_option_snapshot
from app.market.market_data import get_latest_price

def calculate_spread_percent(bid, ask):
    if ask <= 0:
        return 999
    return (ask - bid) / ask


def _strategy_filters(strategy_name: str | None, strictness: str):
    strategy_name = (strategy_name or "").upper()
    delta_min = float(PREFERRED_DELTA_MIN)
    delta_max = float(PREFERRED_DELTA_MAX)
    spread_limit = float(MAX_OPTION_SPREAD_PERCENT)
    min_vol = int(MIN_OPTION_VOLUME)
    min_oi = int(MIN_OPTION_OPEN_INTEREST)
    min_premium = None
    max_premium = None
    require_0dte = False

    if strategy_name in ["MOMENTUM_BREAKOUT", "TREND_PULLBACK", "OPENING_RANGE_BREAKOUT", "GAP_AND_GO"]:
        delta_min = float(MOMENTUM_MIN_DELTA)
        delta_max = float(MOMENTUM_MAX_DELTA)
        spread_limit = min(spread_limit, 0.06)
        min_vol = max(min_vol, 1000)
        min_oi = max(min_oi, 1500)
    elif strategy_name == "VWAP_BOUNCE":
        delta_min = 0.30
        delta_max = 0.50
        spread_limit = min(spread_limit, 0.05)
        min_vol = max(min_vol, 800)
        min_oi = max(min_oi, 1200)
    elif strategy_name == "GAP_FILL_REVERSAL":
        delta_min = 0.30
        delta_max = 0.48
        spread_limit = min(spread_limit, 0.06)
    elif strategy_name == "RANGE_SCALP_0DTE":
        delta_min = 0.30
        delta_max = 0.45
        spread_limit = min(spread_limit, 0.05)
        min_vol = max(min_vol, 1200)
        min_oi = max(min_oi, 2000)
        min_premium = RANGE_SCALP_MIN_PREMIUM
        max_premium = RANGE_SCALP_MAX_PREMIUM
        require_0dte = True
    elif strategy_name == "MEAN_REVERSION_0DTE":
        delta_min = float(MEAN_REVERSION_MIN_DELTA)
        delta_max = float(MEAN_REVERSION_MAX_DELTA)
        spread_limit = min(spread_limit, 0.06)
        min_premium = MEAN_REVERSION_MIN_PREMIUM
        max_premium = MEAN_REVERSION_MAX_PREMIUM
        require_0dte = True

    if strictness == "loose":
        spread_limit = min(0.12, spread_limit * 1.5)
        min_vol = max(100, int(min_vol * 0.5))
        min_oi = max(200, int(min_oi * 0.5))
        delta_min = max(0.2, delta_min - 0.05)
        delta_max = min(0.65, delta_max + 0.05)
    elif strictness == "strict":
        spread_limit = max(0.03, spread_limit * 0.8)
        min_vol = max(min_vol, 800)
        min_oi = max(min_oi, 1500)
        delta_min = max(delta_min, 0.38)
        delta_max = min(delta_max, 0.58)

    return {
        "spread_limit": spread_limit,
        "min_vol": min_vol,
        "min_oi": min_oi,
        "delta_min": delta_min,
        "delta_max": delta_max,
        "min_premium": min_premium,
        "max_premium": max_premium,
        "require_0dte": require_0dte,
    }


def _option_quality_score(*, spread_percent, volume, open_interest, delta, distance_from_price, premium, expiry_days, strategy_name):
    score = 0.0
    score += max(0.0, 30.0 - (float(spread_percent) * 250.0))
    score += min(25.0, (float(volume or 0.0) / 100.0))
    score += min(20.0, (float(open_interest or 0.0) / 200.0))
    if delta is not None:
        target = 0.42
        if strategy_name in ["RANGE_SCALP_0DTE", "MEAN_REVERSION_0DTE"]:
            target = 0.35
        score += max(0.0, 20.0 - abs(float(delta) - target) * 80.0)
    score += max(0.0, 10.0 - float(distance_from_price) / max(float(premium or 1.0), 1.0))
    if expiry_days == 0:
        score += 5.0
    elif expiry_days == 1:
        score += 3.0
    return round(min(score, 100.0), 2)


def choose_best_contract(underlying_symbol, direction, underlying_price, strictness: str = "normal", strategy_name: str | None = None, allow_0dte_override: bool | None = None):
    contracts = get_option_contracts(underlying_symbol, direction)
    if not contracts:
        return None, "No option contracts found"

    strictness = (strictness or "normal").lower()
    filters = _strategy_filters(strategy_name, strictness)
    spread_limit = filters["spread_limit"]
    min_vol = filters["min_vol"]
    min_oi = filters["min_oi"]
    delta_min = filters["delta_min"]
    delta_max = filters["delta_max"]
    min_premium = filters["min_premium"]
    max_premium = filters["max_premium"]
    require_0dte = filters["require_0dte"]
    allow_0dte = ALLOW_0DTE if allow_0dte_override is None else bool(allow_0dte_override)

    if not require_0dte and not allow_0dte:
        non_zero_dte_contracts = []
        for contract in contracts:
            expiration = getattr(contract, "expiration_date", None)
            if expiration is None or str(expiration) != str(date.today()):
                non_zero_dte_contracts.append(contract)
        if not non_zero_dte_contracts:
            fallback_contracts = get_option_contracts_after_today(underlying_symbol, direction)
            if fallback_contracts:
                contracts = fallback_contracts

    preferred_candidates = []
    fallback_candidates = []
    rejected_reasons = {
        "snapshot_missing": 0,
        "bad_quote": 0,
        "zero_dte_block": 0,
        "spread_block": 0,
        "volume_block": 0,
        "oi_block": 0,
        "premium_block": 0,
    }

    contracts = sorted(contracts, key=lambda c: (str(c.expiration_date), abs(float(c.strike_price) - underlying_price)))

    for contract in contracts:
        expiration = getattr(contract, "expiration_date", None)
        expiry_days = None
        if expiration is not None:
            try:
                expiry_days = max((expiration - date.today()).days, 0)
            except Exception:
                expiry_days = None

        if require_0dte or not allow_0dte:
            expiration = getattr(contract, "expiration_date", None)
            if expiration is not None and str(expiration) == str(date.today()):
                rejected_reasons["zero_dte_block"] += 1
                continue
        if require_0dte and expiration is not None and str(expiration) != str(date.today()):
            rejected_reasons["zero_dte_block"] += 1
            continue

        snapshot = get_option_snapshot(contract.symbol)
        if snapshot is None:
            rejected_reasons["snapshot_missing"] += 1
            continue

        quote = snapshot.latest_quote
        greeks = snapshot.greeks
        if quote is None:
            rejected_reasons["bad_quote"] += 1
            continue

        bid = float(quote.bid_price or 0)
        ask = float(quote.ask_price or 0)
        strike = float(contract.strike_price)
        distance_from_price = abs(strike - underlying_price)
        premium = None

        if bid <= 0 or ask <= 0:
            rejected_reasons["bad_quote"] += 1
            continue

        spread_percent = calculate_spread_percent(bid, ask)
        if spread_percent > spread_limit:
            rejected_reasons["spread_block"] += 1
            continue

        daily_bar = getattr(snapshot, "daily_bar", None)
        volume = getattr(daily_bar, "volume", None)
        if volume is not None and float(volume) < min_vol:
            rejected_reasons["volume_block"] += 1
            continue

        open_interest = getattr(snapshot, "open_interest", None)
        if open_interest is None:
            open_interest = getattr(contract, "open_interest", None)
        if open_interest is not None and float(open_interest) < min_oi:
            rejected_reasons["oi_block"] += 1
            continue

        if premium is None:
            premium = round((bid + ask) / 2, 2)

        if min_premium is not None and premium < float(min_premium):
            rejected_reasons["premium_block"] += 1
            continue
        if max_premium is not None and premium > float(max_premium):
            rejected_reasons["premium_block"] += 1
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
            "expiry_days": expiry_days,
            "expiry_type": "0DTE" if expiry_days == 0 else "NEXT_EXPIRY",
            "liquidity_score": round(min(100.0, max(0.0, 100.0 - (spread_percent * 2000.0) + ((float(volume or 0.0) + float(open_interest or 0.0)) / 100.0))), 2),
        }

        if greeks is not None and getattr(greeks, "delta", None) is not None:
            delta = abs(float(greeks.delta))
            candidate["delta"] = round(delta, 4)
            candidate["delta_gap"] = abs(delta - 0.40)
            if delta_min <= delta <= delta_max:
                preferred_candidates.append(candidate)
            else:
                fallback_candidates.append(candidate)
        else:
            # Greeks unavailable: fall back to nearest ATM with tight spread.
            fallback_candidates.append(candidate)

        candidate["strategy_name"] = strategy_name or "default"
        candidate["option_quality_score"] = _option_quality_score(
            spread_percent=spread_percent,
            volume=volume,
            open_interest=open_interest,
            delta=candidate.get("delta"),
            distance_from_price=distance_from_price,
            premium=premium,
            expiry_days=expiry_days or 0,
            strategy_name=strategy_name,
        )

    if preferred_candidates:
        preferred_candidates.sort(
            key=lambda x: (
                str(x.get("expiration")),
                x.get("delta_gap", 999),
                -float(x.get("liquidity_score", 0.0)),
                -float(x.get("option_quality_score", 0.0)),
                x["distance_from_price"],
                x["spread_percent"],
            )
        )
        return preferred_candidates[0], "Best contract selected (preferred delta/liquidity)"

    if not fallback_candidates:
        return None, f"No valid contracts after filters: {rejected_reasons}"

    fallback_candidates.sort(
        key=lambda x: (
            str(x.get("expiration")),
            -float(x.get("liquidity_score", 0.0)),
            -float(x.get("option_quality_score", 0.0)),
            x["distance_from_price"],
            x["spread_percent"],
        )
    )
    return fallback_candidates[0], "Best contract selected (fallback without preferred delta)"


def select_option_contract(symbol, direction):
    """Compatibility wrapper for older call-sites.

    Uses latest underlying stock price and delegates to choose_best_contract.
    """
    underlying_price = get_latest_price(symbol)
    if underlying_price is None:
        return None, f"Unable to fetch latest price for {symbol}"
    return choose_best_contract(symbol, direction, float(underlying_price), strictness="normal")
