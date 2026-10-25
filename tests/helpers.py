"""Helpers for building small, hand-checked databases through the real importer."""
import csv
from pathlib import Path

from app import db
from app.config import EXPECTED_COLUMNS
from app.importer import import_csv


def sale(txn, date, product, region, qty, price, disc, status="Completed"):
    return [txn, date, product, "Cat", region, "Online", str(qty),
            "" if price is None else str(price), str(disc), status]


def build_database(tmp_path: Path, rows, name="analytics.db"):
    csv_path = tmp_path / f"{name}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(EXPECTED_COLUMNS)
        writer.writerows(rows)
    db_path = tmp_path / name
    import_csv(csv_path, db_path, tmp_path / f"{name}.issues.csv")
    return db.connect_readonly(db_path)


class FakeLLMClient:
    """Stands in for OpenAICompatibleClient in tests. Records prompts. Never touches the network."""

    def __init__(self, reply=None, error=None, model="fake-model"):
        self.reply = reply
        self.error = error
        self.model = model
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system, user):
        self.prompts.append((system, user))
        if self.error is not None:
            raise self.error
        return self.reply
