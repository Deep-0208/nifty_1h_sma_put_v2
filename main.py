"""
main.py - Master Orchestration Loop
NIFTY 1-Hour SMA PUT Strategy

State machine:
  STARTUP -> LOGIN -> LOAD INSTRUMENTS -> LOAD DATA -> LOAD STATE
  -> INIT VALIDATION -> CRASH RECOVERY -> MARKET LOOP -> DAY SUMMARY -> END
"""

import sys
import time
import random
import threading
from datetime import datetime, timedelta

from kiteconnect import KiteTicker

from config import CONFIG, IST, now_ist, today_ist, log, log_data, log_orders
from login import create_kite_session, LoginError
from data import DataManager, InstrumentManager
from pattern import detect_signal
from risk import get_atm_strike, calculate_spot_risk
from state import load_state, save_state, fresh_state
from orders import OrderManager
import telegram_alerts as tg

# ── Validation Analytics Engine ──
try:
    from validation import AnalyticsEngine
except ImportError:
    AnalyticsEngine = None

# ── Thread lock for WebSocket exit safety ──
trade_lock = threading.Lock()


def _banner():
    """Print startup banner."""
    mode = CONFIG["trading_mode"]
    log.info("=" * 60)
    log.info("  NIFTY 1-Hour SMA PUT Strategy")
    log.info("  Mode: %s", mode)
    log.info("  Product: %s", CONFIG["product"])
    log.info("  Timeframe: %s", CONFIG["candle_tf"])
    log.info("  SMA: %d / %d", CONFIG["sma_short"], CONFIG["sma_long"])
    log.info("  Strike Step: %d", CONFIG["strike_step"])
    log.info("  Expiry: %s (0DTE allowed)", CONFIG["expiry_preference"])
    log.info("  First Entry: %s", CONFIG["first_entry"])
    log.info("  Last Entry: %s", CONFIG["last_entry"])
    log.info("  Square-off: %s", CONFIG["square_off_time"])
    log.info("=" * 60)


def _is_market_hours() -> bool:
    """Check if current time is within market hours."""
    now = now_ist().time()
    return CONFIG["market_open"] <= now <= CONFIG["market_close"]


def _smart_sleep(in_position: bool) -> None:
    """
    Adaptive sleep:
    - In position: short sleep (WebSocket handles exits)
    - Near hour boundaries: short sleep for timely candle detection
    - Otherwise: longer sleep to reduce API load
    """
    now = now_ist()
    minutes = now.minute

    if in_position:
        time.sleep(CONFIG["position_monitor_interval_s"] + random.uniform(0.1, 0.5))
        return

    # Near hour boundaries (within 4 minutes of :15 mark for 1H candles)
    minutes_to_boundary = (15 - (minutes % 60)) % 60
    if minutes_to_boundary <= 4 or minutes_to_boundary >= 56:
        time.sleep(5 + random.uniform(0.1, 0.5))
    else:
        time.sleep(CONFIG["candle_poll_interval_s"] + random.uniform(0.1, 0.5))


def _crash_recovery(
    state: dict, kite, data_mgr: DataManager, order_mgr: OrderManager,
) -> None:
    """
    Crash recovery on startup.
    If state says we're in position, reconcile with broker state.
    Broker is authoritative in LIVE mode.
    """
    if not state.get("in_position") or not state.get("current_position"):
        return

    pos = state["current_position"]
    symbol = pos.get("tradingsymbol", "?")
    entry_premium = pos.get("entry_premium", 0.0)
    last_hb = pos.get("last_heartbeat", "")

    log.warning(
        "CRASH RECOVERY: State shows open position: %s (entry=%.2f, last_hb=%s)",
        symbol, entry_premium, last_hb,
    )

    # Calculate downtime
    downtime_minutes = 999
    if last_hb:
        try:
            last_hb_dt = datetime.fromisoformat(last_hb)
            downtime_minutes = (now_ist() - last_hb_dt).total_seconds() / 60
        except (ValueError, TypeError):
            pass

    log.warning("Calculated downtime: %.1f minutes.", downtime_minutes)

    # LIVE mode: query broker for actual position
    if CONFIG["trading_mode"] == "LIVE":
        broker_pos = order_mgr.query_broker_position(symbol)
        if broker_pos is None or broker_pos.get("quantity", 0) == 0:
            log.warning(
                "Broker shows NO open position for %s. Reconciling state.",
                symbol,
            )
            state["in_position"] = False
            state["current_position"] = None
            save_state(state)
            tg.bot_restarted(symbol, entry_premium, "BROKER_ALREADY_EXITED")
            return

    # If market is closed, just note it
    if not _is_market_hours():
        log.warning(
            "Market closed. MIS position should have been "
            "auto-squared by broker. Clearing state."
        )
        state["in_position"] = False
        state["current_position"] = None
        save_state(state)
        return

    # If downtime > 15 minutes during market hours, force exit
    if downtime_minutes > 15:
        log.warning(
            "Downtime > 15 min during market hours. Force square-off."
        )
        order_mgr.exit_trade("CRASH_DOWNTIME_EXCEEDED")
        tg.bot_restarted(symbol, entry_premium, "FORCE_EXIT_DOWNTIME")
        return

    # Otherwise, check if SL/Target already breached
    spot_ltp = data_mgr.fetch_spot_ltp()
    if spot_ltp is not None:
        exit_reason = order_mgr.check_exit_conditions_with_spot_ltp(spot_ltp)
        if exit_reason:
            log.warning(
                "SL/Target already breached (spot=%.2f). Exiting: %s",
                spot_ltp, exit_reason,
            )
            exit_premium = data_mgr.fetch_option_ltp(symbol)
            order_mgr.exit_trade(exit_reason, exit_premium)
            tg.bot_restarted(symbol, entry_premium, exit_reason)
            return

    # Resume monitoring
    log.info(
        "Position still valid. Resuming monitoring for %s.", symbol
    )
    tg.bot_restarted(symbol, entry_premium, "RESUME_MONITORING")


