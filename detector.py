"""
detector.py — Pure Python ICT/SMC Liquidity Sweep + Reversal detector

No AI. No LLM. Pure math.
This is deterministic — same candles always produce same result.
Every rule maps exactly to the backtested strategy.

Detection pipeline:
1. Daily bias (bullish / bearish / neutral)
2. Premium / discount zone
3. Equal highs / lows (liquidity pool) on 1H
4. Sweep confirmation (1H candle)
5. Displacement candle after sweep (15M)
6. FVG created by displacement (15M)
7. CHoCH confirmation (15M)
8. Entry price = FVG midpoint
"""

from config import (
    EQUAL_LEVEL_TOLERANCE, MIN_SWEEP_DISTANCE, DISPLACEMENT_BODY_PCT,
    MIN_DISPLACEMENT_BODY, MIN_FVG_SIZE, FVG_EXPIRY_CANDLES, SWING_LOOKBACK,
    SL_BUFFER_PIPS, PIP_SIZE, TP1_RR, TP2_RR,
)


# ============================================================
# Step 1 — Daily bias
# ============================================================

def get_daily_bias(daily_candles: list) -> tuple:
    """
    Determines daily trend bias from the last N daily candles.

    Returns: (bias: str, reason: str)
    bias = "BULLISH" | "BEARISH" | "NEUTRAL"

    Rules:
    - BULLISH: last 3 daily closes making higher highs and higher lows
    - BEARISH: last 3 daily closes making lower highs and lower lows
    - NEUTRAL: mixed
    """
    if len(daily_candles) < 5:
        return "NEUTRAL", "Not enough daily candles"

    # Use last 5 candles for trend detection
    recent = daily_candles[-5:]

    highs  = [c["high"]  for c in recent]
    lows   = [c["low"]   for c in recent]
    closes = [c["close"] for c in recent]

    # Check last 3 swings
    hh = highs[-1]  > highs[-2]  > highs[-3]   # higher highs
    hl = lows[-1]   > lows[-2]   > lows[-3]    # higher lows
    lh = highs[-1]  < highs[-2]  < highs[-3]   # lower highs
    ll = lows[-1]   < lows[-2]   < lows[-3]    # lower lows

    # Also check close direction
    bullish_closes = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
    bearish_closes = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i-1])

    if (hh or hl) and bullish_closes >= 3:
        return "BULLISH", "Daily making higher highs/lows with bullish closes"

    if (lh or ll) and bearish_closes >= 3:
        return "BEARISH", "Daily making lower highs/lows with bearish closes"

    if bullish_closes >= 3:
        return "BULLISH", "Daily closes predominantly bullish"

    if bearish_closes >= 3:
        return "BEARISH", "Daily closes predominantly bearish"

    return "NEUTRAL", "Mixed daily structure"


# ============================================================
# Step 2 — Premium / discount zone
# ============================================================

def get_htf_zone(daily_candles: list, current_price: float) -> str:
    """
    Determines if price is in premium, discount, or equilibrium.

    Uses the range of the last 10 daily candles.
    Above 50% = PREMIUM (good for shorts)
    Below 50% = DISCOUNT (good for longs)
    """
    if len(daily_candles) < 3:
        return "EQUILIBRIUM"

    recent    = daily_candles[-10:] if len(daily_candles) >= 10 else daily_candles
    range_high = max(c["high"]  for c in recent)
    range_low  = min(c["low"]   for c in recent)
    range_size = range_high - range_low

    if range_size == 0:
        return "EQUILIBRIUM"

    position = (current_price - range_low) / range_size   # 0 to 1

    if position > 0.55:
        return "PREMIUM"
    elif position < 0.45:
        return "DISCOUNT"
    else:
        return "EQUILIBRIUM"


# ============================================================
# Step 3 — Equal highs / lows detection
# ============================================================

