import unittest

from app.risk.position_sizing import build_position_sizing_decision, calculate_contract_quantity


class TestPositionSizing(unittest.TestCase):
    def test_quantity_respects_budget_and_limits(self):
        self.assertEqual(calculate_contract_quantity(2.0, 10000.0, 0.35), 10)
        self.assertEqual(calculate_contract_quantity(25.0, 10000.0, 0.35), 1)
        self.assertEqual(calculate_contract_quantity(0.0, 10000.0, 0.35), 0)

    def test_build_position_sizing_decision_returns_expected_shape(self):
        decision = build_position_sizing_decision(2.0, buying_power=10000.0, budget_percent=0.35)

        self.assertEqual(decision["quantity"], 10)
        self.assertEqual(decision["buying_power"], 10000.0)
        self.assertEqual(decision["trade_budget"], 3500.0)
        self.assertEqual(decision["contract_cost"], 200.0)
        self.assertIn(decision["reason"], {"budget_sizing_ok", "budget_too_small"})


if __name__ == "__main__":
    unittest.main()