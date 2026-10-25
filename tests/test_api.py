"""HTTP API tests using FastAPI's TestClient. Uses a temporary database built from the supplied CSV."""
import csv
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import analytics as an
from app import db
from app.config import DEFAULT_CSV_PATH, EXPECTED_COLUMNS
from app.importer import import_csv
from app.main import create_app


@pytest.fixture(scope="module")
def supplied_db(tmp_path_factory):
    folder = tmp_path_factory.mktemp("api_supplied")
    import_csv(DEFAULT_CSV_PATH, folder / "sales.db", folder / "issues.csv")
    return folder / "sales.db"


@pytest.fixture(scope="module")
def client(supplied_db):
    return TestClient(create_app(supplied_db), raise_server_exceptions=False)


def ask(client, question):
    return client.post("/ask", json={"question": question})


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    text = response.text
    assert "Traceback" not in text and "File \"" not in text


# ----------------------------------------------------------------- valid requests

def test_health_endpoint(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["interpretation"]["mode"] == "fallback"


def test_openapi_documents_the_ask_endpoint(client):
    spec = client.get("/openapi.json").json()
    assert "/ask" in spec["paths"] and "post" in spec["paths"]["/ask"]


def test_total_revenue_response(client):
    response = ask(client, "What is the total revenue?")
    assert response.status_code == 200
    body = response.json()
    assert body["operation"] == "total_revenue"
    assert body["interpretation_source"] == "fallback"
    assert body["result"] == {"total_revenue": 1439200.00}
    assert body["supporting_figures"] == {"eligible_transactions": 49}
    assert "1,439,200.00" in body["answer"]
    assert body["notes"] and body["notes"][0].startswith("Net revenue")


def test_top_product_response(client):
    body = ask(client, "Which product generated the highest revenue?").json()
    assert body["operation"] == "top_product"
    assert body["result"] == {"product": "Monitor", "revenue": 473000.00}
    ranking = body["supporting_figures"]["ranking"]
    assert len(ranking) == 7 and ranking[0]["name"] == "Monitor"
    assert "Monitor" in body["answer"]


def test_monthly_trend_response_is_chronological(client):
    body = ask(client, "What is the monthly revenue trend?").json()
    assert body["operation"] == "monthly_trend"
    assert body["result"] == {"first_month": "2026-01", "last_month": "2026-06"}
    monthly = body["supporting_figures"]["monthly_revenue"]
    assert [m["month"] for m in monthly] == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    assert [m["revenue"] for m in monthly] == [210250.00, 234600.00, 223900.00, 240700.00, 318500.00, 211250.00]


def test_top_region_response(client):
    body = ask(client, "Which region generated the highest sales?").json()
    assert body["operation"] == "top_region"
    assert body["result"] == {"region": "South", "revenue": 411200.00}
    assert len(body["supporting_figures"]["ranking"]) == 4


def test_month_comparison_response(client):
    body = ask(client, "How did revenue change between May and June?").json()
    assert body["operation"] == "compare_months"
    assert body["result"] == {"absolute_change": -107250.00, "percentage_change": -33.67, "direction": "decreased"}
    assert body["supporting_figures"]["revenue_a"] == 318500.00
    assert body["supporting_figures"]["revenue_b"] == 211250.00
    assert "decreased" in body["answer"] and "-33.67%" in body["answer"]


def test_month_comparison_with_stated_year(client):
    body = ask(client, "How did revenue change from May 2026 to June 2026?").json()
    assert body["result"]["absolute_change"] == -107250.00


def test_api_results_match_analytics_functions(client, supplied_db):
    conn = db.connect_readonly(supplied_db)
    try:
        expected = an.total_revenue(conn)
    finally:
        conn.close()
    body = ask(client, "What is the total revenue?").json()
    assert body["result"]["total_revenue"] == expected["total_revenue"]


# ----------------------------------------------------------------- malformed requests

@pytest.mark.parametrize(
    "content, headers",
    [
        (b"{not valid json", {"content-type": "application/json"}),
        (b'["a list"]', {"content-type": "application/json"}),
        (b"", {"content-type": "application/json"}),
    ],
)
def test_non_object_or_invalid_json_is_malformed(client, content, headers):
    response = client.post("/ask", content=content, headers=headers)
    assert_error(response, 400, "malformed_request")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": None},
        {"question": 12345},
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 501},
        {"question": ["What is the total revenue?"]},
        {"prompt": "What is the total revenue?"},
    ],
)
def test_missing_empty_or_wrong_type_question_is_malformed(client, payload):
    response = client.post("/ask", json=payload)
    assert_error(response, 400, "malformed_request")


