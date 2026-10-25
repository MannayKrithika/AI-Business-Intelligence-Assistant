"""Groq configuration and safe-failure tests. No network access: the HTTP layer is faked.

These tests prove configuration, request format, validation and fallback behaviour. They do NOT
prove that the real Groq service accepts the request. That is checked only by the opt-in live
test (tests/test_live_provider.py) or `python -m app.verify_llm --yes`, run by the owner.
"""
import socket
import urllib.error
import urllib.request

import pytest

from app import verify_llm
from app.interpreter import Interpreter, InterpretationContext
from app.llm import LLMUnavailable, OpenAICompatibleClient
from app.question_router import QuestionError
from app.settings import GROQ_BASE_URL, GROQ_DEFAULT_MODEL, Settings
from tests.helpers import FakeLLMClient

KEY = "gsk_TEST_ONLY_NOT_A_REAL_KEY_123"
CTX = InterpretationContext(default_year=2026, first_month="2026-01", last_month="2026-06")
TOTAL_REPLY = '{"operation": "total_revenue", "month_a": null, "month_b": null}'
PARAPHRASE = "What is our overall sales income?"


def groq_settings(**overrides):
    env = {"LLM_PROVIDER": "groq", "LLM_API_KEY": KEY}
    env.update(overrides)
    return Settings.from_environment(env, dotenv_path=None)


# ------------------------------------------------------------------ configuration

def test_groq_provider_prefills_endpoint_and_model():
    settings = groq_settings()
    assert settings.problems() == []
    assert settings.llm_active is True
    assert settings.base_url == GROQ_BASE_URL == "https://api.groq.com/openai/v1"
    assert settings.model == GROQ_DEFAULT_MODEL


def test_groq_values_can_be_overridden():
    settings = groq_settings(LLM_MODEL="llama-3.3-70b-versatile", LLM_BASE_URL="https://proxy.test/v1")
    assert settings.model == "llama-3.3-70b-versatile"
    assert settings.base_url == "https://proxy.test/v1"


def test_groq_without_a_key_is_not_active_and_says_why():
    settings = Settings.from_environment({"LLM_PROVIDER": "groq"}, dotenv_path=None)
    assert settings.llm_active is False
    assert "LLM_API_KEY is not set" in settings.llm_problem()


def test_the_env_example_placeholders_are_not_treated_as_real_settings():
    settings = groq_settings(LLM_API_KEY="replace-with-your-key", LLM_MODEL="replace-with-model-name")
    assert settings.llm_active is False
    problem = settings.llm_problem()
    assert "LLM_API_KEY is still the placeholder" in problem
    assert "LLM_MODEL is still the placeholder" in problem


def test_default_provider_is_still_none_and_makes_no_request(monkeypatch):
    def forbidden(request, timeout):
        raise AssertionError("no network call is allowed with LLM_PROVIDER=none")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    settings = Settings.from_environment({}, dotenv_path=None)
    assert settings.provider == "none" and settings.llm_active is False
    result = Interpreter().interpret("What is the total revenue?", CTX)
    assert result.interpretation_source == "fallback"


def test_groq_key_never_appears_in_settings_output():
    settings = groq_settings()
    assert KEY not in repr(settings)
    assert KEY not in str(settings.describe())


def test_groq_key_can_come_from_a_dotenv_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(f"LLM_PROVIDER=groq\nLLM_API_KEY={KEY}\n", encoding="utf-8")
    settings = Settings.from_environment({}, dotenv_path=path)
    assert settings.llm_active is True and settings.provider == "groq"


# ------------------------------------------------------------------ request format

class RecordingPost:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        return self.response


