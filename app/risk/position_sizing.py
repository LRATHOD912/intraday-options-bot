from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Optional

from app.broker.alpaca_client import get_trading_client
from app.config import (
    MAX_CONTRACTS_PER_TRADE,
    MAX_TRADE_BUDGET_PERCENT,
    MIN_CONTRACTS_PER_TRADE,
    MIN_TRADE_BUDGET_PERCENT,
    PAPER_ACCOUNT_SIZE,
    TRADE_BUDGET_PERCENT,
)


@dataclass(frozen=True)
class PositionSizingDecision:
    quantity: int
    buying_power: float
    trade_budget: float
    contract_cost: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "quantity": int(self.quantity),
            "buying_power": round(float(self.buying_power), 2),
            "trade_budget": round(float(self.trade_budget), 2),
            "contract_cost": round(float(self.contract_cost), 2),
            "reason": self.reason,
        }


def get_available_budget() -> float:
    try:
        account = get_trading_client().get_account()
        buying_power = getattr(account, "buying_power", None)
        if buying_power is not None:
            return float(buying_power)
    except Exception:
        pass
    return float(PAPER_ACCOUNT_SIZE)


def calculate_contract_quantity(option_price: float, buying_power: float, budget_percent: float) -> int:
    option_price = float(option_price)
    buying_power = float(buying_power)
    budget_percent = float(budget_percent)
    if option_price <= 0 or buying_power <= 0:
        return 0
    budget_percent = max(float(MIN_TRADE_BUDGET_PERCENT), min(float(MAX_TRADE_BUDGET_PERCENT), budget_percent))
    trade_budget = buying_power * budget_percent
    contract_cost = option_price * 100.0
    if contract_cost <= 0:
        return 0
    quantity = floor(trade_budget / contract_cost)
    quantity = max(0, int(quantity))
    if quantity > 0:
        quantity = max(int(MIN_CONTRACTS_PER_TRADE), min(int(MAX_CONTRACTS_PER_TRADE), quantity))
    return int(quantity)


def build_position_sizing_decision(
    option_price: float,
    buying_power: Optional[float] = None,
    budget_percent: Optional[float] = None,
) -> dict:
    resolved_buying_power = float(get_available_budget() if buying_power is None else buying_power)
    resolved_budget_percent = float(TRADE_BUDGET_PERCENT if budget_percent is None else budget_percent)
    resolved_budget_percent = max(float(MIN_TRADE_BUDGET_PERCENT), min(float(MAX_TRADE_BUDGET_PERCENT), resolved_budget_percent))
    contract_cost = float(option_price) * 100.0
    trade_budget = resolved_buying_power * resolved_budget_percent
    quantity = calculate_contract_quantity(float(option_price), resolved_buying_power, resolved_budget_percent)
    if quantity < 1:
        reason = "budget_too_small"
    else:
        reason = "budget_sizing_ok"
    return PositionSizingDecision(
        quantity=quantity,
        buying_power=resolved_buying_power,
        trade_budget=trade_budget,
        contract_cost=contract_cost,
        reason=reason,
    ).to_dict()