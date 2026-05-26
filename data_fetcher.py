# ============================================================
# data_fetcher.py
# Fetch EUR/USD candles from OANDA
# ============================================================

import os
import requests
from dotenv import load_dotenv

# Load .env locally
load_dotenv()

# -------------------------
# Config
# -------------------------

OANDA_API_KEY = os.getenv("OANDA_API_KEY")

BASE_URL = "https://api-fxpractice.oanda.com/v3"
INSTRUMENT = "EUR_USD"
GRANULARITY = "M15"
COUNT = 50


def get_candles():

    if not OANDA_API_KEY:
        raise Exception(
            "❌ OANDA_API_KEY missing. "
            "Add it in Railway Variables or .env"
        )

    url = f"{BASE_URL}/instruments/{INSTRUMENT}/candles"

    headers = {
        "Authorization": f"Bearer {OANDA_API_KEY}",
        "Content-Type": "application/json"
    }

    params = {
        "count": COUNT,
        "granularity": GRANULARITY,
        "price": "M"
    }

    try:

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

        if not candles:
            print("⚠️ No candles returned")

        return candles


    except requests.exceptions.HTTPError:

        if response.status_code == 401:

            print("""
❌ OANDA Authentication Failed

Possible reasons:
1. Wrong API key
2. Missing Railway variable
3. Practice token used with live endpoint
4. Token expired

Check:

Railway → Variables

OANDA_API_KEY=YOUR_TOKEN
            """)

        raise


    except requests.exceptions.Timeout:
        print("❌ Request timeout")
        raise


    except Exception as e:
        print("❌ Error:", e)
        raise


# -------------------------
# Test
# -------------------------

if __name__ == "__main__":

    candles = get_candles()

    print("Fetched:", len(candles))

    if candles:
        print(candles[-1])