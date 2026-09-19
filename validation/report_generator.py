"""
═════════════════════════════════════════════════════════════
  REPORT GENERATOR — Daily summaries & Monthly Reports
═════════════════════════════════════════════════════════════

Generates structured JSON, CSV, and Markdown performance reports
for the NIFTY 1-Hour SMA PUT Strategy.
"""

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import pandas as pd

# Ensure strategy root directory is in sys.path when executed directly or from subdirectories
STRATEGY_ROOT = Path(__file__).resolve().parent.parent
if str(STRATEGY_ROOT) not in sys.path:
    sys.path.insert(0, str(STRATEGY_ROOT))

from config import CONFIG, STRATEGY_DIR, LOG_DIR
from validation import storage, metrics
from validation.trade_tracker import TRADE_FIELDS
from validation.utils import format_currency, safe_divide, format_duration, normalize_exit_reason


# ═══════════════════════════════════════════════
# HISTORICAL SYNC & BACKFILL FROM JOURNAL.CSV
# ═══════════════════════════════════════════════

def sync_from_journal(force: bool = False) -> int:
    """
    Reconstruct missing validation daily folders, trades.csv,
    and summary.json from logs/journal.csv.
    """
    journal_path = LOG_DIR / "journal.csv"
    if not journal_path.exists():
        return 0

    journal_rows = storage.read_csv(journal_path)
    if not journal_rows:
        return 0

    # Group trades by date
    trades_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for r in journal_rows:
        d = r.get("date")
        if d:
            trades_by_date.setdefault(d, []).append(r)

    global_trade_idx = 1
    synced_days = 0

    for d_str, j_trades in sorted(trades_by_date.items()):
        try:
            t_date = date.fromisoformat(d_str)
        except Exception:
            continue

        daily_dir = storage.get_daily_dir(t_date)
        trades_csv = daily_dir / "trades.csv"

        if not force and trades_csv.exists() and trades_csv.stat().st_size > 50:
            existing = storage.read_csv(trades_csv)
            global_trade_idx += len(existing)
            continue

        trade_records: List[Dict[str, Any]] = []
        for r in j_trades:
            entry_time_str = r.get("entry_time", "")
            exit_time_str = r.get("exit_time", "")
            holding_str = "N/A"
            try:
                e_dt = datetime.fromisoformat(entry_time_str)
                x_dt = datetime.fromisoformat(exit_time_str)
                holding_str = format_duration(x_dt - e_dt)
            except Exception:
                pass

            pnl = float(r.get("gross_pnl", 0.0))
            raw_reason = r.get("exit_reason", "")
            norm_reason = normalize_exit_reason(raw_reason)

            entry_prem = float(r.get("entry_premium", 0.0))
            exit_prem = float(r.get("exit_premium", 0.0))
            qty = int(float(r.get("qty", 65)))

            t_rec = {
                "trade_number": global_trade_idx,
                "linked_setup_number": global_trade_idx,
                "date": d_str,
                "entry_time": entry_time_str,
                "exit_time": exit_time_str,
                "direction": r.get("direction", "PE"),
                "tradingsymbol": r.get("tradingsymbol", ""),
                "strike": float(r.get("strike", 0.0)) if r.get("strike") else "",
                "expiry": r.get("expiry", ""),
                "spot_price_at_entry": float(r.get("entry_spot", 0.0)) if r.get("entry_spot") else "",
                "spot_sl": float(r.get("spot_sl", 0.0)) if r.get("spot_sl") else "",
                "spot_target": float(r.get("spot_target", 0.0)) if r.get("spot_target") else "",
                "option_entry_premium": entry_prem,
                "quantity": qty,
                "highest_premium_reached": max(entry_prem, exit_prem),
                "lowest_premium_after_entry": min(entry_prem, exit_prem),
                "exit_premium": exit_prem,
                "spot_price_at_exit": "",
                "exit_reason": norm_reason,
                "holding_time": holding_str,
                "profit_loss": pnl,
                "winner_loser": "Winner" if pnl > 0 else "Loser",
            }
            trade_records.append(t_rec)
            global_trade_idx += 1

        storage.rewrite_csv(trades_csv, trade_records, TRADE_FIELDS)

        # Generate summary.json & summary.md for this day
        summary_gen = DailySummaryGenerator(t_date)
        cap = float(CONFIG.get("starting_capital", 100000.0))
        day_pnl = sum(t["profit_loss"] for t in trade_records)
        summary_gen.generate(opening_capital=cap, closing_capital=cap + day_pnl)
        synced_days += 1

    return synced_days


