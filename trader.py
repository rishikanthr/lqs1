import requests
import csv
import os
from datetime import datetime, timezone
from config import (
    OANDA_API_KEY, OANDA_BASE_URL, OANDA_ACCOUNT_ID,
    INSTRUMENT, RISK_PERCENT, TRADE_LOG_FILE
)


def calculate_units(balance, entry, stop_loss, signal):
    risk_amount = balance * (RISK_PERCENT / 100)
    pip_risk    = abs(entry - stop_loss)
    if pip_risk == 0:
        return 0
    units = int(risk_amount / pip_risk)
    if signal == "SHORT":
        units = -units
    return units


def place_order(signal_data, balance):
    signal    = signal_data["signal"]
    entry     = signal_data["entry_price"]
    stop_loss = signal_data["stop_loss"]
    tp1       = signal_data["take_profit_1"]
    tp2       = signal_data["take_profit_2"]

    if not entry or not stop_loss:
        print("  [TRADER] Missing price levels — skipping.")
        return None

    units = calculate_units(balance, entry, stop_loss, signal)
    if abs(units) < 1:
        print("  [TRADER] Position size too small — skipping.")
        return None

    url     = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
    headers = {
        "Authorization": f"Bearer {OANDA_API_KEY}",
        "Content-Type":  "application/json"
    }
    order = {
        "order": {
            "type":        "MARKET",
            "instrument":  INSTRUMENT,
            "units":       str(units),
            "timeInForce": "FOK",
            "stopLossOnFill":   {"price": f"{stop_loss:.5f}"},
            "takeProfitOnFill": {"price": f"{tp2:.5f}"}
        }
    }

    response = requests.post(url, headers=headers, json=order)
    result   = response.json()

    if response.status_code in (200, 201):
        fill      = result.get("orderFillTransaction", {})
        trade_id  = fill.get("tradeOpened", {}).get("tradeID", "unknown")
        fill_price = float(fill.get("price", entry))
        print(f"  [TRADER] Filled! ID: {trade_id} | Price: {fill_price:.5f} | Units: {units}")
        return {"trade_id": trade_id, "fill_price": fill_price, "units": units,
                "stop_loss": stop_loss, "tp1": tp1, "tp2": tp2}
    else:
        print(f"  [TRADER] Order failed: {result.get('errorMessage', 'Unknown error')}")
        return None


def log_trade(signal_data, order_result, cost, kz_name):
    file_exists = os.path.isfile(TRADE_LOG_FILE)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    with open(TRADE_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "datetime", "signal", "confidence", "kill_zone",
                "liquidity_level", "fvg_top", "fvg_bot",
                "entry", "stop_loss", "tp1", "tp2",
                "units", "trade_id", "reason", "api_cost",
                "outcome", "pips_result"
            ])
        writer.writerow([
            now,
            signal_data.get("signal"),
            signal_data.get("confidence"),
            kz_name,
            signal_data.get("liquidity_level"),
            signal_data.get("fvg_top"),
            signal_data.get("fvg_bot"),
            order_result["fill_price"] if order_result else signal_data.get("entry_price"),
            signal_data.get("stop_loss"),
            signal_data.get("take_profit_1"),
            signal_data.get("take_profit_2"),
            order_result["units"] if order_result else 0,
            order_result["trade_id"] if order_result else "no_fill",
            signal_data.get("reason"),
            cost,
            "open",
            ""
        ])
    print(f"  [LOG] Logged to {TRADE_LOG_FILE}")


def get_open_trades():
    url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/openTrades"
    headers = {"Authorization": f"Bearer {OANDA_API_KEY}"}
    response = requests.get(url, headers=headers)
    return len(response.json().get("trades", []))