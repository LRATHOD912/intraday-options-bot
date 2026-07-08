from dotenv import load_dotenv
import os

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"
ALPACA_ENDPOINT = os.getenv("ALPACA_ENDPOINT")
ENABLE_TRADING = os.getenv("ENABLE_TRADING", "false").lower() == "true"
SIMULATE_POSITIONS = os.getenv("SIMULATE_POSITIONS", "false").lower() == "true"
USE_ALPACA_PAPER_EXECUTION = os.getenv("USE_ALPACA_PAPER_EXECUTION", "true").lower() == "true"
PAPER_AGGRESSIVE_MODE = os.getenv("PAPER_AGGRESSIVE_MODE", "false").lower() == "true"
PAPER_AGGRESSIVE_MIN_CONFIDENCE = float(os.getenv("PAPER_AGGRESSIVE_MIN_CONFIDENCE", "0.65"))
PAPER_AGGRESSIVE_MAX_SPREAD_PERCENT = float(os.getenv("PAPER_AGGRESSIVE_MAX_SPREAD_PERCENT", "0.08"))
PAPER_AGGRESSIVE_MIN_ENTRY_QUALITY = int(os.getenv("PAPER_AGGRESSIVE_MIN_ENTRY_QUALITY", "55"))
BOT_LOOP_SECONDS = int(os.getenv("BOT_LOOP_SECONDS", "60"))
BOT_START_TIME = os.getenv("BOT_START_TIME", "09:45")
BOT_END_TIME = os.getenv("BOT_END_TIME", "12:00")
API_TOKEN = os.getenv("API_TOKEN", "change_this_secret")
VIEW_TOKEN = os.getenv("VIEW_TOKEN", "change_this_view_token").strip()
POSITION_QUANTITY = int(os.getenv("POSITION_QUANTITY", "4"))
BACKTEST_USE_STAGED_EXITS = os.getenv("BACKTEST_USE_STAGED_EXITS", "false").lower() == "true"
USE_TUNED_STAGED_EXITS = os.getenv("USE_TUNED_STAGED_EXITS", "false").lower() == "true"

# Regime and entry quality controls.
USE_REGIME_FILTER = os.getenv("USE_REGIME_FILTER", "false").lower() == "true"
MIN_ENTRY_QUALITY_SCORE = int(os.getenv("MIN_ENTRY_QUALITY_SCORE", "75"))
REGIME_THRESHOLD_TREND_UP = int(os.getenv("REGIME_THRESHOLD_TREND_UP", "75"))
REGIME_THRESHOLD_TREND_DOWN = int(os.getenv("REGIME_THRESHOLD_TREND_DOWN", "75"))
REGIME_THRESHOLD_POWER_TREND = int(os.getenv("REGIME_THRESHOLD_POWER_TREND", "72"))
REGIME_THRESHOLD_BREAKOUT = int(os.getenv("REGIME_THRESHOLD_BREAKOUT", "70"))
REGIME_THRESHOLD_EXPANSION = int(os.getenv("REGIME_THRESHOLD_EXPANSION", "70"))
REGIME_THRESHOLD_REVERSAL = int(os.getenv("REGIME_THRESHOLD_REVERSAL", "60"))
REGIME_THRESHOLD_RANGE = int(os.getenv("REGIME_THRESHOLD_RANGE", "58"))
REGIME_THRESHOLD_CHOPPY = int(os.getenv("REGIME_THRESHOLD_CHOPPY", "62"))
REGIME_THRESHOLD_LOW_VOLATILITY = int(os.getenv("REGIME_THRESHOLD_LOW_VOLATILITY", "80"))
REGIME_THRESHOLD_HIGH_VOLATILITY = int(os.getenv("REGIME_THRESHOLD_HIGH_VOLATILITY", "72"))
REGIME_THRESHOLD_COMPRESSION = int(os.getenv("REGIME_THRESHOLD_COMPRESSION", "78"))
REGIME_THRESHOLD_DEFAULT = int(os.getenv("REGIME_THRESHOLD_DEFAULT", "75"))

