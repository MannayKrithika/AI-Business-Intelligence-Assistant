"""Interpreter tests: LLM first when active, deterministic fallback otherwise, and clear labelling."""
import pytest

from app.interpreter import Interpreter, InterpretationContext
from app.llm import LLMUnavailable
from app.question_router import UNSUPPORTED, QuestionError
from tests.helpers import FakeLLMClient

CTX = InterpretationContext(default_year=2026, first_month="2026-01", last_month="2026-06")
TOTAL_REPLY = '{"operation": "total_revenue", "month_a": null, "month_b": null}'


def test_without_llm_the_fallback_is_used_and_says_so():
    result = Interpreter().interpret("What is the total revenue?", CTX)
    assert result.operation == "total_revenue"
    assert result.interpretation_source == "fallback"
    assert result.notes[0].startswith("Interpreted by the deterministic fallback (no AI model was used)")


def test_llm_reply_is_used_and_labelled_llm():
    client = FakeLLMClient(reply=TOTAL_REPLY)
    result = Interpreter(client, provider="openai_compatible").interpret("What is the total revenue?", CTX)
    assert result.interpretation_source == "llm"
    assert result.operation == "total_revenue"
    assert "Interpreted by an LLM (fake-model)" in result.notes[0]
    assert len(client.prompts) == 1


def test_llm_understands_a_paraphrase_the_fallback_cannot():
    question = "What is our overall sales income?"
    with pytest.raises(QuestionError):
        Interpreter().interpret(question, CTX)  # fallback has no keyword match
    client = FakeLLMClient(reply=TOTAL_REPLY)
    result = Interpreter(client).interpret(question, CTX)
    assert result.operation == "total_revenue" and result.interpretation_source == "llm"


def test_prompt_sent_to_the_model_contains_the_question_in_the_user_message_only():
    client = FakeLLMClient(reply=TOTAL_REPLY)
    Interpreter(client).interpret("What is the total revenue?", CTX)
    system, user = client.prompts[0]
    assert "What is the total revenue?" in user
    assert "What is the total revenue?" not in system


@pytest.mark.parametrize(
    "error",
    [LLMUnavailable("request timed out"), LLMUnavailable("authentication failed; check LLM_API_KEY")],
)
def test_llm_failure_falls_back_and_explains_why(error):
    client = FakeLLMClient(error=error)
    result = Interpreter(client).interpret("What is the total revenue?", CTX)
    assert result.interpretation_source == "fallback"
    assert result.operation == "total_revenue"
    assert error.reason in result.notes[0]
    assert "deterministic fallback was used" in result.notes[0]


@pytest.mark.parametrize(
    "reply",
    ["not json at all", '{"operation": "delete_everything"}', '{"operation": "compare_months", "month_a": "May", "month_b": "June"}'],
)
def test_malformed_or_invalid_llm_reply_falls_back(reply):
    client = FakeLLMClient(reply=reply)
    question = "How did revenue change between May and June?" if "compare" in reply else "What is the total revenue?"
    result = Interpreter(client).interpret(question, CTX)
    assert result.interpretation_source == "fallback"
    assert "unavailable" in result.notes[0]


def test_llm_refusal_is_final_and_does_not_fall_back():
    client = FakeLLMClient(reply='{"operation": "unsupported"}')
    with pytest.raises(QuestionError) as info:
        Interpreter(client).interpret("What is the total revenue?", CTX)
    assert info.value.code == UNSUPPORTED


def test_llm_month_pair_is_passed_through_for_analytics_to_validate():
    client = FakeLLMClient(reply='{"operation": "compare_months", "month_a": "2026-05", "month_b": "2026-05"}')
    result = Interpreter(client).interpret("anything", CTX)
    assert (result.month_a, result.month_b) == ("2026-05", "2026-05")
    assert result.interpretation_source == "llm"


def test_configuration_problem_falls_back_with_the_reason():
    interpreter = Interpreter(None, "LLM_API_KEY is not set", provider="openai_compatible")
    result = interpreter.interpret("What is the total revenue?", CTX)
    assert result.interpretation_source == "fallback"
    assert "LLM_API_KEY is not set" in result.notes[0]


def test_unsupported_question_with_llm_unavailable_mentions_the_reason():
    client = FakeLLMClient(error=LLMUnavailable("request timed out"))
    with pytest.raises(QuestionError) as info:
        Interpreter(client).interpret("Tell me a joke", CTX)
    assert info.value.code == UNSUPPORTED
    assert "request timed out" in info.value.message


def test_describe_reports_mode_without_any_secret():
    assert Interpreter().describe() == {"mode": "fallback", "provider": None, "model": None, "problem": None}
    active = Interpreter(FakeLLMClient(), provider="openai_compatible").describe()
    assert active["mode"] == "llm" and active["model"] == "fake-model"