def find_swing_highs(candles: list, lookback: int = SWING_LOOKBACK) -> list:
    """
    Finds pivot highs — candles with a high that is the highest
    within `lookback` candles on each side.
    Returns list of (index, price) tuples.
    """
    pivots = []
    for i in range(lookback, len(candles) - lookback):
        high = candles[i]["high"]
        is_pivot = all(
            candles[i - j]["high"] < high and candles[i + j]["high"] < high
            for j in range(1, lookback + 1)
        )
        if is_pivot:
            pivots.append((i, high))
    return pivots


def find_swing_lows(candles: list, lookback: int = SWING_LOOKBACK) -> list:
    """
    Finds pivot lows — candles with a low that is the lowest
    within `lookback` candles on each side.
    Returns list of (index, price) tuples.
    """
    pivots = []
    for i in range(lookback, len(candles) - lookback):
        low = candles[i]["low"]
        is_pivot = all(
            candles[i - j]["low"] > low and candles[i + j]["low"] > low
            for j in range(1, lookback + 1)
        )
        if is_pivot:
            pivots.append((i, low))
    return pivots


def find_equal_highs(candles: list, pair: str) -> list:
    """
    Finds equal highs — two or more swing highs within tolerance of each other.
    Returns list of (level, indices) for each equal high cluster.
    These represent Buy-Side Liquidity (BSL).
    """
    pivots    = find_swing_highs(candles)
    tolerance = EQUAL_LEVEL_TOLERANCE
    clusters  = []

    for i in range(len(pivots)):
        for j in range(i + 1, len(pivots)):
            idx_i, price_i = pivots[i]
            idx_j, price_j = pivots[j]
            # Both pivots must be recent (within last 30 candles)
            if idx_j < len(candles) - 30:
                continue
            diff = abs(price_i - price_j) / max(price_i, price_j)
            if diff <= tolerance:
                level = (price_i + price_j) / 2
                clusters.append({
                    "level":   round(level, 5),
                    "high":    round(max(price_i, price_j), 5),
                    "indices": [idx_i, idx_j],
                    "type":    "BSL",
                })

    # Deduplicate clusters that are very close together
    unique = []
    for c in clusters:
        if not any(abs(c["level"] - u["level"]) < 0.0005 for u in unique):
            unique.append(c)

    return unique


def find_equal_lows(candles: list, pair: str) -> list:
    """
    Finds equal lows — two or more swing lows within tolerance.
    Returns list of (level, indices).
    These represent Sell-Side Liquidity (SSL).
    """
    pivots    = find_swing_lows(candles)
    tolerance = EQUAL_LEVEL_TOLERANCE
    clusters  = []

    for i in range(len(pivots)):
        for j in range(i + 1, len(pivots)):
            idx_i, price_i = pivots[i]
            idx_j, price_j = pivots[j]
            if idx_j < len(candles) - 30:
                continue
            diff = abs(price_i - price_j) / max(price_i, price_j)
            if diff <= tolerance:
                level = (price_i + price_j) / 2
                clusters.append({
                    "level":   round(level, 5),
                    "low":     round(min(price_i, price_j), 5),
                    "indices": [idx_i, idx_j],
                    "type":    "SSL",
                })

    unique = []
    for c in clusters:
        if not any(abs(c["level"] - u["level"]) < 0.0005 for u in unique):
            unique.append(c)

    return unique


# ============================================================
# Step 4 — Sweep detection
# ============================================================

