"""
═════════════════════════════════════════════════════════════
  REPORT GENERATOR — Daily summaries & Monthly Reports
═════════════════════════════════════════════════════════════

Generates structured JSON, CSV, and Markdown performance reports
for the NIFTY 1-Hour SMA PUT Strategy.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import pandas as pd

from config import CONFIG, STRATEGY_DIR
from validation import storage, metrics
from validation.utils import format_currency, safe_divide


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
        # Find all daily folders matching this month
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

        report_md = "\n".join(lines)
        storage.write_text(report_file, report_md)
        return report_md


if __name__ == "__main__":
    import sys
    month = sys.argv[1] if len(sys.argv) > 1 else None
    gen = MonthlyReportGenerator(month)
    rep = gen.generate()
    if rep:
        print("Monthly validation report generated successfully.")
    else:
        print("No validation data found for month.")