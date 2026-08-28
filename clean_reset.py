"""
clean_reset.py - Reset state, remove test entries from journal and validation, and ensure clean baseline.
"""

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 1. Reset state
state = {
    "date": "2026-08-28",
    "trades_today": 0,
    "in_position": False,
    "current_position": None,
    "realized_pnl_today": 0.0,
    "total_realized_pnl": -2492.75,
    "cash": 97507.25,
    "last_signal_candle_time": None,
}

state_path = BASE_DIR / "state" / "state_active.json"
state_path.parent.mkdir(exist_ok=True)
with open(state_path, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2)
print("✓ state_active.json reset to clean baseline (in_position=False, trades_today=0)")

# 2. Clean journal.csv (remove test mock trade)
journal_lines = [
    "date,entry_time,exit_time,direction,tradingsymbol,strike,expiry,qty,entry_premium,exit_premium,entry_spot,spot_sl,spot_target,spot_risk,gross_pnl,exit_reason\n",
    "2026-08-24,2026-08-24T13:15:11.536863+05:30,2026-08-24T15:20:12.112671+05:30,PE,NIFTY26AUG24150PE,24150.0,2026-08-25,65,46.4,37.3,24167.3,24199.55,24135.05,32.25,-591.5,SQUARE_OFF_1520\n",
    "2026-08-25,2026-08-25T13:35:36.262910+05:30,2026-08-25T14:29:02.307929+05:30,PE,NIFTY26SEP24150PE,24150.0,2026-09-29,65,227.0,197.75,24129.35,24181,24077.699999999997,51.650000000001455,-1901.25,STOP_LOSS\n",
]

journal_path = BASE_DIR / "logs" / "journal.csv"
journal_path.parent.mkdir(exist_ok=True)
with open(journal_path, "w", encoding="utf-8") as f:
    f.writelines(journal_lines)
print("✓ journal.csv cleaned (removed test entries)")

# 3. Clean trades.log for today
trades_log_path = BASE_DIR / "logs" / "2026-08-28" / "trades.log"
if trades_log_path.exists():
    with open(trades_log_path, "w", encoding="utf-8") as f:
        f.truncate(0)
    print("✓ logs/2026-08-28/trades.log cleared")

print("Reset completed successfully.")
