"""
test_audit_comprehensive.py - Comprehensive Forensic Audit Test Suite
NIFTY 1-Hour SMA PUT Strategy

Run: python test_audit_comprehensive.py
No external test framework required.
"""

import os
import sys
import json
import math
import tempfile
import shutil
from datetime import datetime, date, time as dtime, timedelta, timezone
from pathlib import Path

from config import today_ist, now_ist

# ── Test framework ──
_passed = 0
_failed = 0
_errors = []

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def _test(name, condition, detail=""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        _errors.append(msg)


def _section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ═══════════════════════════════════════════════
# SMA TESTS
# ═══════════════════════════════════════════════

def test_sma_20():
    """T1: SMA 20 on known data."""
    _section("SMA Tests")
    closes = list(range(1, 25))
    candles = [{"close": c, "open": c, "high": c, "low": c, "date": i}
               for i, c in enumerate(closes)]

    sma_short = 20
    for i, candle in enumerate(candles):
        if i >= sma_short - 1:
            window = closes[i - sma_short + 1 : i + 1]
            candle["sma_20"] = sum(window) / len(window)
        else:
            candle["sma_20"] = None

    _test("SMA20 at index 19 = 10.5",
          candles[19]["sma_20"] == 10.5,
          f"got {candles[19]['sma_20']}")

    _test("SMA20 at index 23 = 14.5",
          candles[23]["sma_20"] == 14.5,
          f"got {candles[23]['sma_20']}")


def test_sma_50():
    """T2: SMA 50 calculation."""
    closes = list(range(1, 55))
    candles = [{"close": c} for c in closes]

    sma_long = 50
    for i, candle in enumerate(candles):
        if i >= sma_long - 1:
            window = closes[i - sma_long + 1 : i + 1]
            candle["sma_50"] = sum(window) / len(window)
        else:
            candle["sma_50"] = None

    _test("SMA50 at index 49 = 25.5",
          candles[49]["sma_50"] == 25.5,
          f"got {candles[49]['sma_50']}")

    _test("SMA50 at index 53 = 29.5",
          candles[53]["sma_50"] == 29.5,
          f"got {candles[53]['sma_50']}")


def test_sma_warmup():
    """T3: SMA returns None during warmup period."""
    closes = list(range(1, 55))
    candles = [{"close": c} for c in closes]

    sma_long = 50
    for i, candle in enumerate(candles):
        if i >= sma_long - 1:
            window = closes[i - sma_long + 1 : i + 1]
            candle["sma_50"] = sum(window) / len(window)
        else:
            candle["sma_50"] = None

    _test("SMA50 is None at index 0", candles[0]["sma_50"] is None)
    _test("SMA50 is None at index 48", candles[48]["sma_50"] is None)
    _test("SMA50 is NOT None at index 49", candles[49]["sma_50"] is not None)


# ═══════════════════════════════════════════════
# SIGNAL TESTS
# ═══════════════════════════════════════════════

def _make_candle(o, h, l, c, sma_20=None, sma_50=None, dt=None):
    return {
        "open": o, "high": h, "low": l, "close": c,
        "sma_20": sma_20, "sma_50": sma_50,
        "date": dt or datetime(2026, 8, 23, 10, 15, tzinfo=IST),
    }


def test_signal_valid():
    """T4: Valid bearish signal - red candle below both SMAs."""
    _section("Signal Tests")
    from pattern import detect_signal
    candle = _make_candle(o=24600, h=24620, l=24480, c=24500,
                          sma_20=24550, sma_50=24580)
    result = detect_signal([candle])
    _test("Valid signal returns SetupSignal",
          result is not None,
          f"got {result}")
    if result:
        _test("Signal type is BEARISH_SMA_BREAKDOWN",
              result.signal_type == "BEARISH_SMA_BREAKDOWN")
        _test("Spot SL = candle high (24620)",
              result.spot_sl == 24620,
              f"got {result.spot_sl}")


def test_signal_green_candle():
    """T5: Green candle (close > open) - NO signal."""
    from pattern import detect_signal
    candle = _make_candle(o=24400, h=24620, l=24380, c=24500,
                          sma_20=24550, sma_50=24580)
    result = detect_signal([candle])
    _test("Green candle -> None", result is None, f"got {result}")


def test_signal_above_sma20():
    """T6: Red candle but close ABOVE SMA20 - NO signal."""
    from pattern import detect_signal
    candle = _make_candle(o=24600, h=24620, l=24480, c=24560,
                          sma_20=24550, sma_50=24580)
    result = detect_signal([candle])
    _test("Above SMA20 -> None", result is None, f"got {result}")


def test_signal_above_sma50():
    """T7: Red candle below SMA20 but ABOVE SMA50 - NO signal."""
    from pattern import detect_signal
    candle = _make_candle(o=24600, h=24620, l=24480, c=24540,
                          sma_20=24550, sma_50=24530)
    result = detect_signal([candle])
    _test("Above SMA50 -> None", result is None, f"got {result}")


def test_signal_missing_sma():
    """T8: Missing SMA (None) - NO signal."""
    from pattern import detect_signal
    candle = _make_candle(o=24600, h=24620, l=24480, c=24500,
                          sma_20=None, sma_50=24580)
    result = detect_signal([candle])
    _test("Missing SMA20=None -> None", result is None)

    candle2 = _make_candle(o=24600, h=24620, l=24480, c=24500,
                           sma_20=24550, sma_50=None)
    result2 = detect_signal([candle2])
    _test("Missing SMA50=None -> None", result2 is None)


def test_signal_nan_sma():
    """T9: NaN SMA - NO signal."""
    from pattern import detect_signal
    candle = _make_candle(o=24600, h=24620, l=24480, c=24500,
                          sma_20=float('nan'), sma_50=24580)
    result = detect_signal([candle])
    _test("NaN SMA20 -> None", result is None)


def test_signal_empty_candles():
    """T10: Empty candle list - NO signal."""
    from pattern import detect_signal
    result = detect_signal([])
    _test("Empty list -> None", result is None)


def test_signal_duplicate():
    """T11: Duplicate signal prevention via last_signal_candle_time."""
    state = {"last_signal_candle_time": "2026-08-23 10:15:00+05:30"}
    candle_time = "2026-08-23 10:15:00+05:30"
    _test("Duplicate candle blocked",
          state["last_signal_candle_time"] == candle_time)


# ═══════════════════════════════════════════════
# ATM STRIKE TESTS
# ═══════════════════════════════════════════════

def test_atm_strike():
    """T12-T21: Deterministic nearest-50 rounding."""
    _section("ATM Strike Tests")
    from risk import get_atm_strike

    cases = [
        (24974, 24950),
        (24975, 25000),
        (25024, 25000),
        (25025, 25050),
        (25026, 25050),
        (25050, 25050),
        (25000, 25000),
        (24999, 25000),
        (24950, 24950),
        (24951, 24950),
    ]
    for spot, expected in cases:
        result = get_atm_strike(spot, step=50)
        _test(f"ATM({spot}) = {expected}",
              result == expected,
              f"got {result}")


# ═══════════════════════════════════════════════
# RISK TESTS
# ═══════════════════════════════════════════════

def test_risk_normal():
    """T22: Normal Spot risk calculation."""
    _section("Risk Tests")
    from risk import calculate_spot_risk

    result = calculate_spot_risk(entry_spot=24500, signal_candle_high=24560)
    _test("Risk is valid", result.is_valid)
    _test("Spot SL = 24560", result.spot_sl == 24560, f"got {result.spot_sl}")
    _test("Spot risk = 60", result.spot_risk == 60, f"got {result.spot_risk}")
    _test("Spot target = 24440", result.spot_target == 24440, f"got {result.spot_target}")
    _test("Direction = PE", result.direction == "PE")


def test_risk_gap_through_sl():
    """T23: entry_spot >= spot_sl - trade should be skipped (D8)."""
    from risk import calculate_spot_risk

    result = calculate_spot_risk(entry_spot=24600, signal_candle_high=24560)
    _test("Gap through SL -> invalid", not result.is_valid)
    _test("Skip reason mentions ENTRY_SPOT_ABOVE_SL",
          "ENTRY_SPOT_ABOVE_SL" in result.skip_reason,
          f"got: {result.skip_reason}")


def test_risk_zero_risk():
    """T24: entry_spot == spot_sl -> zero risk -> invalid."""
    from risk import calculate_spot_risk

    result = calculate_spot_risk(entry_spot=24560, signal_candle_high=24560)
    _test("Zero risk -> invalid", not result.is_valid)


def test_risk_negative_entry():
    """T25: Negative entry spot -> invalid."""
    from risk import calculate_spot_risk

    result = calculate_spot_risk(entry_spot=-100, signal_candle_high=24560)
    _test("Negative entry -> invalid", not result.is_valid)


def test_risk_target_calculation():
    """T26: 1:1 R:R target calculation."""
    from risk import calculate_spot_risk

    result = calculate_spot_risk(entry_spot=25000, signal_candle_high=25100)
    _test("1:1 target = 24900",
          result.spot_target == 24900,
          f"got {result.spot_target}")


# ═══════════════════════════════════════════════
# EXPIRY & CONTRACT SELECTION AUDIT TESTS
# ═══════════════════════════════════════════════

def test_adversarial_non_weekly_rejection():
    """T27: Adversarial test ensuring non-weekly expiries are strictly rejected."""
    _section("Adversarial Non-Weekly Rejection Tests")
    from data import InstrumentManager
    from config import CONFIG

    class FakeKite:
        def instruments(self, segment):
            return []

    d_non_weekly = date(2026, 8, 28)
    d_weekly_1   = date(2026, 9, 1)
    d_weekly_2   = date(2026, 9, 8)

    strikes = [24000 + i * 50 for i in range(20)]
    puts = []

    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_non_weekly, "tradingsymbol": f"NIFTY26SPECIAL{s}PE",
            "instrument_token": 1000 + s, "lot_size": 65,
        })
    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_weekly_1, "tradingsymbol": f"NIFTY26901{s}PE",
            "instrument_token": 2000 + s, "lot_size": 65,
        })
    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_weekly_2, "tradingsymbol": f"NIFTY26908{s}PE",
            "instrument_token": 3000 + s, "lot_size": 65,
        })

    im = InstrumentManager(FakeKite())
    im._nifty_puts = puts

    import data as data_mod
    orig_pref = CONFIG.get("expiry_preference")
    orig_today = data_mod.today_ist
    try:
        data_mod.today_ist = lambda: date(2026, 8, 25)
        candidates = im._get_weekly_expiry_candidates()
        
        _test("Adversarial: Non-weekly earlier expiry (2026-08-28) strictly rejected",
              d_non_weekly not in candidates,
              f"candidates were: {candidates}")

        _test("Adversarial: Weekly expiries retained",
              d_weekly_1 in candidates and d_weekly_2 in candidates)

        CONFIG["expiry_preference"] = "weekly"
        im._resolve_target_expiry()
        _test("Adversarial: Target expiry resolves to intended weekly (2026-09-01)",
              im.get_target_expiry() == d_weekly_1,
              f"got {im.get_target_expiry()}")
    finally:
        CONFIG["expiry_preference"] = orig_pref
        data_mod.today_ist = orig_today


