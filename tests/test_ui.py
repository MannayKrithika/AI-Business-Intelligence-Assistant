"""Streamlit page tests using streamlit.testing.v1.AppTest.

A real FastAPI backend (the same app as production, over the supplied CSV) runs in a background
thread on a free port. The page calls it over HTTP, exactly as in normal use.
"""
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from streamlit.testing.v1 import AppTest

from app.config import DEFAULT_CSV_PATH
from app.importer import import_csv
from app.main import create_app
from tests.helpers import FakeLLMClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_PATH = str(PROJECT_ROOT / "app" / "ui.py")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_backend(tmp_path_factory):
    folder = tmp_path_factory.mktemp("ui_backend")
    import_csv(DEFAULT_CSV_PATH, folder / "sales.db", folder / "issues.csv")
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(folder / "sales.db"), host="127.0.0.1",
                                           port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "test backend did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def page(monkeypatch, live_backend):
    monkeypatch.setenv("RSG_API_URL", live_backend)
    at = AppTest.from_file(UI_PATH, default_timeout=30)
    at.run()
    return at


def ask(at, question):
    at.text_input(key="question").input(question)
    at.button(key="ask").click().run()
    return at


def all_text(elements):
    return [element.value for element in elements]


def test_page_renders_cleanly_with_fallback_mode(page):
    assert not page.exception
    assert page.title[0].value == "AI Business Intelligence Assistant"
    assert len(page.button) >= 6  # five example buttons plus Ask
    assert any("Offline fallback" in text for text in all_text(page.sidebar.info))


def test_total_revenue_answer_and_source_are_shown(page):
    ask(page, "What is the total revenue?")
    assert not page.exception
    assert "1,439,200.00" in page.main.info[0].value
    captions = all_text(page.caption)
    assert any("Deterministic fallback" in text for text in captions)
    assert any("49" in text for text in all_text(page.caption) + [m.value for m in page.metric])


def test_top_product_shows_ranking_table(page):
    ask(page, "Which product generated the highest revenue?")
    assert "Monitor" in page.main.info[0].value
    frame = page.dataframe[0].value
    assert len(frame) == 7
    assert frame.iloc[0]["Product"] == "Monitor"
    assert frame.iloc[0]["Net revenue"] == 473000.00


def test_monthly_trend_shows_six_chronological_months(page):
    ask(page, "What is the monthly revenue trend?")
    frame = page.dataframe[0].value
    assert list(frame["Month"]) == ["January 2026", "February 2026", "March 2026",
                                    "April 2026", "May 2026", "June 2026"]
    assert frame.iloc[4]["Net revenue"] == 318500.00


def test_top_region_shows_south_and_ranking(page):
    ask(page, "Which region generated the highest sales?")
    assert "South" in page.main.info[0].value
    assert len(page.dataframe[0].value) == 4


def test_month_comparison_shows_change_and_percentage(page):
    ask(page, "How did revenue change between May and June?")
    text = page.main.info[0].value
    assert "decreased" in text and "-107,250.00" in text and "-33.67%" in text
    markdown = " ".join(m.value for m in page.markdown)
    assert "-33.67%" in markdown


def test_unsupported_question_shows_a_warning_and_no_result(page):
    ask(page, "What is the weather today?")
    assert not page.exception
    assert "not supported" in page.warning[0].value
    assert len(page.main.info) == 0 and len(page.dataframe) == 0


def test_invalid_month_shows_the_available_range(page):
    ask(page, "How did revenue change between May and July?")
    assert "outside the available data range" in page.warning[0].value
    assert "2026-06" in page.warning[0].value


def test_identical_months_are_explained(page):
    ask(page, "How did revenue change between May and May?")
    assert "different" in page.warning[0].value


def test_empty_question_prompts_without_an_error(page):
    ask(page, "   ")
    assert not page.exception
    assert "Please type a question first" in page.warning[0].value


def test_example_button_fills_the_question_box(page):
    page.button(key="example_Top region").click().run()
    assert page.text_input(key="question").value == "Which region generated the highest sales?"
    ask_result = page.button(key="ask")
    ask_result.click().run()
    assert "South" in page.main.info[0].value


