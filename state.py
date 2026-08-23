"""
state.py - Atomic State Persistence & Crash Recovery
Ported from nifty_4hr_reversal/state.py.
Crash-safe JSON state with tempfile + os.replace().
"""

import os
import csv
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from config import STATE_DIR, LOG_DIR, IST, now_ist, today_ist, log

STATE_FILE = STATE_DIR / "state_active.json"
JOURNAL_FILE = LOG_DIR / "journal.csv"

JOURNAL_HEADERS = [
    "date", "entry_time", "exit_time", "direction", "tradingsymbol",
    "strike", "expiry", "qty", "entry_premium", "exit_premium",
    "entry_spot", "spot_sl", "spot_target", "spot_risk",
    "gross_pnl", "exit_reason",
]


def fresh_state() -> Dict[str, Any]:
    """Return a clean default state dict."""
    return {
        "date": today_ist().isoformat(),
        "trades_today": 0,
        "in_position": False,
        "current_position": None,
        "realized_pnl_today": 0.0,
        "total_realized_pnl": 0.0,
        "cash": 0.0,
        "last_signal_candle_time": None,
    }


def fresh_position() -> Dict[str, Any]:
    """Return a clean default position dict."""
    return {
        "direction": "PE",
        "tradingsymbol": "",
        "instrument_token": 0,
        "qty": 0,
        "strike": 0,
        "expiry": "",
        "entry_order_id": "",
        "entry_premium": 0.0,
        "entry_spot": 0.0,
        "spot_sl": 0.0,
        "spot_target": 0.0,
        "spot_risk": 0.0,
        "entry_time": "",
        "entry_date": "",
        "last_heartbeat": "",
    }


def load_state() -> Dict[str, Any]:
    """
    Load state from disk.
    If state file is missing or corrupt, return fresh_state().
    If the date has changed, reset daily counters but preserve cumulative fields.
    """
    defaults = fresh_state()

    if not STATE_FILE.exists():
        log.info("No existing state file found. Starting fresh.")
        return defaults

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log.warning(f"Corrupt state file, starting fresh: {e}")
        return defaults

    # Merge missing keys from defaults
    for key, val in defaults.items():
        if key not in state:
            state[key] = val

    # Day rollover: reset daily counters
    if state.get("date") != today_ist().isoformat():
        log.info(
            f"Date rollover: {state.get('date')} -> {today_ist().isoformat()}. "
            f"Resetting daily counters."
        )
        state["date"] = today_ist().isoformat()
        state["trades_today"] = 0
        state["realized_pnl_today"] = 0.0
        # Preserve: total_realized_pnl, cash, in_position, current_position

    return state


def save_state(state: Dict[str, Any]) -> None:
    """
    Atomically save state to disk.
    Write to temp file first, then os.replace() for crash safety.
    """
    STATE_DIR.mkdir(exist_ok=True)

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(STATE_DIR), suffix=".tmp", prefix="state_"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)

        os.replace(tmp_path, str(STATE_FILE))

    except Exception as e:
        log.error(f"CRITICAL: Failed to save state: {e}")
        # Try to clean up temp file
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass
        raise


def append_trade_journal(row: Dict[str, Any]) -> None:
    """
    Append a trade record to the persistent journal CSV.
    Creates the file with headers if it doesn't exist.
    """
    LOG_DIR.mkdir(exist_ok=True)

    file_exists = JOURNAL_FILE.exists()

    try:
        with open(JOURNAL_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=JOURNAL_HEADERS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        log.error(f"Failed to append to trade journal: {e}")