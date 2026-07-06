MAX_TRADES_PER_DAY = 2
MAX_LOSSES_PER_DAY = 2
MAX_POSITION_SIZE = 1
DEFAULT_STOP_LOSS_PERCENT = 0.20
DEFAULT_TAKE_PROFIT_PERCENT = 0.25


class RiskManager:
    def __init__(self):
        self.trades_today = 0
        self.losses_today = 0

    def can_trade(self):
        if self.trades_today >= MAX_TRADES_PER_DAY:
            return False, "Max trades reached"
        if self.losses_today >= MAX_LOSSES_PER_DAY:
            return False, "Max losses reached"
        return True, "Trading allowed"

    def get_position_size(self):
        return MAX_POSITION_SIZE

    def record_trade(self, was_loss=False):
        self.trades_today += 1
        if was_loss:
            self.losses_today += 1
