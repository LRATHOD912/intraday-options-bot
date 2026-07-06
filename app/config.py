from dotenv import load_dotenv
import os

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_PAPER = os.getenv("ALPACA_PAPER")
ALPACA_ENDPOINT = os.getenv("ALPACA_ENDPOINT")
ENABLE_TRADING = os.getenv("ENABLE_TRADING", "false").lower() == "true"
SIMULATE_POSITIONS = os.getenv("SIMULATE_POSITIONS", "true").lower() == "true"
BOT_LOOP_SECONDS = int(os.getenv("BOT_LOOP_SECONDS", "60"))
BOT_START_TIME = os.getenv("BOT_START_TIME", "09:45")
BOT_END_TIME = os.getenv("BOT_END_TIME", "12:00")
API_TOKEN = os.getenv("API_TOKEN", "change_this_secret")