# 🏛️ AGENTS.md — Institutional Strategy Engineering Guidelines

> **Standard Operating Procedures, Design Principles & Best Practices for Algorithmic Trading Engines**  
> *Compiled from audited production strategies (`nifty_4hr_reversal`, `nifty_30min_reversal_v2_clean`) for Zerodha Kite Connect.*

---

## 1. Core Engineering Mindset

1. **Capital Safety First**: A bug in execution or risk calculation costs real money. Every edge case must fail safely and loudly.
2. **Zero Assumptions on Network/Broker State**: APIs drop, tokens expire, rate limits trigger, orders get partial fills. Every network call must have retry logic, timeouts, and fallback state.
3. **Determinism & Reproducibility**: Log every decision, candle timestamp, indicator value, and price tick so any trade can be audited post-market.

---

## 2. Standard Institutional Architecture

Every strategy codebase must adhere to the following modular component structure:

```
strategy_root/
├── .env                         # Credentials & trading mode (NEVER commit)
├── .gitignore                   # Excludes .env, state/, logs/, venv/
├── requirements.txt             # Strict pinned dependencies
├── config.py                    # Single source of truth for ALL parameters & logging
├── login.py                     # Automated TOTP 2FA Kite login & session management
├── data.py                      # Data fetcher, caching, candle boundary & instrument lookup
├── pattern.py                   # Pure strategy logic & 1H SMA PUT signal detection
├── risk.py                      # Strike selection, Spot SL/TP calculation & sizing rules
├── orders.py                    # OrderManager (Paper & Live execution, order polling)
├── state.py                     # Atomic state persistence & crash recovery
├── telegram_alerts.py           # Real-time multi-channel notification engine
├── main.py                      # Master orchestration loop & state machine
├── launcher.py                  # 24/7 background manager for systemd deployment
├── test_audit_comprehensive.py  # Standalone comprehensive test suite (78/78 pass)
├── test_validation.py           # Dedicated validation engine test suite
└── validation/                  # Strategy Validation & Trade Analytics Subsystem
    ├── __init__.py              # Facade export (AnalyticsEngine)
    ├── analytics.py             # Central analytics coordinator (fail-safe error isolation)
    ├── setup_tracker.py         # Tracks every 1H SMA evaluation (OHLC, SMAs, Spot SL/Target)
    ├── trade_tracker.py         # Tracks trade entry, exit, MFE/MAE, P&L, holding duration
    ├── decision_tracker.py      # Logs algorithmic state transitions & decision reasons
    ├── metrics.py               # Computes Win Rate, Profit Factor, Drawdown, Expectancy
    ├── report_generator.py      # Generates Daily summaries & Monthly Markdown reports
    ├── storage.py               # Manages data persistence under validation/data/
    └── utils.py                 # Formatting, normalization, and safe math helpers
```

---

## 3. Kite Connect API & Anti-Burst Jitter Rules

### ⏱️ Rate Limits (Zerodha Kite)
* **Historical Data API**: Max 3 requests / second.
* **Quotes / LTP / Orders API**: Max 5–10 requests / second.

### 🛡️ Jitter & Burst Prevention
1. **Randomized Sleep Jitter**:
   Before any historical data or quote request, insert a small randomized jitter:
   ```python
   time.sleep(random.uniform(0.1, 0.4))
   ```
   *Why:* When multiple strategies or background workers run on the same API key, fixed sleep timers cause simultaneous bursts that trigger HTTP 429 / Rate Limit errors.

2. **Smart Boundary Caching**:
   Do **NOT** poll historical candles continuously. Only hit `kite.historical_data()` when:
   * The current candle boundary has actually completed (e.g., at `10:15:02`, `11:15:02` for 1-hour candles + a 2–3s buffer).
   * Otherwise, return the in-memory cached candle list without making an API call.

3. **Loop Polling Cadence**:
   * **When OUT of position (scanning)**: Poll every **30 seconds** (`candle_poll_interval_s = 30`).
   * **When IN position (monitoring SL/TP)**: WebSocket handles live tick-by-tick monitoring. Polling heartbeat writes every **60 seconds**.

---

## 4. Authentication & 2FA Safeguards (`login.py`)

1. **TOTP Expiration Drift Protection (`_wait_for_fresh_totp`)**:
   Standard TOTP tokens rotate every 30 seconds. If a token is generated at second 28, it might expire before reaching Zerodha servers.
   ```python
   def _wait_for_fresh_totp(safe_window_seconds=5):
       seconds_remaining = 30 - (time.time() % 30)
       if seconds_remaining < safe_window_seconds:
           time.sleep(seconds_remaining + 1)
   ```
2. **Session Reuse**:
   Validate existing `access_token` on startup via `kite.profile()`. Only execute full TOTP login if the token is missing or expired (HTTP 403).
3. **Exponential Backoff**:
   Retry login up to 3 times with `delay = base * (2 ** attempt)`.

---

## 5. Multi-Channel Logging System Standards (`config.py`)

All logging is organized under a dedicated root logger (`Nifty1HrSMA`) with daily rotating folders.