# Dynamic position sizing controls.
USE_DYNAMIC_POSITION_SIZE = os.getenv("USE_DYNAMIC_POSITION_SIZE", "false").lower() == "true"
BASE_POSITION_QUANTITY = int(os.getenv("BASE_POSITION_QUANTITY", "1"))
MAX_POSITION_QUANTITY = int(os.getenv("MAX_POSITION_QUANTITY", "4"))

# Multi-position controls.
ALLOW_MULTIPLE_POSITIONS = os.getenv("ALLOW_MULTIPLE_POSITIONS", "true").lower() == "true"
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "4"))
ALLOW_OPPOSITE_DIRECTION_POSITIONS = os.getenv("ALLOW_OPPOSITE_DIRECTION_POSITIONS", "false").lower() == "true"
ENABLE_HEDGE_MODE = os.getenv("ENABLE_HEDGE_MODE", "false").lower() == "true"

# Exit profile controls.
EXIT_PROFILE = os.getenv("EXIT_PROFILE", "baseline").lower()

# Strategy router controls.
USE_STRATEGY_ROUTER = os.getenv("USE_STRATEGY_ROUTER", "false").lower() == "true"
ENABLE_MOMENTUM_BREAKOUT = os.getenv("ENABLE_MOMENTUM_BREAKOUT", "false").lower() == "true"
ENABLE_TREND_PULLBACK = os.getenv("ENABLE_TREND_PULLBACK", "false").lower() == "true"
ENABLE_VWAP_BOUNCE = os.getenv("ENABLE_VWAP_BOUNCE", "false").lower() == "true"
ENABLE_OPENING_RANGE_BREAKOUT = os.getenv("ENABLE_OPENING_RANGE_BREAKOUT", "false").lower() == "true"
ENABLE_GAP_AND_GO = os.getenv("ENABLE_GAP_AND_GO", "false").lower() == "true"
ENABLE_GAP_FILL_REVERSAL = os.getenv("ENABLE_GAP_FILL_REVERSAL", "false").lower() == "true"
ENABLE_RANGE_SCALP_0DTE = os.getenv("ENABLE_RANGE_SCALP_0DTE", "false").lower() == "true"
ENABLE_MEAN_REVERSION_0DTE = os.getenv("ENABLE_MEAN_REVERSION_0DTE", "false").lower() == "true"
ENABLE_MOMENTUM_RUNNER = os.getenv("ENABLE_MOMENTUM_RUNNER", "false").lower() == "true"
RANGE_SCALP_ONLY_PAPER = os.getenv("RANGE_SCALP_ONLY_PAPER", "true").lower() == "true"
ALLOW_0DTE_FOR_RANGE_SCALP = os.getenv("ALLOW_0DTE_FOR_RANGE_SCALP", "true").lower() == "true"
STRATEGY_AUTO_DISABLE_ENABLED = os.getenv("STRATEGY_AUTO_DISABLE_ENABLED", "true").lower() == "true"

# Option selection controls.
MIN_OPTION_VOLUME = int(os.getenv("MIN_OPTION_VOLUME", "500"))
MIN_OPTION_OPEN_INTEREST = int(os.getenv("MIN_OPTION_OPEN_INTEREST", "1000"))
MAX_OPTION_SPREAD_PERCENT = float(os.getenv("MAX_OPTION_SPREAD_PERCENT", "0.05"))
PREFERRED_DELTA_MIN = float(os.getenv("PREFERRED_DELTA_MIN", "0.35"))
PREFERRED_DELTA_MAX = float(os.getenv("PREFERRED_DELTA_MAX", "0.50"))
ALLOW_0DTE = os.getenv("ALLOW_0DTE", "false").lower() == "true"
OPTION_FILTER_STRICTNESS = os.getenv("OPTION_FILTER_STRICTNESS", "normal").lower()

