import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class PositionManager:
    """Persist and manage the single active option position for the bot."""

    def __init__(self, file_path: str = "positions.json") -> None:
        self.file_path = Path(file_path)
        self._position = None
        self._load()

    def _load(self) -> None:
        if not self.file_path.exists():
            self._position = None
            return

        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._position = None
            return

        position = data.get("position") if isinstance(data, dict) else None
        if isinstance(position, dict) and position.get("status") == "OPEN":
            self._position = position
        else:
            self._position = None

    def _save(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"position": self._position}
        self.file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def has_open_position(self) -> bool:
        return self._position is not None and self._position.get("status") == "OPEN"

    def get_open_position(self) -> Optional[dict]:
        if not self.has_open_position():
            return None
        return dict(self._position)

    def open_position(
        self,
        symbol: str,
        option_symbol: str,
        direction: str,
        quantity: int,
        entry_price: float,
        stop_price: float,
        target_0: float,
        target_1: float,
        target_2: float,
        target_3: Optional[float] = None,
        target_4: Optional[float] = None,
        risk_per_contract: Optional[float] = None,
        entry_time: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> dict:
        if self.has_open_position():
            raise ValueError("An open position already exists")

        if direction not in ["CALL", "PUT"]:
            raise ValueError("direction must be CALL or PUT")

        original_quantity = int(quantity)
        risk_value = float(risk_per_contract) if risk_per_contract is not None else abs(float(entry_price) - float(stop_price))
        target_1x = float(target_0) if target_0 is not None else None
        target_2x = float(target_1) if target_1 is not None else None
        target_3x = float(target_2) if target_2 is not None else None
        target_4x = float(target_3) if target_3 is not None else (float(target_4) if target_4 is not None else None)

        self._position = {
            "symbol": symbol,
            "option_symbol": option_symbol,
            "direction": direction,
            "quantity": original_quantity,
            "original_quantity": original_quantity,
            "remaining_quantity": original_quantity,
            "entry_price": float(entry_price),
            "stop_price": float(stop_price),
            "risk_per_contract": float(risk_value),
            "target_1x": target_1x,
            "target_2x": target_2x,
            "target_3x": target_3x,
            "target_4x": target_4x,
            "took_1x_profit": False,
            "took_2x_profit": False,
            "stop_moved_to_breakeven": False,
            "highest_price_seen": float(entry_price) if direction == "CALL" else None,
            "lowest_price_seen": float(entry_price) if direction == "PUT" else None,
            "trailing_stop_price": None,
            "target_0": float(target_0) if target_0 is not None else None,
            "target_1": float(target_1),
            "target_2": float(target_2),
            "target_3": float(target_3) if target_3 is not None else None,
            "target_4": float(target_4) if target_4 is not None else None,
            "entry_time": entry_time or datetime.utcnow().isoformat(),
            "order_id": order_id,
            "status": "OPEN",
        }
        self._save()
        return dict(self._position)

    def update_open_position(self, updates: dict) -> Optional[dict]:
        if not self.has_open_position():
            return None

        for key, value in updates.items():
            self._position[key] = value

        self._save()
        return dict(self._position)

    def close_position(self, close_time: Optional[str] = None, exit_price: Optional[float] = None) -> Optional[dict]:
        if not self.has_open_position():
            return None

        self._position["status"] = "CLOSED"
        self._position["close_time"] = close_time or datetime.utcnow().isoformat()
        if exit_price is not None:
            self._position["exit_price"] = float(exit_price)

        closed_snapshot = dict(self._position)
        self._position = None

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(json.dumps({"position": closed_snapshot}, indent=2), encoding="utf-8")
        return closed_snapshot


_default_manager = PositionManager()


def has_open_position() -> bool:
    return _default_manager.has_open_position()


def get_open_position() -> Optional[dict]:
    return _default_manager.get_open_position()


def open_position(
    symbol: str,
    option_symbol: str,
    direction: str,
    quantity: int,
    entry_price: float,
    stop_price: float,
    target_0: float,
    target_1: float,
    target_2: float,
    target_3: Optional[float] = None,
    target_4: Optional[float] = None,
    risk_per_contract: Optional[float] = None,
    entry_time: Optional[str] = None,
    order_id: Optional[str] = None,
) -> dict:
    return _default_manager.open_position(
        symbol=symbol,
        option_symbol=option_symbol,
        direction=direction,
        quantity=quantity,
        entry_price=entry_price,
        stop_price=stop_price,
        target_0=target_0,
        target_1=target_1,
        target_2=target_2,
        target_3=target_3,
        target_4=target_4,
        risk_per_contract=risk_per_contract,
        entry_time=entry_time,
        order_id=order_id,
    )


def close_position(close_time: Optional[str] = None, exit_price: Optional[float] = None) -> Optional[dict]:
    return _default_manager.close_position(close_time=close_time, exit_price=exit_price)


def update_open_position(updates: dict) -> Optional[dict]:
    return _default_manager.update_open_position(updates=updates)
