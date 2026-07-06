import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


STATE_PATH = Path("logs/daily_risk_state.json")
MAX_TRADES_PER_DAY = 2
MAX_LOSSES_PER_DAY = 2
MAX_DAILY_LOSS = -300.0


class DailyRiskManager:
    def __init__(self, file_path: Path = STATE_PATH):
        self.file_path = file_path
        self.state = {
            "date": self._today_et(),
            "trades_today": 0,
            "losses_today": 0,
            "realized_pnl": 0.0,
        }
        self._load()
        self.reset_if_new_day()

    def _today_et(self) -> str:
        return datetime.now(ZoneInfo("America/New_York")).date().isoformat()

    def _load(self) -> None:
        if not self.file_path.exists():
            return
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.state.update(data)
        except json.JSONDecodeError:
            return

    def _save(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def reset_if_new_day(self) -> None:
        today = self._today_et()
        if self.state.get("date") != today:
            self.state = {
                "date": today,
                "trades_today": 0,
                "losses_today": 0,
                "realized_pnl": 0.0,
            }
            self._save()

    def can_take_new_trade(self) -> bool:
        self.reset_if_new_day()
        trades_today = int(self.state.get("trades_today", 0))
        losses_today = int(self.state.get("losses_today", 0))
        realized_pnl = float(self.state.get("realized_pnl", 0.0))

        if trades_today >= MAX_TRADES_PER_DAY:
            return False
        if losses_today >= MAX_LOSSES_PER_DAY:
            return False
        if realized_pnl <= MAX_DAILY_LOSS:
            return False
        return True

    def record_trade_result(self, pnl, was_loss) -> None:
        self.reset_if_new_day()
        self.state["trades_today"] = int(self.state.get("trades_today", 0)) + 1
        if was_loss:
            self.state["losses_today"] = int(self.state.get("losses_today", 0)) + 1
        self.state["realized_pnl"] = round(float(self.state.get("realized_pnl", 0.0)) + float(pnl), 2)
        self._save()


_default_manager = DailyRiskManager()


def can_take_new_trade() -> bool:
    return _default_manager.can_take_new_trade()


def record_trade_result(pnl, was_loss) -> None:
    _default_manager.record_trade_result(pnl=pnl, was_loss=was_loss)


def reset_if_new_day() -> None:
    _default_manager.reset_if_new_day()
