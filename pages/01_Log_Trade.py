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
    archive_page,
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
from src.trade_math import (
    TradeState,
    compute_1r,
    compute_pct_pnl,
    compute_r_multiple,
    execution_cash,
    replay,
)


def join_fields(names: list[str]) -> str:
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def recompute_trade_fields(state: TradeState, trow, close_date) -> dict:
    """Trade fields to write given a fresh replay of a (possibly corrected) execution set.

    Handles both directions: closes a trade that just sold down to zero (as
    "Add execution" mode always has), and reopens one whose correction means
    it's no longer flat — the piece "Add execution" never needed.
    """
    fields = {
        "Buy count": number(state.buy_count),
        "Sell count": number(state.sell_count),
        "Shares bought": number(state.buy_units_total),
        "Avg cost": number(state.avg_cost),
        "Realized P&L": number(round(state.realized_pnl, 2)),
    }
    pct_pnl = compute_pct_pnl(state.realized_pnl, state.avg_cost, state.buy_units_total)
    if pct_pnl is not None:
        fields["%P&L"] = number(round(pct_pnl, 2))
    r_mult = compute_r_multiple(state.realized_pnl, trow.r1)
    if r_mult is not None:
        fields["R-multiple"] = number(round(r_mult, 2))

    if state.units > 0:
        if trow.status == "Closed":
            fields["Status"] = select("Open")
            fields["Close date"] = date_prop(None)
            fields["Result"] = select(None)
            fields["Holding period"] = number(None)
    else:
        fields["Status"] = select("Closed")
        fields["Close date"] = date_prop(close_date)
        fields["Result"] = select("Win" if state.realized_pnl >= 0 else "Lose")
        if pd.notna(trow.open_date) and close_date is not None:
            fields["Holding period"] = number((pd.Timestamp(close_date) - trow.open_date).days)
    return fields


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

mode = st.radio(
    "Mode", ["Open new trade", "Add execution to open trade", "Correct a trade"],
    horizontal=True, key="lt_mode",
)

setup_options = sorted(trades["setup"].dropna().unique().tolist())
entry_context_options = sorted({v for lst in trades["entry_context"].dropna() for v in lst})
symbol_options = sorted(set(trades["symbol"].dropna()) | set(data["stocks"]["symbol"].dropna()))
exit_reason_options = ["Hit target", "Hit stop", "Trailing stop", "Partial / scale-out",
                        "Bailed early (fear)", "News-driven exit"]
mistakes_options = sorted({v for lst in trades["mistakes"].dropna() for v in lst})
if not mistakes_options:
    mistakes_options = ["Held loser past stop", "Ignored plan", "Held winner too long",
                         "Cut winner early", "Chased entry"]

