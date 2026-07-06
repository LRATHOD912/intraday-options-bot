from datetime import datetime, time
from zoneinfo import ZoneInfo


def is_market_hours():
    eastern = ZoneInfo("America/New_York")
    now = datetime.now(eastern)

    if now.weekday() >= 5:
        return False, "Market closed: weekend"

    market_open = time(9, 30)
    market_close = time(16, 0)

    if not (market_open <= now.time() <= market_close):
        return False, "Market closed: outside regular hours"

    return True, "Market open"
