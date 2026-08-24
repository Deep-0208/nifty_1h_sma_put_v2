"""
config.py - NIFTY 1-Hour SMA PUT Strategy
All strategy parameters and multi-channel logging setup.
No strategy logic lives here.
"""

import os
import logging
from datetime import datetime, date, time as dtime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv

# -- PATH SETUP --
STRATEGY_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = STRATEGY_DIR.parent
DOTENV_PATH = STRATEGY_DIR / ".env"
load_dotenv(DOTENV_PATH)

LOG_DIR = STRATEGY_DIR / "logs"
STATE_DIR = STRATEGY_DIR / "state"
LOG_DIR.mkdir(exist_ok=True)
STATE_DIR.mkdir(exist_ok=True)

# -- IST TIMEZONE --
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


# -- STRATEGY CONFIGURATION --
CONFIG = {
    # Instrument
    "nifty_instrument_token": 256265,

    # Lot size (verified dynamically at startup)
    "lot_size_default": 65,
    "num_lots": 1,

    # ATM strike resolution
    "strike_step": 50,

    # Expiry
    "expiry_preference": "monthly",
    "monthly_rollover_day": 20,       # Date > 20 switches to next month monthly expiry

    # Candle / timeframe
    "candle_tf": "60minute",
    "candle_tf_minutes": 60,

    # Indicators
    "sma_short": 20,
    "sma_long": 50,
    "sma_lookback_days": 20,

    # Risk management
    "max_trades_per_day": 5,          # Maximum trades allowed per day
    "rr_ratio": 1.0,

    # Daily drawdown kill-switch (0 = disabled)
    "max_daily_loss": 0,

    # Market timings (IST)
    "market_open":        dtime(9, 15),
    "first_entry":        dtime(10, 15),
    "last_entry":         dtime(15, 15),
    "expiry_force_exit":  dtime(15, 15),  # Mandatory exit ONLY on contract expiry day
    "square_off_time":    dtime(15, 15),  # Backwards compatibility alias for expiry force exit
    "market_close":       dtime(15, 30),

    # Product type (NRML for positional / carryforward)
    "product": "NRML",

    # Trading mode
    "trading_mode": "PAPER",

    # Virtual starting capital
    "starting_capital": 100000.0,

    # Monitoring intervals
    "candle_poll_interval_s": 30,
    "position_monitor_interval_s": 5,

    # WebSocket / data safety
    "ws_stale_threshold_s": 30,
    "data_unavailable_exit_s": 120,

    # Logging
    "log_level": "INFO",
    "log_max_bytes": 10 * 1024 * 1024,
    "log_backup_count": 10,
}


# ═══════════════════════════════════════════════
# LOGGING SETUP — Multi-channel strategy logging
# ═══════════════════════════════════════════════
#
# Daily directory: logs/YYYY-MM-DD/
#   strategy.log  — Main strategy flow (INFO+)
#   debug.log     — Full debug trace (DEBUG+)
#   trades.log    — Entries, exits, P&L only
#   candles.csv   — Closed 1H bars with SMA20/50 & pattern flags
#   network.log   — Network, HTTP & WebSocket logs
#
# Persistent cross-day ledger:
#   logs/journal.csv
# ═══════════════════════════════════════════════

LOGGER_NAME = "Nifty1HrSMA"


def _make_formatter(include_module: bool = False) -> logging.Formatter:
    if include_module:
        fmt = "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
    else:
        fmt = "%(asctime)s | %(levelname)-5s | %(message)s"
    return logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")


def _add_file_handler(
    logger: logging.Logger,
    filename: str,
    directory: Path,
    level: int = logging.DEBUG,
    include_module: bool = False,
) -> None:
    fh = RotatingFileHandler(
        directory / filename,
        maxBytes=CONFIG["log_max_bytes"],
        backupCount=CONFIG["log_backup_count"],
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(_make_formatter(include_module))
    logger.addHandler(fh)


def setup_logging() -> logging.Logger:
    root_logger = logging.getLogger(LOGGER_NAME)
    if root_logger.handlers:
        return root_logger

    root_logger.setLevel(logging.DEBUG)

    today = today_ist().isoformat()

    # 1. Console handler
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, CONFIG["log_level"], logging.INFO))
    ch.setFormatter(_make_formatter(include_module=False))
    root_logger.addHandler(ch)

    daily_log_dir = LOG_DIR / today
    daily_log_dir.mkdir(exist_ok=True)

    # 2. Main strategy log (INFO+)
    _add_file_handler(root_logger, "strategy.log", daily_log_dir, level=logging.INFO, include_module=True)

    # 3. Full debug log (DEBUG+)
    _add_file_handler(root_logger, "debug.log", daily_log_dir, level=logging.DEBUG, include_module=True)

    # 4. Trade-only log
    class TradeFilter(logging.Filter):
        def filter(self, record):
            return record.name == f"{LOGGER_NAME}.trades"

    trades_logger = logging.getLogger(f"{LOGGER_NAME}.trades")
    trades_fh = RotatingFileHandler(
        daily_log_dir / "trades.log",
        maxBytes=CONFIG["log_max_bytes"],
        backupCount=CONFIG["log_backup_count"],
        encoding="utf-8",
    )
    trades_fh.setLevel(logging.INFO)
    trades_fh.setFormatter(_make_formatter(include_module=True))
    trades_fh.addFilter(TradeFilter())
    trades_logger.addHandler(trades_fh)

    # 5. Dedicated Candle CSV log
    candles_logger = logging.getLogger(f"{LOGGER_NAME}.candles")
    candles_fh = logging.FileHandler(
        daily_log_dir / "candles.csv",
        mode="a",
        encoding="utf-8",
    )
    candles_fh.setLevel(logging.INFO)
    candles_fh.setFormatter(logging.Formatter("%(message)s"))
    candles_logger.addHandler(candles_fh)
    candles_logger.propagate = False

    # Write CSV header if file is new/empty
    candles_csv = daily_log_dir / "candles.csv"
    if not candles_csv.exists() or candles_csv.stat().st_size == 0:
        candles_logger.info(
            "timestamp,type,symbol,open,high,low,close,sma_20,sma_50,is_red,below_sma20,below_sma50"
        )

    # 6. Network log (isolate 3rd-party HTTP/WS noise)
    network_logger = logging.getLogger(f"{LOGGER_NAME}.network")
    _add_file_handler(network_logger, "network.log", daily_log_dir, level=logging.DEBUG, include_module=True)
    network_logger.propagate = False

    # Redirect urllib3/requests/kiteconnect.ticker logs to network logger
    for noisy_name in ("urllib3", "requests", "kiteconnect.ticker"):
        noisy = logging.getLogger(noisy_name)
        noisy.handlers.clear()
        noisy.propagate = False
        _add_file_handler(noisy, "network.log", daily_log_dir, level=logging.DEBUG, include_module=True)

    return root_logger


# -- Initialize logging on import --
log = setup_logging()

# -- Named sub-loggers --
log_pattern = logging.getLogger(f"{LOGGER_NAME}.pattern")
log_risk    = logging.getLogger(f"{LOGGER_NAME}.risk")
log_orders  = logging.getLogger(f"{LOGGER_NAME}.orders")
log_data    = logging.getLogger(f"{LOGGER_NAME}.data")
log_trades  = logging.getLogger(f"{LOGGER_NAME}.trades")
log_candles = logging.getLogger(f"{LOGGER_NAME}.candles")