"""Dashboard aggregate stats — pure functions over the closed-trades DataFrame.

Mirrors the math already verified in trade_math.py and the approved dashboard
mockup (design/dashboard_mockup.html). No Notion or Streamlit imports here.
"""
from __future__ import annotations

from datetime import date

import pandas as pd


def filter_range(closed: pd.DataFrame, start: date | None, end: date | None) -> pd.DataFrame:
    df = closed
    if start is not None:
        df = df[df["close_date"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["close_date"] <= pd.Timestamp(end)]
    return df


def kpis(df: pd.DataFrame) -> dict:
    n = len(df)
    wins = df[df["realized_pnl"] >= 0]
    losses = df[df["realized_pnl"] < 0]
    win_rate = len(wins) / n if n else 0.0
    gross_profit = wins["realized_pnl"].sum()
    gross_loss = losses["realized_pnl"].sum()
    pf = gross_profit / abs(gross_loss) if gross_loss else None
    total_pnl = df["realized_pnl"].sum()
    expectancy = total_pnl / n if n else 0.0
    avg_win = wins["realized_pnl"].mean() if len(wins) else 0.0
    avg_loss = losses["realized_pnl"].mean() if len(losses) else 0.0
    denom = avg_win + abs(avg_loss)
    breakeven_wr = abs(avg_loss) / denom if denom else 0.5
    return dict(
        n=n, wins=len(wins), losses=len(losses), win_rate=win_rate, pf=pf,
        total_pnl=total_pnl, expectancy=expectancy, avg_win=avg_win, avg_loss=avg_loss,
        breakeven_wr=breakeven_wr,
    )


def equity_curve(df: pd.DataFrame) -> pd.DataFrame:
    d = df.sort_values("close_date").copy()
    d["cum_pnl"] = d["realized_pnl"].cumsum()
    d["seq"] = range(1, len(d) + 1)
    return d


def r_multiple_histogram(df: pd.DataFrame) -> pd.DataFrame:
    vals = df["r_multiple"].dropna()
    if vals.empty:
        return pd.DataFrame(columns=["bin", "count"])
    lo = int(vals.min() // 1)
    hi = int(vals.max() // 1) + 1
    bins = list(range(lo, hi + 1))
    counts = pd.cut(vals, bins=bins, right=False, include_lowest=True).value_counts().sort_index()
    return pd.DataFrame({"bin": bins[:-1], "count": counts.to_numpy()})


def setup_vs_tip(df: pd.DataFrame) -> dict:
    has_setup = df[df["setup"].notna()]
    no_setup = df[df["setup"].isna()]
    return dict(
        has_n=len(has_setup),
        has_avg=has_setup["realized_pnl"].mean() if len(has_setup) else 0.0,
        has_sum=has_setup["realized_pnl"].sum(),
        no_n=len(no_setup),
        no_avg=no_setup["realized_pnl"].mean() if len(no_setup) else 0.0,
        no_sum=no_setup["realized_pnl"].sum(),
    )


def sum_by_list_field(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Sum/count/avg realized P&L by a multi-select column (e.g. entry_context, mistakes)."""
    exploded = df.explode(col).dropna(subset=[col])
    if exploded.empty:
        return pd.DataFrame(columns=["label", "n", "sum", "avg"])
    g = exploded.groupby(col)["realized_pnl"].agg(["count", "sum", "mean"]).reset_index()
    g.columns = ["label", "n", "sum", "avg"]
    return g.sort_values("sum")


def sum_by_field(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Sum/count/avg realized P&L by a single-select column (e.g. exit_reason)."""
    d = df.dropna(subset=[col])
    if d.empty:
        return pd.DataFrame(columns=["label", "n", "sum", "avg"])
    g = d.groupby(col)["realized_pnl"].agg(["count", "sum", "mean"]).reset_index()
    g.columns = ["label", "n", "sum", "avg"]
    return g.sort_values("sum")
