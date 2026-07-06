from alpaca.trading.client import TradingClient
from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY

def get_trading_client():
    return TradingClient(
        api_key=ALPACA_API_KEY,
        secret_key=ALPACA_SECRET_KEY,
        paper=True
    )

def test_account_connection():
    client = get_trading_client()
    account = client.get_account()

    print("========== Alpaca Account ==========")
    print(f"Status          : {account.status}")
    print(f"Cash            : {account.cash}")
    print(f"Buying Power    : {account.buying_power}")
    print(f"Portfolio Value : {account.portfolio_value}")