"""
state.py - Atomic State Persistence & Crash Recovery
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
    """Load state from disk."""
    defaults = fresh_state()

    if not STATE_FILE.exists():
        log.info("📂 No existing state file found. Starting fresh.")
        return defaults

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log.warning("⚠️ Corrupt state file, starting fresh: %s", e)
        return defaults

    # Merge missing keys from defaults
    for key, val in defaults.items():
        if key not in state:
            state[key] = val

    # Day rollover: reset daily counters
    if state.get("date") != today_ist().isoformat():
        log.info(
            "🌅 Date rollover: %s -> %s. Resetting daily counters.",
            state.get('date'), today_ist().isoformat(),
        )
        state["date"] = today_ist().isoformat()
        state["trades_today"] = 0
        state["realized_pnl_today"] = 0.0

    return state


def save_state(state: Dict[str, Any]) -> None:
    """Atomic write: write to temp file then rename."""
    STATE_DIR.mkdir(exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(STATE_DIR),
            delete=False,
            encoding="utf-8",
            suffix=".tmp",
        ) as f:
            json.dump(state, f, indent=2)
            tmp_path = f.name

        os.replace(tmp_path, str(STATE_FILE))
    except Exception as e:
        log.error("❌ Failed to save state atomically: %s", e)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def append_trade_journal(record: Dict[str, Any]) -> None:
    """Append completed trade to logs/journal.csv."""
    LOG_DIR.mkdir(exist_ok=True)
    write_header = not JOURNAL_FILE.exists() or JOURNAL_FILE.stat().st_size == 0

    try:
        with open(JOURNAL_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=JOURNAL_HEADERS)
            if write_header:
                writer.writeheader()
            writer.writerow({k: record.get(k, "") for k in JOURNAL_HEADERS})
        log.info(
            "📖 Trade appended to journal: %s | P&L: ₹%+.2f",
            record.get("tradingsymbol", "?"), record.get("gross_pnl", 0.0),
        )
    except Exception as e:
        log.error("❌ Failed to write trade journal: %s", e)