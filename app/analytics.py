"""Deterministic analytics over the transactions table.

Every number returned here comes from fixed SQL. The only text interpolated into
SQL is this module's own constants: REVENUE_EXPR, db.REVENUE_ELIGIBLE_SQL, and an
allow-listed column name. All user-supplied values (months) are validated first and
then passed as bound parameters (`?`).

Rules applied identically by every operation:
  eligible = status = 'Completed' AND unit_price IS NOT NULL   (db.REVENUE_ELIGIBLE_SQL)
  net      = quantity * unit_price - discount_amount            (discount once per transaction)
Monetary outputs are rounded to 2 decimal places.
"""
from __future__ import annotations

import re
import sqlite3

from app.db import REVENUE_ELIGIBLE_SQL

REVENUE_EXPR = "(quantity * unit_price - discount_amount)"
_GROUP_COLUMNS = ("product", "region")
_MONTH_PATTERN = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")
ZERO_BASELINE_NOTE = "Percentage change is undefined because the first month's revenue is zero."
NEGATIVE_BASELINE_NOTE = (
    "The first month's revenue is negative, so the percentage is calculated against its absolute "
    "value. Read it as the size of the change relative to that baseline, not as a growth rate."
)


class AnalyticsError(Exception):
    """Base class for invalid analytics requests."""


class InvalidMonthError(AnalyticsError):
    """A month is malformed, outside the stored data range, or no data exists."""


class IdenticalMonthsError(AnalyticsError):
    """A month comparison was requested with the same month twice."""


def _money(value) -> float:
    return round(float(value or 0), 2)


def data_month_range(conn: sqlite3.Connection) -> tuple[str | None, str | None]:
    """First and last order_month across all stored rows (None when the table is empty)."""
    row = conn.execute(
        "SELECT MIN(order_month) AS first_month, MAX(order_month) AS last_month FROM transactions"
    ).fetchone()
    return row["first_month"], row["last_month"]


def _months_between(first: str, last: str) -> list[str]:
    year, month = (int(part) for part in first.split("-"))
    end_year, end_month = (int(part) for part in last.split("-"))
    months = []
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def validate_month(conn: sqlite3.Connection, value, label: str) -> str:
    """Return the month if it is YYYY-MM and inside the stored data range; otherwise raise."""
    if not isinstance(value, str) or not _MONTH_PATTERN.fullmatch(value):
        raise InvalidMonthError(f"{label} must be a month in YYYY-MM format.")
    first, last = data_month_range(conn)
    if first is None:
        raise InvalidMonthError("No transactions are stored, so no month can be validated.")
    if not first <= value <= last:
        raise InvalidMonthError(f"{label} {value} is outside the available data range {first} to {last}.")
    return value


# ---------------------------------------------------------------- operation 1

def total_revenue(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        f"SELECT ROUND(COALESCE(SUM({REVENUE_EXPR}), 0), 2) AS revenue, COUNT(*) AS transactions "
        f"FROM transactions WHERE {REVENUE_ELIGIBLE_SQL}"
    ).fetchone()
    return {"total_revenue": _money(row["revenue"]), "eligible_transactions": row["transactions"]}


# ---------------------------------------------------------------- operations 2 and 4

def _ranking(conn: sqlite3.Connection, column: str) -> list[dict]:
    if column not in _GROUP_COLUMNS:
        raise ValueError(f"unsupported grouping column: {column}")
    rows = conn.execute(
        f"SELECT {column} AS name, ROUND(SUM({REVENUE_EXPR}), 2) AS revenue, "
        f"COUNT(*) AS transactions, SUM(quantity) AS units "
        f"FROM transactions WHERE {REVENUE_ELIGIBLE_SQL} "
        f"GROUP BY {column} ORDER BY revenue DESC, name ASC"
    ).fetchall()
    return [
        {"name": r["name"], "revenue": _money(r["revenue"]),
         "transactions": r["transactions"], "units": r["units"]}
        for r in rows
    ]


