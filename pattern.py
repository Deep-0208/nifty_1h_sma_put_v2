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

    Signal rules (from locked specification):
        1. Candle is RED: close < open
        2. close < SMA 20
        3. close < SMA 50

    All three conditions on the SAME completed candle.

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
        "Evaluating candle %s: O=%.2f H=%.2f L=%.2f C=%.2f | "
        "SMA20=%s SMA50=%s",
        candle_time, o, h, l, c,
        f"{sma_20:.2f}" if sma_20 is not None else "None",
        f"{sma_50:.2f}" if sma_50 is not None else "None",
    )

    # Guard: reject if SMA values are missing (warmup period)
    if sma_20 is None or sma_50 is None:
        log_pattern.debug(
            "REJECTED: SMA warmup incomplete "
            "(sma_20=%s, sma_50=%s)", sma_20, sma_50,
        )
        return None

    # Guard: reject NaN
    if math.isnan(sma_20) or math.isnan(sma_50):
        log_pattern.debug("REJECTED: SMA contains NaN.")
        return None

    # Condition 1: Red candle
    is_red = c < o
    log_pattern.debug(
        "  Condition 1 (Red candle): close=%.2f < open=%.2f -> %s",
        c, o, is_red,
    )

    # Condition 2: Close below SMA 20
    below_sma20 = c < sma_20
    log_pattern.debug(
        "  Condition 2 (Below SMA20): close=%.2f < sma_20=%.2f -> %s",
        c, sma_20, below_sma20,
    )

    # Condition 3: Close below SMA 50
    below_sma50 = c < sma_50
    log_pattern.debug(
        "  Condition 3 (Below SMA50): close=%.2f < sma_50=%.2f -> %s",
        c, sma_50, below_sma50,
    )

    if is_red and below_sma20 and below_sma50:
        signal = SetupSignal(
            signal_type="BEARISH_SMA_BREAKDOWN",
            signal_candle=candle,
            sma_20=sma_20,
            sma_50=sma_50,
            spot_sl=h,  # Signal candle High = Spot SL
        )
        log_pattern.info(
            "SIGNAL DETECTED on candle %s: "
            "C=%.2f < SMA20=%.2f < SMA50=%.2f | "
            "Spot SL (High)=%.2f",
            candle_time, c, sma_20, sma_50, h,
        )
        return signal

    log_pattern.debug(
        "No signal on candle %s. "
        "Conditions: red=%s, below_sma20=%s, below_sma50=%s",
        candle_time, is_red, below_sma20, below_sma50,
    )
    return None