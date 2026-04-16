import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "15"))
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

MARKET_TZ = ZoneInfo("US/Eastern")
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 0

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "stock_bot.db")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
