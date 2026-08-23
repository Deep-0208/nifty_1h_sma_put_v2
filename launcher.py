"""
launcher.py — 24/7 Bot Manager for NIFTY 1-Hour SMA PUT Strategy
Runs 24/7 as a background service (e.g., via systemd).
Responsible for starting `main.py` at 09:05 IST, monitoring it,
restarting it if it crashes, and idling outside market hours/weekends.
"""

import sys
import time
import signal
import subprocess
from pathlib import Path
from datetime import datetime, time as dtime, timedelta, timezone

# ── IST Timezone ─────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def now_ist() -> datetime:
    """Current datetime in IST."""
    return datetime.now(IST)


# ── Paths & Config ───────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
MAIN_SCRIPT = PROJECT_ROOT / "main.py"
PYTHON_BIN = sys.executable  # Automatically uses the current virtualenv

# Market morning start time (launch bot before 09:15 open)
START_TIME = dtime(9, 5)


def get_ist_datetime(target_time: dtime) -> datetime:
    """Returns today's datetime in IST with the given target time."""
    now = now_ist()
    return now.replace(
        hour=target_time.hour,
        minute=target_time.minute,
        second=0,
        microsecond=0,
    )


def main():
    """Start the launcher loop to manage the trading bot."""
    print(f"🚀 Launcher started. Managing {MAIN_SCRIPT.name}", flush=True)
    process = None
    bot_finished_date = None
    last_idle_log_date = None
    consecutive_crashes = 0
    process_start_time = None

    try:
        while True:
            now = now_ist()

            # ── 1. Check existing process status ─────────────────
            if process is not None:
                poll_result = process.poll()
                if poll_result is None:
                    # Process is currently running
                    time.sleep(10)
                    continue

                # Process has exited
                uptime_seconds = (time.time() - process_start_time) if process_start_time else 0
                if poll_result == 0:
                    print(
                        f"[{now.strftime('%H:%M:%S')}] ✅ Trading session completed successfully. "
                        f"Bot will remain idle until next market morning.",
                        flush=True,
                    )
                    bot_finished_date = now.date()
                    consecutive_crashes = 0
                else:
                    consecutive_crashes += 1
                    if uptime_seconds > 300:
                        consecutive_crashes = 1

                    delay = min(300, 10 * (2 ** min(consecutive_crashes - 1, 5)))
                    print(
                        f"[{now.strftime('%H:%M:%S')}] ⚠️ Bot crashed with exit code {poll_result} "
                        f"(crash #{consecutive_crashes})! Backing off for {delay}s...",
                        flush=True,
                    )
                    time.sleep(delay)

                process = None

            # ── 2. Process is NOT running: determine if we should start it ──

            # Weekend: skip starting new process on Sat/Sun
            if now.weekday() >= 5:  # 5=Saturday, 6=Sunday
                if last_idle_log_date != now.date():
                    print(f"[{now.strftime('%H:%M:%S')}] 🌙 Weekend. Launcher idling until Monday morning...", flush=True)
                    last_idle_log_date = now.date()
                time.sleep(300)
                continue

            start = get_ist_datetime(START_TIME)

            # Before 09:05 IST
            if now < start:
                if last_idle_log_date != now.date():
                    print(f"[{now.strftime('%H:%M:%S')}] ⏳ Pre-market. Launcher waiting until 09:05 IST...", flush=True)
                    last_idle_log_date = now.date()
                time.sleep(30)
                continue

            # Already finished for today (clean exit at market close)
            if bot_finished_date == now.date():
                if last_idle_log_date != now.date():
                    print(f"[{now.strftime('%H:%M:%S')}] 🌙 Market closed. Launcher idling until tomorrow morning...", flush=True)
                    last_idle_log_date = now.date()
                time.sleep(60)
                continue

            # Start main.py as a child process
            print(f"[{now.strftime('%H:%M:%S')}] 🟢 Starting trading bot...", flush=True)
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                creationflags = 0

            process = subprocess.Popen(
                [PYTHON_BIN, str(MAIN_SCRIPT)],
                cwd=str(PROJECT_ROOT),
                creationflags=creationflags,
            )
            process_start_time = time.time()
            time.sleep(10)

    except KeyboardInterrupt:
        print("\n🛑 Launcher manually stopped.", flush=True)
        if process and process.poll() is None:
            print("🛑 Stopping trading bot child process...", flush=True)
            try:
                if sys.platform == "win32":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    process.send_signal(signal.SIGINT)
                process.wait(timeout=30)
                print("✅ Trading bot gracefully stopped.", flush=True)
            except subprocess.TimeoutExpired:
                print("⚠️ Bot didn't stop in time. Forcing kill...", flush=True)
                process.kill()
            except Exception as e:
                print(f"⚠️ Error stopping process: {e}", flush=True)
                process.kill()
        sys.exit(0)


if __name__ == "__main__":
    main()