# Strategy-specific option controls.
RANGE_SCALP_MIN_PREMIUM = float(os.getenv("RANGE_SCALP_MIN_PREMIUM", "0.30"))
RANGE_SCALP_MAX_PREMIUM = float(os.getenv("RANGE_SCALP_MAX_PREMIUM", "1.50"))
MEAN_REVERSION_MIN_PREMIUM = float(os.getenv("MEAN_REVERSION_MIN_PREMIUM", "0.50"))
MEAN_REVERSION_MAX_PREMIUM = float(os.getenv("MEAN_REVERSION_MAX_PREMIUM", "2.00"))
MOMENTUM_MIN_DELTA = float(os.getenv("MOMENTUM_MIN_DELTA", "0.35"))
MOMENTUM_MAX_DELTA = float(os.getenv("MOMENTUM_MAX_DELTA", "0.55"))
MEAN_REVERSION_MIN_DELTA = float(os.getenv("MEAN_REVERSION_MIN_DELTA", "0.25"))
MEAN_REVERSION_MAX_DELTA = float(os.getenv("MEAN_REVERSION_MAX_DELTA", "0.45"))

# Execution quality controls.
USE_LIMIT_ORDERS = os.getenv("USE_LIMIT_ORDERS", "true").lower() == "true"
MAX_ENTRY_SPREAD_PERCENT = float(os.getenv("MAX_ENTRY_SPREAD_PERCENT", "0.05"))
MIN_OPTION_PRICE = float(os.getenv("MIN_OPTION_PRICE", "0.50"))
MAX_OPTION_PRICE = float(os.getenv("MAX_OPTION_PRICE", "15.00"))
BACKTEST_SLIPPAGE_PERCENT = float(os.getenv("BACKTEST_SLIPPAGE_PERCENT", "0.00"))
BACKTEST_ENABLE_WALK_FORWARD = os.getenv("BACKTEST_ENABLE_WALK_FORWARD", "false").lower() == "true"
BACKTEST_WALK_FORWARD_FOLDS = int(os.getenv("BACKTEST_WALK_FORWARD_FOLDS", "3"))
BACKTEST_WALK_FORWARD_DAYS = int(os.getenv("BACKTEST_WALK_FORWARD_DAYS", "1"))

# Budget-based position sizing controls.
USE_BUDGET_POSITION_SIZING = os.getenv("USE_BUDGET_POSITION_SIZING", "true").lower() == "true"
TRADE_BUDGET_PERCENT = float(os.getenv("TRADE_BUDGET_PERCENT", "0.35"))
MIN_TRADE_BUDGET_PERCENT = float(os.getenv("MIN_TRADE_BUDGET_PERCENT", "0.30"))
MAX_TRADE_BUDGET_PERCENT = float(os.getenv("MAX_TRADE_BUDGET_PERCENT", "0.40"))
PAPER_ACCOUNT_SIZE = float(os.getenv("PAPER_ACCOUNT_SIZE", "10000"))
MAX_CONTRACTS_PER_TRADE = int(os.getenv("MAX_CONTRACTS_PER_TRADE", "10"))
MIN_CONTRACTS_PER_TRADE = int(os.getenv("MIN_CONTRACTS_PER_TRADE", "1"))
MAX_TOTAL_OPEN_RISK = float(os.getenv("MAX_TOTAL_OPEN_RISK", "500"))

# Strategy risk controls.
RANGE_SCALP_MAX_HOLD_MINUTES = int(os.getenv("RANGE_SCALP_MAX_HOLD_MINUTES", "12"))
MEAN_REVERSION_MAX_HOLD_MINUTES = int(os.getenv("MEAN_REVERSION_MAX_HOLD_MINUTES", "10"))
MOMENTUM_BREAKOUT_MAX_HOLD_MINUTES = int(os.getenv("MOMENTUM_BREAKOUT_MAX_HOLD_MINUTES", "45"))
VWAP_BOUNCE_MAX_HOLD_MINUTES = int(os.getenv("VWAP_BOUNCE_MAX_HOLD_MINUTES", "12"))

# Auto-pause controls.
USE_AUTO_PAUSE = os.getenv("USE_AUTO_PAUSE", "true").lower() == "true"
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "2"))
MIN_EXPECTANCY_LAST_20_TRADES = float(os.getenv("MIN_EXPECTANCY_LAST_20_TRADES", "0"))
MAX_DRAWDOWN_DAY = float(os.getenv("MAX_DRAWDOWN_DAY", "-300"))