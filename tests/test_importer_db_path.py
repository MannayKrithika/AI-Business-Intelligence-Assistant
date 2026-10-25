"""Regression: the importer command line must honour RSG_DB_PATH, like the backend does."""
import sqlite3

from app.config import DEFAULT_CSV_PATH, PROJECT_ROOT
from app.importer import main


def stored_rows(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        conn.close()


def test_importer_uses_rsg_db_path_when_no_db_argument_is_given(tmp_path, monkeypatch):
    target = tmp_path / "from_env.db"
    monkeypatch.setenv("RSG_DB_PATH", str(target))
    code = main(["--csv", str(DEFAULT_CSV_PATH), "--issues", str(tmp_path / "issues.csv")])
    assert code == 0
    assert stored_rows(target) == 51


def test_explicit_db_argument_wins_over_rsg_db_path(tmp_path, monkeypatch):
    env_target, arg_target = tmp_path / "env.db", tmp_path / "arg.db"
    monkeypatch.setenv("RSG_DB_PATH", str(env_target))
    code = main(["--csv", str(DEFAULT_CSV_PATH), "--db", str(arg_target),
                 "--issues", str(tmp_path / "issues.csv")])
    assert code == 0
    assert arg_target.exists() and not env_target.exists()


def test_relative_rsg_db_path_is_resolved_inside_the_project_folder(tmp_path, monkeypatch):
    # Same rule as the backend. The test removes its own file afterwards.
    relative = "data/_regression_relative_import_test.db"
    monkeypatch.setenv("RSG_DB_PATH", relative)
    expected = PROJECT_ROOT / relative
    try:
        code = main(["--csv", str(DEFAULT_CSV_PATH), "--issues", str(tmp_path / "issues.csv")])
        assert code == 0
        assert expected.exists() and stored_rows(expected) == 51
    finally:
        if expected.exists():
            expected.unlink()