def _execute_entry(
    signal, kite, data_mgr: DataManager,
    instrument_mgr: InstrumentManager, order_mgr: OrderManager,
    state: dict, analytics=None,
) -> bool:
    """
    Execute the entry sequence after a signal is confirmed.
    Returns True if trade was entered, False if skipped.
    """
    mode = CONFIG["trading_mode"]

    # 1. Fetch live Spot LTP (entry_spot = actual Spot at execution)
    spot_ltp = data_mgr.get_cached_spot_ltp()
    if spot_ltp is None:
        spot_ltp = data_mgr.fetch_spot_ltp()
    if spot_ltp is None:
        reason = "SPOT_LTP_UNAVAILABLE"
        log.warning("Entry skipped: %s", reason)
        tg.setup_skipped(reason, mode)
        if analytics:
            analytics.record_setup(
                direction="BEARISH_PUT", spot_price=None, atm_strike=None,
                candle=signal.signal_candle, spot_sl=signal.spot_sl, spot_target=None,
                spot_risk_pts=None, pattern_valid=True, trade_taken=False, skip_reason=reason,
            )
        return False

    entry_spot = spot_ltp

    # 2. Calculate ATM strike
    atm_strike = get_atm_strike(entry_spot)

    # 3. Look up ATM PUT contract on target expiry
    option_info = instrument_mgr.get_atm_put(atm_strike)
    if option_info is None:
        target_exp = instrument_mgr.get_target_expiry()
        reason = (
            f"EXPIRY_CONTRACT_UNAVAILABLE: strike={atm_strike}, "
            f"target_expiry={target_exp.isoformat() if target_exp else 'None'}, "
            f"entry_spot={entry_spot:.2f}"
        )
        log.warning("Entry skipped: %s", reason)
        tg.setup_skipped(reason, mode)
        if analytics:
            analytics.record_setup(
                direction="BEARISH_PUT", spot_price=entry_spot, atm_strike=atm_strike,
                candle=signal.signal_candle, spot_sl=signal.spot_sl, spot_target=None,
                spot_risk_pts=None, pattern_valid=True, trade_taken=False, skip_reason=reason,
            )
        return False

    # 4. Verify contract not expired
    expiry = option_info["expiry"]
    if expiry < today_ist():
        reason = f"CONTRACT_EXPIRED: {option_info['tradingsymbol']} expiry={expiry}"
        log.warning("Entry skipped: %s", reason)
        tg.setup_skipped(reason, mode)
        if analytics:
            analytics.record_setup(
                direction="BEARISH_PUT", spot_price=entry_spot, atm_strike=atm_strike,
                candle=signal.signal_candle, spot_sl=signal.spot_sl, spot_target=None,
                spot_risk_pts=None, pattern_valid=True, trade_taken=False, skip_reason=reason,
            )
        return False

    # 5. Calculate Spot risk
    risk_params = calculate_spot_risk(entry_spot, signal.spot_sl)
    if not risk_params.is_valid:
        reason = risk_params.skip_reason
        log.warning("Entry skipped: %s", reason)
        tg.setup_skipped(reason, mode)
        if analytics:
            analytics.record_setup(
                direction="BEARISH_PUT", spot_price=entry_spot, atm_strike=atm_strike,
                candle=signal.signal_candle, spot_sl=signal.spot_sl, spot_target=None,
                spot_risk_pts=None, pattern_valid=False, trade_taken=False, skip_reason=reason,
            )
        return False

    # 6. Fetch option premium for entry
    entry_premium = data_mgr.fetch_option_ltp(option_info["tradingsymbol"])
    if entry_premium is None or entry_premium <= 0:
        reason = f"OPTION_LTP_UNAVAILABLE: {option_info['tradingsymbol']}"
        log.warning("Entry skipped: %s", reason)
        tg.setup_skipped(reason, mode)
        if analytics:
            analytics.record_setup(
                direction="BEARISH_PUT", spot_price=entry_spot, atm_strike=atm_strike,
                candle=signal.signal_candle, spot_sl=risk_params.spot_sl, spot_target=risk_params.spot_target,
                spot_risk_pts=risk_params.spot_risk, pattern_valid=True, trade_taken=False, skip_reason=reason,
            )
        return False

    # 7. Record setup in validation analytics
    setup_num = 0
    if analytics:
        setup_num = analytics.record_setup(
            direction="BEARISH_PUT", spot_price=entry_spot, atm_strike=atm_strike,
            candle=signal.signal_candle, spot_sl=risk_params.spot_sl, spot_target=risk_params.spot_target,
            spot_risk_pts=risk_params.spot_risk, pattern_valid=True, trade_taken=True,
        )

    # 8. Enter the trade
    log.info(
        "Entering trade: %s | spot=%.2f | atm=%d | premium=%.2f | "
        "SL=%.2f | target=%.2f",
        option_info["tradingsymbol"], entry_spot, atm_strike,
        entry_premium, risk_params.spot_sl, risk_params.spot_target,
    )

    success = order_mgr.enter_trade(
        option_info, risk_params, entry_spot, entry_premium, setup_num=setup_num,
    )
    return success


