from datetime import time


def get_today_bars(df):
    latest_date = df["timestamp"].dt.date.max()
    return df[df["timestamp"].dt.date == latest_date]


def calculate_premarket_levels(df):
    today = get_today_bars(df)

    premarket = today[
        (today["timestamp"].dt.time >= time(4, 0)) &
        (today["timestamp"].dt.time < time(9, 30))
    ]

    if premarket.empty:
        return None, None

    return premarket["high"].max(), premarket["low"].min()


def calculate_opening_range(df):
    today = get_today_bars(df)

    opening_range = today[
        (today["timestamp"].dt.time >= time(9, 30)) &
        (today["timestamp"].dt.time < time(9, 45))
    ]

    if opening_range.empty:
        return None, None

    return opening_range["high"].max(), opening_range["low"].min()


def detect_breakout(latest_close, premarket_high, opening_high):
    levels = [level for level in [premarket_high, opening_high] if level is not None]
    return any(latest_close > level for level in levels)


def detect_breakdown(latest_close, premarket_low, opening_low):
    levels = [level for level in [premarket_low, opening_low] if level is not None]
    return any(latest_close < level for level in levels)


def calculate_previous_day_levels(df):
    latest_date = df["timestamp"].dt.date.max()
    previous_days = df[df["timestamp"].dt.date < latest_date]

    if previous_days.empty:
        return None, None, None

    previous_date = previous_days["timestamp"].dt.date.max()
    previous_day = previous_days[previous_days["timestamp"].dt.date == previous_date]

    return (
        previous_day["high"].max(),
        previous_day["low"].min(),
        previous_day["close"].iloc[-1],
    )