def test_unreachable_backend_shows_a_clear_error_not_a_crash(monkeypatch):
    monkeypatch.setenv("RSG_API_URL", f"http://127.0.0.1:{free_port()}")
    at = AppTest.from_file(UI_PATH, default_timeout=30)
    at.run()
    assert not at.exception
    assert any("not reachable" in text for text in all_text(at.sidebar.error))
    ask(at, "What is the total revenue?")
    assert not at.exception
    message = at.error[0].value
    assert "Cannot reach the backend" in message
    assert "python -m uvicorn app.main:app --reload" in message
    assert len(at.main.info) == 0 and len(at.dataframe) == 0


# ----------------------------------------------------------------- Phase 7 dashboard behaviour

def charts(at):
    return at.get("arrow_vega_lite_chart")


def start_backend(app):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "test backend did not start"
    return f"http://127.0.0.1:{port}", server, thread


@pytest.fixture(scope="module")
def llm_backend(tmp_path_factory):
    """A real backend whose 'model' is a fake client (no network). Proves the LLM label path only."""
    folder = tmp_path_factory.mktemp("ui_llm_backend")
    import_csv(DEFAULT_CSV_PATH, folder / "sales.db", folder / "issues.csv")
    fake = FakeLLMClient(reply='{"operation": "total_revenue", "month_a": null, "month_b": null}',
                         model="fake-groq-model")
    url, server, thread = start_backend(create_app(folder / "sales.db", llm_client=fake))
    yield url
    server.should_exit = True
    thread.join(timeout=10)


def test_page_uses_the_professional_title_and_wide_layout(page):
    assert not page.exception
    assert page.title[0].value == "AI Business Intelligence Assistant"
    # Idle page: no answer card, no chart, no table until a question is asked.
    assert len(page.main.info) == 0 and len(charts(page)) == 0 and len(page.dataframe) == 0


def test_sidebar_shows_backend_connected_and_the_configured_interpreter(page):
    assert any("Backend connected" in text for text in all_text(page.sidebar.success))
    assert any("Offline fallback" in text for text in all_text(page.sidebar.info))


def test_monthly_trend_draws_a_chart_next_to_the_table(page):
    ask(page, "What is the monthly revenue trend?")
    assert len(charts(page)) == 1
    assert len(page.dataframe) == 1


def test_ranking_questions_draw_a_chart_and_the_table(page):
    ask(page, "Which product generated the highest revenue?")
    assert len(charts(page)) == 1 and len(page.dataframe) == 1
    ask(page, "Which region generated the highest sales?")
    assert len(charts(page)) == 1 and len(page.dataframe) == 1


def test_month_comparison_draws_a_two_bar_chart_and_shows_transaction_counts(page):
    ask(page, "How did revenue change between May and June?")
    assert len(charts(page)) == 1
    assert any("Supporting transactions" in text for text in all_text(page.caption))


def test_total_revenue_has_no_chart_because_there_is_no_series_to_plot(page):
    ask(page, "What is the total revenue?")
    assert len(charts(page)) == 0


def test_failures_show_no_chart_and_no_answer_card(page):
    ask(page, "What is the weather today?")
    assert len(charts(page)) == 0 and len(page.main.info) == 0


def test_calculation_notes_are_available_for_an_answer(page):
    ask(page, "What is the total revenue?")
    assert any("Calculation notes" in expander.label for expander in page.expander)


def test_llm_answers_are_labelled_llm_and_the_sidebar_names_the_model(monkeypatch, llm_backend):
    monkeypatch.setenv("RSG_API_URL", llm_backend)
    at = AppTest.from_file(UI_PATH, default_timeout=30)
    at.run()
    assert any("AI interpreter active" in text for text in all_text(at.sidebar.success))
    assert any("fake-groq-model" in text for text in all_text(at.sidebar.caption))
    ask(at, "What is our overall sales income?")
    assert not at.exception
    assert "1,439,200.00" in at.main.info[0].value
    captions = all_text(at.caption)
    assert any("Interpreted by: AI model (LLM)" in text for text in captions)
    assert not any("Deterministic fallback" in text for text in captions)
    markdown = " ".join(m.value for m in at.markdown)
    assert 'class="rsg-badge rsg-badge-llm"' in markdown


def test_fallback_answers_are_labelled_fallback_not_llm(page):
    ask(page, "What is the total revenue?")
    markdown = " ".join(m.value for m in page.markdown)
    assert 'class="rsg-badge rsg-badge-fallback"' in markdown
    assert 'class="rsg-badge rsg-badge-llm"' not in markdown
