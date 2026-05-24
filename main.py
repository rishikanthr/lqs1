import time
import traceback
from datetime import datetime, timezone

from config       import MAX_TRADES_DAY
from data_fetcher import get_candles, in_kill_zone, get_account_balance, format_candles_for_claude
from analyzer     import analyze_setup, print_signal
from trader       import place_order, log_trade, get_open_trades

CHECK_INTERVAL_SECONDS = 900  # 15 minutes

def run_bot():
    print("\n" + "="*55)
    print("  EUR/USD Sweep + Reversal Paper Trading Bot")
    print("  Model: Claude Haiku 4.5  |  Timeframe: 15M")
    print("="*55)

    trades_today   = 0
    last_date      = None
    total_api_cost = 0.0

    while True:
        try:
            now     = datetime.now(timezone.utc)
            now_str = now.strftime("%Y-%m-%d %H:%M UTC")

            if last_date != now.date():
                trades_today = 0
                last_date    = now.date()
                print(f"\n  [BOT] New day — trade counter reset.")

            print(f"\n  [BOT] Checking at {now_str}")

            if trades_today >= MAX_TRADES_DAY:
                print(f"  [BOT] Max trades reached ({MAX_TRADES_DAY}). Waiting...")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            open_trades = get_open_trades()
            if open_trades >= 2:
                print(f"  [BOT] {open_trades} trades open. Waiting...")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            in_kz, kz_name = in_kill_zone()
            if not in_kz:
                print(f"  [BOT] Outside Kill Zone. Next check in 15 min...")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            print(f"  [BOT] Inside Kill Zone: {kz_name}")
            print(f"  [BOT] Fetching candles...")
            candles = get_candles()

            if len(candles) < 20:
                print(f"  [BOT] Not enough candles. Skipping.")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            candle_str = format_candles_for_claude(candles)

            print(f"  [BOT] Sending to Claude...")
            signal_data, cost = analyze_setup(candle_str, in_kz, kz_name)
            total_api_cost += cost
            print_signal(signal_data, cost)

            sig  = signal_data.get("signal", "NO_TRADE")
            conf = signal_data.get("confidence", 0)

            if sig == "NO_TRADE" or conf < 7:
                print(f"  [BOT] No valid setup (signal={sig}, conf={conf}). Waiting...")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            print(f"  [BOT] Valid {sig} setup! Confidence: {conf}/10")
            balance      = get_account_balance()
            order_result = place_order(signal_data, balance)
            log_trade(signal_data, order_result, cost, kz_name)

            if order_result:
                trades_today += 1
                print(f"  [BOT] Trades today: {trades_today}/{MAX_TRADES_DAY}")
                print(f"  [BOT] Total API cost: ${total_api_cost:.4f}")

            time.sleep(CHECK_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print(f"\n  [BOT] Stopped.")
            print(f"  [BOT] Total API cost this session: ${total_api_cost:.4f}")
            break

        except Exception as e:
            print(f"\n  [ERROR] {e}")
            traceback.print_exc()
            print(f"  [BOT] Retrying in 60s...")
            time.sleep(60)


if __name__ == "__main__":
    run_bot()