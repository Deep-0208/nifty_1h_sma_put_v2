"""
data.py - Data Management & Instrument Lookup
Fetches 1H NIFTY Spot candles, calculates SMAs,
manages live Spot LTP cache, and NFO instrument lookup.
"""

import time
import random
import math
import re
from datetime import datetime, timedelta, date, time as dtime
from typing import Dict, List, Optional, Any

from config import CONFIG, IST, now_ist, today_ist, log_data, log


class DataManager:
    """Fetches and caches 1H NIFTY Spot candles, computes SMAs, and manages Spot LTP."""

    def __init__(self, kite):
        self.kite = kite
        self._spot_candles: List[Dict] = []
        self._last_candle_time: Optional[datetime] = None
        self._cached_spot_ltp: Optional[float] = None
        self._spot_ltp_updated_at: Optional[datetime] = None
        self._fetch_count: int = 0
        self._last_boundary_logged: Optional[datetime] = None

    def fetch_spot_candles(self, count: int = 120, force_refresh: bool = False) -> List[Dict]:
        """
        Fetch 1H historical candles for NIFTY Spot.
        Uses smart boundary caching: only hits API when
        a new 1H candle boundary has actually completed.
        """
        now = now_ist()
        today = today_ist()

        # ── Smart Boundary Caching ───────────────────
        if not force_refresh and self._spot_candles:
            last_start = self._spot_candles[-1].get("date")
            if last_start:
                if not hasattr(last_start, "tzinfo") or last_start.tzinfo is None:
                    last_start = last_start.replace(tzinfo=IST)
                else:
                    last_start = last_start.astimezone(IST)

                initial_wait_s = CONFIG.get("boundary_initial_wait_s", 3.5)
                # If all cached candles are from previous days, today's first 1H candle
                # (09:15 - 10:15) closes at 10:15 IST + boundary_initial_wait_s.
                if last_start.date() < today:
                    next_close = datetime.combine(
                        today, dtime(10, 15), tzinfo=IST
                    ) + timedelta(seconds=initial_wait_s)
                else:
                    # Next candle starts at last_start + 1H, and closes at last_start + 2H
                    # Exception: 14:15 candle starts at 14:15 and closes at 15:15
                    if last_start.time() == dtime(14, 15):
                        next_close = last_start + timedelta(minutes=60, seconds=initial_wait_s)
                    else:
                        next_close = last_start + timedelta(
                            minutes=CONFIG["candle_tf_minutes"] * 2,
                            seconds=initial_wait_s,
                        )

                if now < next_close:
                    if self._last_boundary_logged != next_close:
                        mins_left = (next_close - now).total_seconds() / 60
                        log_data.debug(
                            "⏳ Boundary cache active: holding %d bars | Next 1H bar due at %s (in %.1fm)",
                            len(self._spot_candles),
                            next_close.strftime("%H:%M:%S"),
                            mins_left,
                        )
                        self._last_boundary_logged = next_close
                    return self._spot_candles

        lookback_days = CONFIG["sma_lookback_days"]
        from_date = (now - timedelta(days=lookback_days + 5)).strftime(
            "%Y-%m-%d"
        )
        to_date = now.strftime("%Y-%m-%d %H:%M:%S")

        log_data.debug(
            "Fetching Spot 1H candles: token=%d, from=%s, to=%s",
            CONFIG["nifty_instrument_token"], from_date, to_date,
        )

        max_retries = CONFIG.get("api_max_retries", 10)
        timeout_s = CONFIG.get("api_timeout_s", 2.5)
        jitter_min = CONFIG.get("retry_jitter_min_s", 1.0)
        jitter_max = CONFIG.get("retry_jitter_max_s", 3.0)

        for attempt in range(1, max_retries + 1):
            old_timeout = getattr(self.kite, "timeout", None)
            try:
                if attempt > 1:
                    retry_delay = random.uniform(jitter_min, jitter_max)
                    log_data.debug(
                        "FETCH RETRY WAIT | label=spot_1h | attempt=%d/%d | delay=%.2fs",
                        attempt, max_retries, retry_delay
                    )
                    time.sleep(retry_delay)
                elif CONFIG.get("strategy_jitter_offset_s", 0.0) > 0:
                    time.sleep(CONFIG["strategy_jitter_offset_s"])

                self.kite.timeout = timeout_s
                candles = self.kite.historical_data(
                    instrument_token=CONFIG["nifty_instrument_token"],
                    from_date=from_date,
                    to_date=to_date,
                    interval=CONFIG["candle_tf"],
                )
                self._fetch_count += 1
                self._last_boundary_logged = None

                log_data.info(
                    "Fetched %d Spot 1H candles (attempt %d/%d, total API calls: %d)",
                    len(candles), attempt, max_retries, self._fetch_count,
                )

                if candles:
                    # Drop the currently forming candle so cache contains ONLY completed bars
                    completed = self._drop_incomplete_candle(candles)
                    if completed:
                        self._spot_candles = completed
                        self._calculate_sma()

                return self._spot_candles

            except Exception as e:
                log_data.warning(
                    "Failed to fetch Spot candles (attempt %d/%d): %s",
                    attempt, max_retries, e,
                )
                if attempt >= max_retries:
                    log_data.error(
                        "All %d attempts failed to fetch Spot candles: %s. Returning %d cached.",
                        max_retries, e, len(self._spot_candles),
                    )
                    return self._spot_candles
            finally:
                if old_timeout is not None:
                    self.kite.timeout = old_timeout

    def _drop_incomplete_candle(self, candles: List[Dict]) -> List[Dict]:
        """
        Drop the last candle if it belongs to the currently-forming window.
        A 1H candle starting at 09:15 closes at 10:15.
        The 15:15 candle closes at 15:30 (session end).
        """
        if not candles:
            return candles

        now = now_ist()
        last_candle_time = candles[-1]["date"]
        if not hasattr(last_candle_time, "tzinfo") or last_candle_time.tzinfo is None:
            last_candle_time = last_candle_time.replace(tzinfo=IST)
        else:
            last_candle_time = last_candle_time.astimezone(IST)

        if last_candle_time.time() == dtime(15, 15):
            candle_close = last_candle_time + timedelta(minutes=15)
        else:
            candle_close = last_candle_time + timedelta(minutes=CONFIG["candle_tf_minutes"])

        if now < candle_close:
            log_data.debug(
                "Dropping forming candle: %s (closes at %s, now=%s)",
                last_candle_time.strftime("%Y-%m-%d %H:%M:%S"),
                candle_close.strftime("%H:%M:%S"),
                now.strftime("%H:%M:%S"),
            )
            return candles[:-1]

        return candles

    def _calculate_sma(self) -> None:
        """
        Calculate SMA 20 and SMA 50 on Close prices.
        Attaches sma_20 and sma_50 fields to each candle dict.
        SMAs are calculated ONLY from completed candle closes.
        """
        sma_short = CONFIG["sma_short"]
        sma_long = CONFIG["sma_long"]

        closes = [c["close"] for c in self._spot_candles]

        for i, candle in enumerate(self._spot_candles):
            if i >= sma_short - 1:
                window = closes[i - sma_short + 1 : i + 1]
                candle["sma_20"] = sum(window) / len(window)
            else:
                candle["sma_20"] = None

            if i >= sma_long - 1:
                window = closes[i - sma_long + 1 : i + 1]
                candle["sma_50"] = sum(window) / len(window)
            else:
                candle["sma_50"] = None

        if self._spot_candles:
            last = self._spot_candles[-1]
            s20 = last.get("sma_20")
            s50 = last.get("sma_50")
            log_data.debug(
                "📈 Computed SMAs across %d completed bars | Latest C=%.2f, SMA20=%s, SMA50=%s",
                len(self._spot_candles),
                last["close"],
                f"{s20:.2f}" if s20 is not None else "None",
                f"{s50:.2f}" if s50 is not None else "None",
            )

    def get_completed_candles(self) -> List[Dict]:
        """
        Return completed candles (cache strictly holds completed bars).
        """
        return self._spot_candles

    def has_new_completed_candle(self) -> bool:
        """
        Returns True if the latest completed candle has a different
        timestamp than the last one we processed.
        """
        if not self._spot_candles:
            return False

        latest_time = self._spot_candles[-1]["date"]
        if self._last_candle_time is None or latest_time != self._last_candle_time:
            return True
        return False

    def mark_candle_processed(self, candle_time: datetime) -> None:
        """Mark a candle timestamp as processed to avoid re-evaluation."""
        self._last_candle_time = candle_time

    def update_spot_ltp(self, ltp: float) -> None:
        """Called by WebSocket on_ticks to update cached Spot LTP."""
        self._cached_spot_ltp = ltp
        self._spot_ltp_updated_at = now_ist()

    def get_cached_spot_ltp(self, max_age_seconds: int = None) -> Optional[float]:
        """
        Return cached Spot LTP if fresh enough.
        Returns None if cache is stale or empty.
        """
        if max_age_seconds is None:
            max_age_seconds = CONFIG["ws_stale_threshold_s"]

        if self._cached_spot_ltp is None or self._spot_ltp_updated_at is None:
            return None

        age = (now_ist() - self._spot_ltp_updated_at).total_seconds()
        if age > max_age_seconds:
            log_data.debug(
                "Spot LTP cache STALE: age=%.1fs > threshold=%ds",
                age, max_age_seconds,
            )
            return None

        return self._cached_spot_ltp

    def fetch_spot_ltp(self) -> Optional[float]:
        """REST API fallback for Spot LTP when WebSocket is stale with multi-attempt retry."""
        key = "NSE:NIFTY 50"
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                time.sleep(random.uniform(0.1, 0.3))
                data = self.kite.ltp([key])
                if key in data and data[key].get("last_price") is not None:
                    ltp = float(data[key]["last_price"])
                    if ltp > 0:
                        self.update_spot_ltp(ltp)
                        log_data.debug("REST Spot LTP fallback: %.2f (attempt %d)", ltp, attempt)
                        return ltp
            except Exception as e:
                # Secondary fallback: kite.quote()
                try:
                    time.sleep(random.uniform(0.1, 0.2))
                    qdata = self.kite.quote([key])
                    if key in qdata and qdata[key].get("last_price") is not None:
                        ltp = float(qdata[key]["last_price"])
                        if ltp > 0:
                            self.update_spot_ltp(ltp)
                            log_data.info("REST Spot LTP retrieved via quote fallback: %.2f", ltp)
                            return ltp
                except Exception:
                    pass

                log_data.warning(
                    "REST Spot LTP fetch failed (attempt %d/%d): %s",
                    attempt, max_retries, e,
                )
                if attempt < max_retries:
                    time.sleep(0.3 * (2 ** (attempt - 1)))

        log_data.error("All %d attempts to fetch REST Spot LTP failed.", max_retries)
        return None

    def fetch_option_ltp(self, tradingsymbol: str) -> Optional[float]:
        """
        Fetch current LTP for an option contract with multi-tier retries & quote fallback.
        """
        key = f"NFO:{tradingsymbol}"
        max_retries = 4
        for attempt in range(1, max_retries + 1):
            try:
                time.sleep(random.uniform(0.1, 0.3))
                # 1. Primary: kite.ltp([key])
                data = self.kite.ltp([key])
                if key in data and data[key].get("last_price") is not None:
                    ltp = float(data[key]["last_price"])
                    if ltp > 0:
                        log_data.debug("Option LTP [%s]: %.2f (attempt %d)", tradingsymbol, ltp, attempt)
                        return ltp
            except Exception as e:
                log_data.warning(
                    "Option LTP fetch attempt %d/%d failed for %s: %s",
                    attempt, max_retries, tradingsymbol, e,
                )

            # 2. Fallback: kite.quote([key])
            try:
                time.sleep(random.uniform(0.1, 0.2))
                qdata = self.kite.quote([key])
                if key in qdata and qdata[key].get("last_price") is not None:
                    ltp = float(qdata[key]["last_price"])
                    if ltp > 0:
                        log_data.info(
                            "Option LTP retrieved via quote fallback for %s: %.2f (attempt %d)",
                            tradingsymbol, ltp, attempt,
                        )
                        return ltp
            except Exception as qe:
                log_data.debug("Option quote fallback attempt %d failed for %s: %s", attempt, tradingsymbol, qe)

            if attempt < max_retries:
                time.sleep(0.3 * (2 ** (attempt - 1)))

        log_data.error("Option LTP fetch FAILED after %d attempts for %s", max_retries, tradingsymbol)
        return None