def detect_sweep(candles: list, pair: str, liquidity_clusters: list,
                 sweep_type: str) -> dict | None:
    """
    Checks the most recent candles for a sweep of a liquidity level.

    sweep_type: "BSL" (above equal highs) or "SSL" (below equal lows)

    A valid sweep:
    - Wick exceeds the level by MIN_SWEEP_DISTANCE
    - Candle CLOSES back inside (below BSL or above SSL)
    - Happened within the last 5 candles

    Returns sweep dict or None.
    """
    if not candles or not liquidity_clusters:
        return None

    min_dist = MIN_SWEEP_DISTANCE.get(pair, 0.0003)

    # Check last 3 candles for the sweep
    for i in range(max(0, len(candles) - 3), len(candles)):
        candle = candles[i]

        for cluster in liquidity_clusters:
            level = cluster["level"]

            if sweep_type == "BSL":
                # Wick above the BSL level
                swept_distance = candle["high"] - level
                close_back     = candle["close"] < level   # closed back below

                if swept_distance >= min_dist and close_back:
                    return {
                        "type":            "BSL",
                        "liquidity_level": level,
                        "sweep_price":     round(candle["high"], 5),
                        "sweep_candle_idx": i,
                        "sweep_candle":    candle,
                        "signal":          "SHORT",
                    }

            elif sweep_type == "SSL":
                # Wick below the SSL level
                swept_distance = level - candle["low"]
                close_back     = candle["close"] > level   # closed back above

                if swept_distance >= min_dist and close_back:
                    return {
                        "type":            "SSL",
                        "liquidity_level": level,
                        "sweep_price":     round(candle["low"], 5),
                        "sweep_candle_idx": i,
                        "sweep_candle":    candle,
                        "signal":          "LONG",
                    }

    return None


# ============================================================
# Step 5 — Displacement candle
# ============================================================

def find_displacement(candles_15m: list, sweep_candle_time: str,
                      signal: str, pair: str) -> dict | None:
    """
    Finds a displacement candle AFTER the sweep on the 15M chart.

    Displacement requirements:
    - Body >= MIN_DISPLACEMENT_BODY[pair] in price
    - Body >= DISPLACEMENT_BODY_PCT of total candle range
    - Direction matches signal (SHORT = bearish candle, LONG = bullish)
    - Occurs within 5 candles of the sweep

    Returns displacement candle dict or None.
    """
    min_body = MIN_DISPLACEMENT_BODY.get(pair, 0.0025)

    # Find candles AFTER the sweep
    after_sweep = []
    found_sweep = False
    for c in candles_15m:
        if found_sweep:
            after_sweep.append(c)
        if c["time"] >= sweep_candle_time:
            found_sweep = True
        if len(after_sweep) >= 5:
            break

    if not after_sweep:
        # If we can't find by time, use last 5 candles
        after_sweep = candles_15m[-5:]

    for candle in after_sweep:
        body       = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]

        if total_range == 0:
            continue

        body_pct = body / total_range

        # Direction check
        is_bearish = candle["close"] < candle["open"]
        is_bullish = candle["close"] > candle["open"]

        direction_ok = (signal == "SHORT" and is_bearish) or \
                       (signal == "LONG"  and is_bullish)

        if direction_ok and body >= min_body and body_pct >= DISPLACEMENT_BODY_PCT:
            return {
                "candle":       candle,
                "body":         round(body, 5),
                "body_pct":     round(body_pct, 3),
                "body_pips":    round(body / PIP_SIZE.get(pair, 0.0001)),
            }

    return None


# ============================================================
# Step 6 — FVG detection
# ============================================================