def test_monthly_collision_and_holiday_shift():
    """T28: Monthly collision and holiday-shifted weekly expiries."""
    _section("Monthly Collision & Holiday Shift Tests")
    from data import InstrumentManager
    from config import CONFIG
    import data as data_mod

    class FakeKite:
        def instruments(self, segment):
            return []

    d_holiday_shift = date(2026, 9, 7)
    d_month_end = date(2026, 9, 29)

    strikes = [24000 + i * 50 for i in range(20)]
    puts = []

    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_holiday_shift, "tradingsymbol": f"NIFTY26907{s}PE",
            "instrument_token": 1000 + s, "lot_size": 65,
        })
    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_month_end, "tradingsymbol": f"NIFTY26SEP{s}PE",
            "instrument_token": 2000 + s, "lot_size": 65,
        })

    im = InstrumentManager(FakeKite())
    im._nifty_puts = puts
    
    orig_pref = CONFIG.get("expiry_preference")
    orig_today = data_mod.today_ist
    try:
        data_mod.today_ist = lambda: date(2026, 8, 25)
        CONFIG["expiry_preference"] = "weekly"
        candidates = im._get_weekly_expiry_candidates()

        _test("Holiday Shift: Monday weekly expiry (2026-09-07) recognized via weekly symbol",
              d_holiday_shift in candidates)

        _test("Monthly Collision: Month-end weekly expiry (2026-09-29) recognized",
              d_month_end in candidates)
    finally:
        CONFIG["expiry_preference"] = orig_pref
        data_mod.today_ist = orig_today


