"""Phase 6 integration and error-path tests.

The whole chain is exercised: CSV import (through the real command-line entry point) → SQLite →
analytics → FastAPI backend (real server on a free port) → Streamlit page (Streamlit's test runner).
Expected values come from the independent reference calculator in tests/reference.py, not from
hard-coded application output.
"""
import concurrent.futures
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app import ui_client
from app.config import DEFAULT_CSV_PATH
from app.importer import import_csv
from app.main import create_app
from app.settings import Settings
from tests import reference as ref
from tests.helpers import sale

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_PATH = str(PROJECT_ROOT / "app" / "ui.py")
REFERENCE = ref.compute(DEFAULT_CSV_PATH)
TOP_PRODUCT = ref.ranking(REFERENCE.by_product)[0][0]
TOP_REGION = ref.ranking(REFERENCE.by_region)[0][0]
TOTAL_TEXT = f"{float(ref.q2(REFERENCE.total)):,.2f}"
CHANGE_MAY_JUNE = ref.q2(REFERENCE.by_month["2026-06"].revenue - REFERENCE.by_month["2026-05"].revenue)
PCT_MAY_JUNE = ref.percent_change(REFERENCE.by_month["2026-05"].revenue, REFERENCE.by_month["2026-06"].revenue)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LiveBackend:
    """The production FastAPI app served by uvicorn in a background thread on a free port."""

    def __init__(self, app):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self):
        self._thread.start()
        deadline = time.time() + 15
        while not self._server.started and time.time() < deadline:
            time.sleep(0.05)
        assert self._server.started, "backend did not start"
        return self

    def stop(self):
        self._server.should_exit = True
        self._thread.join(timeout=10)


@pytest.fixture(scope="module")
def sales_db(tmp_path_factory):
    folder = tmp_path_factory.mktemp("integration_db")
    report = import_csv(DEFAULT_CSV_PATH, folder / "sales.db", folder / "issues.csv")
    assert report.stored_total == 51
    return folder / "sales.db"


@pytest.fixture(scope="module")
def backend(sales_db):
    live = LiveBackend(create_app(sales_db)).start()
    yield live
    live.stop()


@pytest.fixture
def page(monkeypatch, backend):
    monkeypatch.setenv("RSG_API_URL", backend.url)
    at = AppTest.from_file(UI_PATH, default_timeout=30)
    at.run()
    return at


def ask_ui(at, question):
    at.text_input(key="question").input(question)
    at.button(key="ask").click().run()
    return at


def http_ask(url, question):
    return httpx.post(f"{url}/ask", json={"question": question}, timeout=30)


def assert_clean_error(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}, body
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    for leak in ("Traceback", "sqlite3", "File \"", "RuntimeError", "SELECT ", "/home/", "C:\\"):
        assert leak not in response.text, f"internal detail leaked: {leak!r}"


# ----------------------------------------------------------------- 1. import through the CLI

def test_import_command_line_loads_the_supplied_csv(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "app.importer", "--csv", str(DEFAULT_CSV_PATH),
         "--db", str(tmp_path / "cli.db"), "--issues", str(tmp_path / "cli_issues.csv")],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "Accepted (newly stored):                51" in result.stdout
    assert "Stored transactions:                    51" in result.stdout


