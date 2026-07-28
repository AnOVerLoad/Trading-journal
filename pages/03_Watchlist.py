"""Watchlist — write the plan down before the market moves.

An entry here is a pre-trade plan: trigger, stop, target, thesis, plus an
advisory (not gated) screening checklist. When it's time to act, "Trade
this →" hands the plan off to Log Trade pre-filled, and marks this entry
Traded once the real trade is saved. Nothing here forces a decision — an
entry just sits under Watching until you act on it or drop it.

See CLAUDE.md section 8 and design/watchlist_mockup.html (approved reference).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from notion_client import Client

from src.config import get_settings
from src.notion_sync import sync
from src.notion_write import create_page, date_prop, multi_select, number, rich_text, select, title, update_page
from src.theme import css, register_template

st.set_page_config(page_title="Watchlist", page_icon="🫒", layout="wide")
register_template()
st.markdown(css(), unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner="Syncing from Notion…")
def load_data() -> dict[str, pd.DataFrame]:
    return sync()


try:
    data = load_data()
    settings = get_settings()
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not sync from Notion.\n\n{exc}")
    st.stop()

st.title("Watchlist")
st.caption(
    "Screening criteria found something — write the plan down before the market moves, "
    "so the trade (if it happens) follows the plan, not the moment."
)

if not settings.watchlist_db_id:
    st.info(
        "Watchlist isn't set up yet. Create a blank page in Notion, share it with your "
        "integration (••• → Connections), and add its page ID as `WATCHLIST_DB_ID` in `.env` "
        "— the database itself gets created automatically from there. See CLAUDE.md section 8."
    )
    st.stop()

trades = data["trades"]
watchlist = data["watchlist"]
client = Client(auth=settings.notion_token)

watching = watchlist[watchlist["status"] == "Watching"].copy() if not watchlist.empty else watchlist
history = watchlist[watchlist["status"] != "Watching"].copy() if not watchlist.empty else watchlist

s1, s2, s3 = st.columns(3)
s1.metric("Watching", len(watching), delta_color="off")
s2.metric("Traded", int((watchlist["status"] == "Traded").sum()) if not watchlist.empty else 0, delta_color="off")
s3.metric("Dropped", int((watchlist["status"] == "Dropped").sum()) if not watchlist.empty else 0, delta_color="off")

st.divider()

# --- Add to watchlist ------------------------------------------------------------
st.subheader("Add to watchlist")
st.caption("Same discipline as Log Trade — stop, target, and a one-line thesis, before there's a position to defend.")

symbol_options = sorted(set(trades["symbol"].dropna()) | set(data["stocks"]["symbol"].dropna()))
setup_options = sorted(trades["setup"].dropna().unique().tolist())
checklist_options = sorted({v for lst in watchlist["checklist"].dropna() for v in lst}) if not watchlist.empty else []
if not checklist_options:
    checklist_options = ["Volume confirms it", "Market/sector not fighting me", "Know the catalyst", "Not chasing"]

c1, c2 = st.columns(2)
with c1:
    wl_symbol = st.selectbox("Symbol", options=symbol_options, index=None,
                              accept_new_options=True, placeholder="e.g. BH", key="wl_symbol")
    wl_trigger = st.number_input("Trigger price (฿)", min_value=0.0, step=0.01, format="%.2f",
                                  help="What you're waiting for — optional.", key="wl_trigger")
    wl_stop = st.number_input("Stop (฿)", min_value=0.0, step=0.01, format="%.2f", key="wl_stop")
with c2:
    wl_target = st.number_input("Target (฿)", min_value=0.0, step=0.01, format="%.2f", key="wl_target")
    wl_setup = st.selectbox("Setup", options=setup_options, index=None, accept_new_options=True,
                             placeholder="blank on purpose is fine", key="wl_setup")
    wl_thesis = st.text_area("Thesis — one line", height=70,
                              placeholder="Why this stock, once it triggers.", key="wl_thesis")

st.caption("Screening checklist — advisory, not required. Pick what applies, or type your own.")
wl_checklist = st.multiselect("Screening checklist", options=checklist_options, accept_new_options=True,
                               label_visibility="collapsed", key="wl_checklist")

if wl_trigger and wl_stop and wl_target and wl_trigger > wl_stop:
    rr = (wl_target - wl_trigger) / (wl_trigger - wl_stop)
    (st.success if rr >= 2 else st.warning)(f"Reward:Risk {rr:.1f}:1" + ("" if rr >= 2 else " — below the usual 2:1 bar"))

wl_missing = []
if not wl_symbol:
    wl_missing.append("Symbol")
if not wl_stop:
    wl_missing.append("Stop")
if not wl_target:
    wl_missing.append("Target")
if not wl_thesis or not wl_thesis.strip():
    wl_missing.append("Thesis")
if wl_missing:
    joined = wl_missing[0] if len(wl_missing) <= 1 else ", ".join(wl_missing[:-1]) + f", and {wl_missing[-1]}"
    st.caption(f"Fill in {joined} to save.")

if st.button("Add to watchlist", disabled=bool(wl_missing), type="primary"):
    try:
        create_page(client, settings.watchlist_db_id, {
            "Symbol": title(wl_symbol),
            "Added date": date_prop(date.today()),
            "Trigger price": number(wl_trigger or None),
            "Stop": number(wl_stop),
            "Target": number(wl_target),
            "Setup": select(wl_setup),
            "Thesis": rich_text(wl_thesis.strip()),
            "Screening checklist": multi_select(wl_checklist),
            "Status": select("Watching"),
        })
    except Exception as exc:  # noqa: BLE001
        st.error(f"Save failed — nothing was written.\n\n{exc}")
    else:
        st.cache_data.clear()
        for key in ("wl_symbol", "wl_trigger", "wl_stop", "wl_target", "wl_setup", "wl_thesis", "wl_checklist"):
            st.session_state.pop(key, None)
        st.success(f"{wl_symbol} added to watchlist.")
        st.rerun()

st.divider()

# --- Currently watching ------------------------------------------------------------
st.subheader("Currently watching")
st.caption("Nothing here forces a decision — an entry just sits until you act on it or drop it.")

if watching.empty:
    st.info("Nothing on the watchlist right now.")
else:
    for row in watching.itertuples():
        rr = None
        if pd.notna(row.trigger_price) and pd.notna(row.stop) and pd.notna(row.target) and row.trigger_price > row.stop:
            rr = (row.target - row.trigger_price) / (row.trigger_price - row.stop)
        days = (pd.Timestamp.now().normalize() - row.added_date).days if pd.notna(row.added_date) else None
        checklist_n = len(row.checklist) if isinstance(row.checklist, list) else 0

        with st.container(border=True):
            rc1, rc2, rc3 = st.columns([3, 5, 2])
            with rc1:
                st.markdown(f"**{row.symbol}**")
                st.caption(f"{days}d watching" if days is not None else "")
                st.caption(
                    f"Trigger {row.trigger_price:,.2f} · Stop {row.stop:,.2f} · Target {row.target:,.2f}"
                    if pd.notna(row.trigger_price) else f"Stop {row.stop:,.2f} · Target {row.target:,.2f}"
                )
            with rc2:
                st.caption(row.thesis or "—")
                rr_text = f"R:R {rr:.1f}:1" + ("" if rr is not None and rr >= 2 else " ⚠" if rr is not None else "")
                st.caption(f"{checklist_n} criteria met · {rr_text}")
            with rc3:
                if st.button("Trade this →", key=f"trade_{row.page_id}", type="primary"):
                    st.session_state["lt_symbol"] = row.symbol
                    st.session_state["lt_stop"] = float(row.stop)
                    st.session_state["lt_target"] = float(row.target)
                    if pd.notna(row.setup):
                        st.session_state["lt_setup"] = row.setup
                    st.session_state["lt_thesis"] = row.thesis or ""
                    st.session_state["wl_source_page_id"] = row.page_id
                    st.switch_page("pages/01_Log_Trade.py")
                if st.button("Drop", key=f"drop_{row.page_id}"):
                    try:
                        update_page(client, row.page_id, {"Status": select("Dropped")})
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Couldn't drop {row.symbol}.\n\n{exc}")
                    else:
                        st.cache_data.clear()
                        st.rerun()

st.divider()

# --- History ------------------------------------------------------------------
st.subheader("History")
st.caption("Traded entries link back to the trade they became — did the real fill match the plan?")

if history.empty:
    st.info("Nothing traded or dropped yet.")
else:
    hist_display = history[["symbol", "added_date", "status", "trigger_price", "stop", "target", "traded_as"]].rename(columns={
        "symbol": "Symbol", "added_date": "Added", "status": "Status",
        "trigger_price": "Trigger", "stop": "Stop", "target": "Target", "traded_as": "Traded as",
    })
    st.dataframe(
        hist_display, hide_index=True, use_container_width=True,
        column_config={
            "Added": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "Trigger": st.column_config.NumberColumn(format="%.2f"),
            "Stop": st.column_config.NumberColumn(format="%.2f"),
            "Target": st.column_config.NumberColumn(format="%.2f"),
        },
    )
