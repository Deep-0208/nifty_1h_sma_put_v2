"""
═════════════════════════════════════════════════════════════
  TRADE TRACKER — Records 1H SMA PUT strategy trades
═════════════════════════════════════════════════════════════

Two-phase recording:
  1. open_trade()  — called at entry, stores entry-side fields
  2. close_trade() — called at exit, completes the record

During the trade, update_ltp() tracks MFE and MAE on both
option premium and Spot levels.

P&L formula: (exit_premium - entry_premium) × quantity
"""

from datetime import date, datetime
from typing import Optional, Dict, Any, List

from config import now_ist
from validation import storage
from validation.utils import normalize_exit_reason, format_duration


# ─────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────

TRADE_FIELDS: List[str] = [
    "trade_number", "linked_setup_number", "date",
    "entry_time", "exit_time",
    "direction", "tradingsymbol", "strike", "expiry",
    "spot_price_at_entry", "spot_sl", "spot_target",
    "option_entry_premium", "quantity",
    "highest_premium_reached", "lowest_premium_after_entry",
    "exit_premium", "spot_price_at_exit",
    "exit_reason", "holding_time",
    "profit_loss", "winner_loser",
]


class TradeTracker:
    """Tracks trades with a two-phase open/close lifecycle."""

    def __init__(self, trading_date: date, counters: Dict[str, int]):
        self._trading_date = trading_date
        self._counters = counters
        self._daily_dir = storage.get_daily_dir(trading_date)
        self._csv_path = self._daily_dir / "trades.csv"

        # Active trade state (in-memory only, written to CSV at close)
        self._active: Optional[Dict[str, Any]] = None
        self._active_trade_num: Optional[int] = None
        self._highest_premium: Optional[float] = None
        self._lowest_premium: Optional[float] = None

    # ── Phase 1: Entry ────────────────────────────

    def open_trade(
        self,
        setup_num: int,
        direction: str,
        tradingsymbol: str,
        strike: float,
        expiry: str,
        spot_price: float,
        spot_sl: float,
        spot_target: float,
        entry_premium: float,
        qty: int,
    ) -> int:
        """
        Begin tracking a new trade. Returns the trade number.
        """
        trade_num = self._counters["next_trade"]
        self._counters["next_trade"] += 1
        storage.save_counters(self._counters)

        now = now_ist()
        self._active_trade_num = trade_num
        self._highest_premium = entry_premium
        self._lowest_premium = entry_premium

        self._active = {
            "trade_number": trade_num,
            "linked_setup_number": setup_num,
            "date": now.strftime("%Y-%m-%d"),
            "entry_time": now.isoformat(),
            "direction": direction,
            "tradingsymbol": tradingsymbol,
            "strike": round(strike, 2),
            "expiry": expiry,
            "spot_price_at_entry": round(spot_price, 2),
            "spot_sl": round(spot_sl, 2),
            "spot_target": round(spot_target, 2),
            "option_entry_premium": round(entry_premium, 2),
            "quantity": qty,
            "highest_premium_reached": round(entry_premium, 2),
            "lowest_premium_after_entry": round(entry_premium, 2),
        }
        return trade_num

    # ── Phase 2: Monitoring ───────────────────────

    def update_ltp(self, option_ltp: float) -> None:
        """Update MFE/MAE premium tracking during active trade."""
        if self._active is None:
            return

        if self._highest_premium is None or option_ltp > self._highest_premium:
            self._highest_premium = option_ltp
            self._active["highest_premium_reached"] = round(option_ltp, 2)

        if self._lowest_premium is None or option_ltp < self._lowest_premium:
            self._lowest_premium = option_ltp
            self._active["lowest_premium_after_entry"] = round(option_ltp, 2)

    # ── Phase 3: Exit ─────────────────────────────

    def close_trade(
        self,
        exit_premium: float,
        spot_price_at_exit: float,
        exit_reason: str,
        exit_time: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Complete the trade record, compute P&L, and flush to CSV.
        """
        if self._active is None:
            return None

        now = exit_time or now_ist()
        entry_time_str = self._active["entry_time"]
        entry_dt = datetime.fromisoformat(entry_time_str)
        duration = now - entry_dt

        entry_prem = self._active["option_entry_premium"]
        qty = self._active["quantity"]
        pnl = round((exit_premium - entry_prem) * qty, 2)
        winner_loser = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")

        self.update_ltp(exit_premium)

        self._active.update({
            "exit_time": now.isoformat(),
            "exit_premium": round(exit_premium, 2),
            "spot_price_at_exit": round(spot_price_at_exit, 2),
            "exit_reason": normalize_exit_reason(exit_reason),
            "holding_time": format_duration(duration),
            "profit_loss": pnl,
            "winner_loser": winner_loser,
        })

        completed_record = dict(self._active)
        storage.append_csv(self._csv_path, completed_record, TRADE_FIELDS)

        # Reset active state
        self._active = None
        self._active_trade_num = None
        self._highest_premium = None
        self._lowest_premium = None

        return completed_record