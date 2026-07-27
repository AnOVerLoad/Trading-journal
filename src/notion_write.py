"""Writes new/updated pages to Notion.

Notion just stores; the app computes every derived field (1R, avg cost,
Realized P&L, %P&L, R-multiple, Result) in trade_math.py and writes the
result here. Nothing derived is ever typed by hand in Notion.
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd
from notion_client import Client


def next_trade_id(trades: pd.DataFrame) -> str:
    nums = [int(m.group(1)) for tid in trades["trade_id"].dropna()
            if (m := re.match(r"T(\d+)$", tid))]
    return f"T{(max(nums) + 1) if nums else 1:03d}"


def next_execution_id(executions: pd.DataFrame) -> str:
    nums = [int(m.group(1)) for eid in executions["execution_id"].dropna()
            if (m := re.match(r"E(\d+)$", eid))]
    return f"E{(max(nums) + 1) if nums else 1:04d}"


# --- Notion property builders (one per property type actually used) -------

def title(text: str) -> dict:
    return {"title": [{"text": {"content": text}}]}


def rich_text(text: str | None) -> dict:
    return {"rich_text": [{"text": {"content": text}}] if text else []}


def select(name: str | None) -> dict:
    return {"select": ({"name": name} if name else None)}


def multi_select(names: list[str]) -> dict:
    return {"multi_select": [{"name": n} for n in (names or [])]}


def number(value: float | int | None) -> dict:
    if value is not None and hasattr(value, "item"):
        value = value.item()  # numpy int64/float64 (e.g. straight from a pandas row) -> native Python
    return {"number": value}


def date_prop(value: date | None) -> dict:
    return {"date": ({"start": value.isoformat()} if value else None)}


# --- Writes ------------------------------------------------------------------

def create_execution(client: Client, db_id: str, properties: dict) -> str:
    page = client.pages.create(parent={"database_id": db_id}, properties=properties)
    return page["id"]


def create_trade(client: Client, db_id: str, properties: dict) -> str:
    page = client.pages.create(parent={"database_id": db_id}, properties=properties)
    return page["id"]


def update_trade(client: Client, page_id: str, properties: dict) -> None:
    client.pages.update(page_id=page_id, properties=properties)


def create_page(client: Client, db_id: str, properties: dict) -> str:
    page = client.pages.create(parent={"database_id": db_id}, properties=properties)
    return page["id"]


def update_page(client: Client, page_id: str, properties: dict) -> None:
    client.pages.update(page_id=page_id, properties=properties)


def create_watchlist_database(client: Client, parent_page_id: str, setup_options: list[str]) -> str:
    """One-time setup: create the Watchlist database with correctly typed properties.

    `setup_options` should mirror Trades' Setup select options, so the two stay
    interchangeable when a watchlist entry graduates into a trade.
    """
    properties = {
        "Symbol": {"title": {}},
        "Added date": {"date": {}},
        "Trigger price": {"number": {"format": "number"}},
        "Stop": {"number": {"format": "number"}},
        "Target": {"number": {"format": "number"}},
        "Setup": {"select": {"options": [{"name": n} for n in setup_options]}},
        "Thesis": {"rich_text": {}},
        "Screening checklist": {"multi_select": {"options": [
            {"name": "Volume confirms it"},
            {"name": "Market/sector not fighting me"},
            {"name": "Know the catalyst"},
            {"name": "Not chasing"},
        ]}},
        "Status": {"select": {"options": [
            {"name": "Watching"}, {"name": "Traded"}, {"name": "Dropped"},
        ]}},
        "Traded as": {"rich_text": {}},
    }
    db = client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": "Watchlist"}}],
        properties=properties,
    )
    return db["id"]
