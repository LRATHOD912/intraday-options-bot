from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY


def get_stock_data_client():
    return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def get_latest_price(symbol):
    try:
        client = get_stock_data_client()
        request = StockLatestTradeRequest(
            symbol_or_symbols=[symbol],
            feed=DataFeed.IEX,
        )
        trades = client.get_stock_latest_trade(request)
        trade = trades.get(symbol)
        if trade is None:
            return None
        return float(trade.price)
    except Exception:
        return None


def get_latest_prices(symbols):
    client = get_stock_data_client()
    request = StockLatestTradeRequest(
        symbol_or_symbols=symbols,
        feed=DataFeed.IEX,
    )
    trades = client.get_stock_latest_trade(request)
    prices = {}
    for symbol in symbols:
        try:
            prices[symbol] = float(trades[symbol].price)
        except Exception:
            prices[symbol] = None
    return prices


def get_market_internal_price(symbol):
    for candidate in ["VIXY", "UVXY", "SPY"]:
        if candidate == symbol:
            price = get_latest_price(candidate)
            if price is not None:
                return price
        elif candidate:
            price = get_latest_price(candidate)
            if price is not None:
                return price
    return None


def get_1min_bars(symbol, start_time, end_time):
    client = get_stock_data_client()
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start_time,
        end=end_time,
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request).df
    return bars
