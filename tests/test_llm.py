"""LLM module tests: prompt, output parsing and validation, HTTP client, and HTTP error mapping.
No network access. The HTTP layer is replaced by fakes or monkeypatched urllib calls."""
import json
import socket
import urllib.error
import urllib.request

import pytest

from app import llm
from app.llm import LLMUnavailable, OpenAICompatibleClient, build_prompt, parse_model_output, validate_payload
from app.question_router import UNSUPPORTED, QuestionError

SECRET = "sk-SECRET-DO-NOT-LEAK"


# ----------------------------------------------------------------- prompt

def test_prompt_lists_only_supported_operations_and_the_data_range():
    system, user = build_prompt("What is the total revenue?", "2026-01", "2026-06", 2026)
    for name in ("total_revenue", "top_product", "monthly_trend", "top_region", "compare_months", "unsupported"):
        assert f'"{name}"' in system
    assert "2026-01 to 2026-06" in system
    assert "use 2026" in system
    assert user == "Question: What is the total revenue?"
    assert "Never answer the question" in system


def test_prompt_handles_unknown_data_range_and_missing_default_year():
    system, _ = build_prompt("x", None, None, None)
    assert "data range is not known" in system
    assert "use null for that month" in system


# ----------------------------------------------------------------- parsing

@pytest.mark.parametrize(
    "text",
    [
        '{"operation": "total_revenue", "month_a": null, "month_b": null}',
        '```json\n{"operation": "total_revenue", "month_a": null, "month_b": null}\n```',
        '```\n{"operation": "total_revenue"}\n```',
    ],
)
def test_parse_accepts_bare_and_fenced_json_objects(text):
    assert parse_model_output(text)["operation"] == "total_revenue"


@pytest.mark.parametrize(
    "text",
    ["", "not json", "Sure! {\"operation\": \"total_revenue\"}", '["list"]', None, 42, "```json\nnot json\n```"],
)
def test_parse_rejects_anything_that_is_not_a_json_object(text):
    with pytest.raises(LLMUnavailable, match="malformed model output"):
        parse_model_output(text)


# ----------------------------------------------------------------- validation

def test_valid_operation_is_accepted_and_labelled_llm():
    interp = validate_payload({"operation": "top_region", "month_a": None, "month_b": None})
    assert interp.operation == "top_region"
    assert interp.interpretation_source == "llm"


def test_valid_compare_months_is_accepted():
    interp = validate_payload({"operation": "compare_months", "month_a": "2026-05", "month_b": "2026-06"})
    assert (interp.operation, interp.month_a, interp.month_b) == ("compare_months", "2026-05", "2026-06")


def test_extra_fields_such_as_numbers_are_ignored_not_used():
    interp = validate_payload({"operation": "total_revenue", "total_revenue": 999999, "answer": "x"})
    assert interp.operation == "total_revenue"
    assert not hasattr(interp, "total_revenue")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"operation": None},
        {"operation": 5},
        {"operation": "drop_table"},
        {"operation": "SELECT * FROM transactions"},
        {"operation": "compare_months", "month_a": "May", "month_b": "June"},
        {"operation": "compare_months", "month_a": "2026-05"},
        {"operation": "compare_months", "month_a": "2026-13", "month_b": "2026-06"},
        {"operation": "compare_months", "month_a": 202605, "month_b": "2026-06"},
    ],
)
def test_malformed_or_unknown_operations_are_rejected(payload):
    with pytest.raises(LLMUnavailable):
        validate_payload(payload)


def test_model_unsupported_answer_is_final_and_not_guessed():
    with pytest.raises(QuestionError) as info:
        validate_payload({"operation": "unsupported"})
    assert info.value.code == UNSUPPORTED


# ----------------------------------------------------------------- client

class RecordingPost:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        if self.error:
            raise self.error
        return self.response


def test_client_sends_a_chat_request_with_bearer_auth_and_zero_temperature():
    post = RecordingPost(response={"choices": [{"message": {"content": '{"operation": "total_revenue"}'}}]})
    client = OpenAICompatibleClient("https://example.test/v1/", SECRET, "model-x", 7.5, post=post)
    text = client.complete("system text", "user text")
    assert text == '{"operation": "total_revenue"}'
    url, headers, body, timeout = post.calls[0]
    assert url == "https://example.test/v1/chat/completions"
    assert headers["Authorization"] == f"Bearer {SECRET}"
    assert body["model"] == "model-x" and body["temperature"] == 0
    assert body["messages"][0] == {"role": "system", "content": "system text"}
    assert body["messages"][1] == {"role": "user", "content": "user text"}
    assert timeout == 7.5


def test_client_repr_never_shows_the_key():
    client = OpenAICompatibleClient("https://example.test/v1", SECRET, "model-x")
    assert SECRET not in repr(client)


def test_malformed_provider_envelope_is_unavailable():
    post = RecordingPost(response={"unexpected": True})
    client = OpenAICompatibleClient("https://example.test/v1", SECRET, "m", post=post)
    with pytest.raises(LLMUnavailable, match="malformed provider response"):
        client.complete("s", "u")


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "authentication failed"),
        (403, "authentication failed"),
        (404, "endpoint or model not found"),
        (429, "rate limit"),
        (500, "provider server error"),
        (418, "HTTP 418"),
    ],
)
def test_http_errors_map_to_safe_reasons_without_the_key(monkeypatch, status, expected):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, status, "error", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = OpenAICompatibleClient("https://example.test/v1", SECRET, "m")
    with pytest.raises(LLMUnavailable) as info:
        client.complete("s", "u")
    assert expected in info.value.reason
    assert SECRET not in info.value.reason


def test_timeout_is_reported_as_timeout(monkeypatch):
    def fake_urlopen(request, timeout):
        raise socket.timeout("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = OpenAICompatibleClient("https://example.test/v1", SECRET, "m")
    with pytest.raises(LLMUnavailable, match="timed out"):
        client.complete("s", "u")


def test_url_error_with_timeout_reason_is_reported_as_timeout(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError(socket.timeout("timed out"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = OpenAICompatibleClient("https://example.test/v1", SECRET, "m")
    with pytest.raises(LLMUnavailable, match="timed out"):
        client.complete("s", "u")


def test_network_failure_is_reported_without_internal_detail(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("name resolution failed for internal-host")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = OpenAICompatibleClient("https://example.test/v1", SECRET, "m")
    with pytest.raises(LLMUnavailable) as info:
        client.complete("s", "u")
    assert "network error" in info.value.reason
    assert "internal-host" not in info.value.reason


def test_non_json_provider_body_is_unavailable(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"<html>gateway page</html>"

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: FakeResponse())
    client = OpenAICompatibleClient("https://example.test/v1", SECRET, "m")
    with pytest.raises(LLMUnavailable, match="malformed provider response"):
        client.complete("s", "u")


def test_successful_http_round_trip_parses_json(monkeypatch):
    payload = {"choices": [{"message": {"content": '{"operation": "monthly_trend"}'}}]}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    seen = {}

    def fake_urlopen(request, timeout):
        seen["auth"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = OpenAICompatibleClient("https://example.test/v1", SECRET, "m", 3.0)
    assert client.complete("s", "u") == '{"operation": "monthly_trend"}'
    assert seen == {"auth": f"Bearer {SECRET}", "timeout": 3.0}
