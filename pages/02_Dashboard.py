"""Dashboard — KPIs, equity curve, setup-vs-tip, process, open positions.

Built from the approved reference: design/dashboard_mockup.html. Every number
here is computed in Python (src/dashboard_stats.py, src/trade_math.py) from
the synced executions — never trusted from a stored Notion field. See
CLAUDE.md sections 2, 5, and 8.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard_stats import (
    equity_curve,
    filter_range,
    kpis,
    r_multiple_histogram,
    setup_vs_tip,
    sum_by_field,
    sum_by_list_field,
)
from src.notion_sync import sync
from src.theme import CARD, GRID, LOSS, MUTED, OLIVE, OLIVE_DARK, OLIVE_LIGHT, TEXT, WIN, css, register_template
from src.trade_math import replay

st.set_page_config(page_title="Dashboard", page_icon="🫒", layout="wide")
register_template()
st.markdown(css(), unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner="Syncing from Notion…")
def load_data() -> dict[str, pd.DataFrame]:
    return sync()


try:
    data = load_data()
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not sync from Notion.\n\n{exc}")
    st.stop()

trades, executions = data["trades"], data["executions"]
closed_all = trades[trades["status"] == "Closed"].copy()
open_positions = trades[trades["status"] == "Open"].copy()

st.title("Dashboard")
st.caption("Where does my edge actually come from — and where do my losses actually come from?")

# --- Period filter -----------------------------------------------------------
DATA_MIN = closed_all["close_date"].min().date()
DATA_MAX = closed_all["close_date"].max().date()

period = st.segmented_control(
    "Period", ["All time", "This year", "Last 90 days", "Custom range"],
    default="All time", required=True, label_visibility="collapsed",
)

if period == "All time":
    start, end = None, None
elif period == "This year":
    start, end = date(date.today().year, 1, 1), None
elif period == "Last 90 days":
    start, end = date.today() - timedelta(days=90), None
else:
    custom = st.date_input("Custom range", value=(DATA_MIN, DATA_MAX),
                            min_value=DATA_MIN, max_value=DATA_MAX)
    if isinstance(custom, tuple) and len(custom) == 2:
        start, end = custom
    else:
        start, end = DATA_MIN, DATA_MAX

closed = filter_range(closed_all, start, end)
k = kpis(closed)

# --- KPI strip -----------------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Win rate", f"{k['win_rate']*100:.1f}%", f"{k['wins']}W · {k['losses']}L", delta_color="off")
c2.metric("Profit factor", f"{k['pf']:.2f}" if k["pf"] is not None else "—",
          "gross profit ÷ gross loss", delta_color="off")
c3.metric("Realized P&L", f"{k['total_pnl']:,.2f}", f"{k['n']} closed trades", delta_color="off")
c4.metric("Expectancy / trade", f"{k['expectancy']:,.2f}",
          f"avg win {k['avg_win']:,.2f} · avg loss {k['avg_loss']:,.2f}", delta_color="off")
c5.metric("Open positions", str(len(open_positions)), "unrealized — not counted above", delta_color="off")

st.divider()

# --- Equity curve --------------------------------------------------------------
st.subheader("Equity curve")
st.caption(
    "Cumulative realized P&L after each close, plotted by trade sequence rather than calendar date — "
    "this account sat idle for long stretches, and a true time axis would compress most of this story "
    "into a few months."
)
eq = equity_curve(closed)
if len(eq) >= 2:
    fig = go.Figure()
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED, opacity=0.5)
    fig.add_trace(go.Scatter(
        x=eq["seq"], y=eq["cum_pnl"], mode="lines+markers",
        line=dict(color=OLIVE, width=2), marker=dict(size=5, color=OLIVE),
        fill="tozeroy", fillcolor="rgba(169,179,107,0.2)",
        customdata=list(zip(eq["trade_id"], eq["close_date"].dt.strftime("%Y-%m-%d"), eq["realized_pnl"])),
        hovertemplate="<b>%{customdata[0]}</b> · %{customdata[1]}<br>this trade: %{customdata[2]:,.2f}"
                      "<br>running total: %{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(height=300, xaxis_title="Trade sequence (closed trades, in order)",
                       yaxis_title="Cumulative P&L (฿)")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Not enough closed trades in this period to draw a curve.")

# --- R-multiple distribution -----------------------------------------------------
st.subheader("R-multiple distribution")
st.caption("Outcome sized against the plan, not the ticker — each closed trade's realized P&L divided by its own 1R.")
hist = r_multiple_histogram(closed)
r_count = closed["r_multiple"].notna().sum()
st.caption(f"{r_count} of {len(closed)} closed trades have a 1R on record")
if not hist.empty:
    colors = [WIN if b >= 0 else LOSS for b in hist["bin"]]
    fig2 = go.Figure(go.Bar(x=hist["bin"], y=hist["count"], marker_color=colors, width=0.85))
    fig2.add_vline(x=-0.5, line_color=MUTED, opacity=0.3)
    fig2.update_layout(height=220, xaxis_title="R multiple", yaxis_title="Trades",
                        bargap=0.05, xaxis=dict(dtick=2))
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No R-multiples on record in this period.")

st.divider()

# --- Setup vs tip ----------------------------------------------------------------
st.subheader("Setup vs. tip")
sv = setup_vs_tip(closed)
vc1, vc2 = st.columns(2)
with vc1:
    st.markdown(f"""
    <div style="border:1px solid {GRID}; border-radius:8px; padding:16px 18px; background:{CARD};">
      <div style="font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:{WIN};">Has a real setup</div>
      <div style="color:{MUTED}; font-size:12px; margin:6px 0;">Breakout or red-to-green · {sv['has_n']} of {k['n']} closed trades</div>
      <div style="font-family:Iowan Old Style, Georgia, serif; font-size:26px; color:{WIN};">{sv['has_avg']:+,.2f}</div>
      <div style="color:{MUTED}; font-size:11.5px; margin-top:4px;">sum {sv['has_sum']:+,.2f}</div>
    </div>
    """, unsafe_allow_html=True)
with vc2:
    st.markdown(f"""
    <div style="border:1px solid {GRID}; border-radius:8px; padding:16px 18px; background:{CARD};">
      <div style="font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:{LOSS};">No setup — just a tip</div>
      <div style="color:{MUTED}; font-size:12px; margin:6px 0;">Setup left blank · {sv['no_n']} of {k['n']} closed trades</div>
      <div style="font-family:Iowan Old Style, Georgia, serif; font-size:26px; color:{LOSS};">{sv['no_avg']:+,.2f}</div>
      <div style="color:{MUTED}; font-size:11.5px; margin-top:4px;">sum {sv['no_sum']:+,.2f}</div>
    </div>
    """, unsafe_allow_html=True)

if sv["has_n"] and sv["no_n"]:
    st.caption(
        f"Real technical setups are rare — {sv['has_n']} of {k['n']} closed trades — and they "
        f"{'average a gain' if sv['has_avg'] >= 0 else 'still average a loss'}. The other {sv['no_n']}, "
        f"with no chart pattern on record, {'average a gain' if sv['no_avg'] >= 0 else 'average a loss'}."
    )

st.divider()


# --- Horizontal sign-colored bar helper -----------------------------------------
def bar_chart(df: pd.DataFrame, height: int = 260):
    if df.empty:
        st.info("No data in this period.")
        return
    colors = [WIN if v >= 0 else LOSS for v in df["sum"]]
    span = max(df["sum"].max(), 0) - min(df["sum"].min(), 0)
    pad = span * 0.22 or 1
    fig = go.Figure(go.Bar(
        x=df["sum"], y=df["label"], orientation="h", marker_color=colors,
        customdata=list(zip(df["n"], df["avg"])),
        hovertemplate="<b>%{y}</b><br>n=%{customdata[0]} · sum %{x:,.2f}<br>avg %{customdata[1]:,.2f}<extra></extra>",
        text=[f"n={n}" for n in df["n"]], textposition="outside", cliponaxis=False,
    ))
    fig.add_vline(x=0, line_color=MUTED, opacity=0.4)
    fig.update_layout(
        height=height, xaxis_title="Sum realized P&L (฿)", yaxis_title=None,
        margin=dict(l=140, r=40),
        xaxis=dict(range=[min(df["sum"].min(), 0) - pad, max(df["sum"].max(), 0) + pad]),
    )
    st.plotly_chart(fig, use_container_width=True)


# --- Entry reason ----------------------------------------------------------------
st.subheader("Total P&L by entry reason")
st.caption("Exploded across closed trades — a trade can carry more than one reason.")
bar_chart(sum_by_list_field(closed, "entry_context"))

st.divider()

# --- Process: mistakes donut + exit reason bars --------------------------------
st.subheader("Process")
mistakes = sum_by_list_field(closed, "mistakes")
exits = sum_by_field(closed, "exit_reason")

MISTAKE_COLOR = {
    "Held loser past stop": OLIVE,
    "Ignored plan": "#B08D57",
    "Held winner too long": "#4C7A88",
    "Cut winner early": "#8C6A9E",
    "Chased entry": OLIVE_LIGHT,
}

pc1, pc2 = st.columns(2)
with pc1:
    st.caption("Mistakes logged")
    if mistakes.empty:
        st.info("No mistakes logged in this period.")
    else:
        m = mistakes.sort_values("n", ascending=False)
        total_tags = int(m["n"].sum())
        trades_with_mistake = closed["mistakes"].apply(lambda lst: isinstance(lst, list) and len(lst) > 0).sum()
        fig3 = go.Figure(go.Pie(
            labels=m["label"], values=m["n"], hole=0.6,
            marker=dict(colors=[MISTAKE_COLOR.get(lbl, MUTED) for lbl in m["label"]],
                        line=dict(color=CARD, width=2)),
            customdata=list(zip(m["n"], m["sum"], m["avg"])),
            hovertemplate="<b>%{label}</b><br>%{customdata[0]} of " + str(total_tags) +
                          " tags · %{percent}<br>sum %{customdata[1]:,.2f} · avg %{customdata[2]:,.2f}<extra></extra>",
            textinfo="none", sort=False,
        ))
        fig3.update_layout(
            height=260, showlegend=True, legend=dict(orientation="v", x=1.05, y=0.5),
            annotations=[dict(text=f"<b>{trades_with_mistake}</b><br><span style='font-size:10px'>of {len(closed)} trades</span>",
                               x=0.5, y=0.5, showarrow=False, font=dict(size=16))],
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig3, use_container_width=True)
with pc2:
    st.caption("Exit reason")
    bar_chart(exits, height=260)

holdings = closed["holding_period"].dropna()
if len(holdings):
    st.caption(f"Holding period: avg {holdings.mean():.0f}d · median {holdings.median():.0f}d")

st.divider()

# --- Open positions --------------------------------------------------------------
st.subheader("Open positions")
st.caption(f"{len(open_positions)} open · current holdings — not affected by the period filter above.")

def fmt_or_dash(v: float) -> str:
    return "—" if pd.isna(v) else f"{v:,.2f}"


pos = open_positions.copy()
pos["Plan"] = pos["stop"].apply(lambda v: "" if pd.notna(v) else "No plan on file")
pos["held"] = pos["trade_id"].apply(
    lambda tid: replay(executions[executions["trade_id"] == tid]).units
)
pos_display = pd.DataFrame({
    "Trade": pos["trade_id"], "Symbol": pos["symbol"], "Account": pos["account"],
    "Opened": pos["open_date"], "Avg cost": pos["avg_cost"].map("{:.2f}".format),
    "Shares": pos["held"].astype(int),
    "Stop": pos["stop"].map(fmt_or_dash), "Target": pos["target"].map(fmt_or_dash),
    "Planned 1R": pos["r1"].map(fmt_or_dash), "Plan": pos["Plan"],
})
st.dataframe(
    pos_display, hide_index=True, use_container_width=True,
    column_config={"Opened": st.column_config.DateColumn(format="YYYY-MM-DD")},
)
if pos["Plan"].str.len().gt(0).any():
    flagged = ", ".join(pos.loc[pos["Plan"].str.len().gt(0), "trade_id"])
    st.caption(f"{flagged} predates the plan gate — no stop, target, or 1R on record.")
