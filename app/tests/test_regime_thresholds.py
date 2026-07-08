import unittest

from app.risk.regime_thresholds import get_entry_quality_threshold, get_regime_risk_multiplier


class TestRegimeThresholds(unittest.TestCase):
    def test_choppy_threshold(self):
        self.assertEqual(get_entry_quality_threshold("CHOPPY"), 62)

    def test_low_volatility_threshold(self):
        self.assertEqual(get_entry_quality_threshold("LOW_VOLATILITY"), 80)

    def test_reversal_threshold(self):
        self.assertEqual(get_entry_quality_threshold("REVERSAL"), 60)

    def test_reversal_59_fails_threshold_60(self):
        self.assertLess(59, get_entry_quality_threshold("REVERSAL"))

    def test_reversal_61_passes_even_though_static_75(self):
        self.assertGreaterEqual(61, get_entry_quality_threshold("REVERSAL"))
        self.assertLess(61, 75)

    def test_entry_quality_64_passes_choppy_but_fails_static_75(self):
        entry_quality = 64
        self.assertGreaterEqual(entry_quality, get_entry_quality_threshold("CHOPPY"))
        self.assertLess(entry_quality, 75)

    def test_choppy_64_passes_threshold_62(self):
        self.assertGreaterEqual(64, get_entry_quality_threshold("CHOPPY"))

    def test_entry_quality_64_fails_low_volatility(self):
        entry_quality = 64
        self.assertLess(entry_quality, get_entry_quality_threshold("LOW_VOLATILITY"))

    def test_choppy_multiplier_reduces_size_by_half(self):
        base_quantity = 4
        final_quantity = int(round(base_quantity * get_regime_risk_multiplier("CHOPPY")))
        self.assertEqual(final_quantity, 2)


if __name__ == "__main__":
    unittest.main()
