"""Chooses how a question is interpreted: the LLM when configured, otherwise the deterministic fallback.

Order:
  1. If an LLM client is active, ask it. A usable reply is returned with interpretation_source "llm".
  2. If the LLM is unavailable (not configured, timeout, error, or malformed reply), use the
     deterministic fallback (app/question_router.py) with interpretation_source "fallback".
     The notes say why the fallback was used.
  3. If the model says "unsupported", that answer is final and no fallback is attempted.

Either way the operation is validated, and every number comes from the analytics layer.
"""
from __future__ import annotations

from dataclasses import dataclass

from app import llm
from app import question_router
from app.llm import LLMUnavailable
from app.question_router import Interpretation, QuestionError


@dataclass(frozen=True)
class InterpretationContext:
    default_year: int | None
    first_month: str | None
    last_month: str | None


class Interpreter:
    def __init__(self, llm_client=None, llm_problem: str | None = None, provider: str = "none"):
        self.llm_client = llm_client
        self.llm_problem = llm_problem  # why the LLM is not in use (None when intentionally disabled)
        self.provider = provider

    def describe(self) -> dict:
        """Safe, non-secret summary of how questions are interpreted."""
        if self.llm_client is not None:
            return {"mode": "llm", "provider": self.provider, "model": self.llm_client.model, "problem": None}
        return {"mode": "fallback", "provider": None, "model": None, "problem": self.llm_problem}

    def interpret(self, question: str, context: InterpretationContext) -> Interpretation:
        attempted_reason: str | None = None

        if self.llm_client is not None:
            try:
                interpretation = llm.interpret_with_llm(
                    self.llm_client, question, context.first_month, context.last_month, context.default_year
                )
                interpretation.notes = [
                    f"Interpreted by an LLM ({self.llm_client.model}). "
                    "The numbers are calculated from the database, not by the model."
                ]
                return interpretation
            except LLMUnavailable as error:
                attempted_reason = error.reason
        elif self.llm_problem:
            attempted_reason = self.llm_problem

        try:
            interpretation = question_router.interpret(question, context.default_year)
        except QuestionError as error:
            if attempted_reason:
                raise QuestionError(
                    error.code,
                    f"{error.message} The AI interpreter was unavailable ({attempted_reason}), "
                    "so only the rule-based matcher was used.",
                ) from None
            raise

        if attempted_reason:
            note = f"The AI interpreter was unavailable ({attempted_reason}), so the deterministic fallback was used."
        else:
            note = "Interpreted by the deterministic fallback (no AI model was used)."
        interpretation.notes = [note, *interpretation.notes]
        interpretation.interpretation_source = "fallback"
        return interpretation