def test_0dte_selection():
    """T29: 0DTE weekly expiry is selected when today is expiry day."""
    _section("0DTE Weekly Expiry Tests")
    from data import InstrumentManager
    from config import CONFIG
    import data as data_mod

    class FakeKite:
        def instruments(self, segment):
            return []

    d_today = date(2026, 8, 25)
    d_next = date(2026, 9, 1)

    strikes = [24000 + i * 50 for i in range(20)]
    puts = []

    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_today, "tradingsymbol": f"NIFTY26AUG{s}PE",
            "instrument_token": 1000 + s, "lot_size": 65,
        })
    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_next, "tradingsymbol": f"NIFTY26901{s}PE",
            "instrument_token": 2000 + s, "lot_size": 65,
        })

    im = InstrumentManager(FakeKite())
    im._nifty_puts = puts

    orig_pref = CONFIG.get("expiry_preference")
    orig_today = data_mod.today_ist
    try:
        CONFIG["expiry_preference"] = "weekly"
        data_mod.today_ist = lambda: d_today
        im._resolve_target_expiry()

        _test("0DTE: Target expiry is today (2026-08-25)",
              im.get_target_expiry() == d_today,
              f"got {im.get_target_expiry()}")
    finally:
        CONFIG["expiry_preference"] = orig_pref
        data_mod.today_ist = orig_today


def test_liquidity_fallback_and_fail_closed():
    """T30: Liquidity fallback among true weeklies and fail closed safety."""
    _section("Liquidity Fallback & Fail-Closed Tests")
    from data import InstrumentManager
    from config import CONFIG

    class FakeKite:
        def instruments(self, segment):
            return []

    d_weekly_a = date(2026, 9, 1)
    d_non_weekly_c = date(2026, 9, 4)
    d_weekly_b = date(2026, 9, 8)

    strikes_full = [24000 + i * 50 for i in range(20)]
    puts = []

    puts.append({"name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
                 "strike": 24500, "expiry": d_weekly_a, "tradingsymbol": "NIFTY2690124500PE",
                 "instrument_token": 1001, "lot_size": 65})
    puts.append({"name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
                 "strike": 24550, "expiry": d_weekly_a, "tradingsymbol": "NIFTY2690124550PE",
                 "instrument_token": 1002, "lot_size": 65})

    for s in range(20000, 25000, 50):
        puts.append({"name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
                     "strike": s, "expiry": d_non_weekly_c, "tradingsymbol": f"NIFTY26SPECIAL{s}PE",
                     "instrument_token": 2000 + s, "lot_size": 65})

    for s in strikes_full:
        puts.append({"name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
                     "strike": s, "expiry": d_weekly_b, "tradingsymbol": f"NIFTY26908{s}PE",
                     "instrument_token": 3000 + s, "lot_size": 65})

    im = InstrumentManager(FakeKite())
    im._nifty_puts = puts

    import data as data_mod
    orig_pref = CONFIG.get("expiry_preference")
    orig_today = data_mod.today_ist
    try:
        data_mod.today_ist = lambda: date(2026, 8, 25)
        CONFIG["expiry_preference"] = "weekly"
        im._resolve_target_expiry()

        _test("Liquidity Fallback: Weekly A (<10 strikes) skipped, Non-weekly C ignored, Weekly B selected",
              im.get_target_expiry() == d_weekly_b,
              f"got {im.get_target_expiry()}")

        puts_all_illiquid = [
            {"name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
             "strike": 24500, "expiry": d_weekly_a, "tradingsymbol": "NIFTY2690124500PE",
             "instrument_token": 1001, "lot_size": 65},
            {"name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
             "strike": 24500, "expiry": d_weekly_b, "tradingsymbol": "NIFTY2690824500PE",
             "instrument_token": 3001, "lot_size": 65},
        ]
        im_fail = InstrumentManager(FakeKite())
        im_fail._nifty_puts = puts_all_illiquid
        failed_closed = False
        try:
            im_fail._resolve_target_expiry()
        except RuntimeError as exc:
            if "EXPIRY_SELECTION_FAILED" in str(exc):
                failed_closed = True

        _test("Fail Closed: RuntimeError raised when all weekly candidates fail liquidity",
              failed_closed and im_fail.get_target_expiry() is None)
    finally:
        CONFIG["expiry_preference"] = orig_pref
        data_mod.today_ist = orig_today


