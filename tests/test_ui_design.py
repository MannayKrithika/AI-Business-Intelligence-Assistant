"""Static presentation checks for the dashboard (no Streamlit or network needed)."""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_SOURCE = (PROJECT_ROOT / "app" / "ui.py").read_text(encoding="utf-8")
CLIENT_SOURCE = (PROJECT_ROOT / "app" / "ui_client.py").read_text(encoding="utf-8")
TITLE = "AI Business Intelligence Assistant"


def test_title_constant_is_exact_and_used_for_page_and_header():
    assert f'APP_TITLE = "{TITLE}"' in UI_SOURCE
    assert "page_title=APP_TITLE" in UI_SOURCE      # browser tab title
    assert "st.title(APP_TITLE)" in UI_SOURCE       # visible header


def test_no_rsg_wording_is_visible_in_the_interface():
    visible = (UI_SOURCE + CLIENT_SOURCE).replace("RSG_API_URL", "")
    # Allowed: CSS class names such as .rsg-badge (never displayed). No visible RSG/RSGI text.
    visible = re.sub(r"rsg-badge[\w-]*", "", visible)
    visible = re.sub(r'""".*?"""', "", visible, flags=re.DOTALL)  # docstrings are not displayed
    assert not re.search(r"RSGI?\b", visible), "RSG/RSGI must not appear in the visible UI"


def test_subtitle_explains_natural_language_questions_about_sales_data():
    match = re.search(r'APP_SUBTITLE = "([^"]+)"', UI_SOURCE)
    assert match and "natural-language" in match.group(1) and "sales data" in match.group(1)


def test_light_theme_is_configured_for_a_consistent_look():
    config = (PROJECT_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert re.search(r'base\s*=\s*"light"', config)
    assert re.search(r'primaryColor\s*=\s*"#[0-9a-fA-F]{6}"', config)


def test_suggested_question_keys_and_texts_are_unchanged():
    for label, text in [
        ("Total revenue", "What is the total revenue?"),
        ("Top product", "Which product generated the highest revenue?"),
        ("Monthly trend", "What is the monthly revenue trend?"),
        ("Top region", "Which region generated the highest sales?"),
        ("Month comparison", "How did revenue change between May and June?"),
    ]:
        assert f'("{label}", "{text}")' in UI_SOURCE


def test_ui_does_no_analytics_and_imports_no_backend_modules():
    forbidden = ["import sqlite3", "from app import analytics", "from app.analytics",
                 "from app import db", "from app.llm", "SELECT "]
    for text in forbidden:
        assert text not in UI_SOURCE, text
