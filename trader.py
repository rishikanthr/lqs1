"""
trader.py — Order placement + position sizing + trade management

$100,000 demo account
1% risk = $1,000 per trade
Position size calculated from actual SL distance in pips
TP1 partial close (50%) + SL to breakeven implemented correctly
"""

import csv
import json
import os
import requests
from datetime import datetime, timezone

from config import (
    OANDA_API_KEY, OANDA_BASE_URL, OANDA_ACCOUNT_ID,
    RISK_PERCENT, PIP_SIZE,
    TRADE_LOG_FILE, SIGNAL_LOG_FILE,
)
from data_fetcher import modify_trade_sl, partial_close_trade, get_open_trades

BASE    = f"{OANDA_BASE_URL}/v3"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json",
}


# ============================================================
# Position sizing
# ============================================================

def calculate_units(pair: str, balance: float,
                    entry: float, stop_loss: float, signal: str) -> int:
    """
    Calculates units based on:
    - 1% account risk
    - Actual SL distance in pips
    - Pip value in USD (varies by pair)

    For a $100,000 account:
    risk_amount = $1,000
    units = risk_amount / (sl_pips × pip_value_per_unit)

    Pip value per unit:
    EUR_USD: $0.0001 per unit (1 pip = 0.0001, 1 unit = 1 currency)
    USD_JPY: pip = 0.01, value = 0.01 / current_rate per unit
    etc.

    For simplicity and correctness with OANDA's unit system:
    units = risk_amount / (price_risk_per_unit)
    where price_risk_per_unit = |entry - sl| in the quote currency

    For USD-quoted pairs (EUR/USD, GBP/USD, AUD/USD):
    pip_value_usd = pip_size (since quote is USD)

    For JPY pairs (USD/JPY): convert pip value to USD
    For USD/CHF: pip value in CHF, convert to USD using rate
    For USD/CAD: pip value in CAD, convert to USD using rate

    Conservative approach: use fixed pip value approximations
    that slightly undersize (safer than oversizing).
    """

    risk_amount    = balance * (RISK_PERCENT / 100)   # $1,000
    price_per_pip  = PIP_SIZE.get(pair, 0.0001)
    sl_price_dist  = abs(entry - stop_loss)
    sl_pips        = sl_price_dist / price_per_pip

    if sl_pips == 0:
        return 0

    # Pip value in USD per unit:
    # EUR_USD, GBP_USD, AUD_USD: quote = USD → pip_value = pip_size
    # USD_JPY: base = USD, quote = JPY
    #   1 pip = 0.01 yen per unit
    #   pip value in USD = 0.01 / current_price
    # USD_CHF: base = USD, quote = CHF
    #   pip value in USD ≈ pip_size / current_price
    # USD_CAD: base = USD, quote = CAD
    #   pip value in USD ≈ pip_size / current_price

    if pair in ("EUR_USD", "GBP_USD", "AUD_USD"):
        pip_value_per_unit = price_per_pip   # direct USD quote

    elif pair == "USD_JPY":
        # pip = 0.01 yen; value in USD = 0.01 / rate
        pip_value_per_unit = price_per_pip / entry

    elif pair == "USD_CHF":
        # pip = 0.0001 CHF; value in USD = 0.0001 / rate
        pip_value_per_unit = price_per_pip / entry

    elif pair == "USD_CAD":
        # pip = 0.0001 CAD; value in USD = 0.0001 / rate
        pip_value_per_unit = price_per_pip / entry

    else:
        pip_value_per_unit = price_per_pip

    units = int(risk_amount / (sl_pips * pip_value_per_unit))

    # Apply OANDA minimums and maximums
    units = max(units, 1)
    units = min(units, 10_000_000)   # hard cap

    if signal == "SHORT":
        units = -units

    return units


# ============================================================
# Place initial market order
# ============================================================

def place_order(pair: str, signal: str, analysis: dict, balance: float) -> dict | None:
    """
    Places a market order with SL and TP2 attached.
    TP1 is NOT attached to OANDA — it is monitored by the bot
    and handled via partial close + SL modification.

    Returns order result dict or None on failure.
    """
    entry = analysis["entry"]
    sl    = analysis["stop_loss"]
    tp2   = analysis["tp2"]

    units = calculate_units(pair, balance, entry, sl, signal)

    if abs(units) < 1:
        print(f"  [TRADER] {pair}: Position size = 0 — skipping.")
        return None

    print(
        f"  [TRADER] Placing {signal} {pair} | "
        f"Entry: {entry:.5f} | SL: {sl:.5f} | TP2: {tp2:.5f} | "
        f"Units: {units:,} | Risk: ${balance * RISK_PERCENT / 100:,.0f}"
    )

    order_body = {
        "order": {
            "type":        "MARKET",
            "instrument":  pair,
            "units":       str(units),
            "timeInForce": "FOK",
            "stopLossOnFill": {
                "price":       f"{sl:.5f}",
                "timeInForce": "GTC",
            },
            "takeProfitOnFill": {
                "price":       f"{tp2:.5f}",
                "timeInForce": "GTC",
            },
        }
    }

    url  = f"{BASE}/accounts/{OANDA_ACCOUNT_ID}/orders"
    resp = requests.post(url, headers=HEADERS, json=order_body, timeout=15)

    if resp.status_code in (200, 201):
        result     = resp.json()
        fill       = result.get("orderFillTransaction", {})
        trade_id   = fill.get("tradeOpened", {}).get("tradeID", "UNKNOWN")
        fill_price = float(fill.get("price", entry))
        print(f"  [TRADER] ✅ Filled | ID: {trade_id} | Price: {fill_price:.5f} | Units: {units:,}")
        return {
            "trade_id":   trade_id,
            "fill_price": fill_price,
            "units":      units,
            "stop_loss":  sl,
            "tp1":        analysis["tp1"],
            "tp2":        tp2,
            "entry":      fill_price,   # use actual fill price
        }

    else:
        error = resp.json().get("errorMessage", resp.json().get("message", resp.text[:100]))
        print(f"  [TRADER] ❌ Order failed: {error}")
        return None


