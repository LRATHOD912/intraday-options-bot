import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


class PositionManager:
    """Persist and manage multiple active option positions for the bot."""

    def __init__(self, file_path: str = "positions.json") -> None:
        self.file_path = Path(file_path)
        self._positions = []
        self._load()

    def _default_position(self, position: dict) -> dict:
        normalized = dict(position)
        normalized.setdefault("position_id", str(uuid.uuid4()))
        normalized.setdefault("status", "OPEN")
        normalized.setdefault("realized_pnl", 0.0)
        normalized.setdefault("broker", None)
        normalized.setdefault("strategy_name", None)
        normalized.setdefault("trailing_stop_price", None)
        normalized.setdefault("highest_price_seen", None)
        normalized.setdefault("lowest_price_seen", None)
        normalized.setdefault("exit_time", None)
        normalized.setdefault("exit_price", None)
        normalized.setdefault("close_time", None)
        normalized.setdefault("remaining_quantity", int(normalized.get("remaining_quantity", normalized.get("quantity", 0)) or 0))
        normalized.setdefault("quantity", int(normalized.get("quantity", normalized.get("remaining_quantity", 0)) or 0))
        return normalized

    def _load(self) -> None:
        self._positions = []
        if not self.file_path.exists():
            return

        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return

        positions = []
        if isinstance(data, dict):
            raw_positions = data.get("positions")
            if isinstance(raw_positions, list):
                positions = raw_positions
            else:
                legacy_position = data.get("position")
                if isinstance(legacy_position, dict):
                    positions = [legacy_position]
        elif isinstance(data, list):
            positions = data

        for position in positions:
            if isinstance(position, dict):
                self._positions.append(self._default_position(position))

    def _save(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "positions": self._positions,
            "position": self._positions[0] if self._positions else None,
            "open_positions": [position for position in self._positions if position.get("status") == "OPEN"],
        }
        self.file_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def _open_positions(self) -> list[dict]:
        return [position for position in self._positions if position.get("status") == "OPEN"]

    def _find_index(self, position_id: str) -> Optional[int]:
        for index, position in enumerate(self._positions):
            if str(position.get("position_id")) == str(position_id):
                return index
        return None

    def _first_open_index(self) -> Optional[int]:
        for index, position in enumerate(self._positions):
            if position.get("status") == "OPEN":
                return index
        return None

    def has_open_position(self) -> bool:
        return len(self._open_positions()) > 0

    def get_open_positions(self) -> list[dict]:
        return [dict(position) for position in self._open_positions()]

    def get_open_position(self) -> Optional[dict]:
        positions = self.get_open_positions()
        return positions[0] if positions else None

    def get_position(self, position_id: str) -> Optional[dict]:
        index = self._find_index(position_id)
        if index is None:
            return None
        return dict(self._positions[index])

    def get_all_positions(self) -> list[dict]:
        return [dict(position) for position in self._positions]

    def get_total_open_risk(self) -> float:
        total_risk = 0.0
        for position in self._open_positions():
            risk_per_contract = float(position.get("risk_per_contract", 0.0) or 0.0)
            remaining_quantity = int(position.get("remaining_quantity", position.get("quantity", 0)) or 0)
            total_risk += risk_per_contract * remaining_quantity * 100.0
        return float(total_risk)

    def find_open_positions(self, symbol: Optional[str] = None, option_symbol: Optional[str] = None, direction: Optional[str] = None) -> list[dict]:
        matches = []
        for position in self._open_positions():
            if symbol is not None and str(position.get("symbol")) != str(symbol):
                continue
            if option_symbol is not None and str(position.get("option_symbol")) != str(option_symbol):
                continue
            if direction is not None and str(position.get("direction")) != str(direction):
                continue
            matches.append(dict(position))
        return matches

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
        metadata: Optional[dict] = None,
        entry_time: Optional[str] = None,
        order_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
        broker: Optional[str] = None,
    ) -> dict:
        if direction not in ["CALL", "PUT"]:
            raise ValueError("direction must be CALL or PUT")

        original_quantity = int(quantity)
        risk_value = float(risk_per_contract) if risk_per_contract is not None else abs(float(entry_price) - float(stop_price))
        target_1x = float(target_0) if target_0 is not None else None
        target_2x = float(target_1) if target_1 is not None else None
        target_3x = float(target_2) if target_2 is not None else None
        target_4x = float(target_3) if target_3 is not None else (float(target_4) if target_4 is not None else None)
        position_id = str(uuid.uuid4())

        position = {
            "position_id": position_id,
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
            "took_3x_profit": False,
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
            "strategy_name": strategy_name,
            "broker": broker,
            "status": "OPEN",
            "realized_pnl": 0.0,
            "exit_time": None,
            "exit_price": None,
            "close_time": None,
        }
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                position[str(key)] = value
        self._positions.append(self._default_position(position))
        self._save()
        return dict(self._positions[-1])

    def update_position(self, position_id: str, updates: dict) -> Optional[dict]:
        index = self._find_index(position_id)
        if index is None:
            return None

        for key, value in updates.items():
            self._positions[index][key] = value

        self._save()
        return dict(self._positions[index])

    def update_open_position(self, updates: dict) -> Optional[dict]:
        index = self._first_open_index()
        if index is None:
            return None
        position_id = str(self._positions[index].get("position_id"))
        return self.update_position(position_id, updates)

    def close_position(
        self,
        position_id: Optional[str] = None,
        close_time: Optional[str] = None,
        exit_price: Optional[float] = None,
        realized_pnl: Optional[float] = None,
    ) -> Optional[dict]:
        if position_id is None:
            index = self._first_open_index()
        else:
            index = self._find_index(position_id)
        if index is None:
            return None

        position = self._positions[index]
        position["status"] = "CLOSED"
        position["exit_time"] = close_time or datetime.utcnow().isoformat()
        position["close_time"] = position["exit_time"]
        if exit_price is not None:
            position["exit_price"] = float(exit_price)
        if realized_pnl is not None:
            position["realized_pnl"] = float(realized_pnl)
        position["remaining_quantity"] = 0

        self._save()
        return dict(position)

    def close_all_positions(self, close_time: Optional[str] = None) -> list[dict]:
        closed = []
        for position in list(self._open_positions()):
            closed_position = self.close_position(position.get("position_id"), close_time=close_time)
            if closed_position is not None:
                closed.append(closed_position)
        return closed


