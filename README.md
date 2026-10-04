<p align="center">
  <h1 align="center">📈 NIFTY 1-Hour SMA PUT Strategy v2</h1>
  <p align="center">
    <strong>A production-grade, fully automated positional (carryforward) algorithmic trading bot for NIFTY 50 options (v2)</strong>
  </p>
  <p align="center">
    <a href="#strategy-overview">Strategy</a> •
    <a href="#features">Features</a> •
    <a href="#architecture">Architecture</a> •
    <a href="#quick-start">Quick Start</a> •
    <a href="#deployment">Deployment</a> •
    <a href="#telegram-alerts">Alerts</a>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/Broker-Zerodha_Kite-FF6600?style=for-the-badge" alt="Zerodha" />
    <img src="https://img.shields.io/badge/Mode-Paper_%7C_Live-00C853?style=for-the-badge" alt="Mode" />
    <img src="https://img.shields.io/badge/Product-NRML_Positional-8B008B?style=for-the-badge" alt="NRML" />
    <img src="https://img.shields.io/badge/Alerts-Telegram-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram" />
  </p>
</p>

---

## Strategy Overview

This bot implements an institutional **1-Hour SMA Breakdown Strategy (v2)** on the **NIFTY 50 spot index**. When a completed 1-hour candle satisfies the bearish breakdown criteria (red candle opening between the 20-period SMA and 50-period SMA, and closing below both SMAs), it automatically buys the **ATM (At-The-Money) Monthly PUT option** as a **Positional (`NRML`)** trade, carrying it overnight and managing exit triggers strictly via **Spot-Level Stop Loss and Target levels**.

### How It Works

```
Signal Chart:    NIFTY Spot  →  1-Hour Candles + SMA(20) & SMA(50)  →  Breakdown Signal Detection
Execution:       ATM Monthly PUT Option  →  Buy at Next Bar Open    →  Positional NRML Trade
Exit Triggers:   Live NIFTY Spot WebSocket LTP (Token 256265)        →  Spot SL / Spot Target / Expiry Square-Off
```

### Breakdown Signal Rules (v2) → Buy ATM Monthly PE

| Condition | Rule |
|-----------|------|
| **Candle Color** | Must be **red / bearish** (`Close < Open`) |
| **Open Between SMAs** | Completed candle opens between the SMAs (`SMA(20) < Open < SMA(50)`) |
| **SMA 20 Breakdown** | Completed candle `Close < SMA(20)` |
| **SMA 50 Breakdown** | Completed candle `Close < SMA(50)` |
| **Execution** | Trade entered at next bar open — Buy ATM Monthly PUT (`NRML`) |

### Risk & Exit Management

- **Spot Stop Loss** — High of the completed signal candle (`Spot SL = signal_candle['high']`)
- **Spot Target** — 1:1 Risk:Reward in Spot points (`Spot Target = entry_spot - (signal_candle['high'] - entry_spot)`)
- **Spot-Triggered Option Exit** — Monitored continuously via live Zerodha WebSocket ticks on NIFTY 50 Spot (`instrument_token: 256265`):
  - If `Spot LTP >= Spot SL` $\rightarrow$ **Stop Loss Triggered** (Sell PUT at market)
  - If `Spot LTP <= Spot Target` $\rightarrow$ **Target Triggered** (Sell PUT at market)
- **Contract Expiry Exit** — Exits at **15:15 IST** ONLY on the actual expiry day of the held contract.
- **Overnight Positional Carry** — Positions are held overnight and over weekends (`NRML`) until Spot SL, Target, or contract expiry is reached.
- **Monthly Expiry Rollover** — After the 20th of the current month, selects the next month's monthly expiry contract to avoid theta crush and low liquidity near delivery settlement.

---

## Features

### 🤖 Fully Automated Execution
- **Zero-touch trading** from login to exit — runs 24/7 unattended
- Automated TOTP-based 2FA login via `pyotp` with drift protection
- Mid-day session expiry auto-re-login and WebSocket token re-subscription

### 📊 1-Hour SMA Indicator Engine
- **Signal chart** — NIFTY 50 spot 60-minute broker-computed OHLC (`kite.historical_data()`)
- **SMA Warmup** — Automatically fetches 20+ trading days of historical data for accurate SMA 20 & SMA 50 calculations
- **Drop Incomplete Bars** — Drops forming/partial candles to eliminate lookahead bias

### 🎯 Spot-Level Precision Triggers
- Real-time exit monitoring directly on NIFTY Spot index ticks via KiteTicker WebSocket
- Protects against option premium decay and IV skew distortions during SL/Target evaluation

