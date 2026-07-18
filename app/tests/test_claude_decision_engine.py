import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.ai import claude_decision_engine


class TestClaudeDecisionEngine(unittest.TestCase):
    def test_disabled_engine_returns_no_trade(self):
        with patch.object(claude_decision_engine, "CLAUDE_DECISION_ENABLED", False):
            decision = claude_decision_engine.get_claude_trade_decision({"paper_trading_confirmed": True})

        self.assertEqual(decision.decision, "NO_TRADE")
        self.assertIn("disabled", decision.reason.lower())

    def test_missing_api_key_returns_no_trade(self):
        with patch.object(claude_decision_engine, "CLAUDE_DECISION_ENABLED", True), patch.object(claude_decision_engine, "ANTHROPIC_API_KEY", ""):
            decision = claude_decision_engine.get_claude_trade_decision({"paper_trading_confirmed": True})

        self.assertEqual(decision.decision, "NO_TRADE")
        self.assertIn("missing", decision.reason.lower())

    def test_valid_structured_response_returns_trade(self):
        fake_response = SimpleNamespace(
            id="resp_123",
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_trade_decision",
                    input={
                        "decision": "CALL",
                        "confidence": 0.78,
                        "strategy": "VWAP_BOUNCE",
                        "reason": "Price reclaimed VWAP with supportive trend alignment",
                        "supporting_factors": ["Above VWAP", "Bullish EMA stack"],
                        "conflicting_factors": ["Volume only moderate"],
                        "position_size_percent": 0.2,
                        "exit_profile": "balanced",
                        "max_hold_minutes": 25,
                        "require_tighter_spread": True,
                        "risk_notes": ["Respect VWAP failure"],
                    },
                )
            ],
        )
        fake_client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: fake_response))

        with patch.object(claude_decision_engine, "CLAUDE_DECISION_ENABLED", True), patch.object(claude_decision_engine, "ANTHROPIC_API_KEY", "test-key"), patch.object(claude_decision_engine, "Anthropic", return_value=fake_client):
            decision = claude_decision_engine.get_claude_trade_decision(
                {
                    "paper_trading_confirmed": True,
                    "existing_signal": "CALL",
                    "latest_bar": {"close": 500.0},
                }
            )

        self.assertEqual(decision.decision, "CALL")
        self.assertEqual(decision.strategy, "VWAP_BOUNCE")
        self.assertAlmostEqual(decision.position_size_percent, 0.2)
        self.assertEqual(decision.raw_response_id, "resp_123")

    def test_conflicting_existing_signal_forces_no_trade(self):
        fake_response = SimpleNamespace(
            id="resp_456",
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_trade_decision",
                    input={
                        "decision": "CALL",
                        "confidence": 0.9,
                        "strategy": "VWAP_BOUNCE",
                        "reason": "Bullish reversal",
                        "supporting_factors": ["Bounce off support"],
                        "conflicting_factors": [],
                        "position_size_percent": 0.15,
                        "exit_profile": "balanced",
                        "max_hold_minutes": 20,
                        "require_tighter_spread": False,
                        "risk_notes": [],
                    },
                )
            ],
        )
        fake_client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: fake_response))

        with patch.object(claude_decision_engine, "CLAUDE_DECISION_ENABLED", True), patch.object(claude_decision_engine, "ANTHROPIC_API_KEY", "test-key"), patch.object(claude_decision_engine, "Anthropic", return_value=fake_client):
            decision = claude_decision_engine.get_claude_trade_decision(
                {
                    "paper_trading_confirmed": True,
                    "existing_signal": "PUT",
                    "latest_bar": {"close": 500.0},
                }
            )

        self.assertEqual(decision.decision, "NO_TRADE")
        self.assertIn("conflicts", decision.reason.lower())

    def test_timeout_returns_no_trade(self):
        with patch.object(claude_decision_engine, "CLAUDE_DECISION_ENABLED", True), patch.object(claude_decision_engine, "ANTHROPIC_API_KEY", "test-key"), patch.object(claude_decision_engine, "Anthropic", side_effect=TimeoutError("timeout")):
            decision = claude_decision_engine.get_claude_trade_decision(
                {
                    "paper_trading_confirmed": True,
                    "existing_signal": "PUT",
                    "latest_bar": {"close": 500.0},
                }
            )

        self.assertEqual(decision.decision, "NO_TRADE")
        self.assertIn("timeout", decision.reason.lower())

    def test_invalid_response_returns_no_trade(self):
        fake_response = SimpleNamespace(id="resp_invalid", content=[])
        fake_client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: fake_response))

        with patch.object(claude_decision_engine, "CLAUDE_DECISION_ENABLED", True), patch.object(claude_decision_engine, "ANTHROPIC_API_KEY", "test-key"), patch.object(claude_decision_engine, "Anthropic", return_value=fake_client):
            decision = claude_decision_engine.get_claude_trade_decision(
                {
                    "paper_trading_confirmed": True,
                    "existing_signal": "PUT",
                    "latest_bar": {"close": 500.0},
                }
            )

        self.assertEqual(decision.decision, "NO_TRADE")
        self.assertIn("structured decision", decision.reason.lower())

    def test_sdk_exception_returns_no_trade_and_updates_status(self):
        with patch.object(claude_decision_engine, "CLAUDE_DECISION_ENABLED", True), patch.object(claude_decision_engine, "ANTHROPIC_API_KEY", "test-key"), patch.object(claude_decision_engine, "Anthropic", side_effect=RuntimeError("sdk boom")):
            decision = claude_decision_engine.get_claude_trade_decision(
                {
                    "paper_trading_confirmed": True,
                    "existing_signal": "PUT",
                    "latest_bar": {"close": 500.0},
                }
            )

        self.assertEqual(decision.decision, "NO_TRADE")
        status = claude_decision_engine.get_claude_status()
        self.assertEqual(status["api_status"], "error")
        self.assertIn("RuntimeError", status["last_error"])

    def test_no_api_credits_used_when_disabled(self):
        with patch.object(claude_decision_engine, "CLAUDE_DECISION_ENABLED", False), patch.object(claude_decision_engine, "Anthropic") as mock_sdk:
            decision = claude_decision_engine.get_claude_trade_decision({"paper_trading_confirmed": True})

        self.assertEqual(decision.decision, "NO_TRADE")
        mock_sdk.assert_not_called()


if __name__ == "__main__":
    unittest.main()