"""SQLite connection helpers and the transactions schema."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id   TEXT PRIMARY KEY,
    order_date       TEXT NOT NULL,              -- ISO 8601, YYYY-MM-DD
    order_month      TEXT NOT NULL,              -- YYYY-MM, derived from order_date
    product          TEXT NOT NULL,
    category         TEXT,                       -- NULL when blank in source
    region           TEXT NOT NULL,
    sales_channel    TEXT NOT NULL,
    quantity         INTEGER NOT NULL CHECK (quantity >= 0),
    unit_price       REAL CHECK (unit_price IS NULL OR unit_price >= 0),  -- NULL when blank in source
    discount_amount  REAL NOT NULL CHECK (discount_amount >= 0),          -- transaction-level amount
    status           TEXT NOT NULL,
    source_row       INTEGER NOT NULL            -- line number in the CSV where first stored
);
CREATE INDEX IF NOT EXISTS idx_transactions_order_month ON transactions (order_month);
"""

# The single definition of "counts toward completed-sales revenue".
# Phase 2 analytics must use this predicate and nothing else.
REVENUE_ELIGIBLE_SQL = "status = 'Completed' AND unit_price IS NOT NULL"


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a read-write connection, creating the parent folder if needed."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they do not exist. Safe to run repeatedly."""
    conn.executescript(SCHEMA)


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    """Open the database read-only. Used by analytics; writes raise OperationalError."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    # FastAPI may open a request's connection in one worker thread and close it in another.
    # Each connection serves exactly one request, so cross-thread use is safe here.
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