### 🛡️ Crash Safety & State Persistence
- **Single active state persistence** — `state_active.json` enables multi-day positional carries seamlessly
- **Atomic file writes** — write-to-temp $\rightarrow$ rename pattern prevents file corruption
- **Orphaned position recovery** — on restart, detects and resumes monitoring any open position
- **15-minute downtime safeguard** — checks crash duration during active trading hours

### 📝 Paper & Live Trading Modes
- **Paper mode** — simulates orders with virtual capital, tracks full P&L and cash balance
- **Live mode** — places real MARKET orders via Kite Connect with explicit safety confirmation
- Switch between modes with a single config change (`trading_mode: "PAPER"` / `"LIVE"`)

### ⏰ Market Timing Controls
- **Entry window** — 10:15 to 15:15 IST
- **Expiry Force Exit** — Exits at 15:15 IST ONLY on the contract's expiry day
- **Daily trade cap** — max 5 trades per day (resets daily, positional trades don't consume the new day's cap)

### 🔐 Safety Guards (No-Trade Conditions)
Every entry must pass all of these checks:

| Check | Description |
|-------|-------------|
| Already in position | Only one trade at a time |
| Max trades reached | Daily cap (default: 5) |
| Before first entry | No trades before 10:15 AM |
| After last entry | No trades after 3:15 PM |
| Daily loss limit | Kill-switch if cumulative realized losses exceed threshold |
| Invalid SL | Rejects if `Spot SL <= Entry Spot` |

### 📲 Telegram Real-Time Alerts
Non-blocking, fail-safe notifications for every critical event:

| Event | Alert |
|-------|-------|
| ✅ Bot Started | Mode, time, strategy name |
| ✅ Login Success | User ID, broker info |
| ✅ Trade Executed | Symbol, entry price, entry spot, Spot SL, Spot Target, quantity |
| 🛑 Spot SL Hit | Entry price, exit price, spot LTP, P&L |
| 🎯 Spot Target Hit | Entry price, exit price, spot LTP, P&L |
| ⏰ Expiry Square-off | 15:15 expiry day exit |
| 🚫 Setup Skipped | Reason for skip |
| ❌ Bot Crashed | Error message |
| 📊 Day-End Summary | Active trade status, realized P&L |

### 📝 Multi-Channel Logging
Enterprise-grade observability with dedicated log channels:

```
logs/YYYY-MM-DD/
├── strategy.log    →  Main strategy flow (INFO+)
├── debug.log       →  Full trace with module names (DEBUG+)
├── trades.log      →  Entry, exit, and P&L only
├── candles.csv     →  Every 1H candle with SMA 20/50 & pattern flags
└── network.log     →  HTTP/WebSocket traffic (isolated)

logs/
└── journal.csv     →  Persistent trade journal across all days
```

- **Rotating file handlers** — configurable max size (10 MB) with 10 backup copies
- **Third-party log isolation** — urllib3, requests, kiteconnect.ticker routed to `network.log`
- **Per-module named loggers** — `1HrSMA.pattern`, `.risk`, `.orders`, `.data`, etc.

### ✅ Built-in Validation Engine
Dedicated analytics and trade validation subsystem:
- Setup pattern recording (with breakdown flags and SMA indicators)
- Trade entry/exit metrics with spot and premium data
- Spot trigger execution auditing (MFE / MAE tracking)
- Daily summary and monthly markdown report generation

### 🚀 24/7 Launcher (Production Daemon)
A dedicated `launcher.py` manages the bot lifecycle:
- Starts `main.py` at **09:05 IST** automatically
- Monitors the process and **restarts on crash**
- Gracefully stops the bot at **15:35 IST** via `SIGINT`
- Skips weekends — idles with minimal CPU usage
- Designed for `systemd` service deployment on Linux

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    launcher.py                          │
│          24/7 daemon — starts/stops main.py             │
└──────────────────────┬──────────────────────────────────┘
                       │ spawns