def test_groq_request_goes_to_the_chat_completions_endpoint_with_bearer_auth():
    post = RecordingPost({"choices": [{"message": {"content": TOTAL_REPLY}}]})
    settings = groq_settings()
    client = OpenAICompatibleClient(settings.base_url, settings.api_key, settings.model,
                                    settings.timeout_seconds, post=post)
    assert client.complete("s", "u") == TOTAL_REPLY
    url, headers, body, _ = post.calls[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert body["model"] == GROQ_DEFAULT_MODEL
    assert "response_format" not in body and "tools" not in body  # plain chat request only


def test_real_http_path_sends_a_descriptive_user_agent_not_the_python_default(monkeypatch):
    seen = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"choices": [{"message": {"content": "{\\"operation\\": \\"total_revenue\\"}"}}]}'

    def fake_urlopen(request, timeout):
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    OpenAICompatibleClient(GROQ_BASE_URL, KEY, GROQ_DEFAULT_MODEL).complete("s", "u")
    assert seen["headers"]["user-agent"].startswith("rsg-bi-assistant/")
    assert "python-urllib" not in seen["headers"]["user-agent"].lower()
    assert seen["headers"]["authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize("status, expected", [(400, "HTTP 400"), (422, "HTTP 422")])
def test_rejected_requests_point_the_owner_at_the_model_setting(monkeypatch, status, expected):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, status, "bad request", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = OpenAICompatibleClient(GROQ_BASE_URL, KEY, "retired-model")
    with pytest.raises(LLMUnavailable) as info:
        client.complete("s", "u")
    assert expected in info.value.reason and "LLM_MODEL" in info.value.reason
    assert KEY not in info.value.reason


# ------------------------------------------------------------------ safe failure and fallback

@pytest.mark.parametrize("reply", [
    "Sure! Here is the JSON: " + TOTAL_REPLY,                 # prose around the object
    "SELECT SUM(quantity) FROM transactions",                 # SQL instead of a classification
    '{"operation": "DROP TABLE transactions"}',               # operation outside the allow-list
    '{"operation": "compare_months", "month_a": "May", "month_b": "June"}',  # months not YYYY-MM
    "",                                                       # empty reply
    "null",
])
def test_unusable_model_replies_fall_back_to_the_deterministic_matcher(reply):
    client = FakeLLMClient(reply=reply)
    result = Interpreter(client, provider="groq").interpret("What is the total revenue?", CTX)
    assert result.interpretation_source == "fallback"
    assert result.operation == "total_revenue"
    assert "unavailable" in result.notes[0]


@pytest.mark.parametrize("reason", [
    "authentication failed; check LLM_API_KEY",
    "rate limit or quota reached",
    "request timed out",
    "provider server error",
    "network error; check the internet connection and LLM_BASE_URL",
])
def test_provider_failures_fall_back_and_name_the_reason(reason):
    client = FakeLLMClient(error=LLMUnavailable(reason))
    result = Interpreter(client, provider="groq").interpret("What is the total revenue?", CTX)
    assert result.interpretation_source == "fallback"
    assert reason in result.notes[0]


def test_a_paraphrase_is_answered_by_the_llm_path_and_labelled_llm():
    client = FakeLLMClient(reply=TOTAL_REPLY, model=GROQ_DEFAULT_MODEL)
    result = Interpreter(client, provider="groq").interpret(PARAPHRASE, CTX)
    assert result.interpretation_source == "llm"
    assert result.operation == "total_revenue"
    assert Interpreter(client, provider="groq").describe()["provider"] == "groq"


# ------------------------------------------------------------------ owner-run verification helper

def test_verify_check_passes_when_the_model_picks_total_revenue():
    client = FakeLLMClient(reply=TOTAL_REPLY, model="m")
    passed, message = verify_llm.run_check(groq_settings(), client=client)
    assert passed and "total_revenue" in message
    assert len(client.prompts) == 1  # exactly one request
    assert PARAPHRASE in client.prompts[0][1]


def test_verify_check_fails_for_the_wrong_operation_or_a_provider_error():
    wrong = FakeLLMClient(reply='{"operation": "top_product"}', model="m")
    assert verify_llm.run_check(groq_settings(), client=wrong)[0] is False
    broken = FakeLLMClient(error=LLMUnavailable("rate limit or quota reached"), model="m")
    passed, message = verify_llm.run_check(groq_settings(), client=broken)
    assert not passed and "rate limit" in message
    refused = FakeLLMClient(reply='{"operation": "unsupported"}', model="m")
    assert verify_llm.run_check(groq_settings(), client=refused)[0] is False


def test_verify_check_reports_missing_configuration_without_any_request(monkeypatch):
    def forbidden(request, timeout):
        raise AssertionError("no request may be sent when the provider is not configured")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    settings = Settings.from_environment({}, dotenv_path=None)
    passed, message = verify_llm.run_check(settings)
    assert not passed and "not configured" in message


def test_verify_command_needs_explicit_confirmation(monkeypatch, capsys):
    def forbidden(request, timeout):
        raise AssertionError("the command must not send a request without --yes")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    assert verify_llm.main([]) == 2
    assert "--yes" in capsys.readouterr().out


def test_verify_command_with_yes_and_no_configuration_exits_1_without_a_request(monkeypatch, capsys):
    def forbidden(request, timeout):
        raise AssertionError("no request may be sent when the provider is not configured")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    for name in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(verify_llm.Settings, "from_environment",
                        classmethod(lambda cls, *a, **k: Settings()))
    assert verify_llm.main(["--yes"]) == 1
    assert "not configured" in capsys.readouterr().out


def test_verify_output_never_contains_the_key(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    passed, message = verify_llm.run_check(groq_settings())
    assert not passed and "authentication failed" in message
    assert KEY not in message


def test_a_socket_timeout_is_reported_not_raised(monkeypatch):
    def fake_urlopen(request, timeout):
        raise socket.timeout("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    passed, message = verify_llm.run_check(groq_settings())
    assert not passed and "timed out" in message
