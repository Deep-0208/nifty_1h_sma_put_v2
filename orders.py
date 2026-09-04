"""
orders.py - Order Management (Paper & Live)
Handles BUY/SELL PUT, Spot-level exit monitoring,
broker-state-driven order retries, and P&L calculation.
"""

import time
import random
import threading
from datetime import datetime
from typing import Dict, Optional, Any

from kiteconnect import KiteConnect

from config import CONFIG, IST, now_ist, log, log_orders, log_trades
from state import save_state, append_trade_journal
import telegram_alerts as tg


class OrderManager:
    """Manages PUT order placement, exit monitoring, and P&L."""

    def __init__(self, kite: KiteConnect, state: Dict[str, Any], data_mgr, analytics=None):
        self.kite = kite
        self.state = state
        self.data_mgr = data_mgr
        self.analytics = analytics
        self._exit_lock = threading.Lock()
        self._exit_fired = False

    def enter_trade(
        self,
        option_info: Dict,
        risk_params,      # SpotRiskParams
        entry_spot: float,
        entry_premium: float,
        setup_num: int = 0,
    ) -> bool:
        """
        Place a BUY MARKET order for the ATM PUT.
        """
        mode = CONFIG["trading_mode"]
        qty = self.data_mgr._instrument_mgr.lot_size * CONFIG["num_lots"] \
            if hasattr(self.data_mgr, '_instrument_mgr') else \
            CONFIG["lot_size_default"] * CONFIG["num_lots"]
        symbol = option_info["tradingsymbol"]
        token = option_info["instrument_token"]
        strike = option_info["strike"]
        expiry = option_info["expiry"]

        log_orders.info(
            "🚀 ENTRY ATTEMPT [%s]: %s | Qty: %d | Premium: ₹%.2f | "
            "Spot: %.2f | SL: %.2f | Target: %.2f",
            mode, symbol, qty, entry_premium,
            entry_spot, risk_params.spot_sl, risk_params.spot_target,
        )

        actual_entry_premium = entry_premium
        order_id = ""

        if mode == "LIVE":
            try:
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=self.kite.EXCHANGE_NFO,
                    tradingsymbol=symbol,
                    transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                    quantity=qty,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_NRML,
                )
                log_orders.info("BUY order placed: order_id=%s", order_id)

                actual_entry_premium = self._confirm_order_fill(
                    order_id, symbol, entry_premium, timeout_s=10
                )

            except Exception as e:
                log_orders.error("❌ BUY order FAILED for %s: %s", symbol, e)
                tg.setup_skipped(f"BUY_ORDER_FAILED: {e}", mode)
                return False
        else:
            order_id = f"PAPER_{int(time.time())}"
            log_orders.info("✅ PAPER BUY FILLED: %s @ ₹%.2f", symbol, entry_premium)

        # Update state
        self.state["in_position"] = True
        self.state["current_position"] = {
            "direction": "PE",
            "tradingsymbol": symbol,
            "instrument_token": token,
            "qty": qty,
            "strike": strike,
            "expiry": str(expiry),
            "entry_order_id": str(order_id),
            "entry_premium": actual_entry_premium,
            "entry_spot": entry_spot,
            "spot_sl": risk_params.spot_sl,
            "spot_target": risk_params.spot_target,
            "spot_risk": risk_params.spot_risk,
            "entry_time": now_ist().isoformat(),
            "entry_date": now_ist().date().isoformat(),
            "last_heartbeat": now_ist().isoformat(),
            "setup_num": setup_num,
        }
        self.state["trades_today"] = self.state.get("trades_today", 0) + 1
        self._exit_fired = False
        save_state(self.state)

        # Analytics Hook
        if self.analytics is not None:
            self.analytics.record_trade_entry(
                setup_num=setup_num,
                direction="PE",
                tradingsymbol=symbol,
                strike=float(strike),
                expiry=str(expiry),
                spot_price=entry_spot,
                spot_sl=risk_params.spot_sl,
                spot_target=risk_params.spot_target,
                entry_premium=actual_entry_premium,
                qty=qty,
            )

        log_trades.info(
            "🟢 ENTRY: %s | Qty: %d | Premium: ₹%.2f | Spot: %.2f | "
            "SL: %.2f | Target: %.2f | Mode: %s",
            symbol, qty, actual_entry_premium, entry_spot,
            risk_params.spot_sl, risk_params.spot_target, mode,
        )

        tg.trade_executed(
            symbol, actual_entry_premium, entry_spot,
            risk_params.spot_sl, risk_params.spot_target, qty, mode,
        )
        return True

    def check_exit_conditions_with_spot_ltp(
        self, spot_ltp: float
    ) -> Optional[str]:
        """
        Check if Spot LTP triggers SL or Target.
        """
        if not self.state.get("in_position") or not self.state.get("current_position"):
            return None

        pos = self.state["current_position"]
        spot_sl = pos["spot_sl"]
        spot_target = pos["spot_target"]

        # SL check (priority over target)
        if spot_ltp >= spot_sl:
            log_orders.info(
                "🛑 SPOT SL HIT: Spot LTP %.2f >= SL %.2f", spot_ltp, spot_sl
            )
            return "STOP_LOSS"

        # Target check
        if spot_ltp <= spot_target:
            log_orders.info(
                "🎯 SPOT TARGET HIT: Spot LTP %.2f <= Target %.2f",
                spot_ltp, spot_target,
            )
            return "TARGET_HIT"

        return None

    def exit_trade(self, reason: str, exit_premium: Optional[float] = None) -> bool:
        """
        Exit the current PUT position.
        """
        with self._exit_lock:
            if self._exit_fired:
                log_orders.warning(
                    "Double-exit blocked (already fired). Reason: %s", reason
                )
                return False
            if not self.state.get("in_position"):
                log_orders.warning(
                    "Exit called but not in position. Reason: %s", reason
                )
                return False

            self._exit_fired = True

        pos = self.state["current_position"]
        symbol = pos["tradingsymbol"]
        qty = pos["qty"]
        entry_premium = pos["entry_premium"]
        mode = CONFIG["trading_mode"]

        log_orders.info(
            "🚪 EXIT ATTEMPT [%s]: %s | Qty: %d | Reason: %s",
            mode, symbol, qty, reason,
        )

        # Atomic guard: set in_position False immediately
        self.state["in_position"] = False
        save_state(self.state)

        actual_exit_premium = exit_premium

        if mode == "LIVE":
            try:
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=self.kite.EXCHANGE_NFO,
                    tradingsymbol=symbol,
                    transaction_type=self.kite.TRANSACTION_TYPE_SELL,
                    quantity=qty,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_NRML,
                )
                log_orders.info("SELL order placed: order_id=%s", order_id)

                actual_exit_premium = self._confirm_order_fill(
                    order_id, symbol,
                    actual_exit_premium or 0.0, timeout_s=10,
                )
            except Exception as e:
                log_orders.error(
                    "❌ SELL order FAILED for %s: %s. Restoring state.", symbol, e,
                )
                self.state["in_position"] = True
                self._exit_fired = False
                save_state(self.state)
                tg.bot_crashed(f"SELL_FAILED: {symbol} - {e}")
                return False

        else:
            # Paper mode: use provided exit_premium or fetch LTP
            if actual_exit_premium is None:
                actual_exit_premium = self.data_mgr.fetch_option_ltp(symbol)
                if actual_exit_premium is None:
                    actual_exit_premium = entry_premium * 0.8
                    log_orders.warning(
                        "⚠️ Could not fetch exit LTP for %s, using estimate %.2f",
                        symbol, actual_exit_premium,
                    )
            log_orders.info(
                "✅ PAPER SELL FILLED: %s @ ₹%.2f", symbol, actual_exit_premium
            )

        # P&L from actual option premiums (not Spot points)
        gross_pnl = (actual_exit_premium - entry_premium) * qty

        # Update state
        self.state["realized_pnl_today"] = (
            self.state.get("realized_pnl_today", 0.0) + gross_pnl
        )
        self.state["total_realized_pnl"] = (
            self.state.get("total_realized_pnl", 0.0) + gross_pnl
        )
        self.state["cash"] = self.state.get("cash", 0.0) + gross_pnl
        self.state["current_position"] = None
        save_state(self.state)

        # Analytics Hook
        if self.analytics is not None:
            exit_spot = self.data_mgr.get_cached_spot_ltp() or pos.get("entry_spot", 0.0)
            self.analytics.record_trade_exit(
                exit_premium=actual_exit_premium,
                spot_price_at_exit=exit_spot,
                exit_reason=reason,
            )

        log_trades.info(
            "🏁 EXIT [%s]: %s | Entry: ₹%.2f | Exit: ₹%.2f | Qty: %d | "
            "P&L: ₹%+.2f | Mode: %s",
            reason, symbol, entry_premium, actual_exit_premium, qty,
            gross_pnl, mode,
        )

        # Journal
        append_trade_journal({
            "date": pos.get("entry_date", ""),
            "entry_time": pos.get("entry_time", ""),
            "exit_time": now_ist().isoformat(),
            "direction": "PE",
            "tradingsymbol": symbol,
            "strike": pos.get("strike", ""),
            "expiry": pos.get("expiry", ""),
            "qty": qty,
            "entry_premium": entry_premium,
            "exit_premium": actual_exit_premium,
            "entry_spot": pos.get("entry_spot", ""),
            "spot_sl": pos.get("spot_sl", ""),
            "spot_target": pos.get("spot_target", ""),
            "spot_risk": pos.get("spot_risk", ""),
            "gross_pnl": round(gross_pnl, 2),
            "exit_reason": reason,
        })

        # Telegram
        if reason == "STOP_LOSS":
            tg.sl_hit(symbol, entry_premium, actual_exit_premium, gross_pnl, mode)
        elif reason == "TARGET_HIT":
            tg.target_hit(symbol, entry_premium, actual_exit_premium, gross_pnl, mode)
        else:
            tg.force_squareoff(
                symbol, entry_premium, actual_exit_premium, gross_pnl, reason,
            )

        return True

    def update_heartbeat(self) -> None:
        """Update last_heartbeat timestamp in state (every 60s while in position)."""
        if self.state.get("in_position") and self.state.get("current_position"):
            self.state["current_position"]["last_heartbeat"] = now_ist().isoformat()
            save_state(self.state)
            log_orders.debug(
                "💓 Heartbeat saved: %s | last_hb=%s",
                self.state["current_position"].get("tradingsymbol", "?"),
                self.state["current_position"]["last_heartbeat"],
            )

    def _confirm_order_fill(
        self, order_id: str, symbol: str,
        fallback_price: float, timeout_s: int = 10,
    ) -> float:
        """
        Broker-state-driven order confirmation (FIX3).
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                time.sleep(random.uniform(0.3, 0.8))
                history = self.kite.order_history(order_id)
                if not history:
                    continue

                latest = history[-1]
                status = latest.get("status", "")

                if status == "COMPLETE":
                    avg_price = latest.get("average_price", fallback_price)
                    log_orders.info(
                        "✅ Order %s COMPLETE: avg_price=%.2f", order_id, avg_price
                    )
                    return avg_price

                elif status == "REJECTED":
                    reason = latest.get("status_message", "Unknown")
                    log_orders.error(
                        "❌ Order %s REJECTED: %s", order_id, reason
                    )
                    raise RuntimeError(
                        f"Order {order_id} REJECTED: {reason}"
                    )

                elif status in ("CANCELLED", "CANCEL PENDING"):
                    log_orders.error("❌ Order %s CANCELLED", order_id)
                    raise RuntimeError(f"Order {order_id} CANCELLED")

                else:
                    log_orders.debug(
                        "Order %s status=%s, waiting...", order_id, status
                    )

            except RuntimeError:
                raise
            except Exception as e:
                log_orders.warning(
                    "Error polling order %s: %s", order_id, e
                )

        log_orders.warning(
            "Order %s: timed out after %ds. Using fallback price %.2f",
            order_id, timeout_s, fallback_price,
        )
        return fallback_price

    def query_broker_position(self, symbol: str) -> Optional[Dict]:
        """Query broker for actual position state."""
        try:
            time.sleep(random.uniform(0.1, 0.4))
            positions = self.kite.positions()
            day_positions = positions.get("day", [])
            net_positions = positions.get("net", [])

            for pos in day_positions + net_positions:
                if pos.get("tradingsymbol") == symbol and pos.get("quantity", 0) != 0:
                    log_orders.info(
                        "✅ Broker position found: %s Qty: %d",
                        symbol, pos["quantity"],
                    )
                    return pos

            log_orders.info("No open broker position for %s", symbol)
            return None

        except Exception as e:
            log_orders.error("Failed to query broker positions: %s", e)
            return None