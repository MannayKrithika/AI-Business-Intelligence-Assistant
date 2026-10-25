"""Configuration from environment variables and an optional .env file.

Precedence (highest first): real environment variables, then the .env file, then defaults.
The API key is never printed, logged, or returned by any endpoint.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.config import DEFAULT_DB_PATH, PROJECT_ROOT

DEFAULT_DOTENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# Listed under "Production Models" in Groq's documentation (console.groq.com/docs/models) when this
# was written. Model catalogues change, so LLM_MODEL can always override it.
GROQ_DEFAULT_MODEL = "llama-3.1-8b-instant"
DEFAULT_TIMEOUT_SECONDS = 15.0
PLACEHOLDER_KEY = "replace-with-your-key"
PLACEHOLDER_MODEL = "replace-with-model-name"
# "groq" is the OpenAI-compatible adapter with Groq's endpoint and a default model pre-filled.
VALID_PROVIDERS = ("none", "groq", "openai_compatible")
LLM_PROVIDERS = ("groq", "openai_compatible")


def read_dotenv(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Supports comments, blank lines, 'export ', and single or double quotes.
    Inline comments are not supported."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Settings:
    provider: str = "none"                 # "none" (fallback only), "groq", or "openai_compatible"
    api_key: str = field(default="", repr=False)
    base_url: str = DEFAULT_BASE_URL
    model: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    db_path: str | None = None             # None means the default database location

    def problems(self) -> list[str]:
        """Configuration problems. Empty when the settings are complete and valid."""
        if self.provider not in VALID_PROVIDERS:
            return [f"LLM_PROVIDER '{self.provider}' is not supported (use 'none', 'groq' or 'openai_compatible')"]
        if self.provider == "none":
            return []
        issues = []
        if not self.api_key:
            issues.append("LLM_API_KEY is not set")
        elif self.api_key == PLACEHOLDER_KEY:
            issues.append("LLM_API_KEY is still the placeholder from .env.example")
        if not self.model:
            issues.append("LLM_MODEL is not set")
        elif self.model == PLACEHOLDER_MODEL:
            issues.append("LLM_MODEL is still the placeholder from .env.example")
        if not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            issues.append("LLM_BASE_URL must start with http:// or https://")
        if not self.timeout_seconds > 0:
            issues.append("LLM_TIMEOUT_SECONDS must be a positive number")
        return issues

    @property
    def llm_active(self) -> bool:
        return self.provider in LLM_PROVIDERS and not self.problems()

    def llm_problem(self) -> str | None:
        """Why the LLM is not in use, or None when it is intentionally disabled or active."""
        if self.provider == "none":
            return None
        issues = self.problems()
        return "; ".join(issues) if issues else None

    def describe(self) -> dict:
        """Safe summary for the health endpoint. Never includes the key."""
        return {
            "provider": self.provider,
            "model": self.model or None,
            "base_url": self.base_url,
            "api_key_set": bool(self.api_key),
        }

    @classmethod
    def from_environment(
        cls,
        environ: dict | None = None,
        dotenv_path: Path | None = DEFAULT_DOTENV_PATH,
    ) -> "Settings":
        """Build settings from os.environ (or a supplied mapping) plus the .env file.

        Pass dotenv_path=None to ignore the file. This never modifies os.environ.
        """
        env = dict(os.environ if environ is None else environ)
        if dotenv_path is not None and Path(dotenv_path).is_file():
            for key, value in read_dotenv(Path(dotenv_path)).items():
                env.setdefault(key, value)
        try:
            timeout = float(env.get("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
        except ValueError:
            timeout = -1.0  # reported by problems()
        provider = env.get("LLM_PROVIDER", "none").strip().lower() or "none"
        default_url = GROQ_BASE_URL if provider == "groq" else DEFAULT_BASE_URL
        default_model = GROQ_DEFAULT_MODEL if provider == "groq" else ""
        return cls(
            provider=provider,
            api_key=env.get("LLM_API_KEY", "").strip(),
            base_url=(env.get("LLM_BASE_URL", "").strip() or default_url),
            model=(env.get("LLM_MODEL", "").strip() or default_model),
            timeout_seconds=timeout,
            db_path=(env.get("RSG_DB_PATH", "").strip() or None),
        )