if mode == "Open new trade":
    st.subheader("Plan gate")
    st.caption("Stop, target, size, and a one-line thesis are required before this can save as Open.")

    # Every widget key below is suffixed with this generation number. Bumping
    # it after a successful save forces Streamlit to mount brand-new widget
    # instances next render — a plain st.session_state.pop() of the old keys
    # wasn't reliably enough to reset every field (unkeyed widgets kept their
    # value via positional identity, and even keyed ones could show stale
    # text left over from the previous fill).
    gen = st.session_state.get("lt_new_trade_gen", 0)

    from_watchlist = st.session_state.get("wl_source_page_id")
    if from_watchlist:
        # One-time bridge: Watchlist's "Trade this →" handoff writes to these
        # fixed key names before switch_page(); copy them into this
        # generation's actual widget keys, then consume them so a later
        # generation (e.g. after Save) doesn't pick up stale prefill data.
        for base_key, field_key in (
            ("lt_symbol", f"lt_symbol_{gen}"), ("lt_stop", f"lt_stop_{gen}"),
            ("lt_target", f"lt_target_{gen}"), ("lt_setup", f"lt_setup_{gen}"),
            ("lt_thesis", f"lt_thesis_{gen}"),
        ):
            if base_key in st.session_state:
                st.session_state[field_key] = st.session_state.pop(base_key)
        st.caption(f"Prefilled from your watchlist plan for **{st.session_state.get(f'lt_symbol_{gen}', '')}** "
                    "— edit anything the market's moved on, then add your real fill.")

    c1, c2 = st.columns(2)
    with c1:
        symbol = st.selectbox("Symbol", options=symbol_options, index=None,
                               accept_new_options=True, placeholder="e.g. PTT", key=f"lt_symbol_{gen}")
        account = st.selectbox("Account", options=ACCOUNTS, key=f"lt_account_{gen}")
        entry_date = st.date_input("Entry date", value=date.today(), key=f"lt_entry_date_{gen}")
        entry_price = st.number_input("Entry price (฿)", min_value=0.0, step=0.01, format="%.2f",
                                       key=f"lt_entry_price_{gen}")
        shares = st.number_input("Shares (size)", min_value=0, step=100, key=f"lt_shares_{gen}")
        commission = st.number_input("Commission (฿)", min_value=0.0, step=0.01, format="%.2f",
                                      key=f"lt_commission_{gen}")
    with c2:
        stop = st.number_input("Stop (฿)", min_value=0.0, step=0.01, format="%.2f", key=f"lt_stop_{gen}")
        target = st.number_input("Target (฿)", min_value=0.0, step=0.01, format="%.2f", key=f"lt_target_{gen}")
        setup = st.selectbox(
            "Setup — leave blank if this wasn't a real technical setup",
            options=setup_options, index=None, accept_new_options=True,
            placeholder="blank on purpose is fine", key=f"lt_setup_{gen}",
        )
        entry_context = st.multiselect("Entry context — why did you press the button?",
                                        options=entry_context_options, accept_new_options=True,
                                        key=f"lt_entry_context_{gen}")
        thesis = st.text_area("Thesis — one line", height=80,
                               placeholder="Why this trade, right now, in one sentence.", key=f"lt_thesis_{gen}")

    missing = []
    if not symbol:
        missing.append("Symbol")
    if not shares:
        missing.append("Shares")
    if not stop:
        missing.append("Stop")
    if not target:
        missing.append("Target")
    if not thesis or not thesis.strip():
        missing.append("Thesis")

    invalid_stop = bool(stop and entry_price and stop >= entry_price)
    if invalid_stop:
        st.error("Stop must be below entry price — that's what makes it a stop.")

    if entry_price and stop and shares and stop < entry_price:
        st.metric("Planned 1R (baht risk)", f"฿{(entry_price - stop) * shares:,.2f}")

    if missing:
        st.caption(f"Fill in {join_fields(missing)} to save.")

    if st.button("Save as Open", disabled=bool(missing) or invalid_stop, type="primary"):
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
            st.session_state["lt_new_trade_gen"] = gen + 1
            st.session_state.pop("wl_source_page_id", None)
            st.success(f"{trade_id} saved as Open. Planned 1R: ฿{r1:,.2f}")
            st.rerun()

elif mode == "Add execution to open trade":
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
        st.caption(f"Thesis: {trow.thesis if pd.notna(trow.thesis) else '—'}")
        side = st.radio("Side", ["Buy", "Sell"], horizontal=True, key="lt_exec_side")
        exec_date = st.date_input("Execution date", value=date.today(), key="lt_exec_date")
        exit_reason = None
        mistakes_selected: list[str] = []
        if side == "Sell":
            exit_reason = st.selectbox("Exit reason (optional)", options=exit_reason_options,
                                        index=None, key="lt_exec_reason")
            mistakes_selected = st.multiselect("Mistakes (optional)", options=mistakes_options,
                                                accept_new_options=True, key="lt_exec_mistakes")
    with c2:
        price = st.number_input("Price (฿)", min_value=0.0, step=0.01, format="%.2f", key="lt_exec_price")
        units = st.number_input("Units", min_value=0, step=100, key="lt_exec_units")
        commission = st.number_input("Commission (฿)", min_value=0.0, step=0.01, format="%.2f", key="lt_exec_commission")

    missing = []
    if not price:
        missing.append("Price")
    if not units:
        missing.append("Units")

    oversell = bool(side == "Sell" and units and units > state_before.units)
    if oversell:
        st.error(f"Can't sell more than the {state_before.units:g} shares held.")

    if missing:
        st.caption(f"Fill in {join_fields(missing)} to save.")

    if st.button("Save execution", disabled=bool(missing) or oversell, type="primary"):
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
            if mistakes_selected:
                existing_mistakes = trow.mistakes if isinstance(trow.mistakes, list) else []
                trade_fields["Mistakes"] = multi_select(sorted(set(existing_mistakes) | set(mistakes_selected)))

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
                        "lt_exec_mistakes", "lt_exec_price", "lt_exec_units", "lt_exec_commission"):
                st.session_state.pop(key, None)
            msg = f"Execution saved. Realized P&L so far: ฿{state_after.realized_pnl:,.2f}"
            if state_after.units <= 0:
                msg += f" — trade closed, R-multiple {r_mult:.2f}" if r_mult is not None else " — trade closed"
            st.success(msg)
            st.rerun()

