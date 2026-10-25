"""Independent reference calculator for verification.

Reads the original CSV directly with the standard csv module and Decimal arithmetic.
It shares no code with app/ and never touches SQLite. It implements the same
documented revenue rule from scratch so the SQL results can be checked against it.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path


@dataclass
class Group:
    revenue: Decimal = Decimal("0")
    transactions: int = 0
    units: int = 0


@dataclass
class Reference:
    total: Decimal = Decimal("0")
    eligible_count: int = 0
    by_product: dict[str, Group] = field(default_factory=dict)
    by_region: dict[str, Group] = field(default_factory=dict)
    by_month: dict[str, Group] = field(default_factory=dict)
    all_months: list[str] = field(default_factory=list)  # every month in the CSV, regardless of status


def compute(csv_path: str | Path) -> Reference:
    ref = Reference()
    all_months: set[str] = set()
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            month = datetime.strptime(row["Order_date"].strip(), "%d-%m-%Y").strftime("%Y-%m")
            all_months.add(month)
            if row["Status"].strip() != "Completed":
                continue
            price_text = row["Unit_price"].strip()
            if price_text == "":
                continue  # missing price: not revenue-eligible
            quantity = Decimal(row["Quantity"].strip())
            price = Decimal(price_text)
            discount = Decimal(row["Discount_amount"].strip())
            net = quantity * price - discount  # discount subtracted once per transaction

            ref.total += net
            ref.eligible_count += 1
            for table, key in (
                (ref.by_product, row["Product"].strip()),
                (ref.by_region, row["Region"].strip()),
                (ref.by_month, month),
            ):
                group = table.setdefault(key, Group())
                group.revenue += net
                group.transactions += 1
                group.units += int(quantity)
    ref.all_months = sorted(all_months)
    return ref


def ranking(groups: dict[str, Group]) -> list[tuple[str, Decimal, int, int]]:
    """Sort by revenue descending, then name ascending (the documented tie-break)."""
    ordered = sorted(groups.items(), key=lambda item: (-item[1].revenue, item[0]))
    return [(name, g.revenue, g.transactions, g.units) for name, g in ordered]


def q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def percent_change(revenue_a: Decimal, revenue_b: Decimal) -> Decimal | None:
    """Same convention as app.analytics: change / |baseline| * 100; None for a zero baseline."""
    if revenue_a == 0:
        return None
    return (revenue_b - revenue_a) / abs(revenue_a) * 100
