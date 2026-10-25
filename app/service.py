"""Application service: question -> interpretation -> validated analytics -> response payload.

The service only calls the analytics functions in app/analytics.py. It formats their
results and never computes or alters a number itself.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from app import analytics as an
from app.interpreter import Interpreter, InterpretationContext

BASE_NOTE = (
    "Net revenue = quantity × unit price − discount, counted once per transaction. Only Completed "
    "transactions with a unit price are included. Returned and missing-price transactions are excluded."
)


class DatabaseError(Exception):
    """The database cannot be read (missing, not initialised, or unreadable)."""


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _month_label(month: str) -> str:
    return datetime.strptime(month, "%Y-%m").strftime("%B %Y")


def default_year(conn: sqlite3.Connection) -> int | None:
    first, last = an.data_month_range(conn)
    if first is None:
        return None
    return int(first[:4]) if first[:4] == last[:4] else None


def _answer_total(conn):
    data = an.total_revenue(conn)
    answer = (
        f"Total net revenue is {_money(data['total_revenue'])} "
        f"from {data['eligible_transactions']} eligible transactions."
    )
    return answer, {"total_revenue": data["total_revenue"]}, {"eligible_transactions": data["eligible_transactions"]}, []


def _answer_ranking(data, label):
    top = data["top"]
    if top is None:
        answer = f"No eligible transactions were found, so no top {label} can be identified."
        return answer, {label: None, "revenue": None}, {"ranking": []}, []
    answer = (
        f"The highest-revenue {label} is {top['name']} with net revenue of {_money(top['revenue'])} "
        f"across {top['transactions']} transactions."
        if label == "product"
        else f"The highest-sales region is {top['name']} with net revenue of {_money(top['revenue'])} "
        f"across {top['transactions']} transactions."
    )
    return answer, {label: top["name"], "revenue": top["revenue"]}, {"ranking": data["ranking"]}, []


def _answer_monthly(conn):
    trend = an.monthly_revenue(conn)
    if not trend:
        answer = "No stored transactions were found, so there is no monthly trend."
        return answer, {"first_month": None, "last_month": None}, {"monthly_revenue": []}, []
    first, last = trend[0]["month"], trend[-1]["month"]
    answer = (
        f"Monthly net revenue from {_month_label(first)} to {_month_label(last)} is listed in "
        f"chronological order in the supporting figures ({len(trend)} months)."
    )
    return answer, {"first_month": first, "last_month": last}, {"monthly_revenue": trend}, []


def _answer_compare(conn, month_a, month_b):
    data = an.compare_months(conn, month_a, month_b)
    change = data["absolute_change"]
    sign_change = f"{change:+,.2f}"
    if data["percentage_change"] is None:
        pct_text = "the percentage change is undefined because the first month's revenue is zero"
    else:
        pct_text = f"the percentage change is {data['percentage_change']:+.2f}%"

    a_label, b_label = _month_label(month_a), _month_label(month_b)
    if data["direction"] == "unchanged":
        answer = (
            f"Net revenue was unchanged between {a_label} and {b_label} at "
            f"{_money(data['revenue_a'])}."
        )
    else:
        verb = data["direction"]
        answer = (
            f"Net revenue {verb} from {_money(data['revenue_a'])} in {a_label} to "
            f"{_money(data['revenue_b'])} in {b_label}: change {sign_change}, {pct_text}."
        )
    result = {
        "absolute_change": change,
        "percentage_change": data["percentage_change"],
        "direction": data["direction"],
    }
    supporting = {
        "month_a": data["month_a"], "revenue_a": data["revenue_a"], "transactions_a": data["transactions_a"],
        "month_b": data["month_b"], "revenue_b": data["revenue_b"], "transactions_b": data["transactions_b"],
    }
    extra_notes = [data["note"]] if data["note"] else []
    return answer, result, supporting, extra_notes


def answer_question(conn: sqlite3.Connection, question: str, interpreter: Interpreter) -> dict:
    """Answer one question. Raises QuestionError for bad questions and AnalyticsError for bad months.

    The interpreter (LLM or fallback) only chooses the operation and months. All numbers come from analytics.
    """
    try:
        first_month, last_month = an.data_month_range(conn)
        context = InterpretationContext(default_year(conn), first_month, last_month)
        interpretation = interpreter.interpret(question, context)
        op = interpretation.operation
        if op == "total_revenue":
            answer, result, supporting, extra = _answer_total(conn)
        elif op == "top_product":
            answer, result, supporting, extra = _answer_ranking(an.top_product(conn), "product")
        elif op == "top_region":
            answer, result, supporting, extra = _answer_ranking(an.top_region(conn), "region")
        elif op == "monthly_trend":
            answer, result, supporting, extra = _answer_monthly(conn)
        else:
            answer, result, supporting, extra = _answer_compare(conn, interpretation.month_a, interpretation.month_b)
    except sqlite3.Error as error:
        raise DatabaseError("The database could not be read.") from error

    return {
        "question": question,
        "operation": op,
        "interpretation_source": interpretation.interpretation_source,
        "answer": answer,
        "result": result,
        "supporting_figures": supporting,
        "notes": [BASE_NOTE, *interpretation.notes, *extra],
    }
