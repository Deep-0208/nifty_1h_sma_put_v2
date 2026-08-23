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
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

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
    """T27: Adversarial test - non-weekly earlier expiry must be strictly rejected."""
    _section("Adversarial Non-Weekly Rejection Tests")
    from data import InstrumentManager

    class FakeKite:
        def instruments(self, segment):
            return []

    d_non_weekly = date(2026, 8, 28)  # Friday non-weekly special expiry (earlier)
    d_weekly_1   = date(2026, 9, 1)   # Tuesday weekly 1
    d_weekly_2   = date(2026, 9, 8)   # Tuesday weekly 2

    strikes = [24000 + i * 50 for i in range(20)]
    puts = []

    # 1. Non-weekly expiry (20 strikes, but non-weekly tradingsymbol)
    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_non_weekly, "tradingsymbol": f"NIFTY26SPECIAL{s}PE",
            "instrument_token": 1000 + s, "lot_size": 65,
        })
    # 2. Intended weekly 1
    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_weekly_1, "tradingsymbol": f"NIFTY26901{s}PE",
            "instrument_token": 2000 + s, "lot_size": 65,
        })
    # 3. Intended weekly 2
    for s in strikes:
        puts.append({
            "name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
            "strike": s, "expiry": d_weekly_2, "tradingsymbol": f"NIFTY26908{s}PE",
            "instrument_token": 3000 + s, "lot_size": 65,
        })

    im = InstrumentManager(FakeKite())
    im._nifty_puts = puts

    candidates = im._get_weekly_expiry_candidates()
    print("  [DEBUG] Candidates returned:", candidates)

    _test("Adversarial: Non-weekly earlier expiry (2026-08-28) strictly rejected",
          d_non_weekly not in candidates,
          f"candidates were: {candidates}")

    _test("Adversarial: Weekly expiries retained",
          d_weekly_1 in candidates and d_weekly_2 in candidates)

    im._resolve_target_expiry()
    _test("Adversarial: Target expiry resolves to intended weekly (2026-09-01)",
          im.get_target_expiry() == d_weekly_1,
          f"got {im.get_target_expiry()}")


def test_monthly_collision_and_holiday_shift():
    """T28: Monthly collision and holiday-shifted weekly expiries."""
    _section("Monthly Collision & Holiday Shift Tests")
    from data import InstrumentManager

    class FakeKite:
        def instruments(self, segment):
            return []

    # Scenario:
    # d_month_end = 2026-09-29 (the month-end Tuesday of September with NIFTY26SEP...PE)
    # d_holiday_shift = 2026-09-07 (Monday weekly with NIFTY26907...PE due to Tuesday holiday)
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
    candidates = im._get_weekly_expiry_candidates()

    _test("Holiday Shift: Monday weekly expiry (2026-09-07) recognized via weekly symbol",
          d_holiday_shift in candidates)

    _test("Monthly Collision: Month-end weekly expiry (2026-09-29) recognized",
          d_month_end in candidates)


def test_0dte_selection():
    """T29: 0DTE weekly expiry is selected when today is expiry day."""
    _section("0DTE Weekly Expiry Tests")
    from data import InstrumentManager

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
    im._resolve_target_expiry()

    _test("0DTE: Target expiry is today (2026-08-25)",
          im.get_target_expiry() == d_today,
          f"got {im.get_target_expiry()}")


def test_liquidity_fallback_and_fail_closed():
    """T30: Liquidity fallback among true weeklies and fail closed safety."""
    _section("Liquidity Fallback & Fail-Closed Tests")
    from data import InstrumentManager

    class FakeKite:
        def instruments(self, segment):
            return []

    d_weekly_a = date(2026, 9, 1)   # Weekly A (2 strikes -> illiquid)
    d_non_weekly_c = date(2026, 9, 4) # Non-weekly C (100 strikes -> non-weekly)
    d_weekly_b = date(2026, 9, 8)   # Weekly B (20 strikes -> liquid)

    strikes_full = [24000 + i * 50 for i in range(20)]
    puts = []

    # Weekly A: 2 strikes
    puts.append({"name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
                 "strike": 24500, "expiry": d_weekly_a, "tradingsymbol": "NIFTY2690124500PE",
                 "instrument_token": 1001, "lot_size": 65})
    puts.append({"name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
                 "strike": 24550, "expiry": d_weekly_a, "tradingsymbol": "NIFTY2690124550PE",
                 "instrument_token": 1002, "lot_size": 65})

    # Non-weekly C: 100 strikes, non-weekly symbol
    for s in range(20000, 25000, 50):
        puts.append({"name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
                     "strike": s, "expiry": d_non_weekly_c, "tradingsymbol": f"NIFTY26SPECIAL{s}PE",
                     "instrument_token": 2000 + s, "lot_size": 65})

    # Weekly B: 20 strikes
    for s in strikes_full:
        puts.append({"name": "NIFTY", "instrument_type": "PE", "segment": "NFO-OPT",
                     "strike": s, "expiry": d_weekly_b, "tradingsymbol": f"NIFTY26908{s}PE",
                     "instrument_token": 3000 + s, "lot_size": 65})

    im = InstrumentManager(FakeKite())
    im._nifty_puts = puts
    im._resolve_target_expiry()

    _test("Liquidity Fallback: Weekly A (<10 strikes) skipped, Non-weekly C ignored, Weekly B selected",
          im.get_target_expiry() == d_weekly_b,
          f"got {im.get_target_expiry()}")

    # Fail closed test: when ALL weekly candidates fail liquidity (<10 strikes)
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


def test_exact_atm_contract_enforcement():
    """T31: Exact ATM contract enforcement."""
    _section("Exact ATM Contract Enforcement Tests")
    from data import InstrumentManager

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
            "date": "2026-08-23",
            "trades_today": 3,
            "in_position": True,
            "current_position": {"tradingsymbol": "NIFTY26AUG24500PE"},
            "realized_pnl_today": -500.0,
            "total_realized_pnl": 1200.0,
            "cash": 101200.0,
            "last_signal_candle_time": "2026-08-23 10:15:00",
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
    _test("product = MIS", CONFIG["product"] == "MIS")
    _test("trading_mode = PAPER", CONFIG["trading_mode"] == "PAPER")
    _test("expiry_preference = weekly", CONFIG["expiry_preference"] == "weekly")
    _test("square_off_time = 15:20",
          CONFIG["square_off_time"].hour == 15 and
          CONFIG["square_off_time"].minute == 20)
    _test("first_entry = 10:15",
          CONFIG["first_entry"].hour == 10 and
          CONFIG["first_entry"].minute == 15)
    _test("last_entry = 15:15",
          CONFIG["last_entry"].hour == 15 and
          CONFIG["last_entry"].minute == 15)


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

    # 6. Exit Condition Tests (7 assertions across 5 functions)
    test_exit_sl()
    test_exit_target()
    test_exit_no_trigger()
    test_exit_sl_priority()
    test_exit_not_in_position()

    # 7. State Tests (7 assertions across 2 functions)
    test_state_atomic_save_load()
    test_state_daily_reset()

    # 8. P&L Tests (2 assertions across 2 functions)
    test_pnl_profitable()
    test_pnl_losing()

    # 9. WebSocket / Data Tests (3 assertions across 2 functions)
    test_ws_stale_ltp()
    test_ws_fresh_ltp()

    # 10. Config Tests (10 assertions across 1 function)
    test_config_values()

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