"""
═════════════════════════════════════════════════════════════
  DECISION TRACKER — Records strategy state transitions
═════════════════════════════════════════════════════════════

Logs every significant algorithmic decision made by the strategy:
  • Setup detection
  • Trade entry / skip
  • SL / Target hits
  • Trailing adjustments
  • MIS 15:20 square-off
  • Risk limit blocks (daily loss limit, max trades)
"""

from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional, Dict, Any, List

from config import now_ist
from validation import storage


DECISION_FIELDS: List[str] = [
    "decision_number", "date", "time", "module",
    "event", "message", "setup_number", "trade_number",
]


@dataclass
class DecisionRecord:
    """A single decision / event recorded by the strategy."""
    decision_number: int
    date: str
    time: str
    module: str
    event: str
    message: str
    setup_number: Optional[int] = None
    trade_number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DecisionTracker:
    """Tracks and persists all strategy decisions to CSV."""

    def __init__(self, trading_date: date, counters: Dict[str, int]):
        self._trading_date = trading_date
        self._counters = counters
        self._daily_dir = storage.get_daily_dir(trading_date)
        self._csv_path = self._daily_dir / "decisions.csv"

    def record(
        self,
        event: str,
        module: str,
        message: str,
        setup_num: Optional[int] = None,
        trade_num: Optional[int] = None,
    ) -> int:
        """Record a strategy decision and return its unique number."""
        now = now_ist()
        decision_num = self._counters["next_decision"]
        self._counters["next_decision"] += 1
        storage.save_counters(self._counters)

        record = DecisionRecord(
            decision_number=decision_num,
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"),
            module=module,
            event=event,
            message=message,
            setup_number=setup_num,
            trade_number=trade_num,
        )

        storage.append_csv(self._csv_path, record.to_dict(), DECISION_FIELDS)
        return decision_num