def find_fvg(candles_15m: list, displacement_candle: dict,
             signal: str, pair: str) -> dict | None:
    """
    Finds the Fair Value Gap created by the displacement candle.

    Bearish FVG (after SHORT sweep):
        candle[i-2].low > candle[i].high
        Gap = between candle[i-2].low and candle[i].high

    Bullish FVG (after LONG sweep):
        candle[i-2].high < candle[i].low
        Gap = between candle[i-2].high and candle[i].low

    Returns FVG dict with top, bot, midpoint, or None.
    """
    min_fvg = MIN_FVG_SIZE.get(pair, 0.0002)
    disp_time = displacement_candle["candle"]["time"]

    # Find the displacement candle index in the 15M series
    disp_idx = None
    for i, c in enumerate(candles_15m):
        if c["time"] == disp_time:
            disp_idx = i
            break

    if disp_idx is None or disp_idx < 2:
        # Fallback: search last 10 candles for any FVG
        search_range = candles_15m[-10:]
        disp_idx     = len(candles_15m) - len(search_range)

    # Check 3-candle FVG patterns around the displacement
    start = max(2, disp_idx - 2)
    end   = min(len(candles_15m) - 1, disp_idx + 3)

    for i in range(start, end + 1):
        if i < 2 or i >= len(candles_15m):
            continue

        c_prev2 = candles_15m[i - 2]   # candle before gap
        c_mid   = candles_15m[i - 1]   # displacement candle
        c_curr  = candles_15m[i]       # candle after gap

        if signal == "SHORT":
            # Bearish FVG: c_prev2.low > c_curr.high
            fvg_top = c_prev2["low"]
            fvg_bot = c_curr["high"]
            if fvg_top > fvg_bot and (fvg_top - fvg_bot) >= min_fvg:
                midpoint = (fvg_top + fvg_bot) / 2
                age      = len(candles_15m) - i
                if age <= FVG_EXPIRY_CANDLES:
                    return {
                        "top":      round(fvg_top, 5),
                        "bot":      round(fvg_bot, 5),
                        "midpoint": round(midpoint, 5),
                        "age":      age,
                        "type":     "BEARISH",
                    }

        elif signal == "LONG":
            # Bullish FVG: c_prev2.high < c_curr.low
            fvg_bot = c_prev2["high"]
            fvg_top = c_curr["low"]
            if fvg_top > fvg_bot and (fvg_top - fvg_bot) >= min_fvg:
                midpoint = (fvg_top + fvg_bot) / 2
                age      = len(candles_15m) - i
                if age <= FVG_EXPIRY_CANDLES:
                    return {
                        "top":      round(fvg_top, 5),
                        "bot":      round(fvg_bot, 5),
                        "midpoint": round(midpoint, 5),
                        "age":      age,
                        "type":     "BULLISH",
                    }

    return None


# ============================================================
# Step 7 — CHoCH detection
# ============================================================

def detect_choch(candles_15m: list, signal: str, sweep_idx: int) -> bool:
    """
    Detects Change of Character (CHoCH) on 15M after the sweep.

    Bearish CHoCH (for SHORT):
        After the sweep, price forms a lower high then breaks below
        a prior 15M swing low.

    Bullish CHoCH (for LONG):
        After the sweep, price forms a higher low then breaks above
        a prior 15M swing high.

    Uses the last 8 candles after the sweep candle index.
    """
    if not candles_15m or sweep_idx < 0:
        return False

    # Get candles after the sweep
    post_sweep = candles_15m[sweep_idx:]
    if len(post_sweep) < 3:
        post_sweep = candles_15m[-8:]

    if len(post_sweep) < 3:
        return False

    if signal == "SHORT":
        # Look for: price makes a lower high after sweep
        # Then breaks below a prior swing low
        first_high = post_sweep[0]["high"]
        for i in range(1, len(post_sweep)):
            if post_sweep[i]["high"] < first_high:
                # Lower high confirmed
                prior_low = min(c["low"] for c in post_sweep[:i])
                for j in range(i, len(post_sweep)):
                    if post_sweep[j]["close"] < prior_low:
                        return True   # CHoCH confirmed
        return False

    elif signal == "LONG":
        # Look for: price makes a higher low after sweep
        # Then breaks above a prior swing high
        first_low = post_sweep[0]["low"]
        for i in range(1, len(post_sweep)):
            if post_sweep[i]["low"] > first_low:
                # Higher low confirmed
                prior_high = max(c["high"] for c in post_sweep[:i])
                for j in range(i, len(post_sweep)):
                    if post_sweep[j]["close"] > prior_high:
                        return True   # CHoCH confirmed
        return False

    return False


# ============================================================
# Step 8 — Calculate trade levels
# ============================================================

