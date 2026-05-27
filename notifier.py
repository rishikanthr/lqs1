"""
notifier.py — All Telegram notifications for the LQ Sweep Bot
Every event has its own function. Nothing is silent.
"""

import requests
from datetime import datetime, timezone
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID


# ============================================================
# Core sender — never raises, always logs failures
# ============================================================

def _send(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"  [NOTIFY] Telegram not configured. Message: {message[:80]}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"  [NOTIFY] Telegram error {resp.status_code}: {resp.text[:100]}")
            return False
        return True
    except Exception as e:
        print(f"  [NOTIFY] Telegram request failed: {e}")
        return False


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _pair(p: str) -> str:
    return p.replace("_", "/")


# ============================================================
# Bot lifecycle
# ============================================================

def notify_bot_started(balance: float):
    _send(
        f"🚀 <b>LQ Sweep + Reversal Bot Started</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ Time       : {_now()}\n"
        f"💰 Balance    : ${balance:,.2f}\n"
        f"📊 Strategy   : ICT Liquidity Sweep + Reversal\n"
        f"⏱ Timeframe  : MTF (Daily → 4H → 1H → 15M)\n"
        f"💱 Pairs      : EUR/USD GBP/USD USD/JPY\n"
        f"               USD/CHF AUD/USD USD/CAD\n"
        f"🎯 Risk/trade : 1% (${balance * 0.01:,.0f})\n"
        f"🔒 Max trades : 4/day | 2 open max\n"
        f"🛡 DD limit   : 3% (${balance * 0.03:,.0f})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Monitoring London + NY Kill Zones."
    )


def notify_bot_stopped(trades: int, signals: int, duration: str):
    _send(
        f"🛑 <b>Bot Stopped</b>\n"
        f"⏰ {_now()}\n"
        f"📊 Trades placed : {trades}\n"
        f"🔍 Signals scanned: {signals}\n"
        f"⏱ Duration       : {duration}"
    )


def notify_bot_restarted():
    _send(
        f"🔄 <b>Bot Restarted</b>\n"
        f"⏰ {_now()}\n"
        f"Railway container restarted — resuming monitoring."
    )


# ============================================================
# Kill zone status
# ============================================================

def notify_kill_zone_entered(kz_name: str):
    _send(
        f"⚡ <b>Kill Zone Active — {kz_name}</b>\n"
        f"⏰ {_now()}\n"
        f"🔍 Scanning all 6 pairs for setups..."
    )


def notify_outside_kill_zone():
    _send(
        f"😴 <b>Outside Kill Zones</b>\n"
        f"⏰ {_now()}\n"
        f"💤 Bot idle until next Kill Zone.\n"
        f"Next: London Open 07:00 UTC | NY Open 12:00 UTC"
    )


# ============================================================
# Setup detection
# ============================================================

def notify_setup_found(pair: str, signal: str, kz_name: str,
                       liquidity_level: float, sweep_level: float,
                       fvg_top: float, fvg_bot: float,
                       daily_bias: str, htf_zone: str):
    emoji = "🟢" if signal == "LONG" else "🔴"
    _send(
        f"{emoji} <b>Setup Detected — {_pair(pair)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ Time          : {_now()}\n"
        f"📍 Kill Zone     : {kz_name}\n"
        f"📊 Signal        : {signal}\n"
        f"📈 Daily Bias    : {daily_bias}\n"
        f"📍 HTF Zone      : {htf_zone}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💧 Liquidity Pool: {liquidity_level:.5f}\n"
        f"🌊 Sweep Level   : {sweep_level:.5f}\n"
        f"📦 FVG Zone      : {fvg_bot:.5f} — {fvg_top:.5f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ Waiting for price to retrace to FVG midpoint..."
    )


def notify_no_setup(pair: str, reason: str):
    """Silent in normal operation — only called if you want verbose mode."""
    # Comment this out to reduce noise — only uncomment for debugging
    # _send(f"⏸ {_pair(pair)}: No setup — {reason}")
    pass


# ============================================================
# Trade placed
# ============================================================

def notify_trade_placed(pair: str, signal: str, kz_name: str,
                        entry: float, sl: float,
                        tp1: float, tp2: float,
                        units: int, trade_id: str,
                        risk_amount: float, balance: float,
                        daily_bias: str, reason: str):
    emoji    = "🟢" if signal == "LONG" else "🔴"
    sl_pips  = round(abs(entry - sl) / (0.0001 if "JPY" not in pair else 0.01), 1)
    tp1_pips = round(abs(entry - tp1) / (0.0001 if "JPY" not in pair else 0.01), 1)
    tp2_pips = round(abs(entry - tp2) / (0.0001 if "JPY" not in pair else 0.01), 1)

    _send(
        f"{emoji} <b>TRADE PLACED — {_pair(pair)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ Time       : {_now()}\n"
        f"📍 Session    : {kz_name}\n"
        f"📊 Direction  : {signal}\n"
        f"📈 Daily Bias : {daily_bias}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Entry      : {entry:.5f}\n"
        f"🛑 Stop Loss  : {sl:.5f}  ({sl_pips} pips)\n"
        f"🎯 TP1 (50%)  : {tp1:.5f}  (+{tp1_pips} pips)\n"
        f"🏆 TP2 (50%)  : {tp2:.5f}  (+{tp2_pips} pips)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Units      : {units:,}\n"
        f"💸 Risk       : ${risk_amount:,.2f}\n"
        f"💼 Balance    : ${balance:,.2f}\n"
        f"🆔 Trade ID   : {trade_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {reason}"
    )


# ============================================================
# Trade management updates
# ============================================================

def notify_tp1_hit(pair: str, tp1: float, trade_id: str, pips: float):
    _send(
        f"✅ <b>TP1 Hit — {_pair(pair)}</b>\n"
        f"⏰ {_now()}\n"
        f"🎯 TP1 Price : {tp1:.5f}\n"
        f"📊 Pips won  : +{pips:.1f}\n"
        f"🆔 Trade ID  : {trade_id}\n"
        f"🔄 SL moved to BREAKEVEN\n"
        f"⏳ Waiting for TP2..."
    )


def notify_sl_moved_to_be(pair: str, be_price: float, trade_id: str):
    _send(
        f"🛡 <b>SL Moved to Breakeven — {_pair(pair)}</b>\n"
        f"⏰ {_now()}\n"
        f"📍 New SL    : {be_price:.5f} (entry price)\n"
        f"🆔 Trade ID  : {trade_id}\n"
        f"✅ Trade now risk-free."
    )


def notify_tp2_hit(pair: str, tp2: float, trade_id: str, total_pips: float,
                   profit_usd: float):
    _send(
        f"🏆 <b>TP2 Hit — TRADE COMPLETE — {_pair(pair)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {_now()}\n"
        f"🏆 TP2 Price   : {tp2:.5f}\n"
        f"📊 Total pips  : +{total_pips:.1f}\n"
        f"💰 Profit      : +${profit_usd:,.2f}\n"
        f"🆔 Trade ID    : {trade_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎉 Full target achieved!"
    )


def notify_sl_hit(pair: str, sl: float, trade_id: str, loss_usd: float,
                  was_breakeven: bool):
    if was_breakeven:
        _send(
            f"🔵 <b>BE Stop — {_pair(pair)}</b>\n"
            f"⏰ {_now()}\n"
            f"📍 Closed at breakeven: {sl:.5f}\n"
            f"🆔 Trade ID: {trade_id}\n"
            f"✅ No loss — TP1 was already taken."
        )
    else:
        _send(
            f"❌ <b>Stop Loss Hit — {_pair(pair)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {_now()}\n"
            f"🛑 SL Price  : {sl:.5f}\n"
            f"💸 Loss      : -${loss_usd:,.2f}\n"
            f"🆔 Trade ID  : {trade_id}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 -1R. Moving to next setup."
        )


# ============================================================
# Skips and guards
# ============================================================

def notify_trade_skipped(pair: str, signal: str, reason: str):
    _send(
        f"⏭ <b>Signal Skipped — {_pair(pair)}</b>\n"
        f"⏰ {_now()}\n"
        f"📊 Signal : {signal}\n"
        f"❓ Reason : {reason}"
    )


def notify_order_failed(pair: str, signal: str, error: str):
    _send(
        f"❌ <b>Order FAILED — {_pair(pair)}</b>\n"
        f"⏰ {_now()}\n"
        f"📊 Signal : {signal}\n"
        f"⚠️ Error  : {error}\n"
        f"🔧 Check OANDA account manually!"
    )


# ============================================================
# Risk circuit breakers
# ============================================================

def notify_daily_loss_limit(loss_pct: float, loss_usd: float, limit_pct: float):
    _send(
        f"🚨 <b>DAILY LOSS LIMIT HIT — BOT PAUSED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {_now()}\n"
        f"📉 Loss today  : -{loss_pct:.2f}% (${loss_usd:,.2f})\n"
        f"🔒 Limit       : {limit_pct:.1f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛑 No more trades today.\n"
        f"⏳ Bot resumes tomorrow at 07:00 UTC."
    )


def notify_max_trades_reached(count: int):
    _send(
        f"🔒 <b>Max Trades Reached — {count}/day</b>\n"
        f"⏰ {_now()}\n"
        f"💤 Bot paused until midnight UTC reset."
    )


# ============================================================
# Daily summary
# ============================================================

def notify_daily_summary(date: str, trades: int, wins: int, losses: int,
                          bes: int, pnl_usd: float, pairs_traded: list,
                          signals_scanned: int):
    win_rate = f"{(wins/trades*100):.0f}%" if trades > 0 else "N/A"
    pairs_str = ", ".join(_pair(p) for p in pairs_traded) if pairs_traded else "None"
    emoji = "📈" if pnl_usd >= 0 else "📉"

    _send(
        f"📋 <b>Daily Summary — {date}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} P&L         : ${pnl_usd:+,.2f}\n"
        f"✅ Wins        : {wins}\n"
        f"❌ Losses      : {losses}\n"
        f"🔵 Breakeven   : {bes}\n"
        f"📊 Win Rate    : {win_rate}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Signals scanned: {signals_scanned}\n"
        f"💱 Pairs traded   : {pairs_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 Bot continues tomorrow."
    )


# ============================================================
# Errors
# ============================================================

def notify_error(context: str, error: str):
    _send(
        f"⚠️ <b>Bot Error</b>\n"
        f"⏰ {_now()}\n"
        f"📍 Context : {context}\n"
        f"❌ Error   : {error[:200]}\n"
        f"🔄 Retrying in 60s..."
    )


def notify_critical_error(context: str, error: str):
    _send(
        f"🚨 <b>CRITICAL ERROR — MANUAL CHECK REQUIRED</b>\n"
        f"⏰ {_now()}\n"
        f"📍 Context : {context}\n"
        f"❌ Error   : {error[:300]}\n"
        f"🛑 Bot may have stopped. Check Railway logs!"
    )