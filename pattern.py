"""
pattern.py - Signal Detection
Only signal detection logic. No orders, no P&L, no risk calculations.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from config import log_pattern


@dataclass
class SetupSignal:
    """Represents a confirmed bearish SMA breakdown signal."""
    signal_type: str          # Always "BEARISH_SMA_BREAKDOWN"
    signal_candle: Dict       # The full 1H candle that triggered
    sma_20: float
    sma_50: float
    spot_sl: float            # Signal candle High


def detect_signal(completed_candles: List[Dict]) -> Optional[SetupSignal]:
    """
    Evaluate the latest completed 1H candle for a bearish SMA breakdown.

    Signal rules (v2 specification):
        1. Candle is RED: close < open
        2. Candle OPEN is between 20 SMA and 50 SMA: sma_20 < open < sma_50
        3. Candle CLOSE is below SMA 20: close < sma_20
        4. Candle CLOSE is below SMA 50: close < sma_50

    All conditions on the SAME completed candle.
    Note: sma_20 < open < sma_50 inherently requires 20 SMA to be below 50 SMA (bearish trend).

    Returns SetupSignal if valid, None otherwise.
    """
    if not completed_candles:
        log_pattern.debug("No completed candles to evaluate.")
        return None

    candle = completed_candles[-1]
    candle_time = candle["date"]

    o = candle["open"]
    h = candle["high"]
    l = candle["low"]
    c = candle["close"]
    sma_20 = candle.get("sma_20")
    sma_50 = candle.get("sma_50")

    log_pattern.debug(
        "🔍 Evaluating 1H candle %s: O=%.2f H=%.2f L=%.2f C=%.2f | SMA20=%s SMA50=%s",
        candle_time, o, h, l, c,
        f"{sma_20:.2f}" if sma_20 is not None else "None",
        f"{sma_50:.2f}" if sma_50 is not None else "None",
    )

    # Guard: reject if SMA values are missing (warmup period)
    if sma_20 is None or sma_50 is None:
        log_pattern.debug(
            "❌ REJECTED: SMA warmup incomplete (sma_20=%s, sma_50=%s)", sma_20, sma_50,
        )
        return None

    # Guard: reject NaN
    if math.isnan(sma_20) or math.isnan(sma_50):
        log_pattern.debug("❌ REJECTED: SMA contains NaN.")
        return None

    # Condition 1: Red candle
    is_red = c < o
    log_pattern.debug(
        "  [1/4] Red candle check: close=%.2f < open=%.2f -> %s", c, o, is_red,
    )

    # Condition 2: Open between 20 SMA and 50 SMA (sma_20 < open < sma_50)
    open_between_smas = sma_20 < o < sma_50
    log_pattern.debug(
        "  [2/4] Open between SMAs check: sma_20=%.2f < open=%.2f < sma_50=%.2f -> %s",
        sma_20, o, sma_50, open_between_smas,
    )

    # Condition 3: Close below SMA 20
    below_sma20 = c < sma_20
    log_pattern.debug(
        "  [3/4] Below SMA20 check: close=%.2f < sma_20=%.2f -> %s", c, sma_20, below_sma20,
    )

    # Condition 4: Close below SMA 50
    below_sma50 = c < sma_50
    log_pattern.debug(
        "  [4/4] Below SMA50 check: close=%.2f < sma_50=%.2f -> %s", c, sma_50, below_sma50,
    )

    if is_red and open_between_smas and below_sma20 and below_sma50:
        signal = SetupSignal(
            signal_type="BEARISH_SMA_BREAKDOWN",
            signal_candle=candle,
            sma_20=sma_20,
            sma_50=sma_50,
            spot_sl=h,  # Signal candle High = Spot SL
        )
        log_pattern.info(
            "🎯 BEARISH BREAKDOWN SIGNAL DETECTED on 1H candle %s: "
            "SMA20=%.2f < Open=%.2f < SMA50=%.2f | Close=%.2f < SMAs | Spot SL (High)=%.2f",
            candle_time, sma_20, o, sma_50, c, h,
        )
        return signal

    log_pattern.debug(
        "No signal on 1H candle %s (red=%s, open_between=%s, below_sma20=%s, below_sma50=%s)",
        candle_time, is_red, open_between_smas, below_sma20, below_sma50,
    )
    return None