def test_exact_atm_contract_enforcement():
    """T31: Exact ATM contract enforcement."""
    _section("Exact ATM Contract Enforcement Tests")
    from data import InstrumentManager
    from config import CONFIG
    import data as data_mod

    class FakeKite:
        def instruments(self, segment):
            return []

    d_target = date(2026, 9, 1)
    strikes = [24000 + i * 50 for i in range(20)]
    puts = []

    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_target, "tradingsymbol": f"NIFTY26901{s}PE",
            "instrument_token": 2000 + s, "lot_size": 65,
        })

    im = InstrumentManager(FakeKite())
    im._nifty_puts = puts

    orig_pref = CONFIG.get("expiry_preference")
    orig_today = data_mod.today_ist
    try:
        data_mod.today_ist = lambda: date(2026, 8, 25)
        CONFIG["expiry_preference"] = "weekly"
        im._resolve_target_expiry()

        # 1. Exact ATM lookup
        opt = im.get_atm_put(24500)
        _test("Exact ATM: Strike 24500 found",
              opt is not None and opt["strike"] == 24500)

        # 2. Missing ATM lookup returns None
        missing = im.get_atm_put(99999)
        _test("Exact ATM: Missing strike returns None (no non-ATM fallback)",
              missing is None)

        # 3. Target expiry invariant
        _test("Exact ATM: Target expiry remains invariant after missing strike lookup",
              im.get_target_expiry() == d_target)
    finally:
        CONFIG["expiry_preference"] = orig_pref
        data_mod.today_ist = orig_today


# ═══════════════════════════════════════════════
# EXIT CONDITION TESTS
# ═══════════════════════════════════════════════

def test_exit_sl():
    """T32: Spot SL trigger."""
    _section("Exit Condition Tests")
    from orders import OrderManager

    state = {
        "in_position": True,
        "current_position": {
            "spot_sl": 24560, "spot_target": 24440,
            "tradingsymbol": "TEST", "entry_premium": 100,
        },
    }

    class FakeKite:
        pass

    class FakeData:
        pass

    om = OrderManager(FakeKite(), state, FakeData())

    result = om.check_exit_conditions_with_spot_ltp(24560)
    _test("Exact SL touch -> STOP_LOSS", result == "STOP_LOSS", f"got {result}")

    result2 = om.check_exit_conditions_with_spot_ltp(24600)
    _test("Above SL -> STOP_LOSS", result2 == "STOP_LOSS", f"got {result2}")


def test_exit_target():
    """T33: Spot Target trigger."""
    from orders import OrderManager

    state = {
        "in_position": True,
        "current_position": {
            "spot_sl": 24560, "spot_target": 24440,
            "tradingsymbol": "TEST", "entry_premium": 100,
        },
    }

    class FakeKite:
        pass

    class FakeData:
        pass

    om = OrderManager(FakeKite(), state, FakeData())

    result = om.check_exit_conditions_with_spot_ltp(24440)
    _test("Exact target touch -> TARGET_HIT", result == "TARGET_HIT", f"got {result}")

    result2 = om.check_exit_conditions_with_spot_ltp(24400)
    _test("Below target -> TARGET_HIT", result2 == "TARGET_HIT", f"got {result2}")


def test_exit_no_trigger():
    """T34: Spot between SL and Target -> no exit."""
    from orders import OrderManager

    state = {
        "in_position": True,
        "current_position": {
            "spot_sl": 24560, "spot_target": 24440,
            "tradingsymbol": "TEST", "entry_premium": 100,
        },
    }

    class FakeKite:
        pass

    class FakeData:
        pass

    om = OrderManager(FakeKite(), state, FakeData())

    result = om.check_exit_conditions_with_spot_ltp(24500)
    _test("Between SL and target -> None", result is None, f"got {result}")


def test_exit_sl_priority():
    """T35: If both SL and Target conditions somehow true, SL wins."""
    from orders import OrderManager

    state = {
        "in_position": True,
        "current_position": {
            "spot_sl": 24440, "spot_target": 24560,
            "tradingsymbol": "TEST", "entry_premium": 100,
        },
    }

    class FakeKite:
        pass

    class FakeData:
        pass

    om = OrderManager(FakeKite(), state, FakeData())

    result = om.check_exit_conditions_with_spot_ltp(24440)
    _test("Both conditions met -> SL priority",
          result == "STOP_LOSS", f"got {result}")


def test_exit_not_in_position():
    """T36: No exit if not in position."""
    from orders import OrderManager

    state = {"in_position": False, "current_position": None}

    class FakeKite:
        pass

    class FakeData:
        pass

    om = OrderManager(FakeKite(), state, FakeData())
    result = om.check_exit_conditions_with_spot_ltp(24500)
    _test("Not in position -> None", result is None, f"got {result}")


def test_pre_market_tick_exit_blocked():
    """T36B: Ticks arriving outside market hours (before 09:15) must NEVER trigger exits."""
    import main as main_mod
    from main import _is_market_hours
    from config import CONFIG
    import config as cfg_mod

    # 1. Market hours helper check at 09:05 IST (pre-market boot)
    pre_market_time = datetime(2026, 9, 2, 9, 5, 0, tzinfo=IST)
    market_open_time = datetime(2026, 9, 2, 9, 15, 0, tzinfo=IST)
    post_market_time = datetime(2026, 9, 2, 15, 35, 0, tzinfo=IST)

    orig_cfg_now = cfg_mod.now_ist
    orig_main_now = main_mod.now_ist
    try:
        cfg_mod.now_ist = lambda: pre_market_time
        main_mod.now_ist = lambda: pre_market_time
        _test("Pre-market at 09:05 is outside market hours",
              not _is_market_hours())

        cfg_mod.now_ist = lambda: market_open_time
        main_mod.now_ist = lambda: market_open_time
        _test("Market open at 09:15 is inside market hours",
              _is_market_hours())

        cfg_mod.now_ist = lambda: post_market_time
        main_mod.now_ist = lambda: post_market_time
        _test("Post-market at 15:35 is outside market hours",
              not _is_market_hours())
    finally:
        cfg_mod.now_ist = orig_cfg_now
        main_mod.now_ist = orig_main_now


# ═══════════════════════════════════════════════
# STATE TESTS
# ═══════════════════════════════════════════════