class InstrumentManager:
    """
    Loads NFO instruments, filters NIFTY PEs, and resolves ATM contracts.
    
    Weekly Expiry Classification:
      - Dedicated Weekly format: NIFTY + YY + M (1-9/O/N/D) + DD + Strike + PE
      - Monthly format: NIFTY + YY + MMM (JAN-DEC) + Strike + PE
      - On NSE, month-end expiries use the monthly contract symbol for that week's expiry.
      - Non-weekly / arbitrary expiries lacking valid weekly formats are strictly excluded.
      - 0DTE is explicitly allowed (nearest weekly expiry == today).
      - Applies ENGINEERING LIQUIDITY SAFETY CHECK (>= MIN_STRIKES_PER_EXPIRY active strikes).
      - If candidate is illiquid (< 10 strikes), logs EXPIRY_FALLBACK and evaluates next true weekly candidate.
      - If NO candidate satisfies liquidity requirements, FAILS CLOSED (raises RuntimeError).
    """

    # ENGINEERING LIQUIDITY SAFETY CHECK:
    MIN_STRIKES_PER_EXPIRY = 10

    # NSE standard contract naming conventions
    WEEKLY_SYMBOL_REGEX = re.compile(r"^NIFTY\d{2}[1-9OND]\d{2}\d+PE$")
    MONTHLY_SYMBOL_REGEX = re.compile(r"^NIFTY\d{2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d+PE$")

    def __init__(self, kite):
        self.kite = kite
        self._instruments: List[Dict] = []
        self._nifty_puts: List[Dict] = []
        self._verified_lot_size: Optional[int] = None
        self._target_expiry: Optional[date] = None
        self._weekly_expiries: List[date] = []

    def load_instruments(self) -> None:
        """
        Fetch NFO instruments, filter NIFTY PEs, verify lot size.
        Fails loudly if lot size doesn't match config.
        """
        log.info("📥 Loading NFO instruments from Kite Connect...")
        time.sleep(random.uniform(0.1, 0.4))
        self._instruments = self.kite.instruments("NFO")

        # Filter NIFTY PE options
        self._nifty_puts = [
            i for i in self._instruments
            if i.get("name") == "NIFTY"
            and i.get("instrument_type") == "PE"
            and i.get("segment") == "NFO-OPT"
        ]
        log.info("✅ Loaded %s NIFTY PE option instruments.", f"{len(self._nifty_puts):,}")

        if not self._nifty_puts:
            raise RuntimeError("No NIFTY PE contracts found in NFO instruments!")

        # Verify lot size dynamically against live broker master
        sample_lot = self._nifty_puts[0].get("lot_size", 0)
        expected_lot = CONFIG["lot_size_default"]
        if sample_lot != expected_lot:
            raise RuntimeError(
                f"LOT SIZE MISMATCH! Broker reports lot_size={sample_lot}, "
                f"config expects {expected_lot}. "
                f"Update config['lot_size_default'] and restart."
            )
        self._verified_lot_size = sample_lot
        log.info(
            "Lot size verified: %d (matches config).", self._verified_lot_size
        )

        # Determine target expiry
        self._resolve_target_expiry()

    def _get_monthly_expiry_candidates(self) -> List[date]:
        """
        Identify genuine monthly expiry dates (the last expiry date of each calendar month)
        for NIFTY PE options.
        """
        today = today_ist()
        future_puts = [i for i in self._nifty_puts if i["expiry"] >= today]
        if not future_puts:
            return []

        # Find the last expiry date for each (year, month)
        month_to_expiries = {}
        for i in future_puts:
            if self.MONTHLY_SYMBOL_REGEX.match(i["tradingsymbol"]):
                exp = i["expiry"]
                key = (exp.year, exp.month)
                if key not in month_to_expiries or exp > month_to_expiries[key]:
                    month_to_expiries[key] = exp

        return sorted(month_to_expiries.values())

    def _get_weekly_expiry_candidates(self) -> List[date]:
        """
        Identify all genuine weekly expiry dates >= today from the NFO master.
        
        Rules:
          1. Any expiry date containing dedicated weekly-formatted tradingsymbols (NIFTY26901...)
             is an explicit weekly expiry.
          2. Legitimate monthly expiries (NIFTY26AUG...) are identified by finding the maximum
             (last) expiry of each calendar month. The near month-end expiries complete the weekly cycle.
          3. Arbitrary non-weekly dates lacking weekly or valid month-end contracts are strictly excluded.
        """
        today = today_ist()
        future_puts = [i for i in self._nifty_puts if i["expiry"] >= today]
        if not future_puts:
            return []

        # 1. Dedicated weekly-formatted contracts
        weekly_expiries = set()
        for i in future_puts:
            if self.WEEKLY_SYMBOL_REGEX.match(i["tradingsymbol"]):
                weekly_expiries.add(i["expiry"])

        # 2. Legitimate calendar month-end expiries (max date of each calendar month)
        month_to_expiries = {}
        for i in future_puts:
            if self.MONTHLY_SYMBOL_REGEX.match(i["tradingsymbol"]):
                exp = i["expiry"]
                key = (exp.year, exp.month)
                if key not in month_to_expiries or exp > month_to_expiries[key]:
                    month_to_expiries[key] = exp

        # Near month-end expiries that participate in the active weekly cycle
        near_monthly_expiries = set(sorted(month_to_expiries.values())[:2])

        # Combined weekly candidate pool (chronologically sorted)
        candidates = sorted(weekly_expiries.union(near_monthly_expiries))
        return candidates

    def _resolve_target_expiry(self) -> None:
        """
        Select the target NIFTY PE expiry date based on CONFIG["expiry_preference"].

        For Monthly preference with 20th-Day Rollover:
          - If today.day <= monthly_rollover_day (20):
              Target current calendar month's monthly expiry (if >= today).
          - If today.day > monthly_rollover_day (20):
              Target next calendar month's monthly expiry.
          - Verified with MIN_STRIKES_PER_EXPIRY >= 10 liquidity safety.
        """
        today = today_ist()
        pref = CONFIG.get("expiry_preference", "monthly")

        if pref == "monthly":
            monthly_expiries = self._get_monthly_expiry_candidates()
            if not monthly_expiries:
                self._target_expiry = None
                raise RuntimeError(f"No valid monthly NIFTY PE expiries found >= {today.isoformat()}!")

            rollover_day = CONFIG.get("monthly_rollover_day", 20)
            if today.day <= rollover_day:
                # Target current month's monthly expiry >= today
                candidates = [e for e in monthly_expiries if e >= today]
            else:
                # After 20th: Skip current month, target next month's monthly expiry
                candidates = [
                    e for e in monthly_expiries
                    if (e.year > today.year) or (e.year == today.year and e.month > today.month)
                ]

            if not candidates:
                # Fallback to nearest available monthly expiry if next month is not yet published
                candidates = [e for e in monthly_expiries if e >= today]
        else:
            self._weekly_expiries = self._get_weekly_expiry_candidates()
            candidates = self._weekly_expiries

        if not candidates:
            self._target_expiry = None
            raise RuntimeError(f"No valid NIFTY PE expiries found >= {today.isoformat()}!")

        selected_expiry = None
        for idx, candidate in enumerate(candidates):
            strikes_for_cand = [
                i for i in self._nifty_puts if i["expiry"] == candidate
            ]
            strike_count = len(strikes_for_cand)

            if strike_count >= self.MIN_STRIKES_PER_EXPIRY:
                selected_expiry = candidate
                if idx > 0:
                    requested = candidates[0]
                    log.warning(
                        "EXPIRY_FALLBACK: requested=%s, selected=%s, "
                        "reason=INSUFFICIENT_STRIKES_ON_PRIMARY (had %d strikes, required >= %d)",
                        requested.isoformat(), selected_expiry.isoformat(),
                        len([i for i in self._nifty_puts if i["expiry"] == requested]),
                        self.MIN_STRIKES_PER_EXPIRY,
                    )
                break
            else:
                log.warning(
                    "Candidate expiry %s has only %d strikes (< %d minimum). Evaluating next candidate.",
                    candidate.isoformat(), strike_count, self.MIN_STRIKES_PER_EXPIRY,
                )

        # FAIL CLOSED if no expiry satisfies liquidity requirements
        if selected_expiry is None:
            self._target_expiry = None
            raise RuntimeError(
                f"EXPIRY_SELECTION_FAILED: No candidate expiry >= {today.isoformat()} "
                f"satisfies liquidity safety check (>= {self.MIN_STRIKES_PER_EXPIRY} strikes)."
            )

        self._target_expiry = selected_expiry

        log.info(
            "Target expiry resolved: %s (today=%s, day=%d, pref=%s, rollover_day=%d, strikes=%d)",
            self._target_expiry.isoformat(),
            today.isoformat(),
            today.day,
            pref,
            CONFIG.get("monthly_rollover_day", 20),
            len([i for i in self._nifty_puts if i["expiry"] == self._target_expiry]),
        )

    def get_target_expiry(self) -> Optional[date]:
        """Return the resolved target expiry date."""
        return self._target_expiry

    def get_atm_put(self, atm_strike: int) -> Optional[Dict]:
        """
        Find the exact ATM PUT contract for the given strike on the resolved target expiry.

        STRICT SPECIFICATION RULES:
        1. Exact ATM match only on resolved target_expiry.
        2. Never silently switch to another expiry.
        3. Never silently select a non-ATM strike.
        4. If the exact ATM strike is unavailable on target_expiry:
           Log error with EXPIRY_CONTRACT_UNAVAILABLE.
           Return None -> Main engine marks setup as SKIPPED.
        """
        expiry = self._target_expiry
        if expiry is None:
            log.error("get_atm_put called before target expiry resolved.")
            return None

        # Exact match on target expiry
        target_strike_int = int(round(float(atm_strike)))
        for inst in self._nifty_puts:
            inst_strike = int(round(float(inst.get("strike", 0))))
            if inst_strike == target_strike_int and inst["expiry"] == expiry:
                log_data.info(
                    "ATM PUT found: %s (strike=%d, expiry=%s, token=%d)",
                    inst["tradingsymbol"], atm_strike,
                    expiry.isoformat(), inst["instrument_token"],
                )
                return inst

        # Strict: if exact ATM strike is not listed on target expiry, fail safely
        log.error(
            "EXPIRY_CONTRACT_UNAVAILABLE: target_expiry=%s, atm_strike=%d, "
            "reason=EXACT_ATM_STRIKE_NOT_FOUND_ON_SELECTED_EXPIRY. Setup will be skipped.",
            expiry.isoformat(), atm_strike,
        )
        return None

    @property
    def lot_size(self) -> int:
        return self._verified_lot_size or CONFIG["lot_size_default"]