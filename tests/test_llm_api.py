"""API tests for the Phase 4 interpretation path: LLM success, LLM failure, and secret safety."""
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_CSV_PATH
from app.importer import import_csv
from app.llm import LLMUnavailable
from app.main import create_app
from app.settings import Settings
from tests.helpers import FakeLLMClient

SECRET = "sk-test-SECRET-DO-NOT-LEAK-999"
TOTAL_REPLY = '{"operation": "total_revenue", "month_a": null, "month_b": null}'


@pytest.fixture(scope="module")
def supplied_db(tmp_path_factory):
    folder = tmp_path_factory.mktemp("llm_api")
    import_csv(DEFAULT_CSV_PATH, folder / "sales.db", folder / "issues.csv")
    return folder / "sales.db"


def client_with(supplied_db, llm_client=None, settings=None):
    return TestClient(create_app(supplied_db, settings=settings, llm_client=llm_client), raise_server_exceptions=False)


def test_llm_answers_a_paraphrase_and_numbers_come_from_the_database(supplied_db):
    # The fake model adds a made-up number. It must be ignored: the answer uses the database value.
    reply = '{"operation": "total_revenue", "total_revenue": 999999999, "answer": "fake"}'
    client = client_with(supplied_db, FakeLLMClient(reply=reply))
    body = client.post("/ask", json={"question": "What is our overall sales income?"}).json()
    assert body["interpretation_source"] == "llm"
    assert body["operation"] == "total_revenue"
    assert body["result"] == {"total_revenue": 1439200.00}
    assert "1,439,200.00" in body["answer"]
    assert "999999999" not in str(body)


def test_llm_month_comparison_is_answered_from_the_database(supplied_db):
    reply = '{"operation": "compare_months", "month_a": "2026-05", "month_b": "2026-06"}'
    client = client_with(supplied_db, FakeLLMClient(reply=reply))
    body = client.post("/ask", json={"question": "Did sales drop from spring peak into June?"}).json()
    assert body["interpretation_source"] == "llm"
    assert body["result"]["absolute_change"] == -107250.00
    assert body["result"]["percentage_change"] == -33.67


def test_llm_month_outside_the_data_is_rejected_by_analytics(supplied_db):
    reply = '{"operation": "compare_months", "month_a": "2026-05", "month_b": "2026-09"}'
    client = client_with(supplied_db, FakeLLMClient(reply=reply))
    response = client.post("/ask", json={"question": "anything"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_parameters"


def test_llm_refusal_returns_422_unsupported(supplied_db):
    client = client_with(supplied_db, FakeLLMClient(reply='{"operation": "unsupported"}'))
    response = client.post("/ask", json={"question": "Write me a poem"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_question"


def test_llm_outage_falls_back_for_a_supported_question(supplied_db):
    client = client_with(supplied_db, FakeLLMClient(error=LLMUnavailable("request timed out")))
    body = client.post("/ask", json={"question": "What is the total revenue?"}).json()
    assert body["interpretation_source"] == "fallback"
    assert body["result"] == {"total_revenue": 1439200.00}
    assert any("request timed out" in note for note in body["notes"])


def test_llm_outage_with_unsupported_question_returns_helpful_422(supplied_db):
    client = client_with(supplied_db, FakeLLMClient(error=LLMUnavailable("request timed out")))
    response = client.post("/ask", json={"question": "Tell me a joke"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_question"
    assert "request timed out" in response.json()["error"]["message"]


def test_health_reports_llm_mode_without_the_key(supplied_db):
    client = client_with(supplied_db, FakeLLMClient(reply=TOTAL_REPLY))
    body = client.get("/health").json()
    assert body["interpretation"]["mode"] == "llm"
    assert body["interpretation"]["model"] == "fake-model"
    assert SECRET not in str(body)


def test_missing_key_gives_fallback_with_a_clear_health_problem(supplied_db):
    settings = Settings(provider="openai_compatible", api_key="", model="m1")
    client = client_with(supplied_db, settings=settings)
    health = client.get("/health").json()["interpretation"]
    assert health["mode"] == "fallback"
    assert "LLM_API_KEY is not set" in health["problem"]
    body = client.post("/ask", json={"question": "What is the total revenue?"}).json()
    assert body["interpretation_source"] == "fallback"
    assert any("LLM_API_KEY is not set" in note for note in body["notes"])


def test_real_client_auth_failure_falls_back_and_never_leaks_the_key(supplied_db, monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    settings = Settings(provider="openai_compatible", api_key=SECRET, model="m1")
    client = client_with(supplied_db, settings=settings)
    assert SECRET not in client.get("/health").text
    response = client.post("/ask", json={"question": "What is the total revenue?"})
    assert response.status_code == 200
    body = response.json()
    assert body["interpretation_source"] == "fallback"
    assert "authentication failed" in " ".join(body["notes"])
    assert SECRET not in response.text


def test_api_key_is_never_present_in_any_response_body(supplied_db):
    settings = Settings(provider="openai_compatible", api_key=SECRET, model="m1")
    client = client_with(supplied_db, FakeLLMClient(reply=TOTAL_REPLY), settings=settings)
    for path, kwargs in [
        ("/health", {}),
        ("/ask", {"json": {"question": "What is the total revenue?"}}),
        ("/ask", {"json": {"question": ""}}),
    ]:
        response = client.get(path) if not kwargs else client.post(path, **kwargs)
        assert SECRET not in response.text