class DailySummaryGenerator:
    """Generates daily summary artifacts (JSON & Markdown) for a single session."""

    def __init__(self, trading_date: date):
        self.trading_date = trading_date
        self.daily_dir = storage.get_daily_dir(trading_date)

    def generate(self, opening_capital: float, closing_capital: float) -> Dict[str, Any]:
        """Compute metrics for the day and write daily summary files."""
        trades_rows = storage.read_csv(self.daily_dir / "trades.csv")
        setups_rows = storage.read_csv(self.daily_dir / "setups.csv")

        trades_df = pd.DataFrame(trades_rows) if trades_rows else pd.DataFrame()
        setups_df = pd.DataFrame(setups_rows) if setups_rows else pd.DataFrame()

        m = metrics.compute_all_metrics(trades_df, setups_df, opening_capital)
        net_pnl = m["net_profit"]
        return_pct = round(safe_divide(net_pnl, opening_capital) * 100, 2)

        summary_data = {
            "date": self.trading_date.isoformat(),
            "strategy": "NIFTY 1-Hour SMA PUT Strategy",
            "mode": CONFIG["trading_mode"],
            "opening_capital": opening_capital,
            "closing_capital": closing_capital,
            "net_pnl": net_pnl,
            "return_pct": return_pct,
            "metrics": m,
        }

        # Write summary.json
        storage.write_json(self.daily_dir / "summary.json", summary_data)

        # Write summary.md
        md_text = self._build_markdown(summary_data, trades_df, setups_df)
        storage.write_text(self.daily_dir / "summary.md", md_text)

        # Append to monthly daily_summaries.csv
        month_str = self.trading_date.strftime("%Y-%m")
        monthly_file = storage.MONTHLY_DIR / f"daily_summaries_{month_str}.csv"
        daily_row = {
            "date": self.trading_date.isoformat(),
            "opening_capital": opening_capital,
            "closing_capital": closing_capital,
            "net_pnl": net_pnl,
            "return_pct": return_pct,
            "total_setups": m["total_setups"],
            "total_trades": m["total_trades"],
            "win_rate": m["win_rate"],
            "profit_factor": m["profit_factor"],
        }
        storage.append_csv(
            monthly_file,
            daily_row,
            ["date", "opening_capital", "closing_capital", "net_pnl", "return_pct",
             "total_setups", "total_trades", "win_rate", "profit_factor"],
        )

        return summary_data

    def _build_markdown(
        self,
        s: Dict[str, Any],
        trades_df: pd.DataFrame,
        setups_df: pd.DataFrame,
    ) -> str:
        m = s["metrics"]
        lines = [
            f"# 📊 Daily Strategy Validation Summary — {s['date']}",
            "",
            f"**Strategy**: NIFTY 1-Hour SMA PUT Strategy | **Mode**: {s['mode']}",
            "",
            "## 💰 Capital & P&L",
            "",
            "| Metric | Value |",
            "|:---|:---|",
            f"| Opening Capital | {format_currency(s['opening_capital'])} |",
            f"| Closing Capital | {format_currency(s['closing_capital'])} |",
            f"| Net P&L | {format_currency(s['net_pnl'])} ({s['return_pct']:+.2f}%) |",
            f"| Gross Profit | {format_currency(m['gross_profit'])} |",
            f"| Gross Loss | {format_currency(m['gross_loss'])} |",
            f"| Profit Factor | {m['profit_factor']} |",
            "",
            "## 🎯 Trade Statistics",
            "",
            "| Metric | Value |",
            "|:---|:---|",
            f"| Total 1H Setups Evaluated | {m['total_setups']} |",
            f"| Trades Executed | {m['total_trades']} (Conversion: {m['conversion_rate']}%) |",
            f"| Win Rate | {m['win_rate']}% |",
            f"| Average Winner | {format_currency(m['average_winner'])} |",
            f"| Average Loser | {format_currency(m['average_loser'])} |",
            f"| Payoff Ratio | {m['payoff_ratio']} |",
            f"| Expectancy | {format_currency(m['expectancy'])} |",
            "",
        ]

        if not trades_df.empty:
            lines.append("## 📝 Executed Trades")
            lines.append("")
            lines.append("| # | Time | Contract | Strike | Entry | Exit | Spot SL | Spot Tgt | Exit Reason | P&L | Result |")
            lines.append("|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|")
            for _, r in trades_df.iterrows():
                lines.append(
                    f"| {r.get('trade_number')} | {r.get('entry_time', '')[11:16]} | "
                    f"{r.get('tradingsymbol')} | {r.get('strike')} | ₹{r.get('option_entry_premium')} | "
                    f"₹{r.get('exit_premium')} | {r.get('spot_sl')} | {r.get('spot_target')} | "
                    f"{r.get('exit_reason')} | {format_currency(float(r.get('profit_loss', 0)))} | {r.get('winner_loser')} |"
                )
            lines.append("")

        return "\n".join(lines)


