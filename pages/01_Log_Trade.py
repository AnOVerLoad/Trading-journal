"""Log Trade — the screen that changes behaviour.

Two modes:
  - Open new trade: the plan-gated flow. No trade saves as "Open" without a
    stop, target, size, and a one-line thesis.
  - Add execution to open trade: scale in (Buy) or exit (Sell) an existing
    open trade. Selling down to zero shares auto-computes Result,
    R-multiple, %P&L, and moves the trade to Closed.

Every derived number (1R, avg cost, Realized P&L, %P&L, R-multiple, Result)
is computed here in Python via src/trade_math.py — never typed by hand in
Notion. See CLAUDE.md sections 2, 4, and 8.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from notion_client import Client

from src.config import ACCOUNTS, get_settings
from src.notion_sync import sync
from src.notion_write import (
    create_execution,
    create_trade,
    date_prop,
    multi_select,
    next_execution_id,
    next_trade_id,
    number,
    rich_text,
    select,
    title,
    update_page,
    update_trade,
)
from src.theme import css, register_template
from src.trade_math import compute_1r, compute_pct_pnl, compute_r_multiple, execution_cash, replay

st.set_page_config(page_title="Log Trade", page_icon="🫒", layout="wide")
register_template()
st.markdown(css(), unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner="Syncing from Notion…")
def load_data() -> dict[str, pd.DataFrame]:
    return sync()


try:
    data = load_data()
    settings = get_settings()
except Exception as exc:  # noqa: BLE001 — surface setup errors clearly
    st.error(f"Could not sync from Notion.\n\n{exc}")
    st.stop()

trades, executions = data["trades"], data["executions"]
client = Client(auth=settings.notion_token)

st.title("Log Trade")
st.caption("This is the screen that changes behaviour — no open trade saves without a plan.")

mode = st.radio("Mode", ["Open new trade", "Add execution to open trade"], horizontal=True)

setup_options = sorted(trades["setup"].dropna().unique().tolist())
entry_context_options = sorted({v for lst in trades["entry_context"].dropna() for v in lst})
symbol_options = sorted(set(trades["symbol"].dropna()) | set(data["stocks"]["symbol"].dropna()))
exit_reason_options = ["Hit target", "Hit stop", "Trailing stop", "Partial / scale-out",
                        "Bailed early (fear)", "News-driven exit"]

if mode == "Open new trade":
    st.subheader("Plan gate")
    st.caption("Stop, target, size, and a one-line thesis are required before this can save as Open.")

    from_watchlist = st.session_state.get("wl_source_page_id")
    if from_watchlist:
        st.caption(f"Prefilled from your watchlist plan for **{st.session_state.get('lt_symbol', '')}** "
                    "— edit anything the market's moved on, then add your real fill.")

    c1, c2 = st.columns(2)
    with c1:
        symbol = st.selectbox("Symbol", options=symbol_options, index=None,
                               accept_new_options=True, placeholder="e.g. PTT", key="lt_symbol")
        account = st.selectbox("Account", options=ACCOUNTS)
        entry_date = st.date_input("Entry date", value=date.today())
        entry_price = st.number_input("Entry price (฿)", min_value=0.0, step=0.01, format="%.2f")
        shares = st.number_input("Shares (size)", min_value=0, step=100)
        commission = st.number_input("Commission (฿)", min_value=0.0, step=0.01, format="%.2f")
    with c2:
        stop = st.number_input("Stop (฿)", min_value=0.0, step=0.01, format="%.2f", key="lt_stop")
        target = st.number_input("Target (฿)", min_value=0.0, step=0.01, format="%.2f", key="lt_target")
        setup = st.selectbox(
            "Setup — leave blank if this wasn't a real technical setup",
            options=setup_options, index=None, accept_new_options=True,
            placeholder="blank on purpose is fine", key="lt_setup",
        )
        entry_context = st.multiselect("Entry context — why did you press the button?",
                                        options=entry_context_options, accept_new_options=True)
        thesis = st.text_area("Thesis — one line", height=80,
                               placeholder="Why this trade, right now, in one sentence.", key="lt_thesis")

    errors = []
    if not symbol:
        errors.append("Symbol is required.")
    if not shares:
        errors.append("Shares (size) is required.")
    if not stop:
        errors.append("Stop is required.")
    if not target:
        errors.append("Target is required.")
    if not thesis or not thesis.strip():
        errors.append("A one-line thesis is required.")
    if stop and entry_price and stop >= entry_price:
        errors.append("Stop must be below entry price — that's what makes it a stop.")

    if entry_price and stop and shares and stop < entry_price:
        st.metric("Planned 1R (baht risk)", f"฿{(entry_price - stop) * shares:,.2f}")

    for e in errors:
        st.warning(e)

    if st.button("Save as Open", disabled=bool(errors), type="primary"):
        try:
            trade_id = next_trade_id(trades)
            execution_id = next_execution_id(executions)
            gross_value = entry_price * shares
            cash = execution_cash("Buy", gross_value, commission)
            r1 = compute_1r(cash, shares, stop)
            avg_cost = cash / shares

            create_execution(client, settings.executions_db_id, {
                "Execution ID": title(execution_id),
                "Trade ID": rich_text(trade_id),
                "Symbol": rich_text(symbol),
                "Account": select(account),
                "Side": select("Buy"),
                "Date": date_prop(entry_date),
                "Price": number(entry_price),
                "Units": number(shares),
                "Gross Value": number(gross_value),
                "Commission": number(commission),
                "Cash": number(cash),
            })
            create_trade(client, settings.trades_db_id, {
                "Trade ID": title(trade_id),
                "Symbol": rich_text(symbol),
                "Account": select(account),
                "Status": select("Open"),
                "Setup": select(setup),
                "Entry context": multi_select(entry_context),
                "Stop": number(stop),
                "Target": number(target),
                "Thesis": rich_text(thesis.strip()),
                "Open date": date_prop(entry_date),
                "Buy count": number(1),
                "Sell count": number(0),
                "Shares bought": number(shares),
                "Avg cost": number(avg_cost),
                "1R": number(r1),
                "Realized P&L": number(0),
            })
            if from_watchlist and settings.watchlist_db_id:
                update_page(client, from_watchlist, {
                    "Status": select("Traded"),
                    "Traded as": rich_text(trade_id),
                })
        except Exception as exc:  # noqa: BLE001
            st.error(f"Save failed — nothing was written.\n\n{exc}")
        else:
            st.cache_data.clear()
            for key in ("lt_symbol", "lt_stop", "lt_target", "lt_setup", "lt_thesis", "wl_source_page_id"):
                st.session_state.pop(key, None)
            st.success(f"{trade_id} saved as Open. Planned 1R: ฿{r1:,.2f}")
            st.rerun()

else:  # Add execution to open trade
    open_trades = trades[trades["status"] == "Open"].copy()
    if open_trades.empty:
        st.info("No open trades to add an execution to.")
        st.stop()

    def held_shares(trade_id: str) -> float:
        return replay(executions[executions["trade_id"] == trade_id]).units

    open_trades["held"] = open_trades["trade_id"].apply(held_shares)
    trade_ids = open_trades["trade_id"].tolist()
    trade_label = {
        r.trade_id: f"{r.trade_id} — {r.symbol} ({r.held:g} shares held)"
        for r in open_trades.itertuples()
    }
    # trade_id (stable) is the widget's actual value; the display text carries the
    # live share count. Keeping those separate — instead of embedding the count in
    # the option itself — means a save elsewhere can't silently swap the selection.
    trade_id = st.selectbox(
        "Open trade", options=trade_ids, index=None,
        format_func=lambda tid: trade_label.get(tid, tid),
        placeholder="Choose a trade", key="lt_exec_trade_id",
    )

    if trade_id is None:
        st.stop()

    trow = trades[trades["trade_id"] == trade_id].iloc[0]
    existing_rows = executions[executions["trade_id"] == trade_id]
    state_before = replay(existing_rows)

    def fmt_plan(v: float, decimals: int = 0) -> str:
        return "—" if pd.isna(v) else f"฿{v:,.{decimals}f}"

    c1, c2 = st.columns(2)
    with c1:
        if pd.isna(trow.stop):
            st.caption("No plan on file for this trade (predates the plan gate).")
        else:
            st.caption(f"Stop {fmt_plan(trow.stop)} · Target {fmt_plan(trow.target)} · 1R {fmt_plan(trow.r1, 2)}")
        st.caption(f"Thesis: {trow.thesis or '—'}")
        side = st.radio("Side", ["Buy", "Sell"], horizontal=True, key="lt_exec_side")
        exec_date = st.date_input("Execution date", value=date.today(), key="lt_exec_date")
        exit_reason = None
        if side == "Sell":
            exit_reason = st.selectbox("Exit reason (optional)", options=exit_reason_options,
                                        index=None, key="lt_exec_reason")
    with c2:
        price = st.number_input("Price (฿)", min_value=0.0, step=0.01, format="%.2f", key="lt_exec_price")
        units = st.number_input("Units", min_value=0, step=100, key="lt_exec_units")
        commission = st.number_input("Commission (฿)", min_value=0.0, step=0.01, format="%.2f", key="lt_exec_commission")

    errors = []
    if not price:
        errors.append("Price is required.")
    if not units:
        errors.append("Units is required.")
    if side == "Sell" and units and units > state_before.units:
        errors.append(f"Can't sell more than the {state_before.units:g} shares held.")

    for e in errors:
        st.warning(e)

    if st.button("Save execution", disabled=bool(errors), type="primary"):
        try:
            execution_id = next_execution_id(executions)
            gross_value = price * units
            cash = execution_cash(side, gross_value, commission)

            create_execution(client, settings.executions_db_id, {
                "Execution ID": title(execution_id),
                "Trade ID": rich_text(trade_id),
                "Symbol": rich_text(trow.symbol),
                "Account": select(trow.account),
                "Side": select(side),
                "Date": date_prop(exec_date),
                "Price": number(price),
                "Units": number(units),
                "Gross Value": number(gross_value),
                "Commission": number(commission),
                "Cash": number(cash),
            })

            new_row = pd.DataFrame([{
                "trade_id": trade_id, "side": side, "date": pd.Timestamp(exec_date),
                "units": units, "gross_value": gross_value, "commission": commission, "cash": cash,
            }])
            state_after = replay(pd.concat([existing_rows, new_row], ignore_index=True))

            trade_fields = {
                "Buy count": number(state_after.buy_count),
                "Sell count": number(state_after.sell_count),
                "Shares bought": number(state_after.buy_units_total),
                "Avg cost": number(state_after.avg_cost),
                "Realized P&L": number(round(state_after.realized_pnl, 2)),
            }
            if exit_reason:
                trade_fields["Exit reason"] = select(exit_reason)

            pct_pnl = compute_pct_pnl(state_after.realized_pnl, state_after.avg_cost, state_after.buy_units_total)
            if pct_pnl is not None:
                trade_fields["%P&L"] = number(round(pct_pnl, 2))
            r_mult = compute_r_multiple(state_after.realized_pnl, trow.r1)
            if r_mult is not None:
                trade_fields["R-multiple"] = number(round(r_mult, 2))

            if state_after.units <= 0:
                trade_fields["Status"] = select("Closed")
                trade_fields["Close date"] = date_prop(exec_date)
                trade_fields["Result"] = select("Win" if state_after.realized_pnl >= 0 else "Lose")
                if pd.notna(trow.open_date):
                    trade_fields["Holding period"] = number((pd.Timestamp(exec_date) - trow.open_date).days)

            update_trade(client, trow.page_id, trade_fields)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Save failed — nothing was written.\n\n{exc}")
        else:
            st.cache_data.clear()
            for key in ("lt_exec_trade_id", "lt_exec_side", "lt_exec_date", "lt_exec_reason",
                        "lt_exec_price", "lt_exec_units", "lt_exec_commission"):
                st.session_state.pop(key, None)
            msg = f"Execution saved. Realized P&L so far: ฿{state_after.realized_pnl:,.2f}"
            if state_after.units <= 0:
                msg += f" — trade closed, R-multiple {r_mult:.2f}" if r_mult is not None else " — trade closed"
            st.success(msg)
            st.rerun()