def calculate_trade_levels(pair: str, signal: str,
                            entry: float, sweep_price: float) -> dict:
    """
    Calculates SL, TP1, TP2 from the entry and sweep wick.

    SL: beyond the sweep wick + buffer
    TP1: 1:2 RR
    TP2: 1:4 RR
    """
    pip    = PIP_SIZE.get(pair, 0.0001)
    buffer = SL_BUFFER_PIPS.get(pair, 3) * pip

    if signal == "SHORT":
        sl       = round(sweep_price + buffer, 5)
        risk     = sl - entry
        tp1      = round(entry - risk * TP1_RR, 5)
        tp2      = round(entry - risk * TP2_RR, 5)

    else:  # LONG
        sl       = round(sweep_price - buffer, 5)
        risk     = entry - sl
        tp1      = round(entry + risk * TP1_RR, 5)
        tp2      = round(entry + risk * TP2_RR, 5)

    risk_pips = round(abs(risk) / pip, 1)
    tp1_pips  = round(abs(entry - tp1) / pip, 1)
    tp2_pips  = round(abs(entry - tp2) / pip, 1)

    return {
        "entry":     entry,
        "stop_loss": sl,
        "tp1":       tp1,
        "tp2":       tp2,
        "risk_pips": risk_pips,
        "tp1_pips":  tp1_pips,
        "tp2_pips":  tp2_pips,
        "risk_price": round(abs(risk), 5),
    }


# ============================================================
# Master analysis function
# ============================================================

