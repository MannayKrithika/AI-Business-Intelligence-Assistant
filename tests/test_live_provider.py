"""OPT-IN live check against the real configured AI provider (for example Groq).

Skipped by default, so the normal test run makes no network request and needs no key.
To run it yourself (sends exactly ONE request and may use quota or credit):

    $env:RSG_RUN_LIVE_LLM_TEST = "1"      # PowerShell; your .env must configure the provider
    python -m pytest tests/test_live_provider.py -q
"""
import os

import pytest

from app import verify_llm
from app.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RSG_RUN_LIVE_LLM_TEST") != "1",
    reason="live provider test is opt-in: set RSG_RUN_LIVE_LLM_TEST=1",
)


def test_real_provider_interprets_a_paraphrase_as_total_revenue():
    settings = Settings.from_environment()
    if not settings.llm_active:
        pytest.skip(f"provider not configured: {settings.llm_problem()}")
    passed, message = verify_llm.run_check(settings)
    assert passed, message
