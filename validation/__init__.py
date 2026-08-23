"""
═════════════════════════════════════════════════════════════
  VALIDATION ENGINE — Strategy Validation & Trade Analytics
═════════════════════════════════════════════════════════════

Lightweight analytics layer for the NIFTY 1-Hour SMA PUT Strategy.
Records every setup, trade, and decision during paper trading
validation, and generates daily/monthly reports.

Usage (from strategy code):
    from validation import AnalyticsEngine

    engine = AnalyticsEngine(trading_date, opening_capital)
    engine.record_setup(...)
    engine.record_trade_entry(...)
    engine.record_trade_exit(...)
    engine.generate_daily_summary(closing_capital)

Manual report generation (from project root):
    python -m validation.report_generator
"""

from validation.analytics import AnalyticsEngine

__all__ = ["AnalyticsEngine"]