"""
config.py - NIFTY 1-Hour SMA PUT Strategy
All strategy parameters and logging setup.
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
    "expiry_preference": "weekly",
    # 0DTE is allowed per founder decision

    # Candle / timeframe
    "candle_tf": "60minute",
    "candle_tf_minutes": 60,

    # Indicators
    "sma_short": 20,
    "sma_long": 50,
    "sma_lookback_days": 20,

    # Risk management
    # No max_trades_per_day limit (founder decision: unlimited)
    # No max_spot_risk cap (founder decision: unlimited)
    "rr_ratio": 1.0,

    # Daily drawdown kill-switch (0 = disabled)
    "max_daily_loss": 0,

    # Market timings (IST)
    "market_open":    dtime(9, 15),
    "first_entry":    dtime(10, 15),
    "last_entry":     dtime(15, 15),
    "square_off_time": dtime(15, 20),
    "market_close":   dtime(15, 30),

    # Product type
    "product": "MIS",

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


# -- LOGGING SETUP --
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

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, CONFIG["log_level"], logging.INFO))
    ch.setFormatter(_make_formatter(include_module=False))
    root_logger.addHandler(ch)

    daily_log_dir = LOG_DIR / today
    daily_log_dir.mkdir(exist_ok=True)

    # Main strategy log (INFO+)
    _add_file_handler(root_logger, "strategy.log", daily_log_dir, level=logging.INFO, include_module=True)

    # Full debug log (DEBUG+)
    _add_file_handler(root_logger, "debug.log", daily_log_dir, level=logging.DEBUG, include_module=True)

    # Trade-only log
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

    # Network log (isolate 3rd-party HTTP/WS noise)
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
