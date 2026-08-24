# 📈 NIFTY 1-Hour SMA PUT Strategy

**A production-grade, fully automated positional (carryforward) algorithmic trading bot for NIFTY 50 options**

---

## Strategy Overview

This bot implements an institutional **1-Hour SMA Breakdown Strategy** on the **NIFTY 50 spot index**. When a valid bearish breakdown candle completes, it automatically buys the **ATM (At-The-Money) Monthly PUT option** (`NRML` carryforward) and monitors the trade via **Spot-Level Stop Loss and Target triggers**.

```
Signal Source:     NIFTY Spot 1H completed candles (Red + Close < SMA20 + Close < SMA50)
Trigger Source:    NIFTY Spot live WebSocket LTP (token 256265)
Execution:         ATM Monthly PUT Option (BUY on entry, SELL on exit)
Product Type:      NRML (Positional Carryforward)
Expiry Rule:       Monthly expiry (after 20th of the month, rolls to next month's contract)
Max Trades/Day:    5
Spot SL:           Signal Candle High
Spot Target:       Entry Spot - (Signal Candle High - Entry Spot) [1:1 R:R in Spot points]
Expiry Exit:       15:15 IST (Only on contract expiry day)
P&L:               (Exit Premium - Entry Premium) × Quantity
```

---

## Server Deployment & Hosting Guide

Based on the institutional standard used across all strategies in this suite, this bot is designed to run **24/7 as an unattended background service** on a Linux Cloud Server (AWS EC2, Azure VM, DigitalOcean Droplet, or any VPS).

### Hosting Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Linux systemd Service                │
│         /etc/systemd/system/nifty-1hr-sma.service       │
└──────────────────────────┬──────────────────────────────┘
                           │ manages
┌──────────────────────────▼──────────────────────────────┐
│                      launcher.py                        │
│   24/7 daemon — starts main.py at 09:05 IST, restarts   │
│   on crashes, idles outside market hours & weekends     │
└──────────────────────────┬──────────────────────────────┘
                           │ spawns child process
┌──────────────────────────▼──────────────────────────────┐
│                        main.py                          │
│   Master execution loop + WebSocket + Order Engine      │
└─────────────────────────────────────────────────────────┘
```

---

### Step-by-Step Server Setup

#### 1. Connect to Your Linux Server via SSH

```bash
ssh -i "path/to/your-key.pem" user@your-server-ip
```

#### 2. Install Prerequisites & Setup Directory

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv git

# Navigate to project directory
mkdir -p ~/projects
cd ~/projects
# Clone or copy the strategy folder here:
# cd ~/projects/"NIFTY 1-Hour SMA PUT Strategy"
```

#### 3. Create Virtual Environment & Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. Configure `.env` on Server

```bash
nano .env
```

Paste your Zerodha & Telegram credentials:

```env
API_KEY=your_api_key_here
API_SECRET=your_api_secret_here
ACCESS_TOKEN=
ZERODHA_USER_ID=your_user_id_here
ZERODHA_PASSWORD=your_password_here
TOTP_SECRET=your_totp_secret_here

TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

#### 5. Configure `systemd` Service

Create a systemd unit file:

```bash
sudo nano /etc/systemd/system/nifty-1hr-sma.service
```

Paste the following configuration (adjust paths and user as appropriate):

```ini
[Unit]
Description=NIFTY 1-Hour SMA PUT Strategy Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=azureuser
Group=azureuser
WorkingDirectory=/home/azureuser/projects/NIFTY 1-Hour SMA PUT Strategy

Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Kolkata

ExecStart=/home/azureuser/projects/NIFTY 1-Hour SMA PUT Strategy/venv/bin/python "/home/azureuser/projects/NIFTY 1-Hour SMA PUT Strategy/launcher.py"

Restart=always
RestartSec=10

# Graceful shutdown (sends SIGINT so bot can close open positions cleanly if needed)
KillSignal=SIGINT
TimeoutStopSec=30

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

#### 6. Enable & Start the Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable nifty-1hr-sma
sudo systemctl start nifty-1hr-sma
```

---

### Service Management Commands

```bash
# Check service status
sudo systemctl status nifty-1hr-sma

# Stream live console logs
journalctl -u nifty-1hr-sma -f

# View recent strategy logs
tail -f logs/$(date +%Y-%m-%d)/strategy.log

# Restart the service
sudo systemctl restart nifty-1hr-sma

# Stop the service
sudo systemctl stop nifty-1hr-sma
```

---

### Updating the Code on Server

```bash
cd ~/projects/"NIFTY 1-Hour SMA PUT Strategy"
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart nifty-1hr-sma
```

---

## Key Modules

| Module | Responsibility |
|:---|:---|
| [`config.py`](config.py) | Centralized parameters, timings, and 7-channel logging hierarchy |
| [`login.py`](login.py) | Auto-login with TOTP 2FA, drift prevention, and retry backoff |
| [`data.py`](data.py) | 1H OHLC data manager, SMA 20/50, Spot LTP cache, InstrumentManager |
| [`pattern.py`](pattern.py) | Pure signal detection (Red candle below 20 SMA and 50 SMA) |
| [`risk.py`](risk.py) | Deterministic nearest-50 ATM strike, Spot SL & Spot Target math |
| [`orders.py`](orders.py) | OrderManager (Paper & Live), Spot-level exit monitoring, broker-state confirmation |
| [`state.py`](state.py) | Crash-safe atomic JSON persistence (`state_active.json`) + `journal.csv` |
| [`telegram_alerts.py`](telegram_alerts.py) | 12 real-time non-blocking alert types via daemon threads |
| [`main.py`](main.py) | Master orchestration loop, WebSocket LTP monitoring, 15:20 MIS square-off |
| [`launcher.py`](launcher.py) | 24/7 background process manager for `systemd` deployment |
| [`test_audit_comprehensive.py`](test_audit_comprehensive.py) | 67-test standalone verification suite |