class MonthlyReportGenerator:
    """Generates monthly aggregated performance reports."""

    def __init__(self, month_str: Optional[str] = None):
        self.month_str = month_str or datetime.now().strftime("%Y-%m")

    def generate(self) -> Optional[str]:
        """Aggregate all daily data for the month and output validation report."""
        # Auto-sync any trades from journal.csv
        sync_from_journal(force=False)

        if not storage.DATA_DIR.exists():
            return None

        # Find all daily folders matching this month
        if self.month_str.lower() in ("all", "all-time"):
            month_days = [d for d in storage.DATA_DIR.iterdir() if d.is_dir() and d.name != "monthly"]
        else:
            month_days = [d for d in storage.DATA_DIR.iterdir() if d.is_dir() and d.name.startswith(self.month_str)]

        if not month_days:
            return None

        all_trades = []
        all_setups = []

        for d in sorted(month_days):
            t_file = d / "trades.csv"
            s_file = d / "setups.csv"
            if t_file.exists():
                all_trades.extend(storage.read_csv(t_file))
            if s_file.exists():
                all_setups.extend(storage.read_csv(s_file))

        trades_df = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()
        setups_df = pd.DataFrame(all_setups) if all_setups else pd.DataFrame()

        m = metrics.compute_all_metrics(trades_df, setups_df, CONFIG["starting_capital"])
        report_file = storage.MONTHLY_DIR / f"validation_report_{self.month_str}.md"

        lines = [
            f"# 🏆 Monthly Strategy Validation Report — {self.month_str}",
            "",
            f"**Strategy**: NIFTY 1-Hour SMA PUT Strategy | **Mode**: {CONFIG['trading_mode']}",
            "",
            "## 📈 Performance Summary",
            "",
            "| Metric | Value |",
            "|:---|:---|",
            f"| Total Trading Days | {len(month_days)} |",
            f"| Total Setups Detected | {m['total_setups']} |",
            f"| Total Trades Taken | {m['total_trades']} |",
            f"| Win Rate | {m['win_rate']}% |",
            f"| Profit Factor | {m['profit_factor']} |",
            f"| Total Net P&L | {format_currency(m['net_profit'])} |",
            f"| Max Drawdown | {format_currency(m['max_drawdown_amount'])} ({m['max_drawdown_pct']}%) |",
            f"| Average Winner | {format_currency(m['average_winner'])} |",
            f"| Average Loser | {format_currency(m['average_loser'])} |",
            f"| Payoff Ratio | {m['payoff_ratio']} |",
            f"| Trade Expectancy | {format_currency(m['expectancy'])} |",
            f"| Max Win Streak | {m['max_consecutive_wins']} |",
            f"| Max Loss Streak | {m['max_consecutive_losses']} |",
            "",
        ]

        if not trades_df.empty:
            lines.append("## 📝 Executed Trades")
            lines.append("")
            lines.append("| # | Date | Time | Contract | Strike | Entry | Exit | Spot SL | Spot Tgt | Exit Reason | P&L | Result |")
            lines.append("|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|")
            for _, r in trades_df.iterrows():
                entry_t = str(r.get('entry_time', ''))[11:16] if str(r.get('entry_time', '')) else ''
                lines.append(
                    f"| {r.get('trade_number')} | {r.get('date')} | {entry_t} | "
                    f"{r.get('tradingsymbol')} | {r.get('strike')} | ₹{r.get('option_entry_premium')} | "
                    f"₹{r.get('exit_premium')} | {r.get('spot_sl')} | {r.get('spot_target')} | "
                    f"{r.get('exit_reason')} | {format_currency(float(r.get('profit_loss', 0)))} | {r.get('winner_loser')} |"
                )
            lines.append("")

        report_md = "\n".join(lines)
        storage.write_text(report_file, report_md)
        return report_md


if __name__ == "__main__":
    month = sys.argv[1] if len(sys.argv) > 1 else None
    gen = MonthlyReportGenerator(month)
    rep = gen.generate()
    if rep:
        print(f"✅ Monthly validation report generated successfully for {gen.month_str}:")
        print(f"   Saved to: {storage.MONTHLY_DIR / f'validation_report_{gen.month_str}.md'}\n")
        print(rep)
    else:
        print(f"⚠️ No validation data found for month '{gen.month_str}' in: {storage.DATA_DIR}")