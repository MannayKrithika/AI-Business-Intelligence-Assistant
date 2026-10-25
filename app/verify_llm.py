"""Owner-run check that the configured AI provider really works. Sends ONE request.

    python -m app.verify_llm --yes

It reads the same configuration as the backend (environment variables or .env), sends the single
question "What is our overall sales income?" to the provider, and checks that the validated reply is
the `total_revenue` operation. It does not touch the database and never prints the API key.

The request may count against your provider's quota or billing, so it only runs with --yes.
"""
from __future__ import annotations

import argparse
import sys

from app.llm import LLMUnavailable, OpenAICompatibleClient, interpret_with_llm
from app.question_router import QuestionError
from app.settings import Settings

QUESTION = "What is our overall sales income?"
EXPECTED_OPERATION = "total_revenue"


def run_check(settings: Settings, client=None, question: str = QUESTION,
              expected: str = EXPECTED_OPERATION) -> tuple[bool, str]:
    """Return (passed, message). Makes at most one provider request. Never raises for provider problems."""
    if client is None:
        if not settings.llm_active:
            reason = settings.llm_problem() or "LLM_PROVIDER is 'none'; set it to 'groq' to test the provider"
            return False, f"AI provider is not configured: {reason}."
        client = OpenAICompatibleClient(
            settings.base_url, settings.api_key, settings.model, settings.timeout_seconds
        )
    try:
        interpretation = interpret_with_llm(client, question, "2026-01", "2026-06", 2026)
    except LLMUnavailable as error:
        return False, f"Provider request failed or reply was unusable: {error.reason}."
    except QuestionError:
        return False, "The model answered 'unsupported' for a supported question."
    if interpretation.operation != expected:
        return False, f"Unexpected operation '{interpretation.operation}' (expected '{expected}')."
    return True, (
        f"PASS: the provider interpreted \"{question}\" as '{interpretation.operation}' "
        f"(model: {client.model})."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send one real request to the configured AI provider.")
    parser.add_argument("--yes", action="store_true",
                        help="confirm that you accept one real provider request")
    args = parser.parse_args(argv)
    if not args.yes:
        print("This sends ONE real request to your AI provider and may use quota or credit.\n"
              "Run again with --yes to continue:  python -m app.verify_llm --yes")
        return 2
    settings = Settings.from_environment()
    passed, message = run_check(settings)
    print(message)
    if passed:
        print("Only the choice of operation came from the model. Figures still come from the database.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
