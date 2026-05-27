"""
data_fetcher.py — OANDA multi-timeframe candle fetching
Fetches Daily, 4H, 1H, 15M candles for each pair.
All functions raise on HTTP error so main loop can catch cleanly.
"""

import json
import requests
from datetime import datetime, timezone
from config import (
    OANDA_API_KEY, OANDA_ACCOUNT_ID, OANDA_BASE_URL,
    CANDLE_CONFIG, KILL_ZONES,
)

BASE    = f"{OANDA_BASE_URL}/v3"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json",
}


# ============================================================
# Kill Zone detection (minute-accurate)
# ============================================================

def get_kill_zone() -> tuple:
    """
    Returns (in_kill_zone: bool, kz_name: str | None).
    Uses minute-level precision, not just hour.
    Includes weekend + market-close guards.
    """
    now     = datetime.now(timezone.utc)
    weekday = now.weekday()   # 0=Mon, 4=Fri, 5=Sat, 6=Sun

    # Weekend guard
    if weekday == 5:
        return False, None
    if weekday == 6 and now.hour < 21:
        return False, None
    if weekday == 4 and now.hour >= 21:
        return False, None

    current_min = now.hour * 60 + now.minute

    for kz in KILL_ZONES:
        start_min = kz["start"] * 60
        end_min   = kz["end"]   * 60
        if start_min <= current_min < end_min:
            return True, kz["name"]

    return False, None


def is_market_open() -> bool:
    """
    Returns True if the forex market is open.
    Closed: Saturday all day, Sunday before 21:00 UTC,
    Friday after 21:00 UTC.
    """
    now     = datetime.now(timezone.utc)
    weekday = now.weekday()
    if weekday == 5:
        return False
    if weekday == 6 and now.hour < 21:
        return False
    if weekday == 4 and now.hour >= 21:
        return False
    return True


# ============================================================
# Candle fetching
# ============================================================

def _fetch_candles(pair: str, granularity: str, count: int) -> list:
    """
    Fetches candles from OANDA for a given pair and granularity.
    Returns only COMPLETED candles as a list of dicts.
    """
    url    = f"{BASE}/instruments/{pair}/candles"
    params = {
        "count":       count,
        "granularity": granularity,
        "price":       "M",   # mid prices
    }
    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()

    raw = resp.json().get("candles", [])
    candles = []
    for c in raw:
        if not c.get("complete", True):
            continue   # skip forming candle
        candles.append({
            "time":   c["time"],
            "open":   float(c["mid"]["o"]),
            "high":   float(c["mid"]["h"]),
            "low":    float(c["mid"]["l"]),
            "close":  float(c["mid"]["c"]),
            "volume": int(c.get("volume", 0)),
        })
    return candles


def get_all_timeframes(pair: str) -> dict:
    """
    Fetches all timeframes for a pair in one call.
    Returns: {
        "Daily": [...candles],
        "4H":    [...candles],
        "1H":    [...candles],
        "15M":   [...candles],
    }
    Raises on any HTTP error.
    """
    result = {}
    for granularity, cfg in CANDLE_CONFIG.items():
        candles = _fetch_candles(pair, granularity, cfg["count"])
        result[cfg["label"]] = candles

    return result


def format_candles_for_analysis(candles: list) -> str:
    """
    Converts candle list to a clean JSON string for AI/logging.
    Includes only the most recent 30 for readability.
    """
    recent = candles[-30:] if len(candles) > 30 else candles
    return json.dumps(recent, indent=2)


# ============================================================
# Account data
# ============================================================

def get_account_info() -> dict:
    """
    Returns full account info including balance, NAV, unrealized P&L.
    """
    url  = f"{BASE}/accounts/{OANDA_ACCOUNT_ID}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    acc = resp.json()["account"]
    return {
        "balance":      float(acc["balance"]),
        "nav":          float(acc["NAV"]),
        "unrealized_pl":float(acc["unrealizedPL"]),
        "margin_used":  float(acc["marginUsed"]),
        "open_trades":  int(acc["openTradeCount"]),
    }


def get_open_trades() -> list:
    """
    Returns list of all open trades with full details.
    """
    url  = f"{BASE}/accounts/{OANDA_ACCOUNT_ID}/openTrades"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    trades = resp.json().get("trades", [])
    result = []
    for t in trades:
        result.append({
            "trade_id":   t["id"],
            "instrument": t["instrument"],
            "units":      int(t["currentUnits"]),
            "entry":      float(t["price"]),
            "open_time":  t["openTime"],
            "unrealized_pl": float(t.get("unrealizedPL", 0)),
            "sl": float(t["stopLossOrder"]["price"]) if "stopLossOrder" in t else None,
            "tp": float(t["takeProfitOrder"]["price"]) if "takeProfitOrder" in t else None,
        })
    return result


def get_open_pairs() -> set:
    """Returns set of instruments with open trades."""
    trades = get_open_trades()
    return {t["instrument"] for t in trades}


def get_current_price(pair: str) -> float:
    """Returns the current mid price for a pair."""
    url    = f"{BASE}/instruments/{pair}/candles"
    params = {"count": 1, "granularity": "S5", "price": "M"}
    resp   = requests.get(url, headers=HEADERS, params=params, timeout=10)
    resp.raise_for_status()
    candles = resp.json().get("candles", [])
    if candles:
        return float(candles[-1]["mid"]["c"])
    return 0.0


# ============================================================
# Trade modification — SL to breakeven
# ============================================================

def modify_trade_sl(trade_id: str, new_sl: float) -> bool:
    """
    Modifies the stop loss of an existing trade.
    Used to move SL to breakeven after TP1 is hit.
    Returns True on success.
    """
    url  = f"{BASE}/accounts/{OANDA_ACCOUNT_ID}/trades/{trade_id}/orders"
    body = {
        "stopLoss": {
            "price":       f"{new_sl:.5f}",
            "timeInForce": "GTC",
        }
    }
    resp = requests.put(url, headers=HEADERS, json=body, timeout=10)
    if resp.status_code == 200:
        print(f"  [OANDA] SL moved to {new_sl:.5f} for trade {trade_id}")
        return True
    else:
        print(f"  [OANDA] SL modify failed: {resp.text[:100]}")
        return False


# ============================================================
# Partial close — for TP1 (50% of position)
# ============================================================

def partial_close_trade(trade_id: str, units_to_close: int) -> dict | None:
    """
    Partially closes a trade by reducing position size.
    units_to_close should be POSITIVE (function handles direction).
    """
    url  = f"{BASE}/accounts/{OANDA_ACCOUNT_ID}/trades/{trade_id}/close"
    body = {"units": str(abs(units_to_close))}
    resp = requests.put(url, headers=HEADERS, json=body, timeout=10)
    if resp.status_code == 200:
        result = resp.json()
        fill   = result.get("orderFillTransaction", {})
        price  = float(fill.get("price", 0))
        pl     = float(fill.get("pl", 0))
        print(f"  [OANDA] Partial close {units_to_close} units at {price:.5f} | P&L: ${pl:.2f}")
        return {"price": price, "pl": pl}
    else:
        print(f"  [OANDA] Partial close failed: {resp.text[:100]}")
        return None