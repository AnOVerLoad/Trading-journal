"""Configuration and secrets loading.

Secrets live in `.env` (gitignored). Nothing sensitive is ever hardcoded here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    notion_token: str
    trades_db_id: str
    executions_db_id: str
    stocks_db_id: str
    watchlist_db_id: str | None  # optional — Watchlist works without it, screen just says so


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("your_"):
        raise RuntimeError(
            f"Missing {name}. Copy .env.example to .env and fill in your Notion "
            f"integration token and database IDs. See CLAUDE.md section 6."
        )
    return value


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("your_"):
        return None
    return value


def get_settings() -> Settings:
    return Settings(
        notion_token=_require("NOTION_TOKEN"),
        trades_db_id=_require("TRADES_DB_ID"),
        executions_db_id=_require("EXECUTIONS_DB_ID"),
        stocks_db_id=_require("STOCKS_DB_ID"),
        watchlist_db_id=_optional("WATCHLIST_DB_ID"),
    )


# --- Domain constants (kept in sync with CLAUDE.md) ---------------------------

ACCOUNTS = ("KS", "LIB")

# The sync is correct only if it reproduces these. See src/reconcile.py.
RECON_TARGETS = {
    "trades_total": 59,
    "trades_closed": 46,
    "trades_open": 13,
    "executions_total": 182,
    "stocks_total": 42,
    "realized_closed_baht": -9892.0,   # sum of Realized P&L over CLOSED trades
    "realized_tolerance": 10.0,        # rounding slack
    "win_rate_closed": 0.217,          # 10 wins / 46 closed
    "profit_factor": 0.74,
}
