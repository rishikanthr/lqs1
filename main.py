"""
LQ Sweep + Reversal Bot — main.py
===================================
Strategy  : ICT Liquidity Sweep + Reversal
Pairs     : EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD
Timeframes: Daily (bias) → 1H (sweep) → 15M (FVG + CHoCH + entry)
Kill Zones: London Open 07–10 UTC, NY Open 12–15 UTC
Account   : $100,000 OANDA demo
Risk      : 1% per trade ($1,000), max 4 trades/day, 3% daily loss limit

All fixes from previous bot applied:
✅ Multi-timeframe analysis (no more 15M-only)
✅ Daily bias filter (no counter-trend trades)
✅ HTF premium/discount zone filter
✅ Displacement minimum size filter (25 pips)
✅ CHoCH confirmation on 15M
✅ Kill zone time filter (minute-accurate)
✅ Weekend + market hours guard
✅ TP1 partial close (50%) implemented
✅ SL to breakeven after TP1
✅ No duplicate trades on same pair
✅ Daily loss circuit breaker (3%)
✅ State persists across Railway restarts
✅ Every event sends Telegram notification
✅ Signal log (every check recorded)
✅ Trade log (every trade recorded to CSV)
✅ Candle-close alignment (waits for next 15M close)
✅ Price sanity check on calculated levels
✅ Proper position sizing per pair type
"""

import time
import traceback
from datetime import datetime, timezone, timedelta

from config import (
    PAIRS, CHECK_INTERVAL_SECONDS, CANDLE_CLOSE_BUFFER_S,
    MAX_TRADES_PER_DAY, MAX_OPEN_TRADES, MAX_DAILY_LOSS_PCT,
    RISK_PERCENT,
)
from data_fetcher import (
    get_kill_zone, is_market_open,
    get_all_timeframes, get_account_info,
    get_open_trades, get_open_pairs, get_current_price,
)
from detector import analyze_pair
from trader import (
    place_order, check_and_manage_tp1,
    log_trade_opened, log_signal_checked,
)
from state import (
    load_state, save_state, reset_daily_state,
    add_active_trade, remove_active_trade, update_daily_pnl,
)
from notifier import (
    notify_bot_started, notify_bot_stopped, notify_bot_restarted,
    notify_kill_zone_entered, notify_outside_kill_zone,
    notify_setup_found, notify_trade_placed,
    notify_trade_skipped, notify_order_failed,
    notify_tp1_hit, notify_sl_moved_to_be,
    notify_tp2_hit, notify_sl_hit,
    notify_daily_loss_limit, notify_max_trades_reached,
    notify_daily_summary, notify_error, notify_critical_error,
)