┌──────────────────────▼──────────────────────────────────┐
│                     main.py                             │
│       Master orchestration loop + Kite WebSocket        │
├─────────────┬──────────┬──────────┬──────────┬──────────┤
│  login.py   │ data.py  │pattern.py│ risk.py  │orders.py │
│  Auth +     │ 1H OHLC  │ Pure fn  │ Monthly  │ Entry +  │
│  Session    │ + SMA    │ Breakdown│ Strike + │ Positional│
│  + TOTP     │ Engine   │ Detector │ Spot Math│ NRML Exit│
├─────────────┴──────────┴──────────┴──────────┴──────────┤
│  state.py              │  config.py                     │
│  Single state_active + │  All thresholds + logging      │
│  CSV trade journal     │  setup + module loggers        │
├────────────────────────┼────────────────────────────────┤
│  telegram_alerts.py    │  validation/                   │
│  Non-blocking alerts   │  Analytics engine (optional)   │
└────────────────────────┴────────────────────────────────┘
```

### Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| [config.py](config.py) | Centralized parameters, timings, and logging hierarchy |
| [login.py](login.py) | Broker authentication with auto-TOTP, retry with backoff, session caching |
| [data.py](data.py) | 1H OHLC manager, SMA 20/50 calculator, Spot LTP cache, InstrumentManager |
| [pattern.py](pattern.py) | Pure signal detection (Red candle below 20 SMA and 50 SMA) |
| [risk.py](risk.py) | Deterministic nearest-50 ATM strike, Spot SL & Spot Target math |
| [orders.py](orders.py) | OrderManager (Paper & Live), Spot-level exit monitoring, broker-state confirmation |
| [state.py](state.py) | Crash-safe atomic JSON persistence (`state_active.json`) + `journal.csv` |
| [telegram_alerts.py](telegram_alerts.py) | Thread-safe Telegram notifications — never crashes the bot |
| [main.py](main.py) | Master orchestration loop, WebSocket LTP monitoring, expiry square-off |
| [launcher.py](launcher.py) | 24/7 background process manager for `systemd` deployment |
| [test_audit_comprehensive.py](test_audit_comprehensive.py) | Standalone comprehensive test suite |
| [test_validation.py](test_validation.py) | Dedicated validation engine test suite |

---

## Quick Start

### Prerequisites

- **Python 3.10+**
- **Zerodha Kite Connect** API subscription ([kite.trade](https://kite.trade))
- **(Optional)** Telegram Bot for real-time alerts

### 1. Clone the Repository

```bash
git clone https://github.com/Deep-0208/nifty_1h_sma_put.git
cd nifty_1h_sma_put
```

### 2. Create Virtual Environment & Install Dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```env
# ── Zerodha Credentials (Required) ──
API_KEY=your_api_key_here
API_SECRET=your_api_secret_here
ACCESS_TOKEN=                        # Auto-populated after first login
ZERODHA_USER_ID=your_user_id_here
ZERODHA_PASSWORD=your_password_here
TOTP_SECRET=your_totp_secret_here    # For automated 2FA (recommended)

# ── Telegram Alerts (Optional but Recommended) ──
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

> **🔒 Security:** The `.env` file is already listed in `.gitignore` — your credentials will never be committed to version control.

### 4. Setup Telegram Alerts (Optional)

1. Message **@BotFather** on Telegram → `/newbot` → copy the **Bot Token**
2. Send any message to your new bot, then visit:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
3. Copy the `chat_id` from the response
4. Paste both values into your `.env` file
5. If not configured, the bot runs normally without alerts

### 5. Run the Bot

```bash
# Paper trading (default — safe, no real money)
python main.py

# To switch to LIVE trading, change in config.py:
# "trading_mode": "LIVE"
```

---

## Configuration

All strategy parameters are centralized in [config.py](config.py). Key settings:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `trading_mode` | `"PAPER"` | `"PAPER"` for simulation, `"LIVE"` for real orders |
| `product` | `"NRML"` | Positional trading (overnight carryforward) |
| `expiry_preference` | `"monthly"` | Selects monthly expiry contract (rolls after 20th) |
| `monthly_rollover_day` | `20` | Day of month after which next month's expiry is selected |
| `candle_tf` | `"60minute"` | Candle timeframe |
| `sma_short` | `20` | Fast Simple Moving Average period |
| `sma_long` | `50` | Slow Simple Moving Average period |
| `sma_lookback_days` | `20` | Historical trading days to fetch for indicator warmup |
| `num_lots` | `1` | Number of lots per trade |
| `lot_size_default` | `65` | Expected lot size (verified dynamically at startup) |
| `strike_step` | `50` | NIFTY option strike interval (50 points) |
| `rr_ratio` | `1.0` | Spot Risk:Reward ratio (1:1) |
| `max_trades_per_day` | `5` | Daily trade cap |
| `max_daily_loss` | `0` | Daily loss kill-switch (₹, 0 = disabled) |
| `first_entry` | `10:15` | Earliest entry time (IST) |
| `last_entry` | `15:15` | Latest entry time (IST) |
| `expiry_force_exit` | `15:15` | Unconditional square-off ONLY on contract expiry day |
| `starting_capital` | `₹100,000` | Virtual capital for paper trading |

