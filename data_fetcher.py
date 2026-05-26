# ============================================================
# data_fetcher.py
# OANDA Data Fetcher + Kill Zone + Balance + Formatting
# ============================================================

import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

# ============================================================
# Environment Variables
# ============================================================

OANDA_API_KEY = os.getenv("OANDA_API_KEY")
ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")

BASE_URL = "https://api-fxpractice.oanda.com/v3"


# ============================================================
# Kill Zones
# ============================================================

def in_kill_zone():

    now = datetime.now(timezone.utc)
    hour = now.hour

    # London Kill Zone
    if 7 <= hour < 10:
        return True, "London"

    # New York Kill Zone
    elif 12 <= hour < 15:
        return True, "New York"

    return False, None


# ============================================================
# Fetch EUR/USD candles
# ============================================================

def get_candles():

    if not OANDA_API_KEY:
        raise Exception(
            "❌ Missing OANDA_API_KEY"
        )

    url = f"{BASE_URL}/instruments/EUR_USD/candles"

    headers = {
        "Authorization": f"Bearer {OANDA_API_KEY}",
        "Content-Type": "application/json"
    }

    params = {
        "count": 50,
        "granularity": "M15",
        "price": "M"
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=15
    )

    print("Status:", response.status_code)

    response.raise_for_status()

    data = response.json()

    candles = data.get("candles", [])

    return candles


# ============================================================
# Get account balance
# ============================================================

def get_account_balance():

    if not ACCOUNT_ID:
        raise Exception(
            "❌ Missing OANDA_ACCOUNT_ID"
        )

    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}"

    headers = {
        "Authorization": f"Bearer {OANDA_API_KEY}"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    balance = float(
        data["account"]["balance"]
    )

    return balance


# ============================================================
# Format candles for Claude / AI analysis
# ============================================================

def format_candles_for_claude(candles):

    formatted = []

    for candle in candles:

        formatted.append({

            "time":
            candle["time"],

            "open":
            float(candle["mid"]["o"]),

            "high":
            float(candle["mid"]["h"]),

            "low":
            float(candle["mid"]["l"]),

            "close":
            float(candle["mid"]["c"]),

            "volume":
            candle["volume"]

        })

    return formatted


# ============================================================
# Test
# ============================================================

if __name__ == "__main__":

    print("Testing...\n")

    in_kz, kz_name = in_kill_zone()

    print("Kill Zone:", in_kz)
    print("Session:", kz_name)

    balance = get_account_balance()

    print("Balance:", balance)

    candles = get_candles()

    print("Candles:", len(candles))

    formatted = format_candles_for_claude(
        candles
    )

    print(
        "Latest candle:",
        formatted[-1]
    )