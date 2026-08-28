"""
telegram_alerts.py - Non-blocking, Fail-safe Telegram Notifications
Ported from nifty_4hr_reversal & nifty_30min_reversal standard.

Design principles:
  - NON-BLOCKING: every send runs in a background daemon thread.
  - FAIL-SAFE: any error is logged silently; the bot NEVER crashes.
  - ELEGANT FORMATTING: MarkdownV2 with dividers, emojis, and IST timestamps.
"""

import os
import threading
import requests
import logging
from typing import Any
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

from config import DOTENV_PATH

load_dotenv(DOTENV_PATH)

# -- IST timezone helper --
_IST = timezone(timedelta(hours=5, minutes=30), "IST")


def _now_ist_str() -> str:
    """Return the current time in IST formatted as a string."""
    return datetime.now(_IST).strftime("%d %b %Y, %H:%M:%S IST")


_log = logging.getLogger("Nifty1HrSMA.telegram")
STRATEGY_NAME = "NIFTY 1-Hour SMA PUT Strategy"


class TelegramAlerter:
    """
    Thread-safe, fail-safe Telegram message sender.
    All public methods fire-and-forget in a background daemon thread.
    """

    def __init__(self, token: str = "", chat_id: str = ""):
        self._token = token.strip()
        self._chat_id = chat_id.strip()
        self._enabled = bool(self._token and self._chat_id)

        if self._enabled:
            _log.info("Telegram alerts enabled (chat_id=%s)", self._chat_id)
        else:
            _log.warning(
                "Telegram alerts DISABLED - set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env."
            )

    @staticmethod
    def _escape(text: str) -> str:
        """Escape special characters for Telegram MarkdownV2."""
        special = r"\_*[]()~`>#+-=|{}.!"
        for ch in special:
            text = text.replace(ch, f"\\{ch}")
        return text

    def _send_sync(self, text: str) -> None:
        """Send a Telegram message synchronously. Logs error if it fails with fallback to plain text."""
        if not self._enabled:
            return
        try:
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            resp = requests.post(
                url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                _log.warning(
                    "Telegram API rejected MarkdownV2 (HTTP %s): %s. Retrying with plain-text fallback...",
                    resp.status_code, resp.text,
                )
                plain_text = text.replace("\\", "").replace("*", "").replace("`", "")
                requests.post(
                    url,
                    json={
                        "chat_id": self._chat_id,
                        "text": plain_text,
                    },
                    timeout=10,
                )
        except Exception as exc:
            _log.warning("Telegram send failed (non-critical): %s", exc)


    def _send_async(self, text: str) -> None:
        """Fire-and-forget: send message in a background daemon thread."""
        if not self._enabled:
            return
        t = threading.Thread(target=self._send_sync, args=(text,), daemon=True)
        t.start()

    # ---------------------------------------------------------
    # PUBLIC ALERT METHODS
    # ---------------------------------------------------------

    def bot_started(self, mode: str = "PAPER") -> None:
        """Bot Started"""
        emoji = "📝" if mode == "PAPER" else "🚀"
        msg = (
            f"✅ *Bot Started*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} Mode: `{mode}`\n"
            f"🕐 Time: `{_now_ist_str()}`\n"
            f"📈 Strategy: {self._escape(STRATEGY_NAME)}"
        )
        self._send_async(msg)

    def login_success(self, user_id: str = "") -> None:
        """Login Successful"""
        msg = (
            f"✅ *Login Successful*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User ID: `{self._escape(user_id)}`\n"
            f"🕐 Time: `{_now_ist_str()}`\n"
            f"🔗 Broker: Zerodha Kite Connect"
        )
        self._send_async(msg)

    def signal_detected(
        self,
        candle_time: Any = "",
        close: float = 0.0,
        sma_20: float = 0.0,
        sma_50: float = 0.0,
        spot_sl: float = 0.0,
    ) -> None:
        """Signal Detected Alert"""
        msg = (
            f"🚨 *Bearish Breakdown Signal*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕯️ Candle: `{self._escape(str(candle_time))}`\n"
            f"📉 Close:   `₹{close:.2f}`\n"
            f"📊 SMA 20:  `₹{sma_20:.2f}`\n"
            f"📊 SMA 50:  `₹{sma_50:.2f}`\n"
            f"🛑 Spot SL: `₹{spot_sl:.2f}` \\(Candle High\\)\n"
            f"🕐 Time:    `{_now_ist_str()}`"
        )
        self._send_async(msg)

    def trade_executed(
        self,
        symbol: str,
        entry_premium: float,
        spot_price: float,
        spot_sl: float,
        spot_target: float,
        qty: int,
        mode: str = "PAPER",
    ) -> None:
        """Trade Executed Alert"""
        spot_risk = round(spot_sl - spot_price, 2)
        spot_reward = round(spot_price - spot_target, 2)
        mode_label = "📝 PAPER" if mode == "PAPER" else "🚀 LIVE"
        msg = (
            f"✅ *Trade Executed* \\| {mode_label}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 Symbol:      `{self._escape(symbol)}`\n"
            f"📊 Direction:   `BUY PUT`\n"
            f"💰 Premium:     `₹{entry_premium:.2f}`\n"
            f"📈 Entry Spot:  `₹{spot_price:.2f}`\n"
            f"🛑 Spot SL:     `₹{spot_sl:.2f}` \\(\\+{self._escape(f'{spot_risk:.2f}')} pts\\)\n"
            f"🎯 Spot Target: `₹{spot_target:.2f}` \\(\\-{self._escape(f'{spot_reward:.2f}')} pts\\)\n"
            f"🔢 Quantity:    `{qty}`\n"
            f"🕐 Time:        `{_now_ist_str()}`"
        )
        self._send_async(msg)

    def sl_hit(
        self,
        symbol: str,
        entry_premium: float,
        exit_premium: float,
        pnl: float,
        mode: str = "PAPER",
    ) -> None:
        """Spot Stop Loss Hit Alert"""
        mode_label = "📝 PAPER" if mode == "PAPER" else "🚀 LIVE"
        pnl_sign = "+" if pnl >= 0 else "-"
        pnl_str = f"{pnl_sign}₹{abs(pnl):,.2f}"
        msg = (
            f"🛑 *Spot Stop Loss Hit* \\| {mode_label}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 Symbol:    `{self._escape(symbol)}`\n"
            f"💰 Entry:     `₹{entry_premium:.2f}`\n"
            f"🔴 Exit:      `₹{exit_premium:.2f}`\n"
            f"📉 P&L:       `{pnl_str}`\n"
            f"🕐 Time:      `{_now_ist_str()}`"
        )
        self._send_async(msg)

    def target_hit(
        self,
        symbol: str,
        entry_premium: float,
        exit_premium: float,
        pnl: float,
        mode: str = "PAPER",
    ) -> None:
        """Spot Target Hit Alert"""
        mode_label = "📝 PAPER" if mode == "PAPER" else "🚀 LIVE"
        pnl_sign = "+" if pnl >= 0 else "-"
        pnl_str = f"{pnl_sign}₹{abs(pnl):,.2f}"
        msg = (
            f"🎯 *Spot Target Hit* \\| {mode_label}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 Symbol:    `{self._escape(symbol)}`\n"
            f"💰 Entry:     `₹{entry_premium:.2f}`\n"
            f"🟢 Exit:      `₹{exit_premium:.2f}`\n"
            f"📈 P&L:       `{pnl_str}`\n"
            f"🕐 Time:      `{_now_ist_str()}`"
        )
        self._send_async(msg)

    def force_squareoff(
        self,
        symbol: str,
        entry_premium: float,
        exit_premium: float,
        pnl: float,
        reason: str = "MIS_SQUAREOFF",
        mode: str = "PAPER",
    ) -> None:
        """15:20 MIS Force Square-off Alert"""
        mode_label = "📝 PAPER" if mode == "PAPER" else "🚀 LIVE"
        pnl_sign = "+" if pnl >= 0 else "-"
        pnl_str = f"{pnl_sign}₹{abs(pnl):,.2f}"
        msg = (
            f"⏰ *MIS Force Square\\-off* \\| {mode_label}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 Symbol:    `{self._escape(symbol)}`\n"
            f"📋 Reason:    `{self._escape(reason)}`\n"
            f"💰 Entry:     `₹{entry_premium:.2f}`\n"
            f"🔶 Exit:      `₹{exit_premium:.2f}`\n"
            f"📊 P&L:       `{pnl_str}`\n"
            f"🕐 Time:      `{_now_ist_str()}`"
        )
        self._send_async(msg)

    def setup_skipped(
        self,
        reason: str,
        mode: str = "PAPER",
    ) -> None:
        """Setup Skipped Alert"""
        mode_label = "📝 PAPER" if mode == "PAPER" else "🚀 LIVE"
        msg = (
            f"🚫 *Setup Skipped* \\| {mode_label}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"❌ Reason: `{self._escape(reason)}`\n"
            f"🕐 Time:   `{_now_ist_str()}`"
        )
        self._send_async(msg)

    def day_summary(
        self,
        trades: int,
        day_pnl: float,
        total_pnl: float,
        cash: float,
    ) -> None:
        """Day-end summary"""
        day_sign = "+" if day_pnl >= 0 else "-"
        total_sign = "+" if total_pnl >= 0 else "-"
        day_str = f"{day_sign}₹{abs(day_pnl):,.2f}"
        total_str = f"{total_sign}₹{abs(total_pnl):,.2f}"
        msg = (
            f"📊 *Day\\-End Summary*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Date:      `{_now_ist_str()}`\n"
            f"🔢 Trades:    `{trades}`\n"
            f"📈 Day P&L:   `{day_str}`\n"
            f"💼 Total P&L: `{total_str}`\n"
            f"💰 Cash:      `₹{cash:,.2f}`"
        )
        self._send_sync(msg)

    def bot_crashed(self, error: str = "") -> None:
        """Bot Crashed Alert"""
        short_err = self._escape(str(error)[:300])
        msg = (
            f"❌ *Bot Crashed\\!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💥 Error: `{short_err}`\n"
            f"🕐 Time:  `{_now_ist_str()}`\n"
            f"⚠️ Manual intervention may be required\\!"
        )
        self._send_sync(msg)

    def bot_restarted(
        self,
        position_symbol: str = "",
        entry: float = 0.0,
        action: str = "resumed",
    ) -> None:
        """Bot Restarted / Orphan Position Alert"""
        msg = (
            f"✅ *Bot Restarted*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔄 Crash recovery triggered\n"
            f"📌 Position: `{self._escape(position_symbol)}`\n"
            f"💰 Entry:    `₹{entry:.2f}`\n"
            f"⚡ Action:   `{self._escape(action)}`\n"
            f"🕐 Time:     `{_now_ist_str()}`"
        )
        self._send_async(msg)

    def data_unavailable(self, symbol: str, duration_s: float) -> None:
        """Data Unavailable Force Exit Alert"""
        msg = (
            f"⚠️ *DATA UNAVAILABLE — Force Exit*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 Symbol:   `{self._escape(symbol)}`\n"
            f"⏱️ No data:  `{duration_s:.0f}s` \\(exceeded 120s limit\\)\n"
            f"🛡️ Action:   Force closing position for capital safety\n"
            f"🕐 Time:     `{_now_ist_str()}`"
        )
        self._send_async(msg)


# -- Global Singleton instance & module-level aliases --
tg = TelegramAlerter(
    token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
    chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
)

# Module-level aliases for direct imports
bot_started = tg.bot_started
login_success = tg.login_success
signal_detected = tg.signal_detected
trade_executed = tg.trade_executed
sl_hit = tg.sl_hit
target_hit = tg.target_hit
force_squareoff = tg.force_squareoff
setup_skipped = tg.setup_skipped
day_summary = tg.day_summary
bot_crashed = tg.bot_crashed
bot_restarted = tg.bot_restarted
data_unavailable = tg.data_unavailable