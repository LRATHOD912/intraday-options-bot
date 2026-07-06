import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TRADE_JOURNAL_PATH = Path("logs/trade_journal.jsonl")


def log_trade_event(event_type, payload):
    record = {
        "timestamp": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "event_type": str(event_type),
        "payload": payload,
    }
    TRADE_JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRADE_JOURNAL_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
