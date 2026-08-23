"""
═════════════════════════════════════════════════════════════
  UTILS — Utility functions for the Validation Engine
═════════════════════════════════════════════════════════════

Stateless helpers used across the validation module.
No side effects, no I/O — pure functions only.
"""

from datetime import timedelta
from typing import Optional


# ─────────────────────────────────────────────
# EXIT REASON NORMALIZATION
# ─────────────────────────────────────────────

EXIT_REASON_MAP = {
    "STOP_LOSS": "Stop Loss",
    "TARGET_HIT": "Target Hit",
    "SQUARE_OFF_1520": "MIS Square-off",
    "FORCE_SQUAREOFF_1520": "MIS Square-off",
    "CRASH_RECOVERY_SQUAREOFF": "Recovery Exit",
    "CRASH_DOWNTIME_EXCEEDED": "Downtime Exit",
}


def normalize_exit_reason(reason: str) -> str:
    """Map internal exit reason codes to human-readable labels."""
    return EXIT_REASON_MAP.get(reason, reason)


# ─────────────────────────────────────────────
# FORMATTING
# ─────────────────────────────────────────────

def format_duration(td: timedelta) -> str:
    """Convert a timedelta to a human-readable 'Xh Ym Zs' string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        return "0m 0s"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {seconds}s"


def format_currency(amount: float) -> str:
    """Format a number as Indian Rupee currency string."""
    if amount == 0:
        return "₹0.00"
    return f"₹{amount:+,.2f}"


# ─────────────────────────────────────────────
# MATH HELPERS
# ─────────────────────────────────────────────

def safe_divide(
    numerator: float,
    denominator: float,
    default: float = 0.0,
) -> float:
    """Safe division that returns *default* when denominator is zero."""
    if denominator == 0:
        return default
    return numerator / denominator