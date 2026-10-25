"""Configuration tests: defaults, validation, .env parsing, precedence, and secret safety."""
from app.settings import Settings, read_dotenv

KEY = "sk-test-SECRET-VALUE-123"


def test_defaults_are_fallback_only_and_need_no_key():
    settings = Settings.from_environment({}, dotenv_path=None)
    assert settings.provider == "none"
    assert settings.problems() == []
    assert settings.llm_active is False
    assert settings.llm_problem() is None


def test_complete_openai_compatible_settings_are_active():
    settings = Settings.from_environment(
        {"LLM_PROVIDER": "openai_compatible", "LLM_API_KEY": KEY, "LLM_MODEL": "m1"}, dotenv_path=None
    )
    assert settings.problems() == []
    assert settings.llm_active is True
    assert settings.base_url == "https://api.openai.com/v1"


def test_missing_key_is_reported_and_llm_is_not_active():
    settings = Settings.from_environment({"LLM_PROVIDER": "openai_compatible", "LLM_MODEL": "m1"}, dotenv_path=None)
    assert settings.llm_active is False
    assert "LLM_API_KEY is not set" in settings.llm_problem()


def test_missing_model_is_reported():
    settings = Settings.from_environment({"LLM_PROVIDER": "openai_compatible", "LLM_API_KEY": KEY}, dotenv_path=None)
    assert "LLM_MODEL is not set" in settings.llm_problem()


def test_unknown_provider_is_reported():
    settings = Settings.from_environment({"LLM_PROVIDER": "magic"}, dotenv_path=None)
    assert settings.llm_active is False
    assert "not supported" in settings.llm_problem()


def test_bad_base_url_and_timeout_are_reported():
    settings = Settings.from_environment(
        {"LLM_PROVIDER": "openai_compatible", "LLM_API_KEY": KEY, "LLM_MODEL": "m1",
         "LLM_BASE_URL": "api.example.com", "LLM_TIMEOUT_SECONDS": "soon"},
        dotenv_path=None,
    )
    problem = settings.llm_problem()
    assert "LLM_BASE_URL must start with http" in problem
    assert "LLM_TIMEOUT_SECONDS must be a positive number" in problem


def test_api_key_never_appears_in_repr_or_description():
    settings = Settings.from_environment(
        {"LLM_PROVIDER": "openai_compatible", "LLM_API_KEY": KEY, "LLM_MODEL": "m1"}, dotenv_path=None
    )
    assert KEY not in repr(settings)
    assert KEY not in str(settings.describe())
    assert settings.describe()["api_key_set"] is True


def test_read_dotenv_handles_comments_quotes_and_export(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# a comment\n\nLLM_PROVIDER=openai_compatible\nexport LLM_MODEL=\"quoted-model\"\n"
        "LLM_API_KEY='single-quoted'\nnot a setting line\n",
        encoding="utf-8",
    )
    assert read_dotenv(path) == {
        "LLM_PROVIDER": "openai_compatible",
        "LLM_MODEL": "quoted-model",
        "LLM_API_KEY": "single-quoted",
    }


def test_dotenv_file_is_used_when_environment_does_not_set_a_value(tmp_path):
    path = tmp_path / ".env"
    path.write_text(f"LLM_PROVIDER=openai_compatible\nLLM_API_KEY={KEY}\nLLM_MODEL=from-file\n", encoding="utf-8")
    settings = Settings.from_environment({}, dotenv_path=path)
    assert settings.llm_active is True
    assert settings.model == "from-file"


def test_real_environment_overrides_dotenv(tmp_path):
    path = tmp_path / ".env"
    path.write_text("LLM_PROVIDER=openai_compatible\nLLM_MODEL=from-file\n", encoding="utf-8")
    settings = Settings.from_environment({"LLM_MODEL": "from-env"}, dotenv_path=path)
    assert settings.model == "from-env"


def test_database_path_is_read_from_environment():
    settings = Settings.from_environment({"RSG_DB_PATH": "data/other.db"}, dotenv_path=None)
    assert settings.db_path == "data/other.db"


def test_from_environment_does_not_modify_os_environ(monkeypatch, tmp_path):
    import os
    path = tmp_path / ".env"
    path.write_text("LLM_TEST_MARKER_VALUE=set-by-dotenv\n", encoding="utf-8")
    Settings.from_environment({}, dotenv_path=path)
    assert "LLM_TEST_MARKER_VALUE" not in os.environ