### 📂 Directory Structure
```
logs/
├── journal.csv                  # Cross-day persistent trade journal
└── YYYY-MM-DD/                  # Daily folder
    ├── strategy.log             # Main strategy flow (INFO+)
    ├── debug.log                # Full trace, API payloads, indicators (DEBUG+)
    └── candles.csv              # Raw OHLC + indicators for every closed bar
```

### ⚙️ Handler Specifications
* **Rotation**: `RotatingFileHandler` with `maxBytes = 10MB` and `backupCount = 10`.
* **Encoding**: `utf-8`.
* **Timestamps**: Explicit `IST` (UTC+05:30) in format `%(asctime)s | %(levelname)-5s | %(name)s | %(message)s`.

---

## 6. Data Management & Expiry Resolution (`data.py`)

1. **Completed vs. Forming Candle Separation**:
   * Strategy signals (SMA crosses, red candle closes) MUST ONLY be evaluated on **completed (closed)** 1H bars.
   * `candle_close_time = candle_time + timedelta(minutes=60)` must be $\le \text{now}$.
2. **Indicator Warmup Requirements**:
   * Minimum 50 completed 1-hour bars required for SMA 50. Prefetch at least 20 trading days of 1H data.
3. **Semantic Weekly Expiry Classification**:
   * Matches dedicated weekly symbols: `^NIFTY\d{2}[1-9OND]\d{2}\d+PE$`.
   * Identifies near calendar month-end expiries (`NIFTY26AUG...PE`) completing the active weekly cycle.
   * Strictly excludes non-weekly / arbitrary / distant quarterly dates.
   * Enforces fail-closed liquidity check (`>= 10` strikes).
   * 0DTE is explicitly allowed (`expiry >= today`).
4. **Dynamic Lot Size Verification**:
   * Verify live lot size against `config["lot_size_default"]` (65 for NIFTY derivatives).
   * Fail loudly if mismatch detected.

---

## 7. Strategy Logic & Risk Math (`pattern.py` & `risk.py`)

### 🎯 NIFTY 1-Hour SMA PUT Strategy Rules
1. **Signal Rules**:
   * `is_red = candle['close'] < candle['open']`
   * `below_sma20 = candle['close'] < candle['sma_20']`
   * `below_sma50 = candle['close'] < candle['sma_50']`
   * `signal = is_red and below_sma20 and below_sma50` on completed 1H bar.
2. **ATM Strike Selection**:
   * Nearest 50-point increment: `int(round(spot_price / 50.0) * 50)`
3. **Spot Stop Loss (SL)**:
   * `Spot SL = Signal_Candle['high']`
4. **Spot Target (TP)**:
   * Fixed **1:1 Risk-to-Reward Ratio** in Spot points.
   * `Spot Risk = Signal_Candle['high'] - Entry_Spot`
   * `Spot Target = Entry_Spot - Spot Risk`
5. **Trade Timing**:
   * `first_entry = 10:15:00`
   * `last_entry = 15:15:00`
   * `square_off_time = 15:20:00` (MIS Intraday)

---

## 8. State Persistence & Crash Recovery (`state.py`)

1. **Atomic Disk Writes**:
   Writes JSON state to a temporary file (`state_active.json.tmp`) and atomically replaces `state_active.json`.
2. **State Payload**:
   Persists `in_position`, `current_position`, `trades_today`, `realized_pnl_today`, `total_realized_pnl`, `cash`, `last_signal_candle_time`.
3. **Recovery Sequence**:
   On startup, loads state. If `in_position` is true, validates downtime and reconciles against live broker positions before resuming monitoring.

---

## 9. Order Management & Paper vs Live Mode (`orders.py`)

1. **Trading Mode Toggle**:
   * `CONFIG["trading_mode"] = "PAPER" | "LIVE"`
   * PAPER simulates fills at live option LTP and tracks virtual P&L.
   * LIVE executes real MARKET orders via `kite.place_order`.
2. **Double-Exit Protection**:
   * Thread lock + atomic in-memory state transition ensures an exit fires exactly once.
3. **Exit Precedence**:
   * Spot SL has strict priority over Spot Target if both are touched.
   * Force square-off at `15:20:00` for MIS intraday positions.

---

## 10. Common Mistakes & Anti-Patterns Checklist 🚫

| Anti-Pattern / Mistake | Why It Fails | Correct Solution |
| :--- | :--- | :--- |
| **Evaluating forming candle** | In-progress bar might cross SMA but pull back before close | Only evaluate completed bars (`completed_candles`) |
| **Insufficient history fetch** | 20/50 SMA will return `NaN` if warmup bars are missing | Fetch at least 20 trading days of 1H bars on startup |
| **Hardcoding lot sizes** | NSE changes lot sizes periodically; orders will be rejected | Dynamically verify lot size against broker instruments |
| **Non-atomic state saving** | Crash during write corrupts JSON file | Write to `.tmp` file and atomically rename (`os.replace`) |
| **Missing timezone info** | Comparing naive vs aware timestamps causes silent bugs | Stamp all datetimes with explicit `IST` timezone |
| **Re-entering on same signal** | Bot enters, hits SL, then re-enters on same bar | Mark candle timestamp in `last_signal_candle_time` |
| **Silent expiry fallback** | Picking illiquid or distant contracts on missing strike | Fail closed (`EXPIRY_CONTRACT_UNAVAILABLE` / skip setup) |