"""
═════════════════════════════════════════════════════════════
  METRICS — Pure calculation functions for trade analytics
═════════════════════════════════════════════════════════════

All functions are stateless and reusable. They accept pandas
DataFrames (loaded from trade/setup CSVs) and return
scalar metrics or summary dicts.
"""

from typing import Any, Dict, List, Tuple, Optional
import pandas as pd
import numpy as np

from validation.utils import safe_divide


def _to_numeric(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """Convert columns to numeric, coercing errors to NaN."""
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ─────────────────────────────────────────────
# CORE TRADE PERFORMANCE METRICS
# ─────────────────────────────────────────────

def win_rate(trades_df: pd.DataFrame) -> float:
    """Win rate as percentage (0-100)."""
    if trades_df.empty:
        return 0.0
    df = _to_numeric(trades_df, ["profit_loss"])
    wins = (df["profit_loss"] > 0).sum()
    return round(safe_divide(wins, len(df)) * 100, 2)


def loss_rate(trades_df: pd.DataFrame) -> float:
    """Loss rate as percentage (0-100)."""
    return round(100.0 - win_rate(trades_df), 2)


def average_winner(trades_df: pd.DataFrame) -> float:
    """Average P&L of winning trades."""
    if trades_df.empty:
        return 0.0
    df = _to_numeric(trades_df, ["profit_loss"])
    wins = df.loc[df["profit_loss"] > 0, "profit_loss"]
    return round(wins.mean(), 2) if not wins.empty else 0.0


def average_loser(trades_df: pd.DataFrame) -> float:
    """Average P&L of losing trades (negative number)."""
    if trades_df.empty:
        return 0.0
    df = _to_numeric(trades_df, ["profit_loss"])
    losses = df.loc[df["profit_loss"] <= 0, "profit_loss"]
    return round(losses.mean(), 2) if not losses.empty else 0.0


def largest_winner(trades_df: pd.DataFrame) -> float:
    """Largest single winning trade P&L."""
    if trades_df.empty:
        return 0.0
    df = _to_numeric(trades_df, ["profit_loss"])
    return round(df["profit_loss"].max(), 2) if not df.empty else 0.0


def largest_loser(trades_df: pd.DataFrame) -> float:
    """Largest single losing trade P&L (negative number)."""
    if trades_df.empty:
        return 0.0
    df = _to_numeric(trades_df, ["profit_loss"])
    return round(df["profit_loss"].min(), 2) if not df.empty else 0.0


def gross_profit(trades_df: pd.DataFrame) -> float:
    """Sum of all winning trades."""
    if trades_df.empty:
        return 0.0
    df = _to_numeric(trades_df, ["profit_loss"])
    return round(df.loc[df["profit_loss"] > 0, "profit_loss"].sum(), 2)


def gross_loss(trades_df: pd.DataFrame) -> float:
    """Sum of all losing trades (negative number)."""
    if trades_df.empty:
        return 0.0
    df = _to_numeric(trades_df, ["profit_loss"])
    return round(df.loc[df["profit_loss"] <= 0, "profit_loss"].sum(), 2)


def net_profit(trades_df: pd.DataFrame) -> float:
    """Total net P&L across all trades."""
    if trades_df.empty:
        return 0.0
    df = _to_numeric(trades_df, ["profit_loss"])
    return round(df["profit_loss"].sum(), 2)


def profit_factor(trades_df: pd.DataFrame) -> float:
    """Gross Profit / |Gross Loss|. Returns 0 if no losses."""
    gp = gross_profit(trades_df)
    gl = abs(gross_loss(trades_df))
    return round(safe_divide(gp, gl, default=0.0), 2)


def payoff_ratio(trades_df: pd.DataFrame) -> float:
    """Average Winner / |Average Loser|."""
    aw = average_winner(trades_df)
    al = abs(average_loser(trades_df))
    return round(safe_divide(aw, al, default=0.0), 2)


def expectancy(trades_df: pd.DataFrame) -> float:
    """Expected return per trade in rupees."""
    if trades_df.empty:
        return 0.0
    wr = win_rate(trades_df) / 100.0
    lr = 1.0 - wr
    aw = average_winner(trades_df)
    al = abs(average_loser(trades_df))
    return round((wr * aw) - (lr * al), 2)


def max_drawdown(trades_df: pd.DataFrame, initial_capital: float = 100000.0) -> Tuple[float, float]:
    """
    Calculate maximum drawdown.
    Returns (max_dd_rupees, max_dd_percentage).
    """
    if trades_df.empty:
        return 0.0, 0.0
    df = _to_numeric(trades_df, ["profit_loss"])
    equity_curve = initial_capital + df["profit_loss"].cumsum()
    peak = equity_curve.cummax()
    drawdown = peak - equity_curve
    max_dd = drawdown.max()
    max_dd_pct = (drawdown / peak).max() * 100.0 if not peak.empty else 0.0
    return round(float(max_dd), 2), round(float(max_dd_pct), 2)


def streak_counts(trades_df: pd.DataFrame) -> Tuple[int, int]:
    """Calculate (max_consecutive_wins, max_consecutive_losses)."""
    if trades_df.empty:
        return 0, 0
    df = _to_numeric(trades_df, ["profit_loss"])
    wins = (df["profit_loss"] > 0).astype(int)

    max_w = curr_w = 0
    max_l = curr_l = 0

    for w in wins:
        if w == 1:
            curr_w += 1
            curr_l = 0
        else:
            curr_l += 1
            curr_w = 0
        max_w = max(max_w, curr_w)
        max_l = max(max_l, curr_l)

    return max_w, max_l


def exit_reason_breakdown(trades_df: pd.DataFrame) -> Dict[str, int]:
    """Return count of trades per exit reason."""
    if trades_df.empty or "exit_reason" not in trades_df.columns:
        return {}
    return trades_df["exit_reason"].value_counts().to_dict()


def compute_all_metrics(
    trades_df: pd.DataFrame,
    setups_df: Optional[pd.DataFrame] = None,
    capital: float = 100000.0,
) -> Dict[str, Any]:
    """Compute a complete statistical profile."""
    total_trades = len(trades_df) if not trades_df.empty else 0
    total_setups = len(setups_df) if setups_df is not None and not setups_df.empty else 0
    max_dd_rs, max_dd_pct = max_drawdown(trades_df, capital)
    max_w_streak, max_l_streak = streak_counts(trades_df)

    return {
        "total_setups": total_setups,
        "total_trades": total_trades,
        "conversion_rate": round(safe_divide(total_trades, total_setups) * 100, 2),
        "win_rate": win_rate(trades_df),
        "loss_rate": loss_rate(trades_df),
        "profit_factor": profit_factor(trades_df),
        "payoff_ratio": payoff_ratio(trades_df),
        "expectancy": expectancy(trades_df),
        "gross_profit": gross_profit(trades_df),
        "gross_loss": gross_loss(trades_df),
        "net_profit": net_profit(trades_df),
        "average_winner": average_winner(trades_df),
        "average_loser": average_loser(trades_df),
        "largest_winner": largest_winner(trades_df),
        "largest_loser": largest_loser(trades_df),
        "max_drawdown_amount": max_dd_rs,
        "max_drawdown_pct": max_dd_pct,
        "max_consecutive_wins": max_w_streak,
        "max_consecutive_losses": max_l_streak,
        "exit_reasons": exit_reason_breakdown(trades_df),
    }