def analyze_pair(pair: str, mtf_data: dict) -> dict:
    """
    Runs the full top-down ICT analysis for one pair.

    Returns a result dict:
    {
        "signal":          "SHORT" | "LONG" | "NO_TRADE",
        "reason":          str,
        "daily_bias":      str,
        "htf_zone":        str,
        "liquidity_level": float | None,
        "sweep_price":     float | None,
        "fvg_top":         float | None,
        "fvg_bot":         float | None,
        "entry":           float | None,
        "stop_loss":       float | None,
        "tp1":             float | None,
        "tp2":             float | None,
        "risk_pips":       float | None,
    }
    """
    daily   = mtf_data.get("Daily", [])
    h1      = mtf_data.get("1H", [])
    m15     = mtf_data.get("15M", [])

    no_trade = {
        "signal": "NO_TRADE", "daily_bias": "UNKNOWN", "htf_zone": "UNKNOWN",
        "liquidity_level": None, "sweep_price": None,
        "fvg_top": None, "fvg_bot": None,
        "entry": None, "stop_loss": None, "tp1": None, "tp2": None,
        "risk_pips": None,
    }

    # ── Guard: enough candles ─────────────────────────────
    if len(daily) < 5 or len(h1) < 20 or len(m15) < 30:
        return {**no_trade, "reason": f"Not enough candles (D:{len(daily)} 1H:{len(h1)} 15M:{len(m15)})"}

    # ── Step 1: Daily bias ────────────────────────────────
    daily_bias, bias_reason = get_daily_bias(daily)

    if daily_bias == "NEUTRAL":
        return {**no_trade, "reason": f"Daily bias NEUTRAL — {bias_reason}", "daily_bias": "NEUTRAL", "htf_zone": "EQUILIBRIUM"}

    # ── Step 2: HTF zone ──────────────────────────────────
    current_price = m15[-1]["close"]
    htf_zone = get_htf_zone(daily, current_price)

    # Validate: don't long in premium, don't short in discount
    if daily_bias == "BULLISH" and htf_zone == "PREMIUM":
        return {**no_trade, "reason": "Bullish bias but price in PREMIUM — waiting for discount",
                "daily_bias": daily_bias, "htf_zone": htf_zone}

    if daily_bias == "BEARISH" and htf_zone == "DISCOUNT":
        return {**no_trade, "reason": "Bearish bias but price in DISCOUNT — waiting for premium",
                "daily_bias": daily_bias, "htf_zone": htf_zone}

    # ── Step 3: Find liquidity pools on 1H ───────────────
    signal_direction = "SHORT" if daily_bias == "BEARISH" else "LONG"

    if signal_direction == "SHORT":
        # Looking for BSL sweep (equal highs)
        clusters = find_equal_highs(h1, pair)
        sweep = detect_sweep(h1, pair, clusters, "BSL") if clusters else None
    else:
        # Looking for SSL sweep (equal lows)
        clusters = find_equal_lows(h1, pair)
        sweep = detect_sweep(h1, pair, clusters, "SSL") if clusters else None

    if not sweep:
        return {**no_trade,
                "reason": f"No {signal_direction} sweep found on 1H",
                "daily_bias": daily_bias, "htf_zone": htf_zone}

    # ── Step 4: Displacement on 15M ──────────────────────
    sweep_time = sweep["sweep_candle"]["time"]
    displacement = find_displacement(m15, sweep_time, signal_direction, pair)

    if not displacement:
        return {**no_trade,
                "reason": f"No displacement candle after sweep (need {MIN_DISPLACEMENT_BODY.get(pair,0.0025)/PIP_SIZE.get(pair,0.0001):.0f}+ pip body)",
                "daily_bias": daily_bias, "htf_zone": htf_zone}

    # ── Step 5: FVG on 15M ───────────────────────────────
    fvg = find_fvg(m15, displacement, signal_direction, pair)

    if not fvg:
        return {**no_trade,
                "reason": "No FVG found after displacement",
                "daily_bias": daily_bias, "htf_zone": htf_zone}

    # ── Step 6: CHoCH on 15M ─────────────────────────────
    sweep_idx = sweep["sweep_candle_idx"]
    # Map sweep index from 1H to approximate 15M position
    # 1 × 1H candle ≈ 4 × 15M candles
    m15_sweep_idx = max(0, len(m15) - (len(h1) - sweep_idx) * 4)
    choch = detect_choch(m15, signal_direction, m15_sweep_idx)

    if not choch:
        return {**no_trade,
                "reason": "CHoCH not yet confirmed on 15M",
                "daily_bias": daily_bias, "htf_zone": htf_zone}

    # ── Step 7: Entry at FVG midpoint ────────────────────
    entry = fvg["midpoint"]

    # Validate entry is near current price (within 50 pips)
    pip = PIP_SIZE.get(pair, 0.0001)
    if abs(entry - current_price) > 50 * pip:
        return {**no_trade,
                "reason": f"FVG midpoint {entry:.5f} too far from current price {current_price:.5f}",
                "daily_bias": daily_bias, "htf_zone": htf_zone}

    # ── Step 8: Trade levels ──────────────────────────────
    levels = calculate_trade_levels(pair, signal_direction, entry, sweep["sweep_price"])

    # Validate SL is sensible (not more than 60 pips)
    if levels["risk_pips"] > 60:
        return {**no_trade,
                "reason": f"SL too wide: {levels['risk_pips']} pips (max 60)",
                "daily_bias": daily_bias, "htf_zone": htf_zone}

    if levels["risk_pips"] < 5:
        return {**no_trade,
                "reason": f"SL too tight: {levels['risk_pips']} pips (min 5)",
                "daily_bias": daily_bias, "htf_zone": htf_zone}

    # ── All checks passed — valid setup ──────────────────
    return {
        "signal":          signal_direction,
        "reason":          (
            f"Daily {daily_bias} | {htf_zone} zone | "
            f"{sweep['type']} swept at {sweep['liquidity_level']:.5f} | "
            f"Displacement {displacement['body_pips']:.0f} pips | "
            f"FVG {fvg['bot']:.5f}–{fvg['top']:.5f} | CHoCH confirmed"
        ),
        "daily_bias":      daily_bias,
        "htf_zone":        htf_zone,
        "liquidity_level": sweep["liquidity_level"],
        "sweep_price":     sweep["sweep_price"],
        "fvg_top":         fvg["top"],
        "fvg_bot":         fvg["bot"],
        "entry":           levels["entry"],
        "stop_loss":       levels["stop_loss"],
        "tp1":             levels["tp1"],
        "tp2":             levels["tp2"],
        "risk_pips":       levels["risk_pips"],
        "tp1_pips":        levels["tp1_pips"],
        "tp2_pips":        levels["tp2_pips"],
        "displacement_pips": displacement["body_pips"],
    }