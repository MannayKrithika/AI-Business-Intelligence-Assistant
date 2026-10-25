"""Request and response models for the HTTP API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

MAX_QUESTION_LENGTH = 500


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH,
                          description="A natural-language question about the sales data.")

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped


class AskResponse(BaseModel):
    question: str
    operation: Literal["total_revenue", "top_product", "monthly_trend", "top_region", "compare_months"]
    interpretation_source: Literal["llm", "fallback"]
    answer: str
    result: dict[str, Any]
    supporting_figures: dict[str, Any]
    notes: list[str]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
