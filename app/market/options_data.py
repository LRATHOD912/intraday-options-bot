from datetime import date, timedelta

from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest
from alpaca.trading.enums import AssetStatus
from alpaca.trading.requests import GetOptionContractsRequest

from app.broker.alpaca_client import get_trading_client
from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY


def get_option_data_client():
    return OptionHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def get_option_contracts(underlying_symbol, direction):
    client = get_trading_client()
    today = date.today()
    option_type = "call" if direction == "CALL" else "put"
    request = GetOptionContractsRequest(
        underlying_symbols=[underlying_symbol],
        status=AssetStatus.ACTIVE,
        expiration_date_gte=today,
        expiration_date_lte=today + timedelta(days=14),
        type=option_type,
        limit=100,
    )
    response = client.get_option_contracts(request)
    return response.option_contracts


def get_option_snapshot(symbol):
    client = get_option_data_client()
    request = OptionSnapshotRequest(symbol_or_symbols=symbol)
    snapshots = client.get_option_snapshot(request)
    return snapshots.get(symbol)
