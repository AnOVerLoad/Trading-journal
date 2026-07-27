"""Streamlit entry point — the spine test.

This first screen exists to PROVE the Notion -> pandas pull works and reconciles.
Once these checks pass, the next screen to build is Log Trade (with the plan gate).
Run:  streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.notion_sync import sync
from src.reconcile import compute
from src.theme import WIN, LOSS, OLIVE_DARK, register_template

st.set_page_config(page_title="Trading Journal", page_icon="🫒", layout="wide")
register_template()


@st.cache_data(ttl=300, show_spinner="Syncing from Notion…")
def load_data() -> dict[str, pd.DataFrame]:
    return sync()


st.title("Trading Journal — sync check")
st.caption("Notion is the capture layer; this app is the analytics brain. Prove the pull first.")

try:
    data = load_data()
except Exception as exc:  # noqa: BLE001 — surface any setup error clearly to the user
    st.error(f"Could not sync from Notion.\n\n{exc}")
    st.info("Check your .env (token + database IDs) and that all three databases are "
            "shared with your integration. See CLAUDE.md section 6.")
    st.stop()

checks = compute(data)
all_ok = all(c["ok"] for c in checks)

if all_ok:
    st.success("All reconciliation checks passed — the pipeline is trustworthy.")
else:
    st.warning("Some checks failed — fix the sync before building screens.")

recon = pd.DataFrame([
    {"Check": c["label"], "Expected": c["expected"], "Actual": c["actual"],
     "": "✅" if c["ok"] else "❌"}
    for c in checks
])
st.dataframe(recon, hide_index=True, use_container_width=True)

st.subheader("Data preview")
tabs = st.tabs(["Trades", "Executions", "Stocks"])
for tab, key in zip(tabs, ("trades", "executions", "stocks")):
    with tab:
        st.dataframe(data[key], hide_index=True, use_container_width=True)

st.divider()
st.caption("Next: build **Log Trade** with the plan gate — see CLAUDE.md section 8.")
