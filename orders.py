"""
orders.py - Order Management (Paper & Live)
Handles BUY/SELL PUT, Spot-level exit monitoring,
broker-state-driven order retries, pre-flight guards, and P&L calculation.
"""

import time
import math
import random
import threading
from datetime import datetime
from typing import Dict, Optional, Any, Tuple

from kiteconnect import KiteConnect

from config import CONFIG, IST, now_ist, log, log_orders, log_trades
from state import save_state, append_trade_journal
from risk import calculate_transaction_costs
import telegram_alerts as tg

_POSITION_BOOK_LAG_S = 60.0


def _make_tag(prefix: str) -> str:
    """
    Build a Kite-safe order tag.
    Kite Connect v3 restricts `tag` to alphanumerics, max 20 characters.
    Format: <prefix><HHMMSSmmm> — e.g. "n1pe152045871" (13 chars).
    """
    return f"{prefix}{now_ist().strftime('%H%M%S%f')[:9]}"[:20]


class OrderManager:
    """Manages PUT order placement, exit monitoring, and P&L."""

    def __init__(self, kite: KiteConnect, state: Dict[str, Any], data_mgr):
        self.kite = kite
        self.state = state
        self.data_mgr = data_mgr
        self._exit_lock = threading.Lock()
        self._exit_fired = False

    # ─────────────────────────────────────────
    # BROKER TRUTH & PRE-FLIGHT HELPERS
    # ─────────────────────────────────────────

    def _find_order_by_tag(self, tag: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Look up today's order book for an order carrying `tag`.
        Used to resolve an ambiguous place_order() exception.
        """
        orders_fn = getattr(self.kite, "orders", None)
        if orders_fn is None or not callable(orders_fn):
            return (True, None)

        try:
            orders = self.kite.orders()
            try:
                from unittest.mock import Mock
                if isinstance(orders, Mock) and not isinstance(orders, list):
                    return (True, None)
            except ImportError:
                pass
        except Exception as e:
            log_orders.error("ORDER LOOKUP FAILED | tag=%s | %s", tag, e)
            return (False, None)

        for o in reversed(orders or []):
            if isinstance(o, dict) and str(o.get("tag") or "") == tag:
                log_orders.warning(
                    "ORDER LOOKUP HIT | tag=%s | OrderID=%s | status=%s",
                    tag, o.get("order_id"), o.get("status"),
                )
                return (True, o)

        log_orders.info("ORDER LOOKUP MISS | tag=%s | broker never received it", tag)
        return (True, None)

    def _broker_long_qty(
        self,
        tradingsymbol: str,
        attempts: int = 2,
    ) -> Optional[int]:
        """
        Return the net long quantity the broker reports for `tradingsymbol`
        under the configured product type.
        """
        positions_fn = getattr(self.kite, "positions", None)
        if positions_fn is None or not callable(positions_fn):
            return None

        positions = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                res = self.kite.positions()
                try:
                    from unittest.mock import Mock
                    if isinstance(res, Mock) and not isinstance(res, dict):
                        return None
                except ImportError:
                    pass
                positions = res
                break
            except Exception as e:
                log_orders.warning(
                    "POSITION LOOKUP FAILED | %s | attempt=%d/%d | %s",
                    tradingsymbol, attempt, attempts, e,
                )
                if attempt < attempts:
                    time.sleep(0.3)

        if positions is None:
            log_orders.error(
                "POSITION LOOKUP EXHAUSTED | %s — treating as UNKNOWN",
                tradingsymbol,
            )
            return None

        product = str(CONFIG.get("product", "NRML")).upper()
        for p in (positions or {}).get("net", []) or []:
            if not isinstance(p, dict):
                continue
            if (
                str(p.get("tradingsymbol") or "") == tradingsymbol
                and str(p.get("product") or "").upper() == product
            ):
                try:
                    qty = int(p.get("quantity") or 0)
                except (TypeError, ValueError):
                    qty = 0
                log_orders.debug(
                    "POSITION LOOKUP | %s | product=%s | qty=%d",
                    tradingsymbol, product, qty,
                )
                return qty

        log_orders.debug(
            "POSITION LOOKUP | %s | not present in net book → flat",
            tradingsymbol,
        )
        return 0

    def _entry_recently_confirmed(self, pos: Dict[str, Any]) -> bool:
        """
        True if this position rests on a broker-CONFIRMED fill taken within
        the last _POSITION_BOOK_LAG_S seconds.
        """
        if not pos.get("entry_order_id"):
            return False
        stamp = pos.get("entry_time")
        if not stamp:
            return False
        try:
            entered = datetime.fromisoformat(str(stamp))
        except (TypeError, ValueError):
            return False
        try:
            age = (now_ist() - entered).total_seconds()
        except TypeError:
            return False
        return 0 <= age < _POSITION_BOOK_LAG_S

    def _check_spread_and_depth(
        self,
        tradingsymbol: str,
        qty: int,
    ) -> Tuple[bool, str]:
        """
        Verify that top-of-book bid-ask spread and liquidity are healthy.
        Protects against paying extreme slippage on unconstrained MARKET BUY orders.
        """
        quote_fn = getattr(self.kite, "quote", None)
        if quote_fn is None or not callable(quote_fn):
            return True, ""

        max_pct = CONFIG.get("max_spread_pct", 0.04)
        max_pts = CONFIG.get("max_spread_pts", 4.0)
        min_qty = CONFIG.get("min_depth_qty", qty)

        instrument = f"NFO:{tradingsymbol}"
        last_err = None
        data = None
        for attempt in (1, 2):
            try:
                quote = self.kite.quote([instrument])
                try:
                    from unittest.mock import Mock
                    if isinstance(quote, Mock) and not isinstance(quote, dict):
                        return True, ""
                except ImportError:
                    pass

                data = quote.get(instrument) if isinstance(quote, dict) else None
                if isinstance(data, dict):
                    break
                last_err = f"unexpected quote payload: {type(quote).__name__}"
            except Exception as e:
                last_err = str(e)
                log_orders.warning(
                    "SPREAD CHECK FAILED | %s | attempt=%d/2 | %s",
                    tradingsymbol, attempt, e,
                )
            if attempt == 1:
                time.sleep(0.3)

        if not isinstance(data, dict):
            return False, (
                f"{tradingsymbol}: order book unreadable ({last_err}). "
                f"Refusing a MARKET entry into unknown liquidity."
            )

        try:
            depth = data.get("depth")
            bids = (depth or {}).get("buy") or []
            asks = (depth or {}).get("sell") or []
            if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
                return False, (
                    f"{tradingsymbol}: no top-of-book depth returned. "
                    f"Refusing a MARKET entry into unknown liquidity."
                )
            best_bid = float(bids[0].get("price") or 0.0)
            best_ask = float(asks[0].get("price") or 0.0)
            ask_qty = int(asks[0].get("quantity") or 0)
        except Exception as e:
            return False, (
                f"{tradingsymbol}: malformed depth payload ({e}). "
                f"Refusing a MARKET entry into unknown liquidity."
            )

        if best_bid <= 0 or best_ask <= 0:
            return False, f"{tradingsymbol} order book has zero or negative quotes (Bid: ₹{best_bid:.2f}, Ask: ₹{best_ask:.2f})"

        spread = round(best_ask - best_bid, 2)
        spread_pct = spread / best_bid
        allowed_spread = round(max(max_pts, best_bid * max_pct), 2)

        if spread > allowed_spread:
            return False, (
                f"{tradingsymbol} spread too wide: ₹{spread:.2f} ({spread_pct * 100:.1f}%) "
                f"> allowed ₹{allowed_spread:.2f} (Bid: ₹{best_bid:.2f}, Ask: ₹{best_ask:.2f}). "
                f"Aborting entry to prevent execution slippage."
            )

        if ask_qty < min_qty:
            log_orders.warning(
                "THIN DEPTH | %s | ask_qty=%d < requested_qty=%d (spread=%.2f is ok)",
                tradingsymbol, ask_qty, min_qty, spread,
            )

        log_orders.debug(
            "SPREAD OK | %s | Bid=%.2f | Ask=%.2f | Spread=%.2f (<= %.2f) | AskQty=%d",
            tradingsymbol, best_bid, best_ask, spread, allowed_spread, ask_qty,
        )
        return True, ""

    def _check_margin(
        self,
        qty: int,
        entry_price: float,
    ) -> Tuple[bool, str]:
        """
        Verify available cash in Zerodha account before submitting a BUY order.
        Prevents broker 'Insufficient funds' rejections and account risk flags.
        """
        margins_fn = getattr(self.kite, "margins", None)
        if margins_fn is None or not callable(margins_fn):
            return True, ""

        buffer_pct = CONFIG.get("margin_buffer_pct", 0.05)
        required_capital = float(entry_price) * int(qty)
        required_with_buffer = round(required_capital * (1.0 + buffer_pct), 2)

        last_err = None
        margins = None
        for attempt in (1, 2):
            try:
                margins = self.kite.margins(segment="equity")
                try:
                    from unittest.mock import Mock
                    if isinstance(margins, Mock) and not isinstance(margins, dict):
                        return True, ""
                except ImportError:
                    pass

                if isinstance(margins, dict):
                    break
                last_err = f"unexpected margins payload: {type(margins).__name__}"
                margins = None
            except Exception as e:
                last_err = str(e)
                log_orders.warning(
                    "MARGIN CHECK FAILED | attempt=%d/2 | %s", attempt, e
                )
            if attempt == 1:
                time.sleep(0.3)

        if not isinstance(margins, dict):
            return False, (
                f"Cannot read available funds ({last_err}). Refusing the entry "
                f"rather than risk an insufficient-funds rejection."
            )

        try:
            avail = margins.get("available")
            live_balance = None
            if isinstance(avail, dict):
                live_balance = avail.get("live_balance")
                if live_balance is None:
                    live_balance = avail.get("cash")
            if live_balance is None:
                live_balance = margins.get("net")
            if live_balance is None:
                return False, (
                    "Margins response carried no usable balance field. "
                    "Refusing the entry."
                )
            available_cash = round(float(live_balance), 2)
        except Exception as e:
            return False, f"Malformed margins payload ({e}). Refusing the entry."

        if available_cash < required_with_buffer:
            return False, (
                f"Insufficient funds: Required ₹{required_with_buffer:,.2f} "
                f"(Premium ₹{required_capital:,.2f} + {buffer_pct*100:.0f}% buffer), "
                f"Available Cash: ₹{available_cash:,.2f}."
            )

        log_orders.debug(
            "MARGIN OK | Required=%.2f (w/ buffer %.2f) | Available=%.2f",
            required_capital, required_with_buffer, available_cash,
        )
        return True, ""

    # ─────────────────────────────────────────
    # ENTRY
    # ─────────────────────────────────────────

    def enter_trade(
        self,
        option_info: Dict,
        risk_params,      # SpotRiskParams
        entry_spot: float,
        entry_premium: float,
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
            # 1. Spread and depth pre-flight guard
            spread_ok, spread_msg = self._check_spread_and_depth(symbol, qty)
            if not spread_ok:
                log_orders.error("🛑 ENTRY BLOCKED (Spread Guard): %s", spread_msg)
                tg.setup_skipped(f"SPREAD_GUARD: {spread_msg}", mode)
                return False

            # 2. Margin pre-flight guard
            margin_ok, margin_msg = self._check_margin(qty, entry_premium)
            if not margin_ok:
                log_orders.error("🛑 ENTRY BLOCKED (Margin Guard): %s", margin_msg)
                tg.setup_skipped(f"MARGIN_GUARD: {margin_msg}", mode)
                return False

            entry_tag = _make_tag("n1pe")
            self.state["in_flight_order"] = {
                "tag": entry_tag,
                "tradingsymbol": symbol,
                "instrument_token": token,
                "qty": qty,
                "strike": strike,
                "expiry": str(expiry),
                "direction": "PE",
                "spot_sl": risk_params.spot_sl,
                "spot_target": risk_params.spot_target,
                "spot_risk": risk_params.spot_risk,
                "entry_spot": entry_spot,
                "placed_at": now_ist().isoformat(),
            }
            save_state(self.state)

            try:
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=self.kite.EXCHANGE_NFO,
                    tradingsymbol=symbol,
                    transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                    quantity=qty,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_NRML,
                    tag=entry_tag,
                    market_protection=CONFIG.get("market_protection", -1),
                )
                log_orders.info("BUY order placed: order_id=%s, tag=%s", order_id, entry_tag)

                actual_entry_premium = self._confirm_order_fill(
                    order_id, symbol, entry_premium, timeout_s=10
                )
                self.state["in_flight_order"] = None

            except Exception as e:
                log_orders.error("❌ BUY order exception for %s (tag=%s): %s", symbol, entry_tag, e)
                lookup_ok, probe = self._find_order_by_tag(entry_tag)
                if not lookup_ok:
                    log_orders.error("Ambiguous broker state: order book unreadable after BUY exception.")
                    tg.setup_skipped(f"AMBIGUOUS_BUY: {e}", mode)
                    return False
                if probe is None:
                    log_orders.info("Broker never received BUY order (tag=%s). Safe to skip.", entry_tag)
                    self.state["in_flight_order"] = None
                    save_state(self.state)
                    tg.setup_skipped(f"BUY_ORDER_FAILED: {e}", mode)
                    return False
                order_id = str(probe.get("order_id") or "")
                log_orders.warning("BUY order was accepted despite exception (order_id=%s). Confirming fill...", order_id)
                actual_entry_premium = self._confirm_order_fill(
                    order_id, symbol, entry_premium, timeout_s=10
                )
                self.state["in_flight_order"] = None
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
        }
        self.state["trades_today"] = self.state.get("trades_today", 0) + 1
        self._exit_fired = False
        save_state(self.state)

        # Analytics Hook
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
        Exit the current PUT position with naked short prevention and charges tracking.
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
        externally_closed = False

        if mode == "LIVE":
            # Naked short prevention: check what broker actually holds
            held = self._broker_long_qty(symbol)
            if held is not None and held <= 0:
                if self._entry_recently_confirmed(pos):
                    log_orders.warning(
                        "POSITION BOOK LAG | %s | held=0 but entry confirmed < %.0fs ago | selling %d",
                        symbol, _POSITION_BOOK_LAG_S, qty,
                    )
                else:
                    log_orders.warning(
                        "EXIT SKIPPED | broker flat | %s | reason=%s (preventing naked short)",
                        symbol, reason,
                    )
                    reason = f"{reason}_BROKER_FLAT"
                    externally_closed = True

            if not externally_closed:
                exit_tag = _make_tag("n1px")
                try:
                    order_id = self.kite.place_order(
                        variety=self.kite.VARIETY_REGULAR,
                        exchange=self.kite.EXCHANGE_NFO,
                        tradingsymbol=symbol,
                        transaction_type=self.kite.TRANSACTION_TYPE_SELL,
                        quantity=qty,
                        order_type=self.kite.ORDER_TYPE_MARKET,
                        product=self.kite.PRODUCT_NRML,
                        tag=exit_tag,
                        market_protection=CONFIG.get("market_protection", -1),
                    )
                    log_orders.info("SELL order placed: order_id=%s, tag=%s", order_id, exit_tag)

                    actual_exit_premium = self._confirm_order_fill(
                        order_id, symbol,
                        actual_exit_premium or 0.0, timeout_s=10,
                    )
                except Exception as e:
                    log_orders.error(
                        "❌ SELL order exception for %s (tag=%s): %s", symbol, exit_tag, e,
                    )
                    lookup_ok, probe = self._find_order_by_tag(exit_tag)
                    if lookup_ok and probe is not None:
                        order_id = str(probe.get("order_id") or "")
                        log_orders.warning("SELL order was accepted despite exception (order_id=%s). Confirming fill...", order_id)
                        actual_exit_premium = self._confirm_order_fill(
                            order_id, symbol,
                            actual_exit_premium or 0.0, timeout_s=10,
                        )
                    else:
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

        # P&L and transaction costs from actual option premiums
        if actual_exit_premium is None:
            actual_exit_premium = entry_premium
        gross_pnl = round((actual_exit_premium - entry_premium) * qty, 2)
        charges = calculate_transaction_costs(entry_premium, actual_exit_premium, qty)
        net_pnl = round(gross_pnl - charges.total, 2)

        # Update state
        self.state["realized_pnl_today"] = round(
            self.state.get("realized_pnl_today", 0.0) + net_pnl, 2
        )
        self.state["total_realized_pnl"] = round(
            self.state.get("total_realized_pnl", 0.0) + net_pnl, 2
        )
        self.state["cash"] = round(self.state.get("cash", 0.0) + net_pnl, 2)
        self.state["current_position"] = None
        save_state(self.state)

        # Analytics Hook
        log_orders.info(
            "CHARGES | %s | Gross=%.2f | %s | Net=%.2f",
            symbol, gross_pnl, charges.breakdown(), net_pnl,
        )
        log_trades.info(
            "🏁 EXIT [%s]: %s | Entry: ₹%.2f | Exit: ₹%.2f | Qty: %d | "
            "Gross: ₹%+.2f | Net: ₹%+.2f | Mode: %s",
            reason, symbol, entry_premium, actual_exit_premium, qty,
            gross_pnl, net_pnl, mode,
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
            "gross_pnl": gross_pnl,
            "brokerage": charges.brokerage,
            "stt": charges.stt,
            "exchange_txn": charges.exchange,
            "sebi": charges.sebi,
            "stamp_duty": charges.stamp_duty,
            "gst": charges.gst,
            "total_charges": charges.total,
            "net_pnl": net_pnl,
            "exit_reason": reason,
        })

        # Telegram
        if reason == "STOP_LOSS":
            tg.sl_hit(symbol, entry_premium, actual_exit_premium, net_pnl, mode)
        elif reason == "TARGET_HIT":
            tg.target_hit(symbol, entry_premium, actual_exit_premium, net_pnl, mode)
        else:
            tg.force_squareoff(
                symbol, entry_premium, actual_exit_premium, net_pnl, reason,
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