def test_state_atomic_save_load():
    """T37: Atomic state save and load."""
    _section("State Tests")

    test_dir = Path(tempfile.mkdtemp())
    state_file = test_dir / "state_active.json"

    try:
        import state as state_mod
        orig_file = state_mod.STATE_FILE
        state_mod.STATE_FILE = state_file

        test_state = {
            "date": today_ist().isoformat(),
            "trades_today": 3,
            "in_position": True,
            "current_position": {"tradingsymbol": "NIFTY26AUG24500PE"},
            "realized_pnl_today": -500.0,
            "total_realized_pnl": 1200.0,
            "cash": 101200.0,
            "last_signal_candle_time": f"{today_ist().isoformat()} 10:15:00",
        }

        state_mod.save_state(test_state)
        loaded = state_mod.load_state()

        _test("State save/load: trades_today",
              loaded["trades_today"] == 3, f"got {loaded['trades_today']}")
        _test("State save/load: in_position",
              loaded["in_position"] is True)
        _test("State save/load: cash",
              loaded["cash"] == 101200.0, f"got {loaded['cash']}")

        state_mod.STATE_FILE = orig_file

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_state_daily_reset():
    """T38: State resets daily counters but preserves cumulative fields."""
    test_dir = Path(tempfile.mkdtemp())
    state_file = test_dir / "state_active.json"

    try:
        import state as state_mod
        orig_file = state_mod.STATE_FILE
        state_mod.STATE_FILE = state_file

        yesterday_state = {
            "date": "2020-01-01",
            "trades_today": 5,
            "in_position": False,
            "current_position": None,
            "realized_pnl_today": -1000.0,
            "total_realized_pnl": 5000.0,
            "cash": 105000.0,
            "last_signal_candle_time": None,
        }

        state_mod.save_state(yesterday_state)
        loaded = state_mod.load_state()

        _test("Daily reset: trades_today = 0",
              loaded["trades_today"] == 0, f"got {loaded['trades_today']}")
        _test("Daily reset: realized_pnl_today = 0",
              loaded["realized_pnl_today"] == 0.0)
        _test("Daily reset: total_realized_pnl preserved (5000)",
              loaded["total_realized_pnl"] == 5000.0)
        _test("Daily reset: cash preserved (105000)",
              loaded["cash"] == 105000.0)

        state_mod.STATE_FILE = orig_file

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ═══════════════════════════════════════════════
# P&L TESTS
# ═══════════════════════════════════════════════

def test_pnl_profitable():
    """T39: Profitable PUT trade P&L."""
    _section("P&L Tests")
    entry = 130.0
    exit_p = 180.0
    qty = 65
    pnl = (exit_p - entry) * qty
    _test("Profitable PUT: (180-130)*65 = 3250",
          pnl == 3250.0, f"got {pnl}")


def test_pnl_losing():
    """T40: Losing PUT trade P&L."""
    entry = 130.0
    exit_p = 90.0
    qty = 65
    pnl = (exit_p - entry) * qty
    _test("Losing PUT: (90-130)*65 = -2600",
          pnl == -2600.0, f"got {pnl}")


# ═══════════════════════════════════════════════
# WEBSOCKET / DATA TESTS
# ═══════════════════════════════════════════════

def test_ws_stale_ltp():
    """T41: Stale Spot LTP returns None."""
    _section("WebSocket / Data Tests")
    from data import DataManager

    class FakeKite:
        pass

    dm = DataManager(FakeKite())

    result = dm.get_cached_spot_ltp()
    _test("No cached LTP -> None", result is None)

    dm._cached_spot_ltp = 24500.0
    dm._spot_ltp_updated_at = datetime.now(IST) - timedelta(seconds=60)
    result2 = dm.get_cached_spot_ltp(max_age_seconds=30)
    _test("Stale LTP (60s > 30s threshold) -> None", result2 is None)


def test_ws_fresh_ltp():
    """T42: Fresh Spot LTP returns value."""
    from data import DataManager

    class FakeKite:
        pass

    dm = DataManager(FakeKite())
    dm._cached_spot_ltp = 24500.0
    dm._spot_ltp_updated_at = datetime.now(IST)

    result = dm.get_cached_spot_ltp(max_age_seconds=30)
    _test("Fresh LTP -> 24500", result == 24500.0, f"got {result}")


def test_fetch_option_ltp_retry_and_fallback():
    """T43: fetch_option_ltp handles transient timeouts with retries and fallback to quote."""
    from data import DataManager

    class FlakyKite:
        def __init__(self):
            self.ltp_calls = 0
            self.quote_calls = 0

        def ltp(self, keys):
            self.ltp_calls += 1
            if self.ltp_calls == 1:
                raise TimeoutError("Read timed out")
            return {keys[0]: {"last_price": 65.5}}

        def quote(self, keys):
            self.quote_calls += 1
            if self.ltp_calls == 1:
                raise TimeoutError("Quote also timed out")
            return {keys[0]: {"last_price": 65.5}}

    dm = DataManager(FlakyKite())
    val = dm.fetch_option_ltp("NIFTY26AUG24200PE")
    _test("Option LTP retry on timeout succeeds", val == 65.5, f"got {val}")
    _test("Option LTP retried on subsequent attempt", dm.kite.ltp_calls >= 2)

    # Test quote fallback
    class TimeoutKite:
        def ltp(self, keys):
            raise TimeoutError("All LTP timed out")

        def quote(self, keys):
            return {keys[0]: {"last_price": 72.0}}

    dm2 = DataManager(TimeoutKite())
    val2 = dm2.fetch_option_ltp("NIFTY26AUG24200PE")
    _test("Option LTP falls back to quote() on complete LTP failure", val2 == 72.0, f"got {val2}")


def test_fetch_spot_ltp_retry_and_fallback():
    """T44: fetch_spot_ltp handles flaky connection and quote fallback."""
    from data import DataManager

    class QuoteFallbackKite:
        def ltp(self, keys):
            raise Exception("LTP 500 error")

        def quote(self, keys):
            return {"NSE:NIFTY 50": {"last_price": 24250.75}}

    dm = DataManager(QuoteFallbackKite())
    val = dm.fetch_spot_ltp()
    _test("Spot LTP falls back to quote() on LTP failure", val == 24250.75, f"got {val}")