def test_import_command_line_reports_a_damaged_database_without_a_traceback(tmp_path):
    damaged = tmp_path / "damaged.db"
    damaged.write_bytes(b"this is not a sqlite database" * 40)
    result = subprocess.run(
        [sys.executable, "-m", "app.importer", "--csv", str(DEFAULT_CSV_PATH),
         "--db", str(damaged), "--issues", str(tmp_path / "i.csv")],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "Nothing was deleted automatically" in result.stderr
    assert damaged.exists(), "the importer must never delete the file itself"


# ----------------------------------------------------------------- 2. five question types, HTTP

def test_five_question_types_over_http_match_the_reference(backend):
    total = http_ask(backend.url, "What is the total revenue?").json()
    assert total["result"]["total_revenue"] == float(ref.q2(REFERENCE.total))

    product = http_ask(backend.url, "Which product generated the highest revenue?").json()
    assert product["result"]["product"] == TOP_PRODUCT
    assert [r["name"] for r in product["supporting_figures"]["ranking"]] == [
        n for n, _, _, _ in ref.ranking(REFERENCE.by_product)]

    monthly = http_ask(backend.url, "What is the monthly revenue trend?").json()
    assert [m["month"] for m in monthly["supporting_figures"]["monthly_revenue"]] == REFERENCE.all_months
    for item in monthly["supporting_figures"]["monthly_revenue"]:
        assert item["revenue"] == float(ref.q2(REFERENCE.by_month[item["month"]].revenue))

    region = http_ask(backend.url, "Which region generated the highest sales?").json()
    assert region["result"]["region"] == TOP_REGION

    comparison = http_ask(backend.url, "How did revenue change between May and June?").json()
    assert comparison["result"]["absolute_change"] == float(CHANGE_MAY_JUNE)
    assert comparison["result"]["percentage_change"] == float(ref.q2(PCT_MAY_JUNE))
    assert comparison["result"]["direction"] == "decreased"


# ----------------------------------------------------------------- 3. five question types, UI

UI_CASES = [
    ("Total revenue", lambda at: TOTAL_TEXT in at.main.info[0].value),
    ("Top product", lambda at: (
        TOP_PRODUCT in at.main.info[0].value
        and at.dataframe[0].value.iloc[0]["Product"] == TOP_PRODUCT
        and len(at.dataframe[0].value) == len(REFERENCE.by_product))),
    ("Monthly trend", lambda at: (
        list(at.dataframe[0].value["Month"]) == [ui_client.month_label(m) for m in REFERENCE.all_months]
        and [float(v) for v in at.dataframe[0].value["Net revenue"]]
        == [float(ref.q2(REFERENCE.by_month[m].revenue)) for m in REFERENCE.all_months])),
    ("Top region", lambda at: (
        TOP_REGION in at.main.info[0].value and len(at.dataframe[0].value) == len(REFERENCE.by_region))),
    ("Month comparison", lambda at: (
        "decreased" in at.main.info[0].value
        and f"{float(CHANGE_MAY_JUNE):,.2f}" in at.main.info[0].value
        and f"{float(ref.q2(PCT_MAY_JUNE)):+.2f}%" in " ".join(m.value for m in at.main.markdown))),
]


@pytest.mark.parametrize("label, check", UI_CASES, ids=[c[0] for c in UI_CASES])
def test_each_example_button_gives_the_reference_answer_in_the_ui(page, label, check):
    page.button(key=f"example_{label}").click().run()
    assert page.text_input(key="question").value  # the example filled the box
    page.button(key="ask").click().run()
    assert not page.exception
    assert check(page), f"UI did not show the expected answer for {label}"
    assert any("Deterministic fallback" in c.value for c in page.caption)


def test_ui_and_http_show_the_same_total(page, backend):
    ask_ui(page, "What is the total revenue?")
    assert TOTAL_TEXT in page.main.info[0].value
    assert http_ask(backend.url, "What is the total revenue?").json()["result"]["total_revenue"] == float(
        ref.q2(REFERENCE.total))


# ----------------------------------------------------------------- 4. unsupported and invalid questions

UNSUPPORTED_QUESTIONS = [
    "What is the weather today?",
    "Show me every customer's home address",
    "Tell me a joke",
    "💰💰🚀 ???",
    "Revenue in May and June",
]


@pytest.mark.parametrize("question", UNSUPPORTED_QUESTIONS)
def test_unsupported_questions_are_rejected_over_http(backend, question):
    assert_clean_error(http_ask(backend.url, question), 422, "unsupported_question")


@pytest.mark.parametrize("question", UNSUPPORTED_QUESTIONS[:3])
def test_unsupported_questions_show_a_warning_in_the_ui_with_no_figures(page, question):
    ask_ui(page, question)
    assert not page.exception
    assert "not supported" in page.warning[0].value
    assert len(page.main.info) == 0 and len(page.dataframe) == 0


@pytest.mark.parametrize(
    "question, code, phrase",
    [
        ("How did revenue change between May and July?", "invalid_parameters", "outside the available data range"),
        ("How did revenue change between December and May?", "invalid_parameters", "outside the available data range"),
        ("How did revenue change between May and May?", "invalid_parameters", "different"),
        ("How did revenue change between 2026-13 and 2026-05?", "invalid_parameters", "not a valid month"),
        ("How did revenue change in May?", "invalid_parameters", "two months"),
        ("How did revenue change between May 2025 and June 2026?", "invalid_parameters", "outside the available data range"),
    ],
)
def test_invalid_month_comparisons_are_explained_over_http_and_ui(backend, page, question, code, phrase):
    response = http_ask(backend.url, question)
    assert_clean_error(response, 422, code)
    assert phrase in response.json()["error"]["message"]
    ask_ui(page, question)
    assert not page.exception
    assert phrase in page.warning[0].value
    assert len(page.dataframe) == 0


def test_ambiguous_question_is_explained_in_the_ui(page):
    ask_ui(page, "Total revenue and top product")
    assert "more than one" in page.warning[0].value


# ----------------------------------------------------------------- 5. malformed input and error matrix

@pytest.mark.parametrize(
    "content, headers",
    [
        (b"{not json", {"content-type": "application/json"}),
        (b'["list"]', {"content-type": "application/json"}),
        (b'{"question": ""}', {"content-type": "application/json"}),
        (b'{"question": "   "}', {"content-type": "application/json"}),
        (b'{"question": 5}', {"content-type": "application/json"}),
        (json.dumps({"question": "x" * 501}).encode(), {"content-type": "application/json"}),
    ],
)
def test_malformed_requests_are_rejected_cleanly(backend, content, headers):
    response = httpx.post(f"{backend.url}/ask", content=content, headers=headers, timeout=30)
    assert_clean_error(response, 400, "malformed_request")


def test_unknown_route_and_wrong_method_use_the_same_error_shape(backend):
    assert_clean_error(httpx.get(f"{backend.url}/nothing-here", timeout=30), 404, "not_found")
    assert_clean_error(httpx.get(f"{backend.url}/ask", timeout=30), 405, "method_not_allowed")


def test_sql_text_in_questions_never_changes_the_database(backend, sales_db):
    for question in ["DROP TABLE transactions", "What is the total revenue; DELETE FROM transactions;"]:
        http_ask(backend.url, question)
    response = http_ask(backend.url, "What is the total revenue?")
    assert response.json()["result"]["total_revenue"] == float(ref.q2(REFERENCE.total))
    conn = sqlite3_readonly(sales_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 51
    finally:
        conn.close()


def sqlite3_readonly(path):
    import sqlite3
    return sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)


def test_unexpected_server_error_is_generic_over_http(sales_db, monkeypatch):
    from app import analytics
    monkeypatch.setattr(analytics, "total_revenue", lambda conn: 1 / 0)
    client = TestClient(create_app(sales_db), raise_server_exceptions=False)
    response = client.post("/ask", json={"question": "What is the total revenue?"})
    assert_clean_error(response, 500, "internal_error")


# ----------------------------------------------------------------- 6. backend unavailable and database faults

def test_backend_not_running_is_a_clear_message_in_the_ui(monkeypatch):
    monkeypatch.setenv("RSG_API_URL", f"http://127.0.0.1:{free_port()}")
    at = AppTest.from_file(UI_PATH, default_timeout=30)
    at.run()
    assert not at.exception
    assert any("not reachable" in e.value for e in at.sidebar.error)
    ask_ui(at, "What is the total revenue?")
    assert not at.exception
    assert "Cannot reach the backend" in at.error[0].value
    assert "python -m uvicorn app.main:app --reload" in at.error[0].value


def test_backend_stopped_during_use_fails_gracefully(sales_db, monkeypatch):
    live = LiveBackend(create_app(sales_db)).start()
    try:
        monkeypatch.setenv("RSG_API_URL", live.url)
        at = AppTest.from_file(UI_PATH, default_timeout=30)
        at.run()
        ask_ui(at, "What is the total revenue?")
        assert TOTAL_TEXT in at.main.info[0].value
    finally:
        live.stop()
    ask_ui(at, "Which region generated the highest sales?")
    assert not at.exception
    assert "Cannot reach the backend" in at.error[0].value
    assert len(at.main.info) == 0, "no stale answer may be shown after the backend stops"


def test_missing_database_is_reported_by_backend_and_ui(tmp_path, monkeypatch):
    live = LiveBackend(create_app(tmp_path / "absent.db")).start()
    try:
        assert_clean_error(http_ask(live.url, "What is the total revenue?"), 503, "database_unavailable")
        monkeypatch.setenv("RSG_API_URL", live.url)
        at = AppTest.from_file(UI_PATH, default_timeout=30)
        at.run()
        ask_ui(at, "What is the total revenue?")
        assert not at.exception
        assert "not available" in at.error[0].value
        assert "python -m app.importer" in at.error[0].value
    finally:
        live.stop()


def test_damaged_database_file_is_reported_without_internal_detail(tmp_path):
    damaged = tmp_path / "damaged.db"
    damaged.write_bytes(b"this is not a sqlite database" * 40)
    client = TestClient(create_app(damaged), raise_server_exceptions=False)
    assert_clean_error(client.post("/ask", json={"question": "What is the total revenue?"}),
                       503, "database_unavailable")
    assert client.get("/health").status_code == 200


def test_database_with_no_rows_answers_with_empty_results(tmp_path):
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text(",".join(["Transaction_Id", "Order_date", "Product", "Category", "Region",
                                  "Sales_channel", "Quantity", "Unit_price", "Discount_amount", "Status"]) + "\n",
                        encoding="utf-8")
    import_csv(csv_path, tmp_path / "empty.db", tmp_path / "i.csv")
    client = TestClient(create_app(tmp_path / "empty.db"), raise_server_exceptions=False)
    assert client.post("/ask", json={"question": "What is the total revenue?"}).json()["result"] == {"total_revenue": 0.0}
    assert client.post("/ask", json={"question": "Which region generated the highest sales?"}).json()["result"]["region"] is None
    assert client.post("/ask", json={"question": "What is the monthly revenue trend?"}).json()["supporting_figures"]["monthly_revenue"] == []


# ----------------------------------------------------------------- 7. no key, LLM off (default)

def test_default_configuration_needs_no_key_and_uses_the_fallback(sales_db):
    settings = Settings.from_environment({}, dotenv_path=None)
    assert settings.provider == "none" and settings.llm_active is False
    client = TestClient(create_app(sales_db, settings=settings), raise_server_exceptions=False)
    health = client.get("/health").json()["interpretation"]
    assert health["mode"] == "fallback" and health["problem"] is None
    body = client.post("/ask", json={"question": "What is the total revenue?"}).json()
    assert body["interpretation_source"] == "fallback"
    assert any("no AI model was used" in note for note in body["notes"])


def test_provider_none_ignores_a_stray_key(sales_db):
    settings = Settings.from_environment(
        {"LLM_PROVIDER": "none", "LLM_API_KEY": "sk-should-be-ignored", "LLM_MODEL": "m"}, dotenv_path=None)
    client = TestClient(create_app(sales_db, settings=settings), raise_server_exceptions=False)
    body = client.post("/ask", json={"question": "What is the total revenue?"}).json()
    assert body["interpretation_source"] == "fallback"
    assert "sk-should-be-ignored" not in json.dumps(client.get("/health").json())


def test_no_network_is_needed_for_the_fallback(sales_db, monkeypatch):
    import urllib.request

    def no_network(*args, **kwargs):
        raise AssertionError("the fallback must not open a network connection")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    client = TestClient(create_app(sales_db), raise_server_exceptions=False)
    assert client.post("/ask", json={"question": "Which product generated the highest revenue?"}).status_code == 200


# ----------------------------------------------------------------- 8. concurrency

def test_parallel_requests_all_succeed_with_identical_answers(backend):
    def one(_):
        return http_ask(backend.url, "What is the total revenue?").json()["result"]["total_revenue"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(one, range(40)))
    assert values == [float(ref.q2(REFERENCE.total))] * 40
