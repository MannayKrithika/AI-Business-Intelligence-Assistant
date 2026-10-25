"""Tests for the temporary deterministic question router. No database or network needed."""
import pytest

from app.question_router import AMBIGUOUS, INVALID, UNSUPPORTED, QuestionError, interpret


@pytest.mark.parametrize(
    "question, operation",
    [
        ("What is the total revenue?", "total_revenue"),
        ("Which product generated the highest revenue?", "top_product"),
        ("What is the monthly revenue trend?", "monthly_trend"),
        ("Which region generated the highest sales?", "top_region"),
        ("How did revenue change between May and June?", "compare_months"),
    ],
)
def test_five_example_questions_map_to_their_operation(question, operation):
    interp = interpret(question, default_year=2026)
    assert interp.operation == operation
    assert interp.interpretation_source == "fallback"


@pytest.mark.parametrize(
    "question",
    [
        "How did revenue change between May 2026 and June 2026?",
        "How did revenue change from May 2026 to June 2026?",
        "2026-05 vs 2026-06",
        "Compare revenue for 2026-05 and 2026-06",
    ],
)
def test_month_comparison_phrasings_resolve_to_iso_months(question):
    interp = interpret(question, default_year=2026)
    assert interp.operation == "compare_months"
    assert (interp.month_a, interp.month_b) == ("2026-05", "2026-06")


def test_comparison_without_stated_year_uses_default_and_adds_note():
    interp = interpret("How did revenue change between May and June?", default_year=2026)
    assert (interp.month_a, interp.month_b) == ("2026-05", "2026-06")
    assert interp.notes and "2026" in interp.notes[0]


def test_may_as_an_ordinary_verb_is_not_read_as_a_month():
    interp = interpret("How may revenue change between March and June?", default_year=2026)
    assert (interp.month_a, interp.month_b) == ("2026-03", "2026-06")


def test_comparison_order_is_preserved_as_baseline_first():
    interp = interpret("How did revenue change between June and May?", default_year=2026)
    assert (interp.month_a, interp.month_b) == ("2026-06", "2026-05")


@pytest.mark.parametrize(
    "question",
    [
        "What is the weather today?",
        "Show me all transactions",
        "Tell me a joke",
        "Revenue in May and June",          # two months but no comparison or trend keyword
        "DROP TABLE transactions",
        "",
        "   ",
    ],
)
def test_unsupported_questions_are_rejected_not_guessed(question):
    with pytest.raises(QuestionError) as info:
        interpret(question, default_year=2026)
    assert info.value.code == UNSUPPORTED


@pytest.mark.parametrize(
    "question",
    [
        "Total revenue and top product",
        "Which product generated the highest revenue between May and June?",
        "Which product and which region had the highest revenue?",
    ],
)
def test_questions_matching_several_operations_are_ambiguous(question):
    with pytest.raises(QuestionError) as info:
        interpret(question, default_year=2026)
    assert info.value.code == AMBIGUOUS


@pytest.mark.parametrize(
    "question",
    [
        "How did revenue change in May?",                   # one month
        "How did revenue change?",                          # no months
        "How did revenue change between May, June and July?",  # three months
    ],
)
def test_comparison_needs_exactly_two_months(question):
    with pytest.raises(QuestionError) as info:
        interpret(question, default_year=2026)
    assert info.value.code == INVALID


def test_identical_month_names_are_passed_through_for_analytics_to_reject():
    # The router only extracts; the analytics layer rejects identical months (tested in Phase 2).
    interp = interpret("How did revenue change between May and May?", default_year=2026)
    assert (interp.month_a, interp.month_b) == ("2026-05", "2026-05")


def test_invalid_iso_month_is_rejected():
    with pytest.raises(QuestionError) as info:
        interpret("How did revenue change between 2026-13 and 2026-05?", default_year=2026)
    assert info.value.code == INVALID
    assert "2026-13" in info.value.message


def test_missing_year_is_rejected_when_data_spans_several_years():
    with pytest.raises(QuestionError) as info:
        interpret("How did revenue change between May and June?", default_year=None)
    assert info.value.code == INVALID
    assert "year" in info.value.message


def test_month_names_are_rejected_for_non_comparison_questions():
    with pytest.raises(QuestionError) as info:
        interpret("What is the monthly revenue trend for May?", default_year=2026)
    assert info.value.code == INVALID


def test_sql_text_in_a_question_does_not_change_the_operation_or_run_anything():
    # The text is only tokenised. It can match keywords but is never executed.
    interp = interpret("What is the total revenue; DROP TABLE transactions;", default_year=2026)
    assert interp.operation == "total_revenue"
