"""Import tests. Each test uses its own temporary database and CSV."""
import csv
import hashlib
import sqlite3

import pytest

from app import db
from app.config import DEFAULT_CSV_PATH, EXPECTED_COLUMNS
from app.importer import ImportFileError, import_csv

HEADER = ",".join(EXPECTED_COLUMNS)
# Column indices: 0 Transaction_Id, 1 Order_date, 2 Product, 3 Category, 4 Region,
# 5 Sales_channel, 6 Quantity, 7 Unit_price, 8 Discount_amount, 9 Status
VALID_ROW = ["TXN9001", "05-01-2026", "Monitor", "Electronics", "North", "Online", "2", "9500", "0", "Completed"]


def write_csv(path, rows, header=HEADER):
    # csv.writer quotes values that contain commas, so "1,200" stays one field.
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(header + "\n")
        writer = csv.writer(handle)
        writer.writerows(rows)
    return path


def run_import(tmp_path, rows, name="input.csv", db_name="test.db"):
    csv_path = write_csv(tmp_path / name, rows)
    report = import_csv(csv_path, tmp_path / db_name, tmp_path / "issues.csv")
    return report, tmp_path / db_name


def stored_rows(db_path):
    conn = db.connect_readonly(db_path)
    try:
        return {row["transaction_id"]: dict(row) for row in conn.execute("SELECT * FROM transactions")}
    finally:
        conn.close()


def with_value(index, value):
    row = list(VALID_ROW)
    row[index] = value
    return row


# ------------------------------------------------------- supplied dataset

def test_supplied_csv_import_counts(tmp_path):
    report = import_csv(DEFAULT_CSV_PATH, tmp_path / "sales.db", tmp_path / "issues.csv")
    assert report.rows_read == 51
    assert report.accepted == 51
    assert report.rejected == 0
    assert report.skipped_existing == 0
    assert report.skipped_in_file_duplicates == 0
    assert report.conflicts_with_stored == 0
    assert report.stored_total == 51
    assert report.excluded_from_revenue == 2
    assert report.excluded_not_completed == 1
    assert report.missing_unit_price == 1
    assert report.zero_quantity == 1
    assert report.status_counts == {"Completed": 50, "Returned": 1}


def test_supplied_csv_specific_records(tmp_path):
    report = import_csv(DEFAULT_CSV_PATH, tmp_path / "sales.db", tmp_path / "issues.csv")
    rows = stored_rows(tmp_path / "sales.db")
    assert rows["TXN0001"]["order_date"] == "2026-01-03"
    assert rows["TXN0001"]["order_month"] == "2026-01"
    assert rows["TXN0033"]["status"] == "Returned"
    assert rows["TXN0034"]["quantity"] == 0
    assert rows["TXN0051"]["unit_price"] is None  # NULL, not 0
    assert rows["TXN0051"]["source_row"] == 52    # line 52 of the CSV (header is line 1)


def test_source_csv_is_not_modified(tmp_path):
    before = hashlib.sha256(DEFAULT_CSV_PATH.read_bytes()).hexdigest()
    import_csv(DEFAULT_CSV_PATH, tmp_path / "sales.db", tmp_path / "issues.csv")
    after = hashlib.sha256(DEFAULT_CSV_PATH.read_bytes()).hexdigest()
    assert before == after


def test_rerunning_import_does_not_duplicate_rows(tmp_path):
    first = import_csv(DEFAULT_CSV_PATH, tmp_path / "sales.db", tmp_path / "issues.csv")
    second = import_csv(DEFAULT_CSV_PATH, tmp_path / "sales.db", tmp_path / "issues.csv")
    assert first.accepted == 51
    assert second.accepted == 0
    assert second.skipped_existing == 51
    assert second.stored_total == 51


# ------------------------------------------------------- missing and zero values

def test_blank_unit_price_stored_as_null_and_excluded(tmp_path):
    report, db_path = run_import(tmp_path, [with_value(7, "")])
    assert report.accepted == 1
    assert report.rejected == 0
    assert report.missing_unit_price == 1
    assert report.excluded_from_revenue == 1
    assert stored_rows(db_path)["TXN9001"]["unit_price"] is None


def test_zero_quantity_is_accepted_as_valid(tmp_path):
    report, db_path = run_import(tmp_path, [with_value(6, "0")])
    assert report.accepted == 1
    assert report.zero_quantity == 1
    assert report.excluded_from_revenue == 0  # Completed with price; contributes 0 revenue
    assert stored_rows(db_path)["TXN9001"]["quantity"] == 0


