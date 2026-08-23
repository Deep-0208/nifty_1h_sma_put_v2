"""
═════════════════════════════════════════════════════════════
  ANALYTICS — Main Facade for the Validation Engine
═════════════════════════════════════════════════════════════

Single entry point for the strategy to interact with the
validation engine. The strategy imports only this class:

    from validation import AnalyticsEngine

Every public method is wrapped in try/except so that a failure
in the analytics layer can NEVER crash or disrupt trading execution.
"""

import logging
from datetime import date, datetime
from typing import Optional, Dict, Any

from config import CONFIG, now_ist, STRATEGY_DIR
from validation import storage
from validation.setup_tracker import SetupTracker
from validation.trade_tracker import TradeTracker
from validation.decision_tracker import DecisionTracker
from validation.utils import normalize_exit_reason, format_currency


STRATEGY_VERSION = "1.0.0"


class AnalyticsEngine:
    """
    Central facade for Strategy Validation & Trade Analytics.
    Interacts with trackers and handles daily/monthly aggregation.
    """

    def __init__(self, trading_date: date, opening_capital: float):
        self.trading_date = trading_date
        self.opening_capital = opening_capital
        self._start_time = now_ist()

        # Ensure directory structure
        storage.ensure_dirs()
        self._log = self._setup_logger()

        # Global sequential counters
        self._counters = storage.load_counters()

        # Trackers
        self.setup_tracker = SetupTracker(trading_date, self._counters)
        self.trade_tracker = TradeTracker(trading_date, self._counters)
        self.decision_tracker = DecisionTracker(trading_date, self._counters)

        # Write runtime and config snapshots
        self._write_runtime(completed=False)
        self._write_config_snapshot()

        self._log.info(
            "Validation Engine initialized | Date=%s | Capital=%s | Version=%s",
            trading_date, format_currency(opening_capital), STRATEGY_VERSION,
        )

    # ── Setup Recording ───────────────────────────

    def record_setup(
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
    ) -> int:
        """Record a setup detection and emit associated decisions."""
        try:
            setup_num = self.setup_tracker.record(
                direction=direction,
                spot_price=spot_price,
                atm_strike=atm_strike,
                candle=candle,
                spot_sl=spot_sl,
                spot_target=spot_target,
                spot_risk_pts=spot_risk_pts,
                pattern_valid=pattern_valid,
                trade_taken=trade_taken,
                skip_reason=skip_reason,
            )

            # Record decision
            msg = f"Setup #{setup_num}: {direction}"
            if spot_price is not None:
                msg += f" at spot {spot_price:.2f}"
            self.decision_tracker.record(
                event=f"{direction} Setup Detected",
                module="pattern",
                message=msg,
                setup_num=setup_num,
            )

            if not trade_taken and skip_reason:
                self.decision_tracker.record(
                    event="Trade Skipped",
                    module="main",
                    message=f"Setup #{setup_num} skipped: {skip_reason}",
                    setup_num=setup_num,
                )

            self._log.info(
                "Setup #%d | %s | Valid=%s | Taken=%s%s",
                setup_num, direction, pattern_valid, trade_taken,
                f" | Skip: {skip_reason}" if skip_reason else "",
            )
            return setup_num

        except Exception as e:
            self._log.error("Failed to record setup: %s", e)
            return -1

    # ── Trade Recording ───────────────────────────

    def record_trade_entry(
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
        """Record a trade entry."""
        try:
            trade_num = self.trade_tracker.open_trade(
                setup_num=setup_num,
                direction=direction,
                tradingsymbol=tradingsymbol,
                strike=strike,
                expiry=expiry,
                spot_price=spot_price,
                spot_sl=spot_sl,
                spot_target=spot_target,
                entry_premium=entry_premium,
                qty=qty,
            )

            # Link back to setup
            if setup_num > 0:
                self.setup_tracker.update_linked_trade(setup_num, trade_num)

            # Record decision
            self.decision_tracker.record(
                event="Trade Executed",
                module="orders",
                message=(
                    f"Trade #{trade_num} ENTERED: {tradingsymbol} @ ₹{entry_premium:.2f} "
                    f"(Qty: {qty}, Spot: {spot_price:.2f}, SL: {spot_sl:.2f}, Target: {spot_target:.2f})"
                ),
                setup_num=setup_num if setup_num > 0 else None,
                trade_num=trade_num,
            )

            self._log.info(
                "Trade #%d OPENED: %s @ ₹%.2f (Qty: %d)",
                trade_num, tradingsymbol, entry_premium, qty,
            )
            return trade_num

        except Exception as e:
            self._log.error("Failed to record trade entry: %s", e)
            return -1

    def update_ltp(self, option_ltp: float) -> None:
        """Update active position premium tracking."""
        try:
            self.trade_tracker.update_ltp(option_ltp)
        except Exception as e:
            self._log.debug("Failed to update LTP: %s", e)

    def record_trade_exit(
        self,
        exit_premium: float,
        spot_price_at_exit: float,
        exit_reason: str,
        exit_time: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record a trade exit."""
        try:
            rec = self.trade_tracker.close_trade(
                exit_premium=exit_premium,
                spot_price_at_exit=spot_price_at_exit,
                exit_reason=exit_reason,
                exit_time=exit_time,
            )
            if rec:
                trade_num = rec["trade_number"]
                pnl = rec["profit_loss"]
                self.decision_tracker.record(
                    event=f"Trade Exited: {rec['exit_reason']}",
                    module="orders",
                    message=(
                        f"Trade #{trade_num} EXITED @ ₹{exit_premium:.2f} "
                        f"(Spot: {spot_price_at_exit:.2f}, P&L: {format_currency(pnl)}, "
                        f"Duration: {rec['holding_time']})"
                    ),
                    trade_num=trade_num,
                )
                self._log.info(
                    "Trade #%d CLOSED: Exit=₹%.2f | Reason=%s | P&L=%s",
                    trade_num, exit_premium, rec["exit_reason"], format_currency(pnl),
                )
            return rec
        except Exception as e:
            self._log.error("Failed to record trade exit: %s", e)
            return None

    def record_decision(
        self,
        event: str,
        module: str,
        message: str,
        setup_num: Optional[int] = None,
        trade_num: Optional[int] = None,
    ) -> int:
        """Record an arbitrary strategy decision."""
        try:
            return self.decision_tracker.record(
                event=event, module=module, message=message,
                setup_num=setup_num, trade_num=trade_num,
            )
        except Exception as e:
            self._log.error("Failed to record decision: %s", e)
            return -1

    # ── Daily Summary & Close ─────────────────────

    def generate_daily_summary(self, closing_capital: float) -> Optional[Dict[str, Any]]:
        """Generate daily summary JSON, CSV, and markdown."""
        try:
            from validation.report_generator import DailySummaryGenerator
            gen = DailySummaryGenerator(self.trading_date)
            summary = gen.generate(self.opening_capital, closing_capital)
            self._write_runtime(completed=True)
            self._log.info(
                "Daily summary generated for %s | Net P&L=%s",
                self.trading_date, format_currency(summary.get("net_pnl", 0.0)),
            )
            return summary
        except Exception as e:
            self._log.error("Failed to generate daily summary: %s", e)
            return None

    # ── Helpers ───────────────────────────────────

    def _setup_logger(self) -> logging.Logger:
        """Create dedicated logger writing to validation/logs/."""
        logger = logging.getLogger("Nifty1HrSMA.validation")
        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            fh = logging.FileHandler(
                storage.LOG_DIR / "validation.log",
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-5s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        return logger

    def _write_runtime(self, completed: bool) -> None:
        """Write session runtime metadata."""
        now = now_ist()
        runtime_data = {
            "trading_date": self.trading_date.isoformat(),
            "strategy": "NIFTY 1-Hour SMA PUT Strategy",
            "version": STRATEGY_VERSION,
            "mode": CONFIG["trading_mode"],
            "start_time": self._start_time.isoformat(),
            "last_updated": now.isoformat(),
            "completed": completed,
        }
        daily_dir = storage.get_daily_dir(self.trading_date)
        storage.write_json(daily_dir / "runtime.json", runtime_data)

    def _write_config_snapshot(self) -> None:
        """Save a snapshot of strategy configuration."""
        clean_config = {}
        for k, v in CONFIG.items():
            if isinstance(v, (str, int, float, bool, list)):
                clean_config[k] = v
            elif hasattr(v, "isoformat"):
                clean_config[k] = v.isoformat()
            else:
                clean_config[k] = str(v)
        daily_dir = storage.get_daily_dir(self.trading_date)
        storage.write_json(daily_dir / "config_snapshot.json", clean_config)