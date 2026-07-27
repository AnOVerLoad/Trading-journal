"""Pure trade math: avg-cost accounting, 1R, R-multiple, %P&L.

The accounting method here (moving-average cost, cost basis withdrawn
proportionally on each sell) was reverse-engineered from and verified exact
against all 46 closed historical trades already in Notion. New executions use
the textbook commission-inclusive convention: cash = gross_value + commission
for a Buy, gross_value - commission for a Sell.

No Notion or Streamlit imports here — this is pure, testable math.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def execution_cash(side: str, gross_value: float, commission: float) -> float:
    """Net cash flow for one execution: cost (Buy) or proceeds (Sell)."""
    return gross_value + commission if side == "Buy" else gross_value - commission


@dataclass
class TradeState:
    units: float = 0.0
    buy_cash_total: float = 0.0        # blended cost of ALL buys ever, never reduced by sells
    buy_units_total: float = 0.0
    remaining_cost_basis: float = 0.0  # withdrawn proportionally on sell -> drives realized P&L
    realized_pnl: float = 0.0
    buy_count: int = 0
    sell_count: int = 0
    first_buy_cash: float | None = None
    first_buy_units: float | None = None

    @property
    def avg_cost(self) -> float | None:
        return self.buy_cash_total / self.buy_units_total if self.buy_units_total else None

    def apply_buy(self, units: float, cash: float) -> None:
        self.units += units
        self.buy_cash_total += cash
        self.buy_units_total += units
        self.remaining_cost_basis += cash
        self.buy_count += 1
        if self.first_buy_cash is None:
            self.first_buy_cash = cash
            self.first_buy_units = units

    def apply_sell(self, units: float, cash: float) -> None:
        avg_now = self.remaining_cost_basis / self.units
        self.realized_pnl += cash - avg_now * units
        self.remaining_cost_basis -= avg_now * units
        self.units -= units
        self.sell_count += 1


def replay(executions: pd.DataFrame) -> TradeState:
    """Replay one trade's executions (any order) into a TradeState.

    Trusts each row's existing `cash` value rather than recomputing it from
    gross_value/commission — historical Notion rows carry their own authentic
    cash figure (with migration-era rounding this module doesn't try to
    reproduce). New rows must have `cash` populated via execution_cash()
    before being handed here.
    """
    state = TradeState()
    for _, r in executions.sort_values("date").iterrows():
        if r["side"] == "Buy":
            state.apply_buy(r["units"], r["cash"])
        else:
            state.apply_sell(r["units"], r["cash"])
    return state


def compute_1r(first_buy_cash: float, first_buy_units: float, stop: float) -> float:
    """1R = planned baht risk anchored at inception: (first buy's own avg cost - stop) * units.

    Never recomputed after scaling in — call this once, at trade creation, only.
    """
    return (first_buy_cash / first_buy_units - stop) * first_buy_units


def compute_pct_pnl(realized_pnl: float, avg_cost: float | None, shares_bought: float) -> float | None:
    if not avg_cost or not shares_bought:
        return None
    return realized_pnl / (avg_cost * shares_bought) * 100


def compute_r_multiple(realized_pnl: float, r1: float | None) -> float | None:
    if not r1 or r1 != r1:  # r1 != r1 is True only for NaN
        return None
    return realized_pnl / r1