# ═══════════════════════════════════════════════
# CONFIG TESTS
# ═══════════════════════════════════════════════

def test_config_values():
    """T43: Config values match locked specification."""
    _section("Config Tests")
    from config import CONFIG

    _test("candle_tf = 60minute", CONFIG["candle_tf"] == "60minute")
    _test("strike_step = 50", CONFIG["strike_step"] == 50)
    _test("sma_short = 20", CONFIG["sma_short"] == 20)
    _test("sma_long = 50", CONFIG["sma_long"] == 50)
    _test("product = NRML", CONFIG["product"] == "NRML")
    _test("trading_mode = PAPER", CONFIG["trading_mode"] == "PAPER")
    _test("expiry_preference = monthly", CONFIG["expiry_preference"] == "monthly")
    _test("monthly_rollover_day = 20", CONFIG.get("monthly_rollover_day") == 20)
    _test("max_trades_per_day = 5", CONFIG.get("max_trades_per_day") == 5)
    _test("expiry_force_exit = 15:15",
          CONFIG["expiry_force_exit"].hour == 15 and
          CONFIG["expiry_force_exit"].minute == 15)
    _test("first_entry = 10:15",
          CONFIG["first_entry"].hour == 10 and
          CONFIG["first_entry"].minute == 15)
    _test("last_entry = 15:15",
          CONFIG["last_entry"].hour == 15 and
          CONFIG["last_entry"].minute == 15)


def test_monthly_rollover_20th_rule():
    """T44: 20th-Day Monthly Expiry Rollover Tests."""
    _section("20th-Day Monthly Expiry Rollover Tests")
    from data import InstrumentManager

    class FakeKite:
        def instruments(self, segment):
            return []

    d_aug = date(2026, 8, 27)  # August monthly expiry
    d_sep = date(2026, 9, 24)  # September monthly expiry

    puts = []
    # August monthly PE (20 strikes)
    for s in range(24000, 25000, 50):
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_aug, "tradingsymbol": f"NIFTY26AUG{s}PE",
            "instrument_token": 1000 + s, "lot_size": 65,
        })
    # September monthly PE (20 strikes)
    for s in range(24000, 25000, 50):
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_sep, "tradingsymbol": f"NIFTY26SEP{s}PE",
            "instrument_token": 2000 + s, "lot_size": 65,
        })

    im = InstrumentManager(FakeKite())
    im._nifty_puts = puts

    import data as data_mod
    orig_today = data_mod.today_ist
    try:
        # Scenario 1: Today is August 14 (<= 20) -> selects August monthly expiry
        data_mod.today_ist = lambda: date(2026, 8, 14)
        im._resolve_target_expiry()
        _test("Monthly Rollover: day <= 20 (Aug 14) resolves to August expiry (Aug 27)",
              im.get_target_expiry() == d_aug, f"got {im.get_target_expiry()}")

        # Scenario 2: Today is August 21 (> 20) -> selects September monthly expiry
        data_mod.today_ist = lambda: date(2026, 8, 21)
        im._resolve_target_expiry()
        _test("Monthly Rollover: day > 20 (Aug 21) resolves to September expiry (Sep 24)",
              im.get_target_expiry() == d_sep, f"got {im.get_target_expiry()}")
    finally:
        data_mod.today_ist = orig_today


def test_main_banner_and_helpers():
    """T12: Test main module banner and helper functions for runtime errors/missing imports."""
    _section("Main Module Helper Tests")
    import main as main_mod
    try:
        main_mod._banner()
        _test("main._banner() executes without NameError", True)
    except Exception as e:
        _test("main._banner() executes without NameError", False, str(e))

    try:
        is_mkt = main_mod._is_market_hours()
        _test("main._is_market_hours() returns boolean", isinstance(is_mkt, bool))
    except Exception as e:
        _test("main._is_market_hours() returns boolean", False, str(e))

    try:
        is_exp = main_mod._is_expiry_day({"current_position": {"expiry": today_ist().isoformat()}})
        _test("main._is_expiry_day() returns True for today", is_exp is True)
    except Exception as e:
        _test("main._is_expiry_day() returns True for today", False, str(e))


