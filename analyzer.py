import json
import re
import requests
from config import GROQ_API_KEY, GROQ_MODEL

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are an expert ICT/SMC forex trader analyzing EUR/USD 15-minute candles.
You identify Liquidity Sweep + Reversal setups using this exact framework:

SETUP RULES:
1. Equal Highs/Lows: Two swing highs/lows within 0.0008 of each other = liquidity pool
2. Sweep: Price wick exceeds the level by at least 0.0003, but CLOSES back inside
3. Displacement: Large body candle (body > 60% of total range) moving opposite to sweep
4. FVG: Gap between candle[i-2].high and candle[i].low (bearish) or candle[i-2].low and candle[i].high (bullish)
5. CHoCH: After sweep, price forms a lower high (bearish) or higher low (bullish)

RESPONSE FORMAT — respond ONLY with valid JSON, no extra text, no markdown:
{
  "signal": "SHORT" | "LONG" | "NO_TRADE",
  "confidence": 1-10,
  "liquidity_level": 1.00000,
  "sweep_high_or_low": 1.00000,
  "fvg_top": 1.00000,
  "fvg_bot": 1.00000,
  "entry_price": 1.00000,
  "stop_loss": 1.00000,
  "take_profit_1": 1.00000,
  "take_profit_2": 1.00000,
  "reason": "one sentence explanation",
  "invalidation": "what would cancel this setup"
}

If no valid setup exists return signal: NO_TRADE with null for price fields.
Only return HIGH confidence setups (7+). Be strict."""


def analyze_setup(candle_data_str, in_kill_zone=False, kz_name=""):
    kz_context = (
        f"Current time IS inside {kz_name} Kill Zone."
        if in_kill_zone
        else "Current time is OUTSIDE Kill Zone — be extra strict."
    )

    user_message = f"""Analyze this EUR/USD 15M candle data for a Liquidity Sweep + Reversal setup.

{kz_context}

CANDLE DATA (most recent candle is last):
{candle_data_str}

Check for:
- Equal highs or equal lows forming a liquidity pool
- A sweep of that level (wick beyond, close back inside)
- Displacement candle after the sweep
- FVG created by displacement
- CHoCH confirmation

Respond with JSON only. No markdown, no backticks, no explanation."""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json"
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message}
        ],
        "max_tokens":  400,
        "temperature": 0.1   # low temp = more consistent, less hallucination
    }

    response = requests.post(GROQ_API_URL, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    raw = data["choices"][0]["message"]["content"].strip()

    # strip markdown code fences if model wraps in ```json
    raw = re.sub(r"```json|```", "", raw).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            result = {
                "signal": "NO_TRADE",
                "confidence": 0,
                "reason": "Parse error — model returned non-JSON",
                "entry_price": None
            }

    # Groq usage stats
    usage        = data.get("usage", {})
    input_tokens  = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    # Groq free tier = $0 — paid tier is very cheap
    # llama-3.3-70b: $0.59 input / $0.79 output per million tokens
    cost = (input_tokens / 1_000_000 * 0.59) + (output_tokens / 1_000_000 * 0.79)

    return result, round(cost, 6)


def print_signal(signal_data, cost):
    sig  = signal_data.get("signal", "NO_TRADE")
    conf = signal_data.get("confidence", 0)

    print("\n" + "="*50)
    print(f"  SIGNAL: {sig}  |  Confidence: {conf}/10")
    print("="*50)

    if sig != "NO_TRADE":
        print(f"  Liquidity Level : {signal_data.get('liquidity_level')}")
        print(f"  Sweep Level     : {signal_data.get('sweep_high_or_low')}")
        print(f"  FVG Zone        : {signal_data.get('fvg_bot')} — {signal_data.get('fvg_top')}")
        print(f"  Entry Price     : {signal_data.get('entry_price')}")
        print(f"  Stop Loss       : {signal_data.get('stop_loss')}")
        print(f"  Take Profit 1   : {signal_data.get('take_profit_1')}")
        print(f"  Take Profit 2   : {signal_data.get('take_profit_2')}")

    print(f"  Reason          : {signal_data.get('reason')}")
    if sig != "NO_TRADE":
        print(f"  Invalidation    : {signal_data.get('invalidation')}")
    print(f"  API Cost        : ${cost} (Groq)")
    print("="*50 + "\n")