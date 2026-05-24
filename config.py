import os
from dotenv import load_dotenv

load_dotenv()

# --- Groq ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL   = "llama-3.3-70b-versatile"

# --- OANDA ---
OANDA_API_KEY    = os.environ.get("OANDA_API_KEY")
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID")
OANDA_BASE_URL   = "https://api-fxpractice.oanda.com"

# --- Strategy Settings ---
INSTRUMENT     = "EUR_USD"
GRANULARITY    = "M15"
CANDLE_COUNT   = 50
RISK_PERCENT   = 1.0
MAX_TRADES_DAY = 3

# --- Kill Zone Windows (UTC) ---
KILL_ZONES = [
    {"name": "London Open", "start_hour": 7,  "end_hour": 10},
    {"name": "NY Open",     "start_hour": 12, "end_hour": 15},
]

# --- Logging ---
TRADE_LOG_FILE = "trade_log.csv"