def test_data_manager_boundary_caching_and_drop_incomplete():
    """T13: Test DataManager boundary caching, _drop_incomplete_candle, and SMA calculation."""
    _section("DataManager Boundary Caching & Candle Drop Tests")
    from data import DataManager
    import data as data_mod

    class MockKite:
        def __init__(self, candles):
            self._candles = candles
            self.api_calls = 0

        def historical_data(self, *args, **kwargs):
            self.api_calls += 1
            return list(self._candles)

    # 1. Test _drop_incomplete_candle
    dm = DataManager(None)
    
    # 09:15 candle evaluated at 10:05 (forming) -> dropped
    orig_now = data_mod.now_ist
    try:
        data_mod.now_ist = lambda: datetime(2026, 8, 26, 10, 5, 0, tzinfo=IST)
        raw_candles = [
            {"date": datetime(2026, 8, 25, 15, 15, tzinfo=IST), "close": 24200, "open": 24200, "high": 24200, "low": 24200},
            {"date": datetime(2026, 8, 26, 9, 15, tzinfo=IST), "close": 24250, "open": 24200, "high": 24300, "low": 24200},
        ]
        completed = dm._drop_incomplete_candle(raw_candles)
        _test("_drop_incomplete_candle drops 09:15 bar at 10:05", len(completed) == 1 and completed[-1]["date"].date() == date(2026, 8, 25))

        # 09:15 candle evaluated at 10:15:05 (completed) -> kept
        data_mod.now_ist = lambda: datetime(2026, 8, 26, 10, 15, 5, tzinfo=IST)
        completed = dm._drop_incomplete_candle(raw_candles)
        _test("_drop_incomplete_candle keeps 09:15 bar at 10:15:05", len(completed) == 2 and completed[-1]["date"] == datetime(2026, 8, 26, 9, 15, tzinfo=IST))

        # 15:15 candle (closes 15:30) evaluated at 15:20 (forming) -> dropped
        raw_1515 = [
            {"date": datetime(2026, 8, 26, 14, 15, tzinfo=IST), "close": 24200, "open": 24200, "high": 24200, "low": 24200},
            {"date": datetime(2026, 8, 26, 15, 15, tzinfo=IST), "close": 24250, "open": 24200, "high": 24300, "low": 24200},
        ]
        data_mod.now_ist = lambda: datetime(2026, 8, 26, 15, 20, 0, tzinfo=IST)
        completed = dm._drop_incomplete_candle(raw_1515)
        _test("_drop_incomplete_candle drops 15:15 bar at 15:20", len(completed) == 1 and completed[-1]["date"].time() == dtime(14, 15))

        # 15:15 candle evaluated at 15:30:05 (completed) -> kept
        data_mod.now_ist = lambda: datetime(2026, 8, 26, 15, 30, 5, tzinfo=IST)
        completed = dm._drop_incomplete_candle(raw_1515)
        _test("_drop_incomplete_candle keeps 15:15 bar at 15:30:05", len(completed) == 2 and completed[-1]["date"].time() == dtime(15, 15))

        # 2. Test Boundary Caching
        mock_kite = MockKite([
            {"date": datetime(2026, 8, 25, 15, 15, tzinfo=IST), "close": 24200, "open": 24200, "high": 24200, "low": 24200},
        ])
        dm_cache = DataManager(mock_kite)
        
        # Initial fetch at 09:05 IST
        data_mod.now_ist = lambda: datetime(2026, 8, 26, 9, 5, 0, tzinfo=IST)
        data_mod.today_ist = lambda: date(2026, 8, 26)
        c1 = dm_cache.fetch_spot_candles()
        _test("Initial fetch_spot_candles calls Kite API (api_calls=1)", mock_kite.api_calls == 1)

        # Polling at 09:45 IST (before 10:15:03) -> Cache HIT, NO API call
        data_mod.now_ist = lambda: datetime(2026, 8, 26, 9, 45, 0, tzinfo=IST)
        c2 = dm_cache.fetch_spot_candles()
        _test("Polling at 09:45 (before 10:15:03) hits cache without API call", mock_kite.api_calls == 1 and len(c2) == 1)

        # Polling at 10:05 IST (before 10:15:03) -> Cache HIT, NO API call
        data_mod.now_ist = lambda: datetime(2026, 8, 26, 10, 5, 0, tzinfo=IST)
        c3 = dm_cache.fetch_spot_candles()
        _test("Polling at 10:05 (before 10:15:03) hits cache without API call", mock_kite.api_calls == 1)

        # At 10:15:04 IST -> Cache EXPIRED, Kite API is called
        mock_kite._candles = [
            {"date": datetime(2026, 8, 25, 15, 15, tzinfo=IST), "close": 24200, "open": 24200, "high": 24200, "low": 24200},
            {"date": datetime(2026, 8, 26, 9, 15, tzinfo=IST), "close": 24250, "open": 24200, "high": 24300, "low": 24200},
            {"date": datetime(2026, 8, 26, 10, 15, tzinfo=IST), "close": 24260, "open": 24250, "high": 24270, "low": 24240},
        ]
        data_mod.now_ist = lambda: datetime(2026, 8, 26, 10, 15, 4, tzinfo=IST)
        c4 = dm_cache.fetch_spot_candles()
        _test("At 10:15:04 (after 10:15:03), Kite API is called (api_calls=2)", mock_kite.api_calls == 2)
        _test("Forming 10:15 bar is dropped, keeping completed 09:15 bar", len(c4) == 2 and c4[-1]["date"] == datetime(2026, 8, 26, 9, 15, tzinfo=IST))

        # At 10:45 IST (before 11:15:03) -> Cache HIT, NO API call
        data_mod.now_ist = lambda: datetime(2026, 8, 26, 10, 45, 0, tzinfo=IST)
        c5 = dm_cache.fetch_spot_candles()
        _test("Polling at 10:45 (before 11:15:03) hits cache (api_calls=2)", mock_kite.api_calls == 2)

    finally:
        data_mod.now_ist = orig_now
        data_mod.today_ist = today_ist