_default_manager = PositionManager()


def has_open_position() -> bool:
    return _default_manager.has_open_position()


def get_open_position() -> Optional[dict]:
    return _default_manager.get_open_position()


def get_position(position_id: str) -> Optional[dict]:
    return _default_manager.get_position(position_id)


def get_open_positions() -> list[dict]:
    return _default_manager.get_open_positions()


def get_all_positions() -> list[dict]:
    return _default_manager.get_all_positions()


def get_total_open_risk() -> float:
    return _default_manager.get_total_open_risk()


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
    metadata: Optional[dict] = None,
    entry_time: Optional[str] = None,
    order_id: Optional[str] = None,
    strategy_name: Optional[str] = None,
    broker: Optional[str] = None,
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
        metadata=metadata,
        entry_time=entry_time,
        order_id=order_id,
        strategy_name=strategy_name,
        broker=broker,
    )


def update_position(position_id: str, updates: dict) -> Optional[dict]:
    return _default_manager.update_position(position_id=position_id, updates=updates)


def update_open_position(updates: dict) -> Optional[dict]:
    return _default_manager.update_open_position(updates=updates)


def close_position(position_id: Optional[str] = None, close_time: Optional[str] = None, exit_price: Optional[float] = None, realized_pnl: Optional[float] = None) -> Optional[dict]:
    return _default_manager.close_position(position_id=position_id, close_time=close_time, exit_price=exit_price, realized_pnl=realized_pnl)


def close_all_positions(close_time: Optional[str] = None) -> list[dict]:
    return _default_manager.close_all_positions(close_time=close_time)
