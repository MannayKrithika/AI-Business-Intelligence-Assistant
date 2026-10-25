"""FastAPI application: POST /ask answers sales questions from the SQLite database.

Run from the project folder:   python -m uvicorn app.main:app --reload
Configuration comes from .env (see .env.example) or environment variables.
Without an API key the app uses the deterministic fallback and works fully offline.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse

from app import service
from app.analytics import AnalyticsError
from app.config import DEFAULT_DB_PATH, PROJECT_ROOT
from app.db import connect_readonly
from app.interpreter import Interpreter
from app.llm import OpenAICompatibleClient
from app.question_router import QuestionError
from app.schemas import AskRequest, AskResponse, ErrorResponse
from app.service import DatabaseError
from app.settings import Settings

logger = logging.getLogger("rsg.api")

MALFORMED_MESSAGE = (
    "The request body must be JSON with a non-empty 'question' string of at most 500 characters."
)
DB_UNAVAILABLE_MESSAGE = (
    "The sales database is not available. Run 'python -m app.importer' to create and load it."
)
INTERNAL_MESSAGE = "An unexpected error occurred. Please try again."


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def get_connection(request: Request) -> Iterator[sqlite3.Connection]:
    """Open a read-only connection for one request. Analytics never write to the database."""
    db_path: Path = request.app.state.db_path
    if not db_path.exists():
        raise DatabaseError("database file missing")
    try:
        conn = connect_readonly(db_path)
    except sqlite3.Error as error:
        raise DatabaseError("database could not be opened") from error
    try:
        yield conn
    finally:
        conn.close()


def create_app(
    db_path: str | Path | None = None,
    settings: Settings | None = None,
    llm_client=None,
) -> FastAPI:
    """Create the app.

    settings:   configuration; defaults to Settings() which means fallback only, no environment read.
    llm_client: optional client injected by tests. When None and settings are complete, a real
                OpenAI-compatible client is created from settings.
    """
    settings = Settings() if settings is None else settings
    resolved = Path(db_path or settings.db_path or DEFAULT_DB_PATH)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved

    if llm_client is None and settings.llm_active:
        llm_client = OpenAICompatibleClient(
            settings.base_url, settings.api_key, settings.model, settings.timeout_seconds
        )
    llm_problem = None
    if llm_client is None and settings.provider != "none":
        llm_problem = settings.llm_problem()
        logger.warning("AI interpreter not active (%s). Using the deterministic fallback.", llm_problem)

    app = FastAPI(
        title="RSG Mini AI Business Intelligence Assistant",
        version="0.4.0",
        description="Answers sales questions using fixed, parameterized SQL over the imported dataset.",
    )
    app.state.db_path = resolved
    app.state.interpreter = Interpreter(llm_client, llm_problem, provider=settings.provider)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        codes = {404: "not_found", 405: "method_not_allowed"}
        messages = {
            404: "No such endpoint. Use POST /ask to ask a question, or GET /health.",
            405: "This endpoint does not accept that HTTP method. Use POST /ask.",
        }
        code = codes.get(exc.status_code, "http_error")
        message = messages.get(exc.status_code, f"The request could not be processed (HTTP {exc.status_code}).")
        return _error(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def _malformed(request: Request, exc: RequestValidationError):
        return _error(400, "malformed_request", MALFORMED_MESSAGE)

    @app.exception_handler(QuestionError)
    async def _question(request: Request, exc: QuestionError):
        return _error(422, exc.code, exc.message)

    @app.exception_handler(AnalyticsError)
    async def _analytics(request: Request, exc: AnalyticsError):
        return _error(422, "invalid_parameters", str(exc))

    @app.exception_handler(DatabaseError)
    async def _database(request: Request, exc: DatabaseError):
        logger.warning("database unavailable: %s", exc)
        return _error(503, "database_unavailable", DB_UNAVAILABLE_MESSAGE)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        logger.exception("unexpected error while handling %s %s", request.method, request.url.path)
        return _error(500, "internal_error", INTERNAL_MESSAGE)

    @app.get("/health", tags=["system"])
    def health(request: Request) -> dict:
        return {"status": "ok", "interpretation": request.app.state.interpreter.describe()}

    @app.post(
        "/ask",
        response_model=AskResponse,
        tags=["analytics"],
        responses={
            400: {"model": ErrorResponse, "description": "Malformed request (invalid JSON, missing or empty question)."},
            422: {"model": ErrorResponse, "description": "Unsupported, ambiguous, or invalid-parameter question."},
            500: {"model": ErrorResponse, "description": "Unexpected server error (no details exposed)."},
            503: {"model": ErrorResponse, "description": "The database is missing or unreadable."},
        },
    )
    def ask(request: Request, payload: AskRequest, conn: sqlite3.Connection = Depends(get_connection)) -> dict:
        return service.answer_question(conn, payload.question, request.app.state.interpreter)

    return app


app = create_app(settings=Settings.from_environment())