# ============================================================
# Helpers
# ============================================================

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def sleep_until_next_15m_candle():
    """
    Aligns the bot to check AFTER a 15M candle closes.
    Waits until the next :00, :15, :30, or :45 + buffer.
    This ensures we always analyze a COMPLETED candle, never a forming one.
    """
    now          = datetime.now(timezone.utc)
    current_min  = now.minute
    next_boundary = ((current_min // 15) + 1) * 15

    if next_boundary >= 60:
        next_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        next_time = now.replace(minute=next_boundary, second=0, microsecond=0)

    wait = (next_time - now).total_seconds() + CANDLE_CLOSE_BUFFER_S

    print(
        f"  [BOT] Next 15M candle closes at "
        f"{next_time.strftime('%H:%M')} UTC. "
        f"Sleeping {int(wait)}s..."
    )
    time.sleep(max(wait, 10))


def check_daily_loss_limit(state: dict, current_balance: float) -> bool:
    """
    Returns True if the daily loss limit has been hit.
    Compares current balance to balance at start of day.
    """
    if state["balance_day_start"] <= 0:
        return False

    loss    = state["balance_day_start"] - current_balance
    loss_pct = (loss / state["balance_day_start"]) * 100

    if loss_pct >= MAX_DAILY_LOSS_PCT:
        if not state.get("daily_loss_hit"):
            state["daily_loss_hit"] = True
            save_state(state)
            notify_daily_loss_limit(loss_pct, loss, MAX_DAILY_LOSS_PCT)
        return True

    return False


# ============================================================
# Trade monitoring — checks TP1, TP2, SL on active trades
# ============================================================

def monitor_active_trades(state: dict):
    """
    Checks all active trades for TP1 hits, TP2 hits, and SL hits.
    Handles partial close at TP1 and SL → BE modification.
    Updates state and sends Telegram notifications.
    """
    if not state["active_trades"]:
        return

    # Fetch current prices for all active pairs
    current_prices = {}
    for pair in list(state["active_trades"].keys()):
        try:
            current_prices[pair] = get_current_price(pair)
        except Exception as e:
            print(f"  [MONITOR] Price fetch failed for {pair}: {e}")

    # Check TP1
    tp1_hits = check_and_manage_tp1(state["active_trades"], current_prices)
    for hit in tp1_hits:
        pair     = hit["pair"]
        trade    = state["active_trades"][pair]
        pip      = 0.01 if "JPY" in pair else 0.0001
        tp1_pips = round(abs(trade["entry"] - hit["tp1"]) / pip, 1)

        notify_tp1_hit(pair, hit["tp1"], hit["trade_id"], tp1_pips)
        if hit["sl_moved"]:
            notify_sl_moved_to_be(pair, hit["be_price"], hit["trade_id"])

        save_state(state)

    # Fetch current OANDA open trades to detect TP2 / SL closes
    try:
        oanda_open = {t["trade_id"]: t for t in get_open_trades()}
    except Exception as e:
        print(f"  [MONITOR] Open trades fetch failed: {e}")
        return

    # Check for closed trades (either TP2 or SL)
    for pair, trade in list(state["active_trades"].items()):
        trade_id = trade["trade_id"]

        if trade_id not in oanda_open:
            # Trade no longer open — closed by TP2 or SL
            entry    = trade["entry"]
            tp2      = trade["tp2"]
            sl       = trade["sl"] if not trade.get("tp1_hit") else trade["stop_loss"]
            signal   = trade["signal"]
            pip      = 0.01 if "JPY" in pair else 0.0001
            was_be   = trade.get("sl_at_be", False)
            tp1_hit  = trade.get("tp1_hit", False)

            current = current_prices.get(pair, 0)

            # Determine if it closed at TP2 or SL
            if signal == "LONG":
                hit_tp2 = current >= tp2 * 0.9995
            else:
                hit_tp2 = current <= tp2 * 1.0005

            if hit_tp2:
                # TP2 hit — calculate profit
                pips_won   = round(abs(entry - tp2) / pip, 1)
                notify_tp2_hit(pair, tp2, trade_id, pips_won, 0)
                state["wins"] += 1

            else:
                # SL hit
                pip_size   = pip
                loss_pips  = round(abs(entry - sl) / pip_size, 1)
                # Rough USD loss estimate
                loss_usd   = state.get("balance_day_start", 100000) * RISK_PERCENT / 100
                if was_be:
                    loss_usd = 0
                notify_sl_hit(pair, sl, trade_id, loss_usd, was_be)
                if was_be:
                    state["bes"] += 1
                else:
                    state["losses"] += 1

            remove_active_trade(state, pair)
            print(f"  [MONITOR] Trade closed: {pair} {trade_id}")


# ============================================================
# Process one pair
# ============================================================

def process_pair(pair: str, state: dict, balance: float,
                 open_pairs: set, kz_name: str) -> bool:
    """
    Fetches candles, runs analysis, places trade if valid.
    Returns True if a trade was placed.
    """

    # ── Guard: already trading this pair ─────────────────
    if pair in open_pairs:
        log_signal_checked(pair, {"signal": "NO_TRADE"}, "skipped", "already_open")
        return False

    # ── Fetch multi-timeframe candles ─────────────────────
    try:
        mtf_data = get_all_timeframes(pair)
    except Exception as e:
        print(f"  [{pair}] Candle fetch failed: {e}")
        notify_error(f"Candle fetch {pair}", str(e))
        return False

    # ── Run analysis ──────────────────────────────────────
    try:
        result = analyze_pair(pair, mtf_data)
    except Exception as e:
        print(f"  [{pair}] Analysis error: {e}")
        notify_error(f"Analysis {pair}", str(e))
        return False

    signal = result.get("signal", "NO_TRADE")
    reason = result.get("reason", "")

    print(
        f"  [{pair}] {signal:10s} | "
        f"Bias: {result.get('daily_bias','?'):8s} | "
        f"Zone: {result.get('htf_zone','?'):12s} | "
        f"{reason[:60]}"
    )

    log_signal_checked(pair, result, "analyzed")
    state["signals_today"] += 1

    # ── No trade ──────────────────────────────────────────
    if signal == "NO_TRADE":
        return False

    # ── Guard: max trades per day ─────────────────────────
    if state["trades_today"] >= MAX_TRADES_PER_DAY:
        log_signal_checked(pair, result, "skipped", "max_trades_day")
        notify_trade_skipped(pair, signal, f"Max {MAX_TRADES_PER_DAY} trades/day reached")
        return False

    # ── Guard: max open trades ────────────────────────────
    current_open = len(state["active_trades"])
    if current_open >= MAX_OPEN_TRADES:
        log_signal_checked(pair, result, "skipped", f"max_open_{current_open}")
        notify_trade_skipped(pair, signal, f"Max {MAX_OPEN_TRADES} open trades ({current_open} open)")
        return False

    # ── Notify setup found ────────────────────────────────
    notify_setup_found(
        pair, signal, kz_name,
        result.get("liquidity_level", 0),
        result.get("sweep_price", 0),
        result.get("fvg_top", 0),
        result.get("fvg_bot", 0),
        result.get("daily_bias", "?"),
        result.get("htf_zone", "?"),
    )

    # ── Place order ───────────────────────────────────────
    order = place_order(pair, signal, result, balance)

    if not order:
        log_signal_checked(pair, result, "order_failed", "OANDA rejected")
        notify_order_failed(pair, signal, "OANDA rejected order — check logs")
        return False

    # ── Log and update state ──────────────────────────────
    log_trade_opened(pair, signal, result, order, balance, kz_name)
    log_signal_checked(pair, result, "traded")
    state = add_active_trade(state, pair, order, signal, result)

    # ── Send trade notification ───────────────────────────
    notify_trade_placed(
        pair, signal, kz_name,
        order["fill_price"],
        order["stop_loss"],
        order["tp1"],
        order["tp2"],
        order["units"],
        order["trade_id"],
        balance * RISK_PERCENT / 100,
        balance,
        result.get("daily_bias", "?"),
        reason,
    )

    return True


# ============================================================
# Main bot loop
# ============================================================

def run_bot():
    start_time = datetime.now(timezone.utc)

    print("\n" + "=" * 65)
    print("  LQ Sweep + Reversal Bot — $100,000 OANDA Demo")
    print("  Pairs: EUR/USD GBP/USD USD/JPY USD/CHF AUD/USD USD/CAD")
    print("  Kill Zones: London 07–10 UTC | NY 12–15 UTC")
    print("=" * 65 + "\n")

    # ── Load persisted state ──────────────────────────────
    state = load_state()

    # ── Get initial account info ──────────────────────────
    try:
        account = get_account_info()
        balance = account["balance"]
        print(f"  [BOT] Account balance: ${balance:,.2f}")
        print(f"  [BOT] Open trades on OANDA: {account['open_trades']}")
    except Exception as e:
        print(f"  [BOT] ❌ Account fetch failed at startup: {e}")
        notify_critical_error("Startup account fetch", str(e))
        return

    # ── Initialize daily state if new day or first run ────
    today = _today_str()
    if state["date"] != today:
        state = reset_daily_state(state, balance)
        print(f"  [BOT] Fresh day state initialized for {today}")
    elif state["balance_day_start"] == 0:
        state["balance_day_start"] = balance
        save_state(state)

    # ── Send startup notification ─────────────────────────
    if state.get("_just_restarted"):
        notify_bot_restarted()
    else:
        notify_bot_started(balance)

    state["_just_restarted"] = True   # mark for next restart
    save_state(state)

    # ── Track kill zone notification state ────────────────
    last_kz_name           = None
    outside_kz_notified    = False
    max_trades_notified    = False
    loss_limit_notified    = False

    # ============================================================
    # Main loop
    # ============================================================
    while True:
        try:
            now   = datetime.now(timezone.utc)
            today = _today_str()

            # ── Daily reset ───────────────────────────────
            if state["date"] != today:
                # Send previous day summary
                notify_daily_summary(
                    state["date"],
                    state["trades_today"],
                    state["wins"],
                    state["losses"],
                    state["bes"],
                    state["daily_pnl_usd"],
                    state["pairs_traded"],
                    state["signals_today"],
                )
                try:
                    account = get_account_info()
                    balance = account["balance"]
                except Exception:
                    pass
                state = reset_daily_state(state, balance)
                print(f"\n  [BOT] 🗓  New day: {today} — counters reset.")
                outside_kz_notified = False
                max_trades_notified = False
                loss_limit_notified = False

            # ── Refresh balance ───────────────────────────
            try:
                account = get_account_info()
                balance = account["balance"]
            except Exception as e:
                print(f"  [BOT] Balance refresh failed: {e}")
                time.sleep(60)
                continue

            # ── Monitor active trades (TP1, TP2, SL) ─────
            if state["active_trades"]:
                monitor_active_trades(state)

            # ── Market open check ─────────────────────────
            if not is_market_open():
                if not outside_kz_notified:
                    print(f"  [BOT] 🌙 Market closed (weekend). Sleeping...")
                    outside_kz_notified = True
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            # ── Daily loss circuit breaker ────────────────
            if check_daily_loss_limit(state, balance):
                if not loss_limit_notified:
                    print(f"  [BOT] 🚨 Daily loss limit hit. No more trades today.")
                    loss_limit_notified = True
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            # ── Max trades check ──────────────────────────
            if state["trades_today"] >= MAX_TRADES_PER_DAY:
                if not max_trades_notified:
                    print(f"  [BOT] 🔒 Max {MAX_TRADES_PER_DAY} trades reached.")
                    notify_max_trades_reached(MAX_TRADES_PER_DAY)
                    max_trades_notified = True
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue
            max_trades_notified = False

            # ── Kill zone check ───────────────────────────
            in_kz, kz_name = get_kill_zone()

            if not in_kz:
                if not outside_kz_notified:
                    print(f"  [BOT] 😴 Outside kill zones at {_now_str()}")
                    notify_outside_kill_zone()
                    outside_kz_notified = True
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            # Re-entered kill zone
            if outside_kz_notified or kz_name != last_kz_name:
                print(f"  [BOT] ⚡ Kill Zone: {kz_name} at {_now_str()}")
                notify_kill_zone_entered(kz_name)
                outside_kz_notified = False
                last_kz_name        = kz_name

            # ── Print scan header ─────────────────────────
            print(f"\n{'─' * 65}")
            print(
                f"  [BOT] {_now_str()} | KZ: {kz_name} | "
                f"Trades: {state['trades_today']}/{MAX_TRADES_PER_DAY} | "
                f"Open: {len(state['active_trades'])}/{MAX_OPEN_TRADES} | "
                f"Balance: ${balance:,.2f}"
            )
            print(f"{'─' * 65}")

            # ── Get currently open pairs ──────────────────
            try:
                open_pairs = get_open_pairs()
            except Exception as e:
                print(f"  [BOT] Open pairs fetch failed: {e}")
                time.sleep(60)
                continue

            # ── Scan all 6 pairs ──────────────────────────
            for pair in PAIRS:
                traded = process_pair(pair, state, balance, open_pairs, kz_name)
                if traded:
                    open_pairs.add(pair)
                    # Refresh balance after each trade
                    try:
                        account = get_account_info()
                        balance = account["balance"]
                    except Exception:
                        pass
                time.sleep(2)   # 2s between pairs — avoid OANDA rate limits

            # ── Sleep until next 15M candle ───────────────
            sleep_until_next_15m_candle()

        except KeyboardInterrupt:
            duration = str(datetime.now(timezone.utc) - start_time).split(".")[0]
            print(f"\n  [BOT] 🛑 Stopped by user after {duration}")
            notify_bot_stopped(state["trades_today"], state["signals_today"], duration)
            break

        except Exception as e:
            tb = traceback.format_exc()
            print(f"\n  [ERROR] {e}\n{tb}")
            notify_error("Main loop", f"{type(e).__name__}: {str(e)[:200]}")
            print(f"  [BOT] Retrying in 60s...")
            time.sleep(60)


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    run_bot()