---

## Deployment

### Deploying on Linux Server (Azure/AWS/VPS)

#### 1. Connect via SSH

```bash
ssh -i "path/to/your-key.pem" user@your-server-ip
```

#### 2. Create a systemd Service

```bash
sudo nano /etc/systemd/system/nifty-1hr-sma.service
```

Paste this configuration:

```ini
[Unit]
Description=NIFTY 1-Hour SMA PUT Strategy 24/7 Launcher
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=azureuser
Group=azureuser
WorkingDirectory=/home/azureuser/projects/nifty_1hr_sma_put

Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Kolkata

ExecStart=/home/azureuser/projects/nifty_1hr_sma_put/venv/bin/python /home/azureuser/projects/nifty_1hr_sma_put/launcher.py

Restart=always
RestartSec=10

KillMode=mixed
TimeoutStopSec=30

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

#### 3. Enable & Start the Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable nifty-1hr-sma
sudo systemctl start nifty-1hr-sma
```

#### 4. Useful Management Commands

```bash
# Check service status
sudo systemctl status nifty-1hr-sma

# View live logs
journalctl -u nifty-1hr-sma -f

# Restart the bot
sudo systemctl restart nifty-1hr-sma

# Stop the bot
sudo systemctl stop nifty-1hr-sma
```

#### 5. Updating After a Push

```bash
cd ~/projects/nifty_1hr_sma_put
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart nifty-1hr-sma
```

---

## Tech Stack

| Technology | Purpose |
|------------|---------|
| **Python 3.10+** | Core runtime |
| **[Kite Connect](https://kite.trade)** | Zerodha broker API — orders, historical data, WebSocket |
| **Pandas & NumPy** | OHLC handling, SMA 20 & SMA 50 vector calculations |
| **KiteTicker (WebSocket)** | Real-time Spot LTP monitoring for SL/Target triggers |
| **pyotp** | Automated TOTP generation for unattended 2FA |
| **python-dotenv** | Secure credential management via `.env` files |
| **requests** | HTTP client for login flow and Telegram API |

---

## Project Structure

```
nifty_1h_sma_put/
├── main.py                      # Master orchestration loop + WebSocket Spot monitor
├── config.py                    # All configuration + logging setup
├── login.py                     # Kite Connect auth + auto-TOTP
├── data.py                      # 1H OHLC data manager + SMA 20/50 indicator engine
├── pattern.py                   # Pure breakdown pattern detection (Red < SMA20 & SMA50)
├── risk.py                      # Monthly ATM strike resolution + Spot SL/Target math
├── orders.py                    # Order placement (PAPER/LIVE) + NRML positional logic
├── state.py                     # Single JSON persistence (state_active.json) + CSV journal
├── telegram_alerts.py           # Non-blocking Telegram notifications
├── launcher.py                  # 24/7 process manager (systemd)
├── nifty-1hr-sma.service        # Reference systemd service unit file
├── test_audit_comprehensive.py  # Standalone comprehensive test suite
├── test_validation.py           # Dedicated validation engine test suite
├── requirements.txt             # Python dependencies
├── .env                         # Credentials (git-ignored)
├── .gitignore
├── validation/                  # Strategy validation & analytics subsystem
│   ├── __init__.py              # Facade export (AnalyticsEngine)
│   ├── analytics.py             # Central analytics coordinator
│   ├── metrics.py               # Performance metrics calculator
│   ├── setup_tracker.py         # Pattern setup recording
│   ├── trade_tracker.py         # Trade entry/exit tracking
│   ├── decision_tracker.py      # Decision audit trail
│   ├── report_generator.py      # Daily summary reports
│   ├── storage.py               # Analytics data persistence
│   └── utils.py                 # Shared utilities
├── logs/                        # Runtime logs (git-ignored)
│   ├── YYYY-MM-DD/              # Daily log directories
│   └── journal.csv              # Persistent trade journal
└── state/                       # Runtime state files (git-ignored)
    └── state_active.json        # Positional tracking state file
```

---

## Disclaimer

> ⚠️ **This software is for educational purposes only.** Algorithmic trading involves significant financial risk. The creators of this bot are not responsible for any financial losses incurred while using this code. Always test strategies extensively using **paper trading** before risking real capital. Past performance does not guarantee future results.

---

<p align="center">
  Made with ❤️ for the Indian markets
</p>