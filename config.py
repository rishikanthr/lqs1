"""
config.py — All settings for the Liquidity Sweep + Reversal Bot
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# OANDA API
# ============================================================
OANDA_API_KEY    = os.environ.get("OANDA_API_KEY", "")
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "")
OANDA_PRACTICE   = os.environ.get("OANDA_PRACTICE", "true").lower() == "true"

# Automatically switches between practice and live
OANDA_BASE_URL = (
    "https://api-fxpractice.oanda.com"
    if OANDA_PRACTICE else
    "https://api-fxtrade.oanda.com"
)

# ============================================================
# Telegram
# ============================================================
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ============================================================
# Pairs and pip sizes
# ============================================================
PAIRS = [
    "EUR_USD",
    "GBP_USD",
    "USD_JPY",
    "USD_CHF",
    "AUD_USD",
    "USD_CAD",
]

# Pip size per pair — used for SL/TP/position sizing
PIP_SIZE = {
    "EUR_USD": 0.0001,
    "GBP_USD": 0.0001,
    "USD_JPY": 0.01,
    "USD_CHF": 0.0001,
    "AUD_USD": 0.0001,
    "USD_CAD": 0.0001,
}

# Pip value per unit in USD (approximate, for a standard 1-unit position)
# Used for position sizing on JPY and CAD pairs
# EUR_USD, GBP_USD, AUD_USD, USD_CHF: pip value ~ $0.0001 per unit
# USD_JPY: pip = 0.01 yen, value in USD depends on rate — handled dynamically
# USD_CAD: pip = 0.0001, value ~ $0.0001 / CAD rate
PIP_VALUE_USD = {
    "EUR_USD": 0.0001,
    "GBP_USD": 0.0001,
    "USD_JPY": 0.0001,   # approximate — recalculated dynamically in trader.py
    "USD_CHF": 0.0001,   # approximate
    "AUD_USD": 0.0001,
    "USD_CAD": 0.0001,   # approximate
}

# ============================================================
# Candle settings
# ============================================================
# We fetch multiple timeframes for proper top-down analysis
CANDLE_CONFIG = {
    "D":   {"count": 15,  "label": "Daily"},    # 15 daily candles for trend
    "H4":  {"count": 30,  "label": "4H"},        # 30 × 4H = 5 days
    "H1":  {"count": 50,  "label": "1H"},        # 50 × 1H for sweep detection
    "M15": {"count": 100, "label": "15M"},       # 100 × 15M for entry + FVG + CHoCH
}

# ============================================================
# Strategy parameters
# ============================================================

# Equal highs/lows tolerance — two swings within this % = liquidity pool
EQUAL_LEVEL_TOLERANCE = 0.0008    # 0.08% — ~8 pips on EUR/USD

# Minimum sweep distance beyond the level (in price, not pips)
MIN_SWEEP_DISTANCE = {
    "EUR_USD": 0.0003,   # 3 pips
    "GBP_USD": 0.0003,
    "USD_JPY": 0.03,
    "USD_CHF": 0.0003,
    "AUD_USD": 0.0003,
    "USD_CAD": 0.0003,
}

# Displacement: body must be at least this % of total candle range
DISPLACEMENT_BODY_PCT = 0.60    # 60%

# Minimum displacement body size in price
MIN_DISPLACEMENT_BODY = {
    "EUR_USD": 0.0025,   # 25 pips
    "GBP_USD": 0.0025,
    "USD_JPY": 0.25,
    "USD_CHF": 0.0025,
    "AUD_USD": 0.0025,
    "USD_CAD": 0.0025,
}

# FVG minimum size
MIN_FVG_SIZE = {
    "EUR_USD": 0.0002,   # 2 pips
    "GBP_USD": 0.0002,
    "USD_JPY": 0.02,
    "USD_CHF": 0.0002,
    "AUD_USD": 0.0002,
    "USD_CAD": 0.0002,
}

# FVG expiry — how many candles old an FVG can be before ignored
FVG_EXPIRY_CANDLES = 20

# Swing detection lookback — how many candles each side to confirm a pivot
SWING_LOOKBACK = 5

# ============================================================
# Kill Zones (UTC hours)
# ============================================================
KILL_ZONES = [
    {"name": "London Open",  "start": 7,  "end": 10},
    {"name": "NY Open",      "start": 12, "end": 15},
    {"name": "London Close", "start": 10, "end": 12},   # optional, lower weight
]

# Only take signals inside kill zones
REQUIRE_KILL_ZONE = True

# ============================================================
# Risk Management — $100,000 account
# ============================================================
RISK_PERCENT        = 1.0     # 1% per trade = $1,000 risk per trade
MAX_TRADES_PER_DAY  = 4       # maximum across all pairs combined
MAX_OPEN_TRADES     = 2       # maximum simultaneously open positions
MAX_DAILY_LOSS_PCT  = 3.0     # circuit breaker: stop if down 3% ($3,000) in one day

# Take profit levels
TP1_RR = 2.0    # TP1 at 1:2 RR — close 50% here
TP2_RR = 4.0    # TP2 at 1:4 RR — close remaining 50% here

# After TP1 is hit, move SL to breakeven
MOVE_SL_TO_BE = True

# SL is placed this many pips BEYOND the sweep wick
SL_BUFFER_PIPS = {
    "EUR_USD": 3,
    "GBP_USD": 3,
    "USD_JPY": 5,
    "USD_CHF": 3,
    "AUD_USD": 3,
    "USD_CAD": 3,
}

# ============================================================
# Bot timing
# ============================================================
CHECK_INTERVAL_SECONDS = 60     # check for new candles every 60s
CANDLE_CLOSE_BUFFER_S  = 5      # wait 5s after candle close for OANDA to finalize

# ============================================================
# Logging — use /data for Railway persistent volume
# ============================================================
LOG_DIR         = "/data"
TRADE_LOG_FILE  = f"{LOG_DIR}/trades.csv"
SIGNAL_LOG_FILE = f"{LOG_DIR}/signals.csv"
STATE_FILE      = f"{LOG_DIR}/bot_state.json"    # persists daily counters across restarts