def test_get_on_ask_is_not_allowed(client):
    assert client.get("/ask").status_code == 405


# ----------------------------------------------------------------- unsupported and ambiguous

@pytest.mark.parametrize("question", ["What is the weather today?", "Show me every customer's address", "Tell me a joke"])
def test_unsupported_question_returns_422_without_an_answer(client, question):
    response = ask(client, question)
    assert_error(response, 422, "unsupported_question")
    assert "result" not in response.json()


def test_ambiguous_question_returns_422(client):
    assert_error(ask(client, "Total revenue and top product"), 422, "ambiguous_question")


def test_sql_text_is_not_executed_and_database_is_unchanged(client, supplied_db):
    unsupported = ask(client, "DROP TABLE transactions")
    assert_error(unsupported, 422, "unsupported_question")
    conn = sqlite3.connect(f"file:{supplied_db.as_posix()}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 51
    finally:
        conn.close()
    # Keywords in a supported question do not make the text run as SQL either.
    body = ask(client, "What is the total revenue; DELETE FROM transactions;").json()
    assert body["operation"] == "total_revenue"
    assert body["result"]["total_revenue"] == 1439200.00


# ----------------------------------------------------------------- invalid months

@pytest.mark.parametrize(
    "question",
    [
        "How did revenue change between May and May?",     # identical
        "How did revenue change between May and July?",    # outside 2026-01..2026-06
        "How did revenue change between December and May?",  # December 2026 is outside the data
        "How did revenue change between 2025-12 and 2026-05?",  # year outside the data
        "How did revenue change between 2026-13 and 2026-05?",  # invalid month number
        "How did revenue change in May?",                  # only one month
    ],
)
def test_invalid_month_comparisons_return_422(client, question):
    response = ask(client, question)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_parameters"
    assert "result" not in response.json()


def test_out_of_range_message_states_available_range(client):
    response = ask(client, "How did revenue change between May and July?")
    assert "2026-01" in response.json()["error"]["message"]
    assert "2026-06" in response.json()["error"]["message"]


def test_identical_month_message_is_clear(client):
    message = ask(client, "How did revenue change between May and May?").json()["error"]["message"]
    assert "different" in message


# ----------------------------------------------------------------- database availability

def test_missing_database_returns_503_and_does_not_expose_the_path(tmp_path):
    client = TestClient(create_app(tmp_path / "does_not_exist.db"), raise_server_exceptions=False)
    response = ask(client, "What is the total revenue?")
    assert_error(response, 503, "database_unavailable")
    assert str(tmp_path) not in response.text
    assert client.get("/health").status_code == 200


def test_uninitialised_database_returns_503(tmp_path):
    empty_file = tmp_path / "empty.db"
    sqlite3.connect(empty_file).close()  # a valid SQLite file with no tables
    client = TestClient(create_app(empty_file), raise_server_exceptions=False)
    assert_error(ask(client, "What is the total revenue?"), 503, "database_unavailable")


def test_empty_but_initialised_database_answers_with_no_data(tmp_path):
    csv_path = tmp_path / "header_only.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(EXPECTED_COLUMNS)
    import_csv(csv_path, tmp_path / "empty.db", tmp_path / "issues.csv")
    client = TestClient(create_app(tmp_path / "empty.db"), raise_server_exceptions=False)

    total = ask(client, "What is the total revenue?")
    assert total.status_code == 200
    assert total.json()["result"] == {"total_revenue": 0.0}

    product = ask(client, "Which product generated the highest revenue?").json()
    assert product["result"] == {"product": None, "revenue": None}
    assert "No eligible transactions" in product["answer"]

    trend = ask(client, "What is the monthly revenue trend?").json()
    assert trend["supporting_figures"]["monthly_revenue"] == []

    comparison = ask(client, "How did revenue change between May and June?")
    assert_error(comparison, 422, "invalid_parameters")


# ----------------------------------------------------------------- unexpected errors

def test_unexpected_error_returns_generic_500_without_internals(client, monkeypatch):
    def broken(conn):
        raise RuntimeError("secret internal detail SELECT * FROM transactions")

    monkeypatch.setattr(an, "total_revenue", broken)
    response = ask(client, "What is the total revenue?")
    assert_error(response, 500, "internal_error")
    text = response.text
    assert "secret internal detail" not in text
    assert "RuntimeError" not in text
    assert "SELECT" not in text
