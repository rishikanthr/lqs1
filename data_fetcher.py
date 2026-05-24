import requests
from datetime import datetime, timezone
from config import OANDA_API_KEY, OANDA_BASE_URL, INSTRUMENT, GRANULARITY, CANDLE_COUNT, KILL_ZONES


def get_candles():
    url = f"{OANDA_BASE_URL}/v3/instruments/{INSTRUMENT}/candles"
    headers = {
        "Authorization": f"Bearer {OANDA_API_KEY}",
        "Content-Type": "application/json"
    }
    params = {
        "count": CANDLE_COUNT,
        "granularity": GRANULARITY,
        "price": "M"
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    raw = response.json()["candles"]

    candles = []
    for c in raw:
        if not c["complete"]:
            continue
        candles.append({
            "time":   c["time"],
            "open":   float(c["mid"]["o"]),
            "high":   float(c["mid"]["h"]),
            "low":    float(c["mid"]["l"]),
            "close":  float(c["mid"]["c"]),
            "volume": int(c["volume"])
        })
    return candles


def in_kill_zone():
    now_hour = datetime.now(timezone.utc).hour
    for kz in KILL_ZONES:
        if kz["start_hour"] <= now_hour < kz["end_hour"]:
            return True, kz["name"]
    return False, None


def get_account_balance():
    from config import OANDA_ACCOUNT_ID
    url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}"
    headers = {"Authorization": f"Bearer {OANDA_API_KEY}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return float(response.json()["account"]["balance"])


def format_candles_for_claude(candles):
    lines = ["idx | time            | open    | high    | low     | close   | volume"]
    lines.append("-" * 75)
    for i, c in enumerate(candles[-20:]):
        t = c["time"][:16].replace("T", " ")
        lines.append(
            f"{i:3d} | {t} | {c['open']:.5f} | {c['high']:.5f} | "
            f"{c['low']:.5f} | {c['close']:.5f} | {c['volume']}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    candles = get_candles()
    print(f"Fetched {len(candles)} candles for {INSTRUMENT}")
    print(format_candles_for_claude(candles))
    in_kz, kz_name = in_kill_zone()
    print(f"\nIn Kill Zone: {in_kz} ({kz_name})")