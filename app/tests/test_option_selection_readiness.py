import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.market.options_selector import choose_best_contract


class TestOptionSelectionReadiness(unittest.TestCase):
    def _contract(self, symbol, strike, days_out=1, oi=2500):
        return SimpleNamespace(symbol=symbol, strike_price=strike, expiration_date=date.today() + timedelta(days=days_out), open_interest=oi)

    def _snapshot(self, bid=1.0, ask=1.04, volume=2000, oi=2500, delta=0.4):
        return SimpleNamespace(
            latest_quote=SimpleNamespace(bid_price=bid, ask_price=ask),
            greeks=SimpleNamespace(delta=delta),
            daily_bar=SimpleNamespace(volume=volume),
            open_interest=oi,
        )

    @patch("app.market.options_selector.get_option_snapshot")
    @patch("app.market.options_selector.get_option_contracts")
    def test_choose_best_contract_put_returns_real_symbol(self, mock_contracts, mock_snapshot):
        mock_contracts.return_value = [self._contract("QQQ260710P00700000", 700)]
        mock_snapshot.return_value = self._snapshot(delta=0.42)

        contract, reason = choose_best_contract("QQQ", "PUT", 707.0)

        self.assertIsNotNone(contract)
        self.assertEqual(contract["symbol"], "QQQ260710P00700000")

    @patch("app.market.options_selector.get_option_snapshot")
    @patch("app.market.options_selector.get_option_contracts")
    def test_choose_best_contract_call_returns_real_symbol(self, mock_contracts, mock_snapshot):
        mock_contracts.return_value = [self._contract("QQQ260710C00710000", 710)]
        mock_snapshot.return_value = self._snapshot(delta=0.41)

        contract, reason = choose_best_contract("QQQ", "CALL", 707.0)

        self.assertIsNotNone(contract)
        self.assertEqual(contract["symbol"], "QQQ260710C00710000")

    @patch("app.market.options_selector.get_option_snapshot")
    @patch("app.market.options_selector.get_option_contracts_after_today")
    @patch("app.market.options_selector.get_option_contracts")
    @patch("app.market.options_selector.ALLOW_0DTE", False)
    def test_choose_best_contract_falls_back_to_non_zero_dte(self, mock_contracts, mock_after_today, mock_snapshot):
        mock_contracts.return_value = [self._contract("QQQ0DTEP00700000", 700, days_out=0)]
        mock_after_today.return_value = [self._contract("QQQ260710P00700000", 700, days_out=1)]
        mock_snapshot.return_value = self._snapshot(delta=0.42)

        contract, reason = choose_best_contract("QQQ", "PUT", 707.0)

        self.assertIsNotNone(contract)
        self.assertEqual(contract["symbol"], "QQQ260710P00700000")


if __name__ == "__main__":
    unittest.main()