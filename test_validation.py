"""
test_validation.py - Test Suite for Validation Engine (Isolated)
NIFTY 1-Hour SMA PUT Strategy
"""

import sys
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
import pandas as pd

from validation import AnalyticsEngine
from validation import storage, metrics
from validation.report_generator import DailySummaryGenerator, MonthlyReportGenerator

def test_validation_engine_lifecycle():
    print("\n--- Testing Validation Engine Lifecycle ---")
    
    # Use temporary isolated directory for tests
    temp_dir = Path(tempfile.mkdtemp())
    orig_data_dir = storage.DATA_DIR
    orig_monthly_dir = storage.MONTHLY_DIR
    orig_log_dir = storage.LOG_DIR
    orig_counter_file = storage.COUNTER_FILE
    
    try:
        storage.DATA_DIR = temp_dir / "data"
        storage.MONTHLY_DIR = storage.DATA_DIR / "monthly"
        storage.LOG_DIR = temp_dir / "logs"
        storage.COUNTER_FILE = storage.DATA_DIR / "counters.json"
        storage.ensure_dirs()
        
        today = date(2026, 8, 23)
        opening_capital = 100000.0

        engine = AnalyticsEngine(today, opening_capital)
        assert engine is not None, "Engine initialization failed"

        # 1. Record a setup
        candle = {
            "open": 24600.0, "high": 24620.0, "low": 24480.0, "close": 24500.0,
            "sma_20": 24550.0, "sma_50": 24580.0, "date": datetime(2026, 8, 23, 10, 15),
        }
        setup_num = engine.record_setup(
            direction="BEARISH_PUT",
            spot_price=24500.0,
            atm_strike=24500,
            candle=candle,
            spot_sl=24620.0,
            spot_target=24380.0,
            spot_risk_pts=120.0,
            pattern_valid=True,
            trade_taken=True,
        )
        assert setup_num > 0, f"Expected setup_num > 0, got {setup_num}"
        print(f"  PASS: Setup #{setup_num} recorded")

        # 2. Record trade entry
        trade_num = engine.record_trade_entry(
            setup_num=setup_num,
            direction="PE",
            tradingsymbol="NIFTY26AUG24500PE",
            strike=24500.0,
            expiry="2026-08-25",
            spot_price=24500.0,
            spot_sl=24620.0,
            spot_target=24380.0,
            entry_premium=130.0,
            qty=65,
        )
        assert trade_num > 0, f"Expected trade_num > 0, got {trade_num}"
        print(f"  PASS: Trade #{trade_num} entry recorded")

        # 3. Update LTP
        engine.update_ltp(155.0)
        engine.update_ltp(120.0)
        engine.update_ltp(180.0)
        print("  PASS: LTP tracking updated (MFE/MAE)")

        # 4. Record trade exit
        exit_rec = engine.record_trade_exit(
            exit_premium=180.0,
            spot_price_at_exit=24380.0,
            exit_reason="TARGET_HIT",
        )
        assert exit_rec is not None, "Expected completed trade record"
        assert exit_rec["profit_loss"] == (180.0 - 130.0) * 65, f"P&L mismatch: {exit_rec['profit_loss']}"
        assert exit_rec["winner_loser"] == "WIN"
        print(f"  PASS: Trade #{trade_num} exit recorded | P&L: {exit_rec['profit_loss']}")

        # 5. Generate daily summary
        closing_capital = opening_capital + exit_rec["profit_loss"]
        summary = engine.generate_daily_summary(closing_capital)
        assert summary is not None, "Summary generation failed"
        assert summary["net_pnl"] == 3250.0, f"Expected 3250.0, got {summary['net_pnl']}"
        print(f"  PASS: Daily summary generated | Net P&L: {summary['net_pnl']}")

        # 6. Generate monthly report
        m_gen = MonthlyReportGenerator("2026-08")
        m_report = m_gen.generate()
        assert m_report is not None, "Monthly report generation failed"
        print("  PASS: Monthly validation report generated successfully")

        print("\nALL VALIDATION ENGINE TESTS PASSED!")

    finally:
        storage.DATA_DIR = orig_data_dir
        storage.MONTHLY_DIR = orig_monthly_dir
        storage.LOG_DIR = orig_log_dir
        storage.COUNTER_FILE = orig_counter_file
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    test_validation_engine_lifecycle()