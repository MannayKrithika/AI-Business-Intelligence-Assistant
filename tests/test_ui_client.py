"""Tests for the UI's HTTP client and display helpers. Uses httpx.MockTransport, so no server is needed."""
import httpx
import pytest

from app import ui_client
from app.ui_client import ApiResult

BASE = "http://backend.test"


def mock(handler):
    return httpx.MockTransport(handler)


def json_response(status, body):
    return httpx.Response(status, json=body)


SUCCESS_BODY = {
    "question": "What is the total revenue?",
    "operation": "total_revenue",
    "interpretation_source": "fallback",
    "answer": "Total net revenue is 1,439,200.00 from 49 eligible transactions.",
    "result": {"total_revenue": 1439200.0},
    "supporting_figures": {"eligible_transactions": 49},
    "notes": ["Net revenue = quantity × unit price − discount."],
}


def test_successful_answer_is_returned_unchanged():
    seen = {}

    def handler(request):
        seen["body"] = request.read()
        seen["url"] = str(request.url)
        return json_response(200, SUCCESS_BODY)

    result = ui_client.ask("  What is the total revenue?  ", BASE, transport=mock(handler))
    assert result.ok is True and result.status == 200
    assert result.data == SUCCESS_BODY
    assert seen["url"] == f"{BASE}/ask"
    import json
    assert json.loads(seen["body"]) == {"question": "What is the total revenue?"}  # trimmed before sending


@pytest.mark.parametrize(
    "status, code",
    [
        (400, "malformed_request"),
        (422, "unsupported_question"),
        (422, "invalid_parameters"),
        (503, "database_unavailable"),
        (500, "internal_error"),
    ],
)
def test_backend_error_bodies_map_to_code_and_message(status, code):
    body = {"error": {"code": code, "message": f"Message for {code}."}}
    result = ui_client.ask("x", BASE, transport=mock(lambda r: json_response(status, body)))
    assert result.ok is False
    assert result.status == status
    assert result.error_code == code
    assert result.message == f"Message for {code}."
    assert result.data is None


def test_error_without_expected_body_still_gives_a_safe_message():
    result = ui_client.ask("x", BASE, transport=mock(lambda r: httpx.Response(502, text="<html>bad gateway</html>")))
    assert result.ok is False and result.error_code == "unexpected_response"


def test_error_json_without_error_object_is_http_error():
    result = ui_client.ask("x", BASE, transport=mock(lambda r: json_response(418, {"teapot": True})))
    assert result.error_code == "http_error"
    assert "418" in result.message


def test_success_without_answer_fields_is_rejected_not_shown():
    result = ui_client.ask("x", BASE, transport=mock(lambda r: json_response(200, {"status": "ok"})))
    assert result.ok is False and result.error_code == "unexpected_response"
    assert result.data is None


def test_non_json_success_is_unexpected_response():
    result = ui_client.ask("x", BASE, transport=mock(lambda r: httpx.Response(200, text="not json")))
    assert result.ok is False and result.error_code == "unexpected_response"


def test_connection_refused_gives_clear_start_instructions():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    result = ui_client.ask("x", BASE, transport=mock(handler))
    assert result.ok is False
    assert result.error_code == "backend_unreachable"
    assert BASE in result.message
    assert ui_client.START_COMMAND in result.message


def test_timeout_is_reported_separately():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    result = ui_client.ask("x", BASE, transport=mock(handler))
    assert result.error_code == "backend_timeout"
    assert BASE in result.message


def test_empty_or_blank_question_never_reaches_the_backend():
    def handler(request):
        raise AssertionError("the backend must not be called for an empty question")

    for question in ["", "   ", None]:
        result = ui_client.ask(question, BASE, transport=mock(handler))
        assert result.ok is False
        assert result.error_code == "empty_question"
        assert result.message == ui_client.EMPTY_MESSAGE


def test_health_returns_body_when_reachable():
    body = {"status": "ok", "interpretation": {"mode": "fallback"}}
    assert ui_client.health(BASE, transport=mock(lambda r: json_response(200, body))) == body


def test_health_returns_none_when_unreachable_or_broken():
    def refuse(request):
        raise httpx.ConnectError("refused")

    assert ui_client.health(BASE, transport=mock(refuse)) is None
    assert ui_client.health(BASE, transport=mock(lambda r: httpx.Response(200, text="nope"))) is None
    assert ui_client.health(BASE, transport=mock(lambda r: httpx.Response(500, json={}))) is None


# ----------------------------------------------------------------- configuration

def test_api_url_defaults_when_nothing_is_set(tmp_path):
    assert ui_client.api_base_url({}, dotenv_path=None) == ui_client.DEFAULT_API_URL


def test_api_url_environment_variable_wins_over_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("RSG_API_URL=http://from-file:9000\n", encoding="utf-8")
    assert ui_client.api_base_url({"RSG_API_URL": "http://from-env:8100/"}, dotenv_path=env_file) == "http://from-env:8100"
    assert ui_client.api_base_url({}, dotenv_path=env_file) == "http://from-file:9000"


# ----------------------------------------------------------------- display helpers

@pytest.mark.parametrize(
    "value, text",
    [(1439200.0, "1,439,200.00"), (-107250.0, "-107,250.00"), (0.0, "0.00"), (None, "—")],
)
def test_format_money(value, text):
    assert ui_client.format_money(value) == text


def test_format_percentage_shows_sign_and_undefined_case():
    assert ui_client.format_percentage(-33.67) == "-33.67%"
    assert ui_client.format_percentage(51.49) == "+51.49%"
    assert "Undefined" in ui_client.format_percentage(None)


def test_month_label_and_unknown_month_passthrough():
    assert ui_client.month_label("2026-05") == "May 2026"
    assert ui_client.month_label("not-a-month") == "not-a-month"
    assert ui_client.month_label(None) == "—"


def test_source_labels_distinguish_llm_and_fallback():
    assert "LLM" in ui_client.source_label("llm")
    assert "Deterministic fallback" in ui_client.source_label("fallback")
    assert "no AI model" in ui_client.source_label("fallback")


def test_interpreter_summary_levels():
    assert ui_client.interpreter_summary(None)[0] == "error"
    level, text = ui_client.interpreter_summary({"interpretation": {"mode": "llm", "model": "m1"}})
    assert level == "success" and "m1" in text
    level, text = ui_client.interpreter_summary(
        {"interpretation": {"mode": "fallback", "problem": "LLM_API_KEY is not set"}})
    assert level == "info" and "LLM_API_KEY is not set" in text
    level, text = ui_client.interpreter_summary({"interpretation": {"mode": "fallback", "problem": None}})
    assert level == "info" and "no AI key" in text


def test_api_result_dataclass_defaults():
    failure = ApiResult(False, None, error_code="x", message="m")
    assert failure.data is None and failure.status is None
