"""Reconciliation: prove the pulled data matches the known-good numbers.

These targets come from the deterministic prep script that produced the import CSVs.
If any check fails, the sync/extraction is wrong — fix it before building screens.
"""
from __future__ import annotations

import pandas as pd

from .config import RECON_TARGETS as T


def compute(data: dict[str, pd.DataFrame]) -> list[dict]:
    """Return a list of checks: {label, expected, actual, ok}."""
    trades = data["trades"]
    executions = data["executions"]
    stocks = data["stocks"]

    closed = trades[trades["status"] == "Closed"]
    wins = closed[closed["result"] == "Win"]
    loses = closed[closed["result"] == "Lose"]

    realized_closed = float(closed["realized_pnl"].fillna(0).sum())
    gross_profit = float(wins["realized_pnl"].fillna(0).sum())
    gross_loss = float(loses["realized_pnl"].fillna(0).sum())
    win_rate = (len(wins) / len(closed)) if len(closed) else 0.0
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss else float("inf")

    def approx(a: float, b: float, tol: float) -> bool:
        return abs(a - b) <= tol

    checks = [
        {"label": "Trades total", "expected": T["trades_total"],
         "actual": len(trades), "ok": len(trades) == T["trades_total"]},
        {"label": "Trades closed", "expected": T["trades_closed"],
         "actual": len(closed), "ok": len(closed) == T["trades_closed"]},
        {"label": "Trades open", "expected": T["trades_open"],
         "actual": len(trades) - len(closed),
         "ok": (len(trades) - len(closed)) == T["trades_open"]},
        {"label": "Executions total", "expected": T["executions_total"],
         "actual": len(executions), "ok": len(executions) == T["executions_total"]},
        {"label": "Stocks total", "expected": T["stocks_total"],
         "actual": len(stocks), "ok": len(stocks) == T["stocks_total"]},
        {"label": "Realized P&L (closed, ฿)", "expected": T["realized_closed_baht"],
         "actual": round(realized_closed, 2),
         "ok": approx(realized_closed, T["realized_closed_baht"], T["realized_tolerance"])},
        {"label": "Win rate (closed)", "expected": T["win_rate_closed"],
         "actual": round(win_rate, 3), "ok": approx(win_rate, T["win_rate_closed"], 0.01)},
        {"label": "Profit factor", "expected": T["profit_factor"],
         "actual": round(profit_factor, 2),
         "ok": approx(profit_factor, T["profit_factor"], 0.02)},
    ]
    return checks


def print_reconciliation(data: dict[str, pd.DataFrame]) -> bool:
    checks = compute(data)
    print("=" * 52)
    print("RECONCILIATION")
    print("=" * 52)
    for c in checks:
        mark = "PASS" if c["ok"] else "FAIL"
        print(f"[{mark}] {c['label']:<28} expected {c['expected']!s:>10}  got {c['actual']!s:>10}")
    all_ok = all(c["ok"] for c in checks)
    print("-" * 52)
    print("ALL CHECKS PASSED" if all_ok else ">>> SOME CHECKS FAILED — fix sync before building screens")
    print("=" * 52)
    return all_ok
