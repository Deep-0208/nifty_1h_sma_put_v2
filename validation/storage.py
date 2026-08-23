"""
═════════════════════════════════════════════════════════════
  STORAGE — File I/O for the Validation Engine
═════════════════════════════════════════════════════════════

Handles directory creation, CSV/JSON/text file operations,
global counter persistence, and daily data aggregation.

All data is stored under:  <strategy_dir>/validation/data/
All logs are stored under: <strategy_dir>/validation/logs/
"""

import csv
import json
from datetime import date
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import STRATEGY_DIR


# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

VALIDATION_DIR = STRATEGY_DIR / "validation"
DATA_DIR = VALIDATION_DIR / "data"
MONTHLY_DIR = DATA_DIR / "monthly"
LOG_DIR = VALIDATION_DIR / "logs"
COUNTER_FILE = DATA_DIR / "counters.json"


def get_daily_dir(trading_date: date) -> Path:
    """Return the daily data directory, creating it if needed."""
    daily = DATA_DIR / trading_date.isoformat()
    daily.mkdir(parents=True, exist_ok=True)
    return daily


def ensure_dirs() -> None:
    """Create all required directories."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# GLOBAL COUNTERS (persist across days)
# ─────────────────────────────────────────────

def load_counters() -> Dict[str, int]:
    """Load global sequential counters from disk."""
    if COUNTER_FILE.exists():
        try:
            data = json.loads(COUNTER_FILE.read_text(encoding="utf-8"))
            return {
                "next_setup": data.get("next_setup", 1),
                "next_trade": data.get("next_trade", 1),
                "next_decision": data.get("next_decision", 1),
            }
        except Exception:
            pass
    return {"next_setup": 1, "next_trade": 1, "next_decision": 1}


def save_counters(counters: Dict[str, int]) -> None:
    """Persist global sequential counters to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COUNTER_FILE.write_text(
        json.dumps(counters, indent=2),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────
# CSV OPERATIONS
# ─────────────────────────────────────────────

def append_csv(
    filepath: Path,
    row: Dict[str, Any],
    fieldnames: List[str],
) -> None:
    """Append a single row to a CSV file, writing header if file is new."""
    is_new = not filepath.exists() or filepath.stat().st_size == 0
    with filepath.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, extrasaction="ignore",
        )
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def read_csv(filepath: Path) -> List[Dict[str, str]]:
    """Read all rows from a CSV file as a list of dicts."""
    if not filepath.exists():
        return []
    with filepath.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rewrite_csv(
    filepath: Path,
    rows: List[Dict[str, Any]],
    fieldnames: List[str],
) -> None:
    """Overwrite a CSV file with the provided rows."""
    with filepath.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


# ─────────────────────────────────────────────
# JSON OPERATIONS
# ─────────────────────────────────────────────

def write_json(filepath: Path, data: Any) -> None:
    """Write data to a JSON file (indented, UTF-8)."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(
        json.dumps(data, indent=2, default=str),
        encoding="utf-8",
    )


def read_json(filepath: Path) -> Optional[Any]:
    """Read and parse a JSON file, returning None on failure."""
    if not filepath.exists():
        return None
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except Exception:
        return None


# ─────────────────────────────────────────────
# TEXT OPERATIONS
# ─────────────────────────────────────────────

def write_text(filepath: Path, content: str) -> None:
    """Write text content to a file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")


def read_text(filepath: Path) -> Optional[str]:
    """Read text content from a file, returning None if missing."""
    if not filepath.exists():
        return None
    try:
        return filepath.read_text(encoding="utf-8")
    except Exception:
        return None