else:  # Correct a trade
    st.subheader("Correct a trade")
    st.caption(
        "Fix a wrong price, units, or a trade that shouldn't have closed. Every derived "
        "number gets recomputed from the corrected executions — nothing here is typed by hand."
    )

    all_trades = trades.copy()
    trade_ids = all_trades["trade_id"].tolist()
    trade_label = {
        r.trade_id: f"{r.trade_id} — {r.symbol} ({r.status})"
        for r in all_trades.itertuples()
    }
    preselect = st.session_state.pop("lt_correct_trade_id", None)
    correct_trade_id = st.selectbox(
        "Trade to correct", options=trade_ids,
        index=trade_ids.index(preselect) if preselect in trade_ids else None,
        format_func=lambda tid: trade_label.get(tid, tid),
        placeholder="Choose a trade", key="lt_correct_trade_id_widget",
    )

    if correct_trade_id is None:
        st.stop()

    trow = trades[trades["trade_id"] == correct_trade_id].iloc[0]
    existing_rows = executions[executions["trade_id"] == correct_trade_id].copy()

    st.divider()
    st.markdown(f"**{trow.symbol}** · {trow.account} · {trow.status}")

    c1, c2 = st.columns(2)
    with c1:
        symbol_idx = symbol_options.index(trow.symbol) if trow.symbol in symbol_options else None
        correct_symbol = st.selectbox("Symbol", options=symbol_options, index=symbol_idx,
                                       accept_new_options=True, key="lt_correct_symbol")
        account_idx = ACCOUNTS.index(trow.account) if trow.account in ACCOUNTS else 0
        correct_account = st.selectbox("Account", options=ACCOUNTS, index=account_idx, key="lt_correct_account")
        correct_stop = st.number_input(
            "Stop (฿)", min_value=0.0, step=0.01, format="%.2f",
            value=float(trow.stop) if pd.notna(trow.stop) else 0.0, key="lt_correct_stop",
        )
        correct_target = st.number_input(
            "Target (฿)", min_value=0.0, step=0.01, format="%.2f",
            value=float(trow.target) if pd.notna(trow.target) else 0.0, key="lt_correct_target",
        )
    with c2:
        setup_idx = setup_options.index(trow.setup) if trow.setup in setup_options else None
        correct_setup = st.selectbox(
            "Setup", options=setup_options, index=setup_idx, accept_new_options=True,
            placeholder="blank on purpose is fine", key="lt_correct_setup",
        )
        thesis_value = trow.thesis if pd.notna(trow.thesis) else ""
        correct_thesis = st.text_area("Thesis", value=thesis_value, height=80, key="lt_correct_thesis")
        correct_mistakes = st.multiselect(
            "Mistakes", options=mistakes_options,
            default=trow.mistakes if isinstance(trow.mistakes, list) else [],
            accept_new_options=True, key="lt_correct_mistakes",
        )
        recompute_1r = st.checkbox(
            "Recompute 1R from this stop", value=False, key="lt_correct_recompute_1r",
            help="Also recomputes R-multiple using this trade's current Realized P&L, "
                 "so the two stay consistent.",
        )

    st.caption(
        "Only this trade record's Symbol/Account update here — executions below keep "
        "whatever Symbol/Account they were logged with; edit those individually if they're wrong too."
    )

    correct_missing = []
    if not correct_symbol:
        correct_missing.append("Symbol")
    if correct_missing:
        st.caption(f"Fill in {join_fields(correct_missing)} to save.")

    if st.button("Save trade details", type="primary", disabled=bool(correct_missing), key="lt_correct_save_trade"):
        try:
            trade_fields = {
                "Symbol": rich_text(correct_symbol),
                "Account": select(correct_account),
                "Stop": number(correct_stop),
                "Target": number(correct_target),
                "Thesis": rich_text((correct_thesis or "").strip()),
                "Setup": select(correct_setup),
                "Mistakes": multi_select(correct_mistakes),
            }
            if recompute_1r:
                buys = existing_rows[existing_rows["side"] == "Buy"].sort_values("date")
                if buys.empty:
                    st.warning("No Buy execution on record — can't recompute 1R.")
                else:
                    first_buy = buys.iloc[0]
                    new_r1 = compute_1r(first_buy["cash"], first_buy["units"], correct_stop)
                    trade_fields["1R"] = number(round(new_r1, 2))
                    if pd.notna(trow.realized_pnl):
                        new_r_mult = compute_r_multiple(trow.realized_pnl, new_r1)
                        if new_r_mult is not None:
                            trade_fields["R-multiple"] = number(round(new_r_mult, 2))
            update_trade(client, trow.page_id, trade_fields)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Save failed — nothing was written.\n\n{exc}")
        else:
            st.cache_data.clear()
            for key in ("lt_correct_symbol", "lt_correct_account", "lt_correct_stop", "lt_correct_target",
                        "lt_correct_thesis", "lt_correct_setup", "lt_correct_mistakes", "lt_correct_recompute_1r"):
                st.session_state.pop(key, None)
            st.success(f"{correct_trade_id} trade details saved.")
            st.rerun()

    st.divider()
    st.subheader("Executions")

    if existing_rows.empty:
        st.info("No executions on this trade.")
    else:
        only_buy_id = None
        buy_rows = existing_rows[existing_rows["side"] == "Buy"]
        if len(buy_rows) == 1:
            only_buy_id = buy_rows.iloc[0]["page_id"]

        for erow in existing_rows.sort_values("date").itertuples():
            editing_key = f"lt_correct_editing_{erow.page_id}"
            confirm_key = f"lt_correct_confirm_delete_{erow.page_id}"

            with st.container(border=True):
                rc1, rc2 = st.columns([5, 2])
                with rc1:
                    st.markdown(f"**{erow.side}** {erow.units:g} @ ฿{erow.price:,.2f} — {erow.date.date()}")
                    st.caption(f"Commission ฿{erow.commission:,.2f} · Cash ฿{erow.cash:,.2f}")
                with rc2:
                    ec1, ec2 = st.columns(2)
                    if ec1.button("Edit", key=f"lt_correct_edit_btn_{erow.page_id}"):
                        st.session_state[editing_key] = not st.session_state.get(editing_key, False)
                    if ec2.button("Delete", key=f"lt_correct_delete_btn_{erow.page_id}"):
                        st.session_state[confirm_key] = True

                if st.session_state.get(confirm_key):
                    if len(existing_rows) == 1:
                        st.error(
                            "This is the only execution on this trade — deleting it would leave "
                            "an empty trade record. Deleting a whole trade isn't supported yet."
                        )
                    elif erow.page_id == only_buy_id:
                        st.error(
                            "Can't delete the only Buy on this trade — every trade needs at least "
                            "one Buy to anchor cost basis and 1R."
                        )
                    else:
                        corrected_rows = existing_rows[existing_rows["page_id"] != erow.page_id]
                        hyp = replay(corrected_rows)
                        if hyp.units < 0:
                            st.error(
                                f"This would leave a negative position ({hyp.units:g} shares) — "
                                "cumulative sells would exceed cumulative buys."
                            )
                        else:
                            st.warning(
                                f"Delete this {erow.side} execution ({erow.units:g} @ ฿{erow.price:,.2f})? "
                                "This can't be undone from here."
                            )
                            dc1, dc2 = st.columns(2)
                            if dc1.button("Confirm delete", key=f"lt_correct_confirm_delete_btn_{erow.page_id}",
                                          type="primary"):
                                try:
                                    archive_page(client, erow.page_id)
                                    close_date = None
                                    if hyp.units <= 0:
                                        sells = corrected_rows[corrected_rows["side"] == "Sell"].sort_values("date")
                                        if not sells.empty:
                                            close_date = sells.iloc[-1]["date"].date()
                                    trade_fields = recompute_trade_fields(hyp, trow, close_date)
                                    update_trade(client, trow.page_id, trade_fields)
                                except Exception as exc:  # noqa: BLE001
                                    st.error(f"Delete failed.\n\n{exc}")
                                else:
                                    st.cache_data.clear()
                                    st.session_state.pop(confirm_key, None)
                                    st.success("Execution deleted and trade recomputed.")
                                    st.rerun()
                            if dc2.button("Cancel", key=f"lt_correct_cancel_delete_{erow.page_id}"):
                                st.session_state.pop(confirm_key, None)
                                st.rerun()

                if st.session_state.get(editing_key):
                    if erow.page_id == only_buy_id:
                        st.caption(
                            "This trade's 1R was computed from this Buy. If you change price or "
                            "units, check 'Recompute 1R' above so 1R and R-multiple stay accurate."
                        )
                    ex1, ex2 = st.columns(2)
                    with ex1:
                        edit_side = st.radio(
                            "Side", ["Buy", "Sell"], horizontal=True,
                            index=0 if erow.side == "Buy" else 1,
                            key=f"lt_correct_edit_side_{erow.page_id}",
                        )
                        edit_date = st.date_input(
                            "Date", value=erow.date.date(), key=f"lt_correct_edit_date_{erow.page_id}",
                        )
                    with ex2:
                        edit_price = st.number_input(
                            "Price (฿)", min_value=0.0, step=0.01, format="%.2f",
                            value=float(erow.price), key=f"lt_correct_edit_price_{erow.page_id}",
                        )
                        edit_units = st.number_input(
                            "Units", min_value=0, step=100,
                            value=int(erow.units), key=f"lt_correct_edit_units_{erow.page_id}",
                        )
                        edit_commission = st.number_input(
                            "Commission (฿)", min_value=0.0, step=0.01, format="%.2f",
                            value=float(erow.commission), key=f"lt_correct_edit_commission_{erow.page_id}",
                        )

                    if st.button("Save correction", key=f"lt_correct_save_edit_{erow.page_id}", type="primary"):
                        new_gross = edit_price * edit_units
                        new_cash = execution_cash(edit_side, new_gross, edit_commission)
                        corrected_rows = existing_rows.copy()
                        mask = corrected_rows["page_id"] == erow.page_id
                        corrected_rows.loc[mask, "side"] = edit_side
                        corrected_rows.loc[mask, "date"] = pd.Timestamp(edit_date)
                        corrected_rows.loc[mask, "units"] = edit_units
                        corrected_rows.loc[mask, "gross_value"] = new_gross
                        corrected_rows.loc[mask, "commission"] = edit_commission
                        corrected_rows.loc[mask, "cash"] = new_cash
                        hyp = replay(corrected_rows)

                        if hyp.units < 0:
                            st.error(
                                f"This would leave a negative position ({hyp.units:g} shares) — "
                                "cumulative sells would exceed cumulative buys."
                            )
                        else:
                            try:
                                update_page(client, erow.page_id, {
                                    "Side": select(edit_side),
                                    "Date": date_prop(edit_date),
                                    "Price": number(edit_price),
                                    "Units": number(edit_units),
                                    "Gross Value": number(new_gross),
                                    "Commission": number(edit_commission),
                                    "Cash": number(new_cash),
                                })
                                close_date = None
                                if hyp.units <= 0:
                                    sells = corrected_rows[corrected_rows["side"] == "Sell"].sort_values("date")
                                    if not sells.empty:
                                        close_date = sells.iloc[-1]["date"].date()
                                trade_fields = recompute_trade_fields(hyp, trow, close_date)
                                update_trade(client, trow.page_id, trade_fields)
                            except Exception as exc:  # noqa: BLE001
                                st.error(f"Save failed.\n\n{exc}")
                            else:
                                st.cache_data.clear()
                                for key in (
                                    editing_key,
                                    f"lt_correct_edit_side_{erow.page_id}",
                                    f"lt_correct_edit_date_{erow.page_id}",
                                    f"lt_correct_edit_price_{erow.page_id}",
                                    f"lt_correct_edit_units_{erow.page_id}",
                                    f"lt_correct_edit_commission_{erow.page_id}",
                                ):
                                    st.session_state.pop(key, None)
                                st.success("Execution corrected and trade recomputed.")
                                st.rerun()
