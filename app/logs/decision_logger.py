import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


def _to_jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (np.ndarray,)):
        return [_to_jsonable(item) for item in value.tolist()]
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().isoformat()
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return _to_jsonable(value.to_dict())
        except Exception:
            pass
    return str(value)


def log_decision(decision: dict) -> Path:
    root = Path(__file__).resolve().parents[2]
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "decisions.jsonl"

    eastern = ZoneInfo("America/New_York")
    payload = {
        "timestamp": datetime.now(eastern).isoformat(),
        **_to_jsonable(decision),
    }

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return log_path
