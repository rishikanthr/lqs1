"""
state.py — Persistent bot state stored to disk

Survives Railway restarts when using a persistent volume at /data.
Tracks: trades today, daily P&L, active trades, daily loss breaker.
"""

import json
import os
from datetime import datetime, timezone
from config import STATE_FILE, LOG_DIR


def _ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def load_state() -> dict:
    """
    Loads persisted state from disk.
    Returns default state if file doesn't exist or is corrupted.
    """
    _ensure_dir()
    default = {
        "date":              "",
        "trades_today":      0,
        "signals_today":     0,
        "daily_pnl_usd":     0.0,
        "balance_day_start": 0.0,
        "pairs_traded":      [],
        "active_trades":     {},   # pair → trade info dict
        "tp1_notified":      [],   # trade_ids already notified for TP1
        "daily_loss_hit":    False,
        "wins":              0,
        "losses":            0,
        "bes":               0,
    }

    if not os.path.isfile(STATE_FILE):
        return default

    try:
        with open(STATE_FILE, "r") as f:
            saved = json.load(f)
        # Merge with defaults to handle new fields
        for k, v in default.items():
            if k not in saved:
                saved[k] = v
        return saved
    except Exception as e:
        print(f"  [STATE] Load error: {e} — using defaults.")
        return default


def save_state(state: dict):
    """Saves state to disk."""
    _ensure_dir()
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"  [STATE] Save error: {e}")


def reset_daily_state(state: dict, balance: float) -> dict:
    """
    Resets daily counters while preserving active trades.
    Called at midnight UTC.
    """
    state["date"]              = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state["trades_today"]      = 0
    state["signals_today"]     = 0
    state["daily_pnl_usd"]     = 0.0
    state["balance_day_start"] = balance
    state["pairs_traded"]      = []
    state["daily_loss_hit"]    = False
    state["wins"]              = 0
    state["losses"]            = 0
    state["bes"]               = 0
    # DO NOT reset active_trades — preserve open positions
    save_state(state)
    return state


def add_active_trade(state: dict, pair: str, trade_info: dict,
                     signal: str, analysis: dict) -> dict:
    """Adds a new trade to active tracking."""
    state["active_trades"][pair] = {
        **trade_info,
        "signal":     signal,
        "tp1_hit":    False,
        "sl_at_be":   False,
        "daily_bias": analysis.get("daily_bias"),
        "reason":     analysis.get("reason"),
    }
    if pair not in state["pairs_traded"]:
        state["pairs_traded"].append(pair)
    state["trades_today"] += 1
    save_state(state)
    return state


def remove_active_trade(state: dict, pair: str) -> dict:
    """Removes a trade from active tracking (after close)."""
    state["active_trades"].pop(pair, None)
    save_state(state)
    return state


def update_daily_pnl(state: dict, pnl_usd: float) -> dict:
    state["daily_pnl_usd"] = round(state["daily_pnl_usd"] + pnl_usd, 2)
    save_state(state)
    return state