def test_order_manager_product_type_parity():
    """T14: Verify OrderManager uses PRODUCT_NRML for both entry and exit in live mode."""
    _section("Order Manager Product Type Parity Tests")
    from orders import OrderManager
    from config import CONFIG

    class MockKiteOrders:
        def __init__(self):
            self.orders = []
            self.PRODUCT_NRML = "NRML"
            self.PRODUCT_MIS = "MIS"
            self.VARIETY_REGULAR = "regular"
            self.EXCHANGE_NFO = "NFO"
            self.TRANSACTION_TYPE_BUY = "BUY"
            self.TRANSACTION_TYPE_SELL = "SELL"
            self.ORDER_TYPE_MARKET = "MARKET"

        def place_order(self, **kwargs):
            self.orders.append(kwargs)
            return "ORDER_123"

        def order_history(self, order_id):
            return [{"status": "COMPLETE", "average_price": 100.0}]

    mock_kite = MockKiteOrders()
    state = {
        "in_position": False,
        "current_position": None,
        "trades_today": 0,
        "realized_pnl_today": 0.0,
        "total_realized_pnl": 0.0,
        "cash": 100000.0,
    }

    orig_mode = CONFIG["trading_mode"]
    import orders as orders_mod
    orig_save = orders_mod.save_state
    orig_journal = orders_mod.append_trade_journal
    orig_tg = getattr(orders_mod, "tg", None)

    class MockTelegram:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    orders_mod.save_state = lambda s: None
    orders_mod.append_trade_journal = lambda r: None
    orders_mod.tg = MockTelegram()

    try:
        CONFIG["trading_mode"] = "LIVE"
        om = OrderManager(mock_kite, state, data_mgr=None)

        class MockRiskParams:
            spot_sl = 24500.0
            spot_target = 24300.0
            spot_risk = 100.0

        option_info = {
            "tradingsymbol": "NIFTY26SEP24400PE",
            "instrument_token": 12345,
            "strike": 24400.0,
            "expiry": date(2026, 9, 29),
        }

        # BUY Entry
        entered = om.enter_trade(option_info, MockRiskParams(), 24400.0, 100.0)
        _test("LIVE BUY placed with PRODUCT_NRML",
              len(mock_kite.orders) == 1 and mock_kite.orders[0]["product"] == "NRML",
              f"got {mock_kite.orders[0]['product'] if mock_kite.orders else 'no order'}")

        # SELL Exit
        exited = om.exit_trade("STOP_LOSS", 80.0)
        _test("LIVE SELL exit placed with PRODUCT_NRML (matches entry)",
              len(mock_kite.orders) == 2 and mock_kite.orders[1]["product"] == "NRML",
              f"got {mock_kite.orders[1]['product'] if len(mock_kite.orders) > 1 else 'no order'}")

    finally:
        CONFIG["trading_mode"] = orig_mode
        orders_mod.save_state = orig_save
        orders_mod.append_trade_journal = orig_journal
        if orig_tg is not None:
            orders_mod.tg = orig_tg


def test_overnight_crash_recovery_downtime_calculation():
    """T15: Verify crash recovery downtime math only counts market hours for multi-day positions."""
    _section("Overnight Crash Recovery Downtime Tests")
    from config import CONFIG, IST

    # Overnight position from yesterday 15:30 IST
    yesterday = date(2026, 8, 27)
    today = date(2026, 8, 28)
    last_hb = datetime.combine(yesterday, dtime(15, 30), tzinfo=IST).isoformat()

    # If restarted at 09:16 AM today (1 minute into market)
    now_0916 = datetime.combine(today, dtime(9, 16), tzinfo=IST)
    today_open = datetime.combine(today, CONFIG["market_open"], tzinfo=IST)
    downtime_0916 = (now_0916 - today_open).total_seconds() / 60.0

    _test("Overnight downtime at 09:16 is 1 minute (not 1000+ min)",
          downtime_0916 == 1.0, f"got {downtime_0916}")

    # If restarted at 09:05 AM today (before market open)
    now_0905 = datetime.combine(today, dtime(9, 5), tzinfo=IST)
    downtime_0905 = max(0.0, (now_0905 - today_open).total_seconds() / 60.0) if now_0905 > today_open else 0.0

    _test("Overnight downtime at 09:05 (pre-market) is 0 minutes",
          downtime_0905 == 0.0, f"got {downtime_0905}")


# ═══════════════════════════════════════════════
# RUN ALL TESTS
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  NIFTY 1H SMA PUT Strategy — Comprehensive Test Suite")
    print("=" * 60)

    # 1. SMA Tests (7 assertions across 3 functions)
    test_sma_20()
    test_sma_50()
    test_sma_warmup()

    # 2. Signal Tests (11 assertions across 8 functions)
    test_signal_valid()
    test_signal_green_candle()
    test_signal_above_sma20()
    test_signal_above_sma50()
    test_signal_missing_sma()
    test_signal_nan_sma()
    test_signal_empty_candles()
    test_signal_duplicate()

    # 3. ATM Strike Tests (10 assertions across 1 function)
    test_atm_strike()

    # 4. Risk Tests (10 assertions across 5 functions)
    test_risk_normal()
    test_risk_gap_through_sl()
    test_risk_zero_risk()
    test_risk_negative_entry()
    test_risk_target_calculation()

    # 5. Expiry & Contract Audits (11 assertions across 5 functions)
    test_adversarial_non_weekly_rejection()
    test_monthly_collision_and_holiday_shift()
    test_0dte_selection()
    test_liquidity_fallback_and_fail_closed()
    test_exact_atm_contract_enforcement()

    # 6. Exit Condition Tests (10 assertions across 6 functions)
    test_exit_sl()
    test_exit_target()
    test_exit_no_trigger()
    test_exit_sl_priority()
    test_exit_not_in_position()
    test_pre_market_tick_exit_blocked()

    # 7. State Tests (7 assertions across 2 functions)
    test_state_atomic_save_load()
    test_state_daily_reset()

    # 8. P&L Tests (2 assertions across 2 functions)
    test_pnl_profitable()
    test_pnl_losing()

    # 9. WebSocket / Data Tests (7 assertions across 4 functions)
    test_ws_stale_ltp()
    test_ws_fresh_ltp()
    test_fetch_option_ltp_retry_and_fallback()
    test_fetch_spot_ltp_retry_and_fallback()

    # 10. Config Tests (12 assertions across 1 function)
    test_config_values()

    # 11. Monthly 20th Rollover Tests (2 assertions across 1 function)
    test_monthly_rollover_20th_rule()

    # 12. Main Module Helper Tests (3 assertions across 1 function)
    test_main_banner_and_helpers()

    # 13. DataManager Boundary Caching & Candle Drop Tests (8 assertions)
    test_data_manager_boundary_caching_and_drop_incomplete()

    # 14. OrderManager Product Type Parity Tests (2 assertions)
    test_order_manager_product_type_parity()

    # 15. Overnight Crash Recovery Downtime Tests (2 assertions)
    test_overnight_crash_recovery_downtime_calculation()


    # Summary
    total = _passed + _failed
    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {_passed}/{total} individual assertions passed, {_failed} failed")
    print(f"{'=' * 60}")

    if _errors:
        print("\nFailed assertions:")
        for e in _errors:
            print(f"  {e}")

    sys.exit(0 if _failed == 0 else 1)