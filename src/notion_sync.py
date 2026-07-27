"""The sync spine: pull the three Notion databases into pandas DataFrames.

This module has NO Streamlit dependency so it can run as a standalone smoke test:

    python -m src.notion_sync

It should print the reconciliation and match the targets in CLAUDE.md section 5.
The app (app.py) wraps `sync()` in st.cache_data; never re-pull on every rerun.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from notion_client import Client

from .config import get_settings

# --- Column maps: Notion property name -> tidy DataFrame column ----------------
TRADES_COLUMNS = {
    "Trade ID": "trade_id", "Symbol": "symbol", "Account": "account",
    "Status": "status", "Result": "result", "Setup": "setup",
    "Entry context": "entry_context", "Exit reason": "exit_reason",
    "Mistakes": "mistakes", "Emotion": "emotion",
    "Open date": "open_date", "Close date": "close_date",
    "Holding period": "holding_period", "Buy count": "buy_count",
    "Sell count": "sell_count", "Shares bought": "shares_bought",
    "Avg cost": "avg_cost", "Realized P&L": "realized_pnl", "%P&L": "pct_pnl",
    "1R": "r1", "R-multiple": "r_multiple", "Stop": "stop", "Target": "target",
    "Thesis": "thesis", "Grade": "grade",
}
EXECUTIONS_COLUMNS = {
    "Execution ID": "execution_id", "Trade ID": "trade_id", "Symbol": "symbol",
    "Account": "account", "Side": "side", "Date": "date", "Price": "price",
    "Units": "units", "Gross Value": "gross_value", "Commission": "commission",
    "Cash": "cash",
}
STOCKS_COLUMNS = {
    "Symbol": "symbol", "Name": "name", "Sector": "sector", "Market": "market",
}
WATCHLIST_COLUMNS = {
    "Symbol": "symbol", "Added date": "added_date", "Trigger price": "trigger_price",
    "Stop": "stop", "Target": "target", "Setup": "setup", "Thesis": "thesis",
    "Screening checklist": "checklist", "Status": "status", "Traded as": "traded_as",
}

# Fields to coerce to real datetimes / numbers after extraction.
_DATE_COLS = {"open_date", "close_date", "date", "added_date"}


def _extract(prop: dict[str, Any]) -> Any:
    """Turn one Notion property object into a plain Python value."""
    t = prop.get("type")
    v = prop.get(t)
    if t in ("title", "rich_text"):
        return "".join(part.get("plain_text", "") for part in (v or [])) or None
    if t in ("select", "status"):
        return v["name"] if v else None
    if t == "multi_select":
        return [o["name"] for o in (v or [])]
    if t == "number":
        return v
    if t == "date":
        return v["start"] if v else None
    if t == "checkbox":
        return bool(v)
    if t == "relation":
        return [r["id"] for r in (v or [])]
    if t == "formula":
        return v.get(v["type"]) if v else None
    if t == "rollup":
        return v.get(v["type"]) if v else None
    return None


def _query_all(client: Client, database_id: str) -> list[dict]:
    """Return every page in a database, following pagination (100/page)."""
    pages: list[dict] = []
    cursor: str | None = None
    while True:
        kwargs = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = client.databases.query(**kwargs)
        pages.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]
    return pages


def _to_frame(pages: list[dict], colmap: dict[str, str]) -> pd.DataFrame:
    rows = []
    for page in pages:
        props = page.get("properties", {})
        row = {col: _extract(props[name]) for name, col in colmap.items() if name in props}
        row["page_id"] = page["id"]
        rows.append(row)
    df = pd.DataFrame(rows, columns=list(colmap.values()) + ["page_id"])
    for col in df.columns:
        if col in _DATE_COLS:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def sync() -> dict[str, pd.DataFrame]:
    """Pull all databases into tidy DataFrames keyed by name.

    Watchlist is optional: if WATCHLIST_DB_ID isn't set yet, its frame comes
    back empty rather than failing the whole sync.
    """
    s = get_settings()
    client = Client(auth=s.notion_token)
    trades = _to_frame(_query_all(client, s.trades_db_id), TRADES_COLUMNS)
    executions = _to_frame(_query_all(client, s.executions_db_id), EXECUTIONS_COLUMNS)
    stocks = _to_frame(_query_all(client, s.stocks_db_id), STOCKS_COLUMNS)
    if s.watchlist_db_id:
        watchlist = _to_frame(_query_all(client, s.watchlist_db_id), WATCHLIST_COLUMNS)
    else:
        watchlist = pd.DataFrame(columns=list(WATCHLIST_COLUMNS.values()) + ["page_id"])
    # Sort for stable, human-friendly ordering.
    if not trades.empty:
        trades = trades.sort_values("trade_id").reset_index(drop=True)
    if not executions.empty:
        executions = executions.sort_values("execution_id").reset_index(drop=True)
    if not watchlist.empty:
        watchlist = watchlist.sort_values("added_date").reset_index(drop=True)
    return {"trades": trades, "executions": executions, "stocks": stocks, "watchlist": watchlist}


if __name__ == "__main__":
    from .reconcile import print_reconciliation

    data = sync()
    print_reconciliation(data)