def top_product(conn: sqlite3.Connection) -> dict:
    """Ranking by revenue (ties broken alphabetically by product name). Top is None when nothing is eligible."""
    ranking = _ranking(conn, "product")
    return {"top": ranking[0] if ranking else None, "ranking": ranking}


def top_region(conn: sqlite3.Connection) -> dict:
    """Ranking by revenue (ties broken alphabetically by region name). Top is None when nothing is eligible."""
    ranking = _ranking(conn, "region")
    return {"top": ranking[0] if ranking else None, "ranking": ranking}


# ---------------------------------------------------------------- operation 3

def monthly_revenue(conn: sqlite3.Connection) -> list[dict]:
    """Revenue for every month from the first to the last stored month, in chronological order.

    Months with no eligible sales appear with revenue 0.0 and 0 transactions, so the
    trend has no silent gaps. Returns [] when the table is empty.
    """
    first, last = data_month_range(conn)
    if first is None:
        return []
    rows = conn.execute(
        f"SELECT order_month AS month, ROUND(SUM({REVENUE_EXPR}), 2) AS revenue, COUNT(*) AS transactions "
        f"FROM transactions WHERE {REVENUE_ELIGIBLE_SQL} GROUP BY order_month"
    ).fetchall()
    by_month = {r["month"]: r for r in rows}
    result = []
    for month in _months_between(first, last):
        row = by_month.get(month)
        result.append({
            "month": month,
            "revenue": _money(row["revenue"]) if row else 0.0,
            "transactions": row["transactions"] if row else 0,
        })
    return result


# ---------------------------------------------------------------- operation 5

def _month_revenue(conn: sqlite3.Connection, month: str) -> tuple[float, int]:
    row = conn.execute(
        f"SELECT ROUND(COALESCE(SUM({REVENUE_EXPR}), 0), 2) AS revenue, COUNT(*) AS transactions "
        f"FROM transactions WHERE order_month = ? AND {REVENUE_ELIGIBLE_SQL}",
        (month,),
    ).fetchone()
    return _money(row["revenue"]), row["transactions"]


def compare_months(conn: sqlite3.Connection, month_a: str, month_b: str) -> dict:
    """Change in revenue from month_a (baseline) to month_b.

    absolute_change    = revenue(month_b) - revenue(month_a)
    percentage_change  = absolute_change / |revenue(month_a)| * 100, rounded to 2 dp
    direction          = "increased" / "decreased" / "unchanged" (from the rounded absolute change)

    Baseline rules (see docs/analytics_policy.md):
      * zero baseline     -> percentage_change is None; note explains why
      * negative baseline -> percentage uses |baseline|; note warns it is not a growth rate
      * positive baseline -> ordinary percentage change
    """
    validate_month(conn, month_a, "First month")
    validate_month(conn, month_b, "Second month")
    if month_a == month_b:
        raise IdenticalMonthsError("The two months must be different.")

    revenue_a, count_a = _month_revenue(conn, month_a)
    revenue_b, count_b = _month_revenue(conn, month_b)
    change = round(revenue_b - revenue_a, 2)

    if change > 0:
        direction = "increased"
    elif change < 0:
        direction = "decreased"
    else:
        direction = "unchanged"

    if revenue_a == 0:
        percentage = None
        note = ZERO_BASELINE_NOTE
    else:
        percentage = round(change / abs(revenue_a) * 100, 2)
        note = NEGATIVE_BASELINE_NOTE if revenue_a < 0 else None

    return {
        "month_a": month_a,
        "revenue_a": revenue_a,
        "transactions_a": count_a,
        "month_b": month_b,
        "revenue_b": revenue_b,
        "transactions_b": count_b,
        "absolute_change": change,
        "percentage_change": percentage,
        "direction": direction,
        "note": note,
    }
