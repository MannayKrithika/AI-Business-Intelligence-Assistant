"""Project hygiene checks: no secrets, no machine-specific paths, pinned dependencies, ignored outputs.

Test files are excluded from the secret and path scans on purpose: they contain deliberately fake
keys so the tests can prove that keys are never leaked.
"""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCANNED_SUFFIXES = {".py", ".md", ".txt", ".ini", ".example", ""}
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "output", "tests"}
SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{16,}")
MACHINE_PATH_PATTERN = re.compile(r"/home/claude|/mnt/user-data|C:\\Users\\|/Users/[A-Za-z]+/")


def project_text_files():
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(PROJECT_ROOT)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if path.suffix in SCANNED_SUFFIXES or path.name in {".env.example", ".gitignore", "requirements.txt"}:
            yield path


def test_env_example_contains_only_placeholders():
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert not SECRET_PATTERN.search(text)
    values = dict(
        line.split("=", 1) for line in text.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert values["LLM_PROVIDER"] == "none", "the shipped default must not use an AI provider"
    assert values["LLM_API_KEY"] == "replace-with-your-key"


def test_no_api_key_like_strings_in_shipped_source_or_documentation():
    offenders = [str(p.relative_to(PROJECT_ROOT)) for p in project_text_files()
                 if SECRET_PATTERN.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert offenders == []


def test_no_machine_specific_paths_in_shipped_files():
    offenders = [str(p.relative_to(PROJECT_ROOT)) for p in project_text_files()
                 if MACHINE_PATH_PATTERN.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert offenders == []


def test_gitignore_excludes_secrets_databases_caches_and_outputs():
    lines = {line.strip() for line in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    for required in [".env", ".venv/", "data/sales.db", "output/", "__pycache__/", ".pytest_cache/"]:
        assert required in lines, f".gitignore must contain {required}"


def test_every_dependency_is_pinned_to_an_exact_version():
    requirements = [
        line.strip() for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    names = {r.split("==")[0] for r in requirements}
    assert all("==" in r for r in requirements), requirements
    for needed in ["pytest", "fastapi", "uvicorn", "pydantic", "httpx", "streamlit", "pandas"]:
        assert needed in names, f"{needed} must be listed in requirements.txt"


def test_sample_data_is_present_and_unmodified_in_shape():
    csv_path = PROJECT_ROOT / "data" / "sales.csv"
    lines = csv_path.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].split(",")[0] == "Transaction_Id"
    assert len(lines) - 1 == 51
