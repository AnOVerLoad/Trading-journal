"""Trade Log — every trade, open and closed, in one browsable list.

Exists so a wrongly-closed or mispriced trade can be spotted by eye, without
already knowing its Trade ID — then handed straight to Log Trade's
"Correct a trade" mode to fix. See CLAUDE.md section 8 (roadmap item 4,
"Trade review") and the "Correct a trade" mode this page hands off to.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import ACCOUNTS, get_settings
from src.notion_sync import sync
from src.theme import css, pl_color, register_template

st.set_page_config(page_title="Trade Log", page_icon="🫒", layout="wide")
register_template()
st.markdown(css(), unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner="Syncing from Notion…")
def load_data() -> dict[str, pd.DataFrame]:
    return sync()


try:
    data = load_data()
    get_settings()
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not sync from Notion.\n\n{exc}")
    st.stop()

trades = data["trades"]

st.title("Trade Log")
st.caption("Every trade, open and closed — find the one that needs correcting.")

if trades.empty:
    st.info("No trades yet.")
    st.stop()


def fmt(v, decimals: int = 2) -> str:
    return "—" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:,.{decimals}f}"


symbol_options = sorted(trades["symbol"].dropna().unique().tolist())
setup_options = sorted(trades["setup"].dropna().unique().tolist())

f1, f2, f3 = st.columns(3)
with f1:
    status_filter = st.multiselect("Status", options=["Open", "Closed"])
with f2:
    symbol_filter = st.selectbox("Symbol", options=symbol_options, index=None, placeholder="All symbols")
with f3:
    account_filter = st.multiselect("Account", options=list(ACCOUNTS))

f4, f5 = st.columns(2)
with f4:
    setup_filter = st.selectbox("Setup", options=setup_options, index=None, placeholder="All setups")
with f5:
    result_filter = st.selectbox("Result", options=["Win", "Lose"], index=None, placeholder="All results")

filtered = trades.copy()
if status_filter:
    filtered = filtered[filtered["status"].isin(status_filter)]
if symbol_filter:
    filtered = filtered[filtered["symbol"] == symbol_filter]
if account_filter:
    filtered = filtered[filtered["account"].isin(account_filter)]
if setup_filter:
    filtered = filtered[filtered["setup"] == setup_filter]
if result_filter:
    filtered = filtered[filtered["result"] == result_filter]

filtered = filtered.sort_values("open_date", ascending=False, na_position="last")

st.caption(f"{len(filtered)} of {len(trades)} trades")

if filtered.empty:
    st.info("No trades match these filters.")
else:
    for row in filtered.itertuples():
        with st.container(border=True):
            rc1, rc2, rc3, rc4 = st.columns([2, 3, 3, 2])
            with rc1:
                st.markdown(f"**{row.trade_id}** — {row.symbol}")
                st.caption(f"{row.account} · {row.status}")
            with rc2:
                st.caption(f"Setup: {row.setup if pd.notna(row.setup) else '—'}")
                open_str = row.open_date.date() if pd.notna(row.open_date) else "—"
                close_str = row.close_date.date() if pd.notna(row.close_date) else "—"
                st.caption(f"Open {open_str} → Close {close_str}")
            with rc3:
                pnl_color = pl_color(row.realized_pnl) if pd.notna(row.realized_pnl) else None
                pnl_text = f"฿{fmt(row.realized_pnl)}" if pd.notna(row.realized_pnl) else "—"
                if pnl_color:
                    st.markdown(f"<span style='color:{pnl_color}'>{pnl_text}</span>", unsafe_allow_html=True)
                else:
                    st.write(pnl_text)
                r_text = f"{fmt(row.r_multiple)}R" if pd.notna(row.r_multiple) else "—"
                result_text = row.result if pd.notna(row.result) else "—"
                st.caption(f"{r_text} · {result_text}")
            with rc4:
                if st.button("Correct this trade →", key=f"correct_{row.trade_id}"):
                    st.session_state["lt_correct_trade_id"] = row.trade_id
                    st.session_state["lt_mode"] = "Correct a trade"
                    st.switch_page("pages/01_Log_Trade.py")
