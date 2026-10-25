"""CSV importer for the RSG sales dataset.

Validation and data policy:
- Every row is validated. A row with any invalid value is rejected and not stored.
- Required text (Transaction_Id, Product, Region, Sales_channel, Status) must be non-blank.
- Order_date must be a real calendar date in DD-MM-YYYY format. Stored as ISO YYYY-MM-DD.
- Quantity must be a whole number >= 0. Zero is valid and yields zero revenue.
- Unit_price: blank is valid. The row is stored with unit_price = NULL and is excluded from
  revenue. It is never replaced with 0 or an estimate. A nonblank value must be a
  non-negative decimal number (e.g. "1200" or "899.50"). Anything else, such as "abc",
  "1,200", or "-5", rejects the row.
- Discount_amount is required and must be a non-negative decimal number.
- Leading and trailing whitespace is trimmed. The number of trimmed fields is reported.
- Duplicate Transaction_Id:
    * identical copies in the same file: one is stored, the rest are skipped and reported;
    * conflicting copies in the same file: all copies are rejected, since the correct one is unknown;
    * a record already stored from an earlier run: an identical copy is skipped and reported;
      a conflicting copy is skipped, the stored record is kept, and the difference is reported.
  Nothing is overwritten.
- Every rejection, skip, and conflict is written to the issues report (CSV).
- The source CSV is opened read-only and never modified.
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app import db
from app.config import DEFAULT_CSV_PATH, DEFAULT_DB_PATH, DEFAULT_ISSUES_PATH, EXPECTED_COLUMNS, PROJECT_ROOT
from app.settings import Settings

REQUIRED_TEXT_COLUMNS = ("Transaction_Id", "Product", "Region", "Sales_channel", "Status")
DATE_PATTERN = re.compile(r"\d{2}-\d{2}-\d{4}")
WHOLE_NUMBER_PATTERN = re.compile(r"-?\d+")
NON_NEGATIVE_DECIMAL_PATTERN = re.compile(r"\d+(\.\d+)?")

# Fields compared when deciding whether two records are identical.
COMPARABLE_FIELDS = (
    "transaction_id",
    "order_date",
    "order_month",
    "product",
    "category",
    "region",
    "sales_channel",
    "quantity",
    "unit_price",
    "discount_amount",
    "status",
)
INSERT_COLUMNS = COMPARABLE_FIELDS + ("source_row",)
ISSUE_FIELDS = ("line_number", "transaction_id", "issue_type", "detail")


class ImportFileError(Exception):
    """The CSV as a whole cannot be imported (for example, a missing column)."""


@dataclass
class ImportReport:
    rows_read: int = 0
    accepted: int = 0                       # newly stored in this run
    skipped_existing: int = 0               # identical record already stored from an earlier run
    skipped_in_file_duplicates: int = 0     # identical repeat of a row in the same file
    conflicts_with_stored: int = 0          # same ID, different values, from an earlier run; stored record kept
    rejected: int = 0                       # rows not stored because of validation or in-file conflicts
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    trimmed_fields: int = 0
    # Database totals after this run (cover all stored rows, not only this file):
    stored_total: int = 0
    excluded_from_revenue: int = 0
    excluded_not_completed: int = 0
    missing_unit_price: int = 0
    zero_quantity: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    issues_path: str | None = None
    issues: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- parsing

def _read_rows(csv_path: Path) -> list[tuple[int, dict[str, str]]]:
    """Return (line_number, row) pairs. Raises ImportFileError if required columns are missing."""
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        missing = [column for column in EXPECTED_COLUMNS if column not in header]
        if missing:
            raise ImportFileError(f"CSV is missing required column(s): {', '.join(missing)}")
        rows = []
        for raw in reader:
            # Short rows give None for missing fields; treat them as blank.
            cleaned = {key: (value or "") for key, value in raw.items() if key is not None}
            rows.append((reader.line_num, cleaned))
    return rows


def _parse_date(text: str, errors: list[str]):
    if not text:
        errors.append("Order_date: required value is blank")
        return None
    if not DATE_PATTERN.fullmatch(text):
        errors.append(f"Order_date: '{text}' is not in DD-MM-YYYY format")
        return None
    try:
        return datetime.strptime(text, "%d-%m-%Y").date()
    except ValueError:
        errors.append(f"Order_date: '{text}' is not a valid calendar date")
        return None


def _parse_quantity(text: str, errors: list[str]) -> int | None:
    if not text:
        errors.append("Quantity: required value is blank")
        return None
    if not WHOLE_NUMBER_PATTERN.fullmatch(text):
        errors.append(f"Quantity: '{text}' is not a whole number")
        return None
    value = int(text)
    if value < 0:
        errors.append(f"Quantity: negative value {value} is not allowed")
        return None
    return value


def _parse_non_negative_decimal(column: str, text: str, errors: list[str]) -> float | None:
    if not NON_NEGATIVE_DECIMAL_PATTERN.fullmatch(text):
        errors.append(f"{column}: '{text}' is not a non-negative number")
        return None
    return float(text)


def _parse_unit_price(text: str, errors: list[str]) -> float | None:
    """Blank is valid and returns None (stored as NULL, excluded from revenue)."""
    if not text:
        return None
    return _parse_non_negative_decimal("Unit_price", text, errors)


def _parse_discount(text: str, errors: list[str]) -> float | None:
    if not text:
        errors.append("Discount_amount: required value is blank")
        return None
    return _parse_non_negative_decimal("Discount_amount", text, errors)


def parse_row(raw: dict[str, str]) -> tuple[dict | None, list[str], int]:
    """Validate and convert one CSV row.

    Returns (values, errors, trimmed_count). values is None when errors is non-empty.
    """
    errors: list[str] = []
    trimmed = 0
    cleaned: dict[str, str] = {}
    for column in EXPECTED_COLUMNS:
        value = raw.get(column, "")
        stripped = value.strip()
        if stripped != value:
            trimmed += 1
        cleaned[column] = stripped

    for column in REQUIRED_TEXT_COLUMNS:
        if not cleaned[column]:
            errors.append(f"{column}: required value is blank")

    order_date = _parse_date(cleaned["Order_date"], errors)
    quantity = _parse_quantity(cleaned["Quantity"], errors)
    unit_price = _parse_unit_price(cleaned["Unit_price"], errors)
    discount = _parse_discount(cleaned["Discount_amount"], errors)

    if errors:
        return None, errors, trimmed

    iso_date = order_date.isoformat()
    values = {
        "transaction_id": cleaned["Transaction_Id"],
        "order_date": iso_date,
        "order_month": iso_date[:7],
        "product": cleaned["Product"],
        "category": cleaned["Category"] or None,
        "region": cleaned["Region"],
        "sales_channel": cleaned["Sales_channel"],
        "quantity": quantity,
        "unit_price": unit_price,
        "discount_amount": discount,
        "status": cleaned["Status"],
    }
    return values, [], trimmed


# ---------------------------------------------------------------- reporting helpers

def _reject(report: ImportReport, line_number: int, transaction_id: str, reasons: list[str]) -> None:
    report.rejected += 1
    for reason in reasons:
        column = reason.split(":", 1)[0]
        report.rejection_reasons[column] = report.rejection_reasons.get(column, 0) + 1
    _issue(report, line_number, transaction_id, "rejected", "; ".join(reasons))


def _issue(report: ImportReport, line_number: int, transaction_id: str, issue_type: str, detail: str) -> None:
    report.issues.append({
        "line_number": line_number,
        "transaction_id": transaction_id,
        "issue_type": issue_type,
        "detail": detail,
    })


def _comparable(values: dict) -> tuple:
    return tuple(values[name] for name in COMPARABLE_FIELDS)


# ---------------------------------------------------------------- import steps

def _resolve_in_file_duplicates(report: ImportReport, candidates: dict[str, list[dict]]) -> list[dict]:
    to_store: list[dict] = []
    for transaction_id, copies in candidates.items():
        first = copies[0]
        first_key = _comparable(first)
        if all(_comparable(copy) == first_key for copy in copies[1:]):
            to_store.append(first)
            for duplicate in copies[1:]:
                report.skipped_in_file_duplicates += 1
                _issue(report, duplicate["source_row"], transaction_id, "duplicate_in_file_skipped",
                       f"identical to line {first['source_row']}; first copy kept")
        else:
            line_list = ", ".join(str(copy["source_row"]) for copy in copies)
            for copy in copies:
                _reject(report, copy["source_row"], transaction_id,
                        [f"Transaction_Id: conflicting copies in file (lines {line_list}); none stored"])
    return to_store


def _store_candidate(conn, report: ImportReport, values: dict) -> None:
    transaction_id = values["transaction_id"]
    stored = conn.execute(
        "SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()

    if stored is None:
        placeholders = ", ".join("?" for _ in INSERT_COLUMNS)
        conn.execute(
            f"INSERT INTO transactions ({', '.join(INSERT_COLUMNS)}) VALUES ({placeholders})",
            [values[column] for column in INSERT_COLUMNS],
        )
        report.accepted += 1
        return

    differing = [name for name in COMPARABLE_FIELDS if stored[name] != values[name]]
    if not differing:
        report.skipped_existing += 1
        _issue(report, values["source_row"], transaction_id, "duplicate_already_stored_skipped",
               "identical to record stored from an earlier import")
    else:
        report.conflicts_with_stored += 1
        _issue(report, values["source_row"], transaction_id, "conflict_with_stored_record",
               "differs from stored record in: " + ", ".join(differing)
               + "; stored record kept, not overwritten")


def _summarize_database(conn, report: ImportReport) -> None:
    def count(where: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM transactions" + (f" WHERE {where}" if where else "")
        return conn.execute(sql).fetchone()[0]

    report.stored_total = count()
    report.excluded_from_revenue = count(f"NOT ({db.REVENUE_ELIGIBLE_SQL})")
    report.excluded_not_completed = count("status <> 'Completed'")
    report.missing_unit_price = count("unit_price IS NULL")
    report.zero_quantity = count("quantity = 0")
    report.status_counts = {
        row[0]: row[1]
        for row in conn.execute("SELECT status, COUNT(*) FROM transactions GROUP BY status ORDER BY status")
    }


def _write_issues(report: ImportReport, issues_path: Path) -> None:
    issues_path.parent.mkdir(parents=True, exist_ok=True)
    with open(issues_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ISSUE_FIELDS)
        writer.writeheader()
        for issue in report.issues:
            writer.writerow(issue)


# ---------------------------------------------------------------- public API

def import_csv(
    csv_path: str | Path = DEFAULT_CSV_PATH,
    db_path: str | Path = DEFAULT_DB_PATH,
    issues_path: str | Path = DEFAULT_ISSUES_PATH,
) -> ImportReport:
    """Validate the CSV and store valid rows in SQLite. Safe to run repeatedly."""
    report = ImportReport(issues_path=str(issues_path))
    rows = _read_rows(Path(csv_path))
    report.rows_read = len(rows)

    candidates: dict[str, list[dict]] = {}
    for line_number, raw in rows:
        values, errors, trimmed = parse_row(raw)
        report.trimmed_fields += trimmed
        if errors:
            _reject(report, line_number, raw.get("Transaction_Id", "").strip(), errors)
            continue
        values["source_row"] = line_number
        candidates.setdefault(values["transaction_id"], []).append(values)

    to_store = _resolve_in_file_duplicates(report, candidates)

    conn = db.connect(db_path)
    try:
        db.init_schema(conn)
        with conn:  # one transaction: either the whole run is committed or nothing is
            for values in sorted(to_store, key=lambda item: item["source_row"]):
                _store_candidate(conn, report, values)
        _summarize_database(conn, report)
    finally:
        conn.close()

    _write_issues(report, Path(issues_path))
    return report


def format_report(report: ImportReport) -> str:
    lines = [
        "Import summary (this run)",
        f"  CSV rows read:                          {report.rows_read}",
        f"  Accepted (newly stored):                {report.accepted}",
        f"  Skipped: identical, already stored:     {report.skipped_existing}",
        f"  Skipped: identical duplicate in file:   {report.skipped_in_file_duplicates}",
        f"  Skipped: conflicts with stored record:  {report.conflicts_with_stored}",
        f"  Rejected (not stored):                  {report.rejected}",
        f"  Whitespace-trimmed fields:              {report.trimmed_fields}",
    ]
    if report.rejection_reasons:
        reasons = ", ".join(f"{k}={v}" for k, v in sorted(report.rejection_reasons.items()))
        lines.append(f"  Rejection reasons by column:            {reasons}")
    lines += [
        "",
        "Database totals after this run",
        f"  Stored transactions:                    {report.stored_total}",
        f"  Excluded from revenue (total):          {report.excluded_from_revenue}",
        f"    - status not Completed:               {report.excluded_not_completed}",
        f"    - missing Unit_price (NULL):          {report.missing_unit_price}",
        f"  Zero-quantity rows (kept, 0 revenue):   {report.zero_quantity}",
        f"  Status counts: {report.status_counts}",
        "",
        f"Issues report: {report.issues_path}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the sales CSV into SQLite.")
    parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH), help="path to the CSV file")
    parser.add_argument("--db", default=None,
                        help="path to the SQLite database (default: RSG_DB_PATH from the environment "
                             "or .env, otherwise data/sales.db)")
    parser.add_argument("--issues", default=str(DEFAULT_ISSUES_PATH), help="path for the issues report CSV")
    args = parser.parse_args(argv)
    if args.db is None:
        # Same rule as the backend: RSG_DB_PATH, relative to the project folder, else the default.
        configured = Settings.from_environment().db_path
        if configured:
            path = Path(configured)
            args.db = str(path if path.is_absolute() else PROJECT_ROOT / path)
        else:
            args.db = str(DEFAULT_DB_PATH)
    try:
        report = import_csv(args.csv, args.db, args.issues)
    except FileNotFoundError:
        print(f"Import failed: CSV not found at {args.csv}", file=sys.stderr)
        return 1
    except ImportFileError as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1
    except sqlite3.Error:
        print(
            f"Import failed: the database file {args.db} exists but cannot be used as a database "
            "(it may be damaged). Close any program using it, delete that file yourself, and run "
            "the import again. Nothing was deleted automatically.",
            file=sys.stderr,
        )
        return 1
    print(format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
