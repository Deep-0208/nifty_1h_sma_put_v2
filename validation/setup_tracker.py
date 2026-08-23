"""
═════════════════════════════════════════════════════════════
  SETUP TRACKER — Records 1H SMA PUT setups detected
═════════════════════════════════════════════════════════════

Captures all 1H candle pattern evaluations:
  • Red candle (close < open)
  • Close < SMA20
  • Close < SMA50
  • Spot SL (candle high) & Spot Target (1:1 Spot R:R)
  • ATM Strike
  • Trade taken / skip reason
"""

from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional, Dict, Any, List

from config import now_ist
from validation import storage


# ─────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────

SETUP_FIELDS: List[str] = [
    "setup_number", "date", "time", "direction",
    "spot_price", "atm_strike",
    "candle_time", "candle_open", "candle_high", "candle_low", "candle_close",
    "sma_20", "sma_50", "spot_sl", "spot_target", "spot_risk_pts",
    "pattern_valid", "trade_taken", "linked_trade_number", "skip_reason",
]


@dataclass
class SetupRecord:
    """A single 1H SMA PUT setup evaluated by the strategy."""
    setup_number: int
    date: str
    time: str
    direction: str                        # "BEARISH_PUT"
    spot_price: Optional[float]
    atm_strike: Optional[int]
    candle_time: str
    candle_open: float
    candle_high: float
    candle_low: float
    candle_close: float
    sma_20: Optional[float]
    sma_50: Optional[float]
    spot_sl: Optional[float]
    spot_target: Optional[float]
    spot_risk_pts: Optional[float]
    pattern_valid: str                    # "Yes" / "No"
    trade_taken: str = "No"               # "Yes" / "No"
    linked_trade_number: Optional[int] = None
    skip_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────
# TRACKER
# ─────────────────────────────────────────────

class SetupTracker:
    """Tracks and persists all setup detections to CSV."""

    def __init__(self, trading_date: date, counters: Dict[str, int]):
        self._trading_date = trading_date
        self._counters = counters
        self._daily_dir = storage.get_daily_dir(trading_date)
        self._csv_path = self._daily_dir / "setups.csv"

    def record(
        self,
        direction: str,
        spot_price: Optional[float],
        atm_strike: Optional[int],
        candle: Dict[str, Any],
        spot_sl: Optional[float],
        spot_target: Optional[float],
        spot_risk_pts: Optional[float],
        pattern_valid: bool,
        trade_taken: bool,
        skip_reason: Optional[str] = None,
        linked_trade_number: Optional[int] = None,
    ) -> int:
        """
        Record a setup and return its globally unique setup number.
        """
        now = now_ist()
        setup_num = self._counters["next_setup"]
        self._counters["next_setup"] += 1
        storage.save_counters(self._counters)

        c_time = candle.get("date", now)
        c_time_str = c_time.isoformat() if hasattr(c_time, "isoformat") else str(c_time)

        record = SetupRecord(
            setup_number=setup_num,
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"),
            direction=direction,
            spot_price=round(spot_price, 2) if spot_price is not None else None,
            atm_strike=atm_strike,
            candle_time=c_time_str,
            candle_open=round(candle.get("open", 0.0), 2),
            candle_high=round(candle.get("high", 0.0), 2),
            candle_low=round(candle.get("low", 0.0), 2),
            candle_close=round(candle.get("close", 0.0), 2),
            sma_20=round(candle.get("sma_20", 0.0), 2) if candle.get("sma_20") is not None else None,
            sma_50=round(candle.get("sma_50", 0.0), 2) if candle.get("sma_50") is not None else None,
            spot_sl=round(spot_sl, 2) if spot_sl is not None else None,
            spot_target=round(spot_target, 2) if spot_target is not None else None,
            spot_risk_pts=round(spot_risk_pts, 2) if spot_risk_pts is not None else None,
            pattern_valid="Yes" if pattern_valid else "No",
            trade_taken="Yes" if trade_taken else "No",
            linked_trade_number=linked_trade_number,
            skip_reason=skip_reason,
        )

        storage.append_csv(self._csv_path, record.to_dict(), SETUP_FIELDS)
        return setup_num

    def update_linked_trade(
        self,
        setup_number: int,
        trade_number: int,
    ) -> None:
        """Back-fill linked_trade_number after order confirmation."""
        rows = storage.read_csv(self._csv_path)
        updated = False
        for row in rows:
            if row.get("setup_number") == str(setup_number):
                row["linked_trade_number"] = str(trade_number)
                row["trade_taken"] = "Yes"
                updated = True
                break
        if updated and rows:
            storage.rewrite_csv(self._csv_path, rows, SETUP_FIELDS)