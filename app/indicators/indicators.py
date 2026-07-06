def calculate_ema(df, period):
    return df["close"].ewm(span=period, adjust=False).mean()


def calculate_vwap(df):
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    volume_price = typical_price * df["volume"]
    return volume_price.cumsum() / df["volume"].cumsum()


def calculate_volume_average(df, period=20):
    return df["volume"].rolling(window=period).mean()
