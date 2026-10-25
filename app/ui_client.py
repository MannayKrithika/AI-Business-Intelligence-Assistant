"""HTTP client and display helpers for the Streamlit UI.

This module calls the FastAPI backend (POST /ask, GET /health) and formats values for display.
It does not calculate any analytics. Every number shown comes from the backend response.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.settings import DEFAULT_DOTENV_PATH, read_dotenv

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0
HEALTH_TIMEOUT_SECONDS = 3.0

START_COMMAND = "python -m uvicorn app.main:app --reload"
UNREACHABLE_MESSAGE = (
    "Cannot reach the backend at {url}. Start it in a separate PowerShell window with: "
    + START_COMMAND
)
TIMEOUT_MESSAGE = "The backend at {url} did not respond in time. Try again, or check that it is running."
EMPTY_MESSAGE = "Please type a question first."


@dataclass
class ApiResult:
    """Outcome of one question. Exactly one of `data` (success) or `error_code` (failure) is set."""

    ok: bool
    status: int | None
    data: dict | None = None
    error_code: str | None = None
    message: str = ""


def api_base_url(environ: dict | None = None, dotenv_path: Path | None = DEFAULT_DOTENV_PATH) -> str:
    """Backend address. Order: RSG_API_URL environment variable, then .env, then the default."""
    env = dict(os.environ if environ is None else environ)
    if "RSG_API_URL" not in env and dotenv_path is not None and Path(dotenv_path).is_file():
        env.update({k: v for k, v in read_dotenv(Path(dotenv_path)).items() if k == "RSG_API_URL"})
    return (env.get("RSG_API_URL") or "").strip().rstrip("/") or DEFAULT_API_URL


def ask(question: str, base_url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None) -> ApiResult:
    """Send one question to the backend and return a structured result. Never raises."""
    text = (question or "").strip()
    if not text:
        return ApiResult(False, None, error_code="empty_question", message=EMPTY_MESSAGE)
    try:
        with httpx.Client(base_url=base_url, timeout=timeout, transport=transport) as http:
            response = http.post("/ask", json={"question": text})
    except httpx.TimeoutException:
        return ApiResult(False, None, error_code="backend_timeout",
                         message=TIMEOUT_MESSAGE.format(url=base_url))
    except httpx.HTTPError:
        # Covers connection refused, DNS failure, and other transport errors.
        return ApiResult(False, None, error_code="backend_unreachable",
                         message=UNREACHABLE_MESSAGE.format(url=base_url))

    try:
        body: Any = response.json()
    except ValueError:
        return ApiResult(False, response.status_code, error_code="unexpected_response",
                         message="The backend returned a response the interface could not read.")

    if response.is_success:
        if isinstance(body, dict) and "answer" in body and "operation" in body:
            return ApiResult(True, response.status_code, data=body)
        return ApiResult(False, response.status_code, error_code="unexpected_response",
                         message="The backend returned an incomplete answer, so nothing is shown.")

    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        code = str(error.get("code", "http_error"))
        message = str(error.get("message", f"The backend returned HTTP {response.status_code}."))
    else:
        code = "http_error"
        message = f"The backend returned HTTP {response.status_code}."
    return ApiResult(False, response.status_code, error_code=code, message=message)


def health(base_url: str, timeout: float = HEALTH_TIMEOUT_SECONDS,
           transport: httpx.BaseTransport | None = None) -> dict | None:
    """Backend health and interpreter mode, or None when the backend cannot be reached."""
    try:
        with httpx.Client(base_url=base_url, timeout=timeout, transport=transport) as http:
            response = http.get("/health")
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return body if response.is_success and isinstance(body, dict) else None


# ---------------------------------------------------------------- display helpers

def format_money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}"


def format_percentage(value: float | None) -> str:
    if value is None:
        return "Undefined (the first month's revenue is zero)"
    return f"{value:+.2f}%"


def month_label(month: str | None) -> str:
    if not month:
        return "—"
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    except ValueError:
        return month


def source_label(source: str | None) -> str:
    if source == "llm":
        return "AI model (LLM)"
    if source == "fallback":
        return "Deterministic fallback (rule-based, no AI model used)"
    return source or "unknown"


def interpreter_summary(health_body: dict | None) -> tuple[str, str]:
    """(level, text) for the sidebar. level is one of 'success', 'info', 'error'."""
    if health_body is None:
        return "error", "Backend is not reachable."
    info = health_body.get("interpretation", {}) or {}
    if info.get("mode") == "llm":
        return "success", f"AI interpreter active: {info.get('model') or 'model not named'}."
    problem = info.get("problem")
    if problem:
        return "info", f"Offline fallback in use. AI interpreter not active: {problem}."
    return "info", "Offline fallback in use (no AI key configured). No cost, no network needed."
