"""Deterministic rule-based interpreter (the fallback path).

Maps a natural-language question to one supported operation and, for month comparisons,
two validated YYYY-MM months, using keyword and token rules only. It never produces numbers
and never produces SQL. It is used whenever the LLM is not configured or is unavailable.
Interpretations from this module are labelled interpretation_source = "fallback".

Rejections are explicit:
  unsupported_question  no supported operation is recognised
  ambiguous_question    more than one operation is recognised
  invalid_parameters    month references are missing, malformed, or unusable
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SUPPORTED_OPERATIONS = ("total_revenue", "top_product", "monthly_trend", "top_region", "compare_months")

UNSUPPORTED = "unsupported_question"
AMBIGUOUS = "ambiguous_question"
INVALID = "invalid_parameters"

MONTH_NAMES = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
# "may" is also an ordinary verb, so it counts as a month only after one of these words.
MAY_CONTEXT = {"in", "of", "from", "between", "and", "to", "vs", "versus", "during", "for", "till", "until"}
RANK_WORDS = {"highest", "top", "best", "most", "which"}
TREND_WORDS = {"monthly", "trend"}
COMPARE_WORDS = {
    "change", "changed", "compare", "comparison", "difference",
    "vs", "versus", "between", "growth", "increase", "decrease",
}

_TOKEN = re.compile(r"\d{4}-\d{2}|[a-z]+|\d{4}")
_ISO_MONTH = re.compile(r"(\d{4})-(\d{2})")
_YEAR = re.compile(r"\d{4}")


class QuestionError(Exception):
    """A question that cannot be answered. `code` is one of UNSUPPORTED, AMBIGUOUS, INVALID."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MonthRef:
    year: int | None
    month: int | None  # None when the written month is not 1..12
    text: str


@dataclass
class Interpretation:
    operation: str
    month_a: str | None = None  # YYYY-MM, baseline month for compare_months
    month_b: str | None = None  # YYYY-MM, second month for compare_months
    notes: list[str] = field(default_factory=list)
    interpretation_source: str = "fallback"


def _tokens(question: str) -> list[str]:
    return _TOKEN.findall(question.lower())


def _month_refs(tokens: list[str]) -> list[MonthRef]:
    refs: list[MonthRef] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        iso = _ISO_MONTH.fullmatch(token)
        if iso:
            month = int(iso.group(2))
            refs.append(MonthRef(int(iso.group(1)), month if 1 <= month <= 12 else None, token))
        elif token in MONTH_NAMES:
            if token == "may" and not (i > 0 and tokens[i - 1] in MAY_CONTEXT):
                i += 1
                continue  # the ordinary verb "may"
            year = None
            if i + 1 < len(tokens) and _YEAR.fullmatch(tokens[i + 1]):
                year = int(tokens[i + 1])
                i += 1
            refs.append(MonthRef(year, MONTH_NAMES[token], token))
        i += 1
    return refs


def _matched_operations(tokens: list[str]) -> list[str]:
    words = set(tokens)
    matched = []
    if "total" in words and "revenue" in words:
        matched.append("total_revenue")
    if "product" in words and words & RANK_WORDS:
        matched.append("top_product")
    if "region" in words and words & RANK_WORDS:
        matched.append("top_region")
    if words & TREND_WORDS:
        matched.append("monthly_trend")
    if words & COMPARE_WORDS:
        matched.append("compare_months")
    return matched


def interpret(question: str, default_year: int | None) -> Interpretation:
    """Interpret one question or raise QuestionError.

    default_year is used only when a month is written without a year. It is None when the
    stored data spans more than one year, in which case the year must be stated.
    """
    tokens = _tokens(question) if isinstance(question, str) else []
    operations = _matched_operations(tokens)
    if not operations:
        raise QuestionError(
            UNSUPPORTED,
            "This question is not one of the supported analyses. You can ask for total revenue, "
            "the highest-revenue product, the monthly revenue trend, the highest-sales region, "
            "or how revenue changed between two months.",
        )
    if len(operations) > 1:
        raise QuestionError(
            AMBIGUOUS,
            "This question could mean more than one analysis. Please ask one question at a time.",
        )

    operation = operations[0]
    refs = _month_refs(tokens)

    if operation != "compare_months":
        if refs:
            raise QuestionError(INVALID, "Month names are only supported in month-comparison questions.")
        return Interpretation(operation)

    if len(refs) != 2:
        raise QuestionError(
            INVALID,
            f"Please name exactly two months to compare, for example 'between May and June'. "
            f"Found {len(refs)}.",
        )

    resolved: list[str] = []
    defaulted = False
    for ref in refs:
        if ref.month is None:
            raise QuestionError(INVALID, f"'{ref.text}' is not a valid month.")
        year = ref.year
        if year is None:
            if default_year is None:
                raise QuestionError(INVALID, f"Please include the year for '{ref.text}', for example 'May 2026'.")
            year = default_year
            defaulted = True
        resolved.append(f"{year:04d}-{ref.month:02d}")

    notes = []
    if defaulted:
        notes.append(f"No year was stated, so {default_year} was used from the stored data.")
    return Interpretation("compare_months", resolved[0], resolved[1], notes)