def test_returned_transaction_is_stored_but_excluded(tmp_path):
    report, db_path = run_import(tmp_path, [with_value(9, "Returned")])
    assert report.accepted == 1
    assert report.excluded_not_completed == 1
    assert report.excluded_from_revenue == 1
    assert stored_rows(db_path)["TXN9001"]["status"] == "Returned"


# ------------------------------------------------------- invalid rows

@pytest.mark.parametrize(
    "index, value, column",
    [
        (7, "abc", "Unit_price"),        # nonblank, nonnumeric
        (7, "1,200", "Unit_price"),      # thousands separator not accepted
        (7, "-5", "Unit_price"),         # negative price
        (1, "2026-01-05", "Order_date"),  # wrong format
        (1, "31-02-2026", "Order_date"),  # impossible date
        (1, "", "Order_date"),           # blank date
        (6, "-1", "Quantity"),           # negative quantity
        (6, "2.5", "Quantity"),          # not a whole number
        (8, "-100", "Discount_amount"),  # negative discount
        (8, "", "Discount_amount"),      # blank discount
        (4, "", "Region"),               # missing dimension
        (2, "", "Product"),              # missing dimension
    ],
)
def test_invalid_value_rejects_row_and_is_reported(tmp_path, index, value, column):
    report, db_path = run_import(tmp_path, [with_value(index, value)])
    assert report.rejected == 1
    assert report.accepted == 0
    assert "TXN9001" not in stored_rows(db_path)
    assert report.rejection_reasons.get(column) == 1
    issues = (tmp_path / "issues.csv").read_text(encoding="utf-8")
    assert "rejected" in issues and column in issues


def test_whitespace_is_trimmed_and_counted(tmp_path):
    report, db_path = run_import(tmp_path, [with_value(2, "  Monitor  ")])
    assert report.accepted == 1
    assert report.trimmed_fields == 1
    assert stored_rows(db_path)["TXN9001"]["product"] == "Monitor"


# ------------------------------------------------------- duplicates

def test_identical_duplicate_in_file_is_stored_once_and_reported(tmp_path):
    report, db_path = run_import(tmp_path, [VALID_ROW, VALID_ROW])
    assert report.accepted == 1
    assert report.skipped_in_file_duplicates == 1
    assert report.stored_total == 1
    assert "duplicate_in_file_skipped" in (tmp_path / "issues.csv").read_text(encoding="utf-8")


def test_conflicting_duplicate_in_file_rejects_all_copies(tmp_path):
    report, db_path = run_import(tmp_path, [VALID_ROW, with_value(6, "3")])
    assert report.accepted == 0
    assert report.rejected == 2
    assert report.stored_total == 0
    assert report.rejection_reasons.get("Transaction_Id") == 2


def test_conflict_with_stored_record_keeps_stored_value(tmp_path):
    run_import(tmp_path, [VALID_ROW], name="first.csv")
    report = import_csv(
        write_csv(tmp_path / "second.csv", [with_value(7, "9999")]),
        tmp_path / "test.db",
        tmp_path / "issues.csv",
    )
    assert report.accepted == 0
    assert report.conflicts_with_stored == 1
    assert report.stored_total == 1
    assert stored_rows(tmp_path / "test.db")["TXN9001"]["unit_price"] == 9500.0
    assert "unit_price" in (tmp_path / "issues.csv").read_text(encoding="utf-8")


# ------------------------------------------------------- file-level and DB safety

def test_missing_required_column_fails_whole_import(tmp_path):
    bad_header = ",".join(c for c in EXPECTED_COLUMNS if c != "Unit_price")
    csv_path = write_csv(tmp_path / "bad.csv", [], header=bad_header)
    with pytest.raises(ImportFileError, match="Unit_price"):
        import_csv(csv_path, tmp_path / "test.db", tmp_path / "issues.csv")


def test_readonly_connection_rejects_writes(tmp_path):
    conn = db.connect(tmp_path / "ro.db")
    db.init_schema(conn)
    conn.close()
    readonly = db.connect_readonly(tmp_path / "ro.db")
    try:
        with pytest.raises(sqlite3.OperationalError):
            readonly.execute("DELETE FROM transactions")
    finally:
        readonly.close()