# ============================================================
# TP1 monitoring and partial close
# ============================================================

def check_and_manage_tp1(active_trades: dict, current_prices: dict) -> list:
    """
    Monitors open trades for TP1 hits.
    When TP1 is hit:
    1. Partially closes 50% of the position
    2. Moves SL to breakeven (entry price)
    3. Sends notification (handled by caller)

    active_trades: dict of {pair: trade_info}
    current_prices: dict of {pair: current_price}

    Returns list of pairs where TP1 was hit this cycle.
    """
    tp1_hits = []

    for pair, trade in list(active_trades.items()):
        if trade.get("tp1_hit"):
            continue   # already processed

        current  = current_prices.get(pair, 0)
        tp1      = trade["tp1"]
        signal   = trade["signal"]
        trade_id = trade["trade_id"]

        tp1_hit = (
            (signal == "LONG"  and current >= tp1) or
            (signal == "SHORT" and current <= tp1)
        )

        if tp1_hit:
            # Close 50% of units
            units_to_close = abs(trade["units"]) // 2
            close_result   = partial_close_trade(trade_id, units_to_close)

            if close_result:
                # Move SL to breakeven
                be_price  = trade["entry"]
                sl_moved  = modify_trade_sl(trade_id, be_price)
                trade["tp1_hit"]  = True
                trade["sl_at_be"] = sl_moved
                trade["sl"]       = be_price   # update local record

                tp1_hits.append({
                    "pair":      pair,
                    "trade_id":  trade_id,
                    "tp1":       tp1,
                    "close_pl":  close_result.get("pl", 0),
                    "be_price":  be_price,
                    "sl_moved":  sl_moved,
                })

                print(
                    f"  [MANAGE] ✅ TP1 hit {pair} | "
                    f"Closed {units_to_close} units | "
                    f"SL → BE {be_price:.5f}"
                )

    return tp1_hits


# ============================================================
# CSV Logging
# ============================================================

def _ensure_dir(filepath: str):
    """Creates the directory for a file if it doesn't exist."""
    d = os.path.dirname(filepath)
    if d:
        os.makedirs(d, exist_ok=True)


def log_trade_opened(pair: str, signal: str, analysis: dict,
                     order: dict, balance: float, kz_name: str):
    _ensure_dir(TRADE_LOG_FILE)
    new_file = not os.path.isfile(TRADE_LOG_FILE)
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    with open(TRADE_LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow([
                "opened_utc", "pair", "signal", "kill_zone",
                "daily_bias", "htf_zone",
                "liquidity_level", "sweep_price",
                "fvg_top", "fvg_bot",
                "entry", "stop_loss", "tp1", "tp2",
                "risk_pips", "tp1_pips", "tp2_pips",
                "units", "risk_usd", "balance_at_entry",
                "trade_id", "reason",
                "status", "closed_utc", "exit_price", "pnl_usd",
            ])
        w.writerow([
            now, pair, signal, kz_name,
            analysis.get("daily_bias"), analysis.get("htf_zone"),
            analysis.get("liquidity_level"), analysis.get("sweep_price"),
            analysis.get("fvg_top"), analysis.get("fvg_bot"),
            order["fill_price"], order["stop_loss"], order["tp1"], order["tp2"],
            analysis.get("risk_pips"), analysis.get("tp1_pips"), analysis.get("tp2_pips"),
            order["units"], round(balance * RISK_PERCENT / 100, 2), round(balance, 2),
            order["trade_id"], analysis.get("reason"),
            "open", "", "", "",   # status, closed_utc, exit_price, pnl
        ])
    print(f"  [LOG] Trade logged → {TRADE_LOG_FILE}")


def log_signal_checked(pair: str, result: dict, action: str, skip_reason: str = ""):
    _ensure_dir(SIGNAL_LOG_FILE)
    new_file = not os.path.isfile(SIGNAL_LOG_FILE)
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    with open(SIGNAL_LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow([
                "checked_utc", "pair", "signal",
                "daily_bias", "htf_zone",
                "reason", "action", "skip_reason",
            ])
        w.writerow([
            now, pair,
            result.get("signal", "NO_TRADE"),
            result.get("daily_bias", ""),
            result.get("htf_zone", ""),
            result.get("reason", ""),
            action, skip_reason,
        ])