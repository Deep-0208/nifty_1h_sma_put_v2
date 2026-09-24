"""
risk.py - ATM Strike Calculation & Spot-Level Risk Parameters
Implements Spot SL, Spot Target, and ATM strike logic.
No option-premium SL/TP is computed here.
"""

from dataclasses import dataclass
from typing import Optional

from config import CONFIG, log_risk


@dataclass
class SpotRiskParams:
    """Spot-level risk parameters for a PUT trade."""
    entry_spot: float
    spot_sl: float
    spot_target: float
    spot_risk: float
    direction: str        # Always "PE"
    is_valid: bool
    skip_reason: str


def get_atm_strike(spot_price: float, step: int = None) -> int:
    """
    Deterministic nearest-strike rounding.
    Uses floor((spot + half_step) / step) * step to avoid
    Python's bankers rounding behavior.
    """
    if step is None:
        step = CONFIG["strike_step"]

    half_step = step // 2  # 25 for step=50
    atm = int((spot_price + half_step) // step) * step

    log_risk.debug(
        "🎯 ATM strike math: spot=%.2f, step=%d, half=%d -> ATM=%d",
        spot_price, step, half_step, atm,
    )
    return atm


def calculate_spot_risk(
    entry_spot: float,
    signal_candle_high: float,
) -> SpotRiskParams:
    """
    Calculate Spot-level SL, Target, and Risk.

    Rules (from locked specification):
        spot_sl     = signal_candle.high
        spot_risk   = spot_sl - entry_spot
        spot_target = entry_spot - spot_risk   (1:1 R:R in Spot points)
    """
    spot_sl = signal_candle_high
    spot_risk = spot_sl - entry_spot
    spot_target = entry_spot - spot_risk

    # Validation
    if entry_spot <= 0:
        reason = f"Invalid entry_spot={entry_spot}"
        log_risk.warning("⚠️ Risk validation FAILED: %s", reason)
        return SpotRiskParams(
            entry_spot=entry_spot, spot_sl=spot_sl,
            spot_target=spot_target, spot_risk=spot_risk,
            direction="PE", is_valid=False, skip_reason=reason,
        )

    if spot_risk <= 0:
        # entry_spot >= spot_sl -> gap through SL (D8: skip trade)
        reason = (
            f"ENTRY_SPOT_ABOVE_SL: entry_spot={entry_spot:.2f} >= "
            f"spot_sl={spot_sl:.2f} (spot_risk={spot_risk:.2f}). "
            f"Bearish thesis already invalidated."
        )
        log_risk.warning("⚠️ Risk validation FAILED: %s", reason)
        return SpotRiskParams(
            entry_spot=entry_spot, spot_sl=spot_sl,
            spot_target=spot_target, spot_risk=spot_risk,
            direction="PE", is_valid=False, skip_reason=reason,
        )

    if spot_target <= 0:
        reason = (
            f"Negative spot_target={spot_target:.2f} "
            f"(entry_spot={entry_spot:.2f}, spot_risk={spot_risk:.2f})"
        )
        log_risk.warning("⚠️ Risk validation FAILED: %s", reason)
        return SpotRiskParams(
            entry_spot=entry_spot, spot_sl=spot_sl,
            spot_target=spot_target, spot_risk=spot_risk,
            direction="PE", is_valid=False, skip_reason=reason,
        )

    # Max spot risk ceiling check (0 = disabled)
    max_spot_risk = CONFIG.get("max_spot_risk", 0)
    if max_spot_risk > 0 and spot_risk > max_spot_risk:
        reason = (
            f"SPOT_RISK_EXCEEDS_CAP: spot_risk={spot_risk:.2f} > "
            f"max_spot_risk={max_spot_risk:.2f}. Setup skipped."
        )
        log_risk.warning("⚠️ Risk validation FAILED: %s", reason)
        return SpotRiskParams(
            entry_spot=entry_spot, spot_sl=spot_sl,
            spot_target=spot_target, spot_risk=spot_risk,
            direction="PE", is_valid=False, skip_reason=reason,
        )

    log_risk.info(
        "🛡️ Spot risk calculated: entry=%.2f, SL=%.2f, target=%.2f, risk=%.2f pts (1:1 R:R in Spot points)",
        entry_spot, spot_sl, spot_target, spot_risk,
    )
    return SpotRiskParams(
        entry_spot=entry_spot, spot_sl=spot_sl,
        spot_target=spot_target, spot_risk=spot_risk,
        direction="PE", is_valid=True, skip_reason="",
    )