def main():
    """Main entry point."""
    _banner()

    mode = CONFIG["trading_mode"]

    # LIVE mode safety confirmation
    if mode == "LIVE":
        print("\n" + "=" * 60)
        print("WARNING: You are about to start LIVE trading with real money!")
        print("Strategy: NIFTY 1H SMA PUT Strategy")
        print("Product: MIS (Intraday)")
        print("=" * 60)
        confirm = input("Proceed? (y/n): ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)

    # 1. Authenticate
    try:
        kite = create_kite_session()
    except LoginError as e:
        log.error("Authentication failed: %s", e)
        tg.bot_crashed(f"LOGIN_FAILED: {e}")
        sys.exit(1)

    user_id = ""
    try:
        profile = kite.profile()
        user_id = profile.get("user_id", "")
    except Exception:
        pass

    tg.bot_started(mode)
    tg.login_success(user_id)

    # 2. Load instruments
    instrument_mgr = InstrumentManager(kite)
    try:
        instrument_mgr.load_instruments()
    except RuntimeError as e:
        log.error("Instrument loading failed: %s", e)
        tg.bot_crashed(f"INSTRUMENTS_FAILED: {e}")
        sys.exit(1)

    # 3. Initialize data manager
    data_mgr = DataManager(kite)
    data_mgr._instrument_mgr = instrument_mgr  # Cross-reference for lot_size

    # 4. Prefetch candle data
    log.info("Prefetching Spot 1H candles for SMA warmup...")
    candles = data_mgr.fetch_spot_candles()
    completed = data_mgr.get_completed_candles()
    log.info(
        "Data ready: %d total candles, %d completed.",
        len(candles), len(completed),
    )

    # 5. Load state
    state = load_state()
    if state.get("cash", 0) == 0 and not state.get("in_position"):
        state["cash"] = CONFIG["starting_capital"]
        save_state(state)

    # 6. Initialize Validation Analytics Engine
    analytics = None
    if AnalyticsEngine is not None:
        try:
            analytics = AnalyticsEngine(
                today_ist(), state.get("cash", CONFIG["starting_capital"]),
            )
            log.info("Validation Analytics Engine initialized.")
        except Exception as e:
            log.warning("Validation Analytics Engine failed to init: %s", e)

    # 7. Initialize order manager
    order_mgr = OrderManager(kite, state, data_mgr, analytics=analytics)

    # 8. Crash recovery
    _crash_recovery(state, kite, data_mgr, order_mgr)

    # 9. WebSocket setup
    ws_connected = threading.Event()
    last_data_time = [now_ist()]  # mutable container for closure

    def on_ticks(ws, ticks):
        """Process incoming WebSocket ticks for NIFTY Spot."""
        for tick in ticks:
            if tick.get("instrument_token") == CONFIG["nifty_instrument_token"]:
                ltp = tick.get("last_price", 0)
                if ltp <= 0:
                    continue

                data_mgr.update_spot_ltp(ltp)
                last_data_time[0] = now_ist()

                # Check exit conditions if in position
                if state.get("in_position"):
                    with trade_lock:
                        exit_reason = order_mgr.check_exit_conditions_with_spot_ltp(ltp)
                        if exit_reason:
                            symbol = state["current_position"]["tradingsymbol"]
                            exit_premium = data_mgr.fetch_option_ltp(symbol)
                            order_mgr.exit_trade(exit_reason, exit_premium)

    def on_connect(ws, response):
        log.info("WebSocket connected. Subscribing to NIFTY Spot (256265)...")
        ws.subscribe([CONFIG["nifty_instrument_token"]])
        ws.set_mode(ws.MODE_LTP, [CONFIG["nifty_instrument_token"]])
        ws_connected.set()

    def on_close(ws, code, reason):
        log.warning("WebSocket closed: code=%s, reason=%s", code, reason)
        ws_connected.clear()

    def on_error(ws, code, reason):
        log.error("WebSocket error: code=%s, reason=%s", code, reason)

    kws = KiteTicker(kite.api_key, kite.access_token)
    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close
    kws.on_error = on_error

    kws.connect(threaded=True)
    log.info("WebSocket thread started.")

    # 10. Main market loop
    last_heartbeat = time.time()
    last_rollover_date = today_ist()

    try:
        while True:
            now = now_ist()
            current_time = now.time()
            current_date = now.date()

            # Date rollover check
            if current_date != last_rollover_date:
                log.info(
                    "Date rollover: %s -> %s. Resetting daily counters.",
                    last_rollover_date, current_date,
                )
                if analytics:
                    analytics.generate_daily_summary(state.get("cash", CONFIG["starting_capital"]))
                    analytics = AnalyticsEngine(current_date, state.get("cash", CONFIG["starting_capital"]))
                    order_mgr.analytics = analytics

                state["trades_today"] = 0
                state["realized_pnl_today"] = 0.0
                state["date"] = current_date.isoformat()
                state["last_signal_candle_time"] = None
                save_state(state)
                last_rollover_date = current_date

            # Square-off at 15:20 (D5/D6)
            if current_time >= CONFIG["square_off_time"]:
                if state.get("in_position"):
                    log.info("Square-off time (15:20) reached. Exiting position.")
                    with trade_lock:
                        if state.get("in_position"):
                            symbol = state["current_position"]["tradingsymbol"]
                            exit_premium = data_mgr.fetch_option_ltp(symbol)
                            order_mgr.exit_trade("SQUARE_OFF_1520", exit_premium)

                # Day summary after market close
                if current_time >= CONFIG["market_close"]:
                    log.info("Market closed for the day.")
                    if analytics:
                        analytics.generate_daily_summary(state.get("cash", CONFIG["starting_capital"]))

                    tg.day_summary(
                        state.get("trades_today", 0),
                        state.get("realized_pnl_today", 0.0),
                        state.get("total_realized_pnl", 0.0),
                        state.get("cash", 0.0),
                    )
                    # Sleep until next market open
                    log.info("Sleeping until next market open...")
                    while now_ist().time() >= CONFIG["market_close"] or \
                          now_ist().time() < CONFIG["market_open"]:
                        time.sleep(60)
                    continue

            # Wait for market open
            if current_time < CONFIG["market_open"]:
                _smart_sleep(False)
                continue

            # If in position, WebSocket handles exits.
            if state.get("in_position"):
                if time.time() - last_heartbeat >= 60:
                    order_mgr.update_heartbeat()
                    last_heartbeat = time.time()

                data_age = (now_ist() - last_data_time[0]).total_seconds()
                if data_age > CONFIG["data_unavailable_exit_s"]:
                    log.error(
                        "DATA UNAVAILABLE for %.0fs. Force square-off.",
                        data_age,
                    )
                    rest_ltp = data_mgr.fetch_spot_ltp()
                    if rest_ltp is not None:
                        last_data_time[0] = now_ist()
                        with trade_lock:
                            exit_reason = order_mgr.check_exit_conditions_with_spot_ltp(rest_ltp)
                            if exit_reason:
                                symbol = state["current_position"]["tradingsymbol"]
                                exit_premium = data_mgr.fetch_option_ltp(symbol)
                                order_mgr.exit_trade(exit_reason, exit_premium)
                    else:
                        with trade_lock:
                            if state.get("in_position"):
                                symbol = state["current_position"]["tradingsymbol"]
                                tg.data_unavailable(symbol, data_age)
                                exit_premium = data_mgr.fetch_option_ltp(symbol)
                                order_mgr.exit_trade("DATA_UNAVAILABLE", exit_premium)

                _smart_sleep(True)
                continue

            # REST fallback for Spot LTP when WebSocket is stale
            cached = data_mgr.get_cached_spot_ltp()
            if cached is None:
                data_mgr.fetch_spot_ltp()

            # Fetch candles and check for new completed candle
            data_mgr.fetch_spot_candles()
            completed = data_mgr.get_completed_candles()

            if not data_mgr.has_new_completed_candle():
                _smart_sleep(False)
                continue

            latest_candle = completed[-1]
            candle_time = latest_candle["date"]

            # Log candle
            log_data.info(
                "New 1H candle: %s | O=%.2f H=%.2f L=%.2f C=%.2f | "
                "SMA20=%s SMA50=%s",
                candle_time,
                latest_candle["open"], latest_candle["high"],
                latest_candle["low"], latest_candle["close"],
                f"{latest_candle.get('sma_20', 'N/A'):.2f}"
                if latest_candle.get("sma_20") is not None else "N/A",
                f"{latest_candle.get('sma_50', 'N/A'):.2f}"
                if latest_candle.get("sma_50") is not None else "N/A",
            )

            data_mgr.mark_candle_processed(candle_time)

            # No-trade checks
            if current_time < CONFIG["first_entry"]:
                log.debug("Before first_entry (%s). Skipping.", CONFIG["first_entry"])
                _smart_sleep(False)
                continue

            if current_time > CONFIG["last_entry"]:
                log.debug("Past last_entry (%s). Skipping.", CONFIG["last_entry"])
                _smart_sleep(False)
                continue

            # Duplicate signal guard
            candle_time_str = str(candle_time)
            if state.get("last_signal_candle_time") == candle_time_str:
                log.debug("Duplicate candle %s already evaluated.", candle_time_str)
                _smart_sleep(False)
                continue

            # Daily loss circuit breaker
            max_loss = CONFIG.get("max_daily_loss", 0)
            if max_loss > 0 and state.get("realized_pnl_today", 0) <= -max_loss:
                log.warning(
                    "Daily loss limit reached: %.2f <= -%.2f",
                    state["realized_pnl_today"], max_loss,
                )
                _smart_sleep(False)
                continue

            # Evaluate signal
            signal = detect_signal(completed)

            if signal is None:
                _smart_sleep(False)
                continue

            # Signal found!
            state["last_signal_candle_time"] = candle_time_str
            save_state(state)

            tg.signal_detected(
                candle_time, signal.signal_candle["close"],
                signal.sma_20, signal.sma_50, signal.spot_sl,
            )

            # Execute entry
            with trade_lock:
                _execute_entry(
                    signal, kite, data_mgr, instrument_mgr, order_mgr, state, analytics=analytics,
                )

            _smart_sleep(state.get("in_position", False))

    except KeyboardInterrupt:
        log.info("KeyboardInterrupt received. Shutting down...")
        if state.get("in_position"):
            log.warning("Open position detected. Force square-off...")
            with trade_lock:
                if state.get("in_position"):
                    symbol = state["current_position"]["tradingsymbol"]
                    exit_premium = data_mgr.fetch_option_ltp(symbol)
                    order_mgr.exit_trade("KEYBOARD_INTERRUPT", exit_premium)

    except Exception as e:
        log.error("UNHANDLED EXCEPTION: %s", e, exc_info=True)
        tg.bot_crashed(str(e))

        if state.get("in_position"):
            log.warning("Crash with open position. Force square-off...")
            try:
                with trade_lock:
                    if state.get("in_position"):
                        symbol = state["current_position"]["tradingsymbol"]
                        exit_premium = data_mgr.fetch_option_ltp(symbol)
                        order_mgr.exit_trade("CRASH_SQUAREOFF", exit_premium)
            except Exception as exit_err:
                log.error("CRITICAL: Crash square-off also failed: %s", exit_err)

        raise

    finally:
        log.info("Strategy shutdown complete.")
        if analytics:
            analytics.generate_daily_summary(state.get("cash", CONFIG["starting_capital"]))

        tg.day_summary(
            state.get("trades_today", 0),
            state.get("realized_pnl_today", 0.0),
            state.get("total_realized_pnl", 0.0),
            state.get("cash", 0.0),
        )


if __name__ == "__main__":
    main()