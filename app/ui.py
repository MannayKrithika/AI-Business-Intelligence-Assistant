"""Streamlit dashboard for the AI Business Intelligence Assistant.

Start the backend first (see README.md), then run:
    python -m streamlit run app/ui.py

This file only lays out and styles the page. The HTTP calls and formatting live in app/ui_client.py,
and every number shown here comes from the FastAPI backend. Nothing is calculated in this file:
charts are drawn from the lists the backend returns, in the order it returns them.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import ui_client  # noqa: E402

APP_TITLE = "AI Business Intelligence Assistant"
APP_SUBTITLE = "Ask natural-language questions about your sales data and get answers backed by SQL."

NAVY = "#0f2a5c"
BLUE = "#2563eb"
BLUE_SOFT = "#93b4f2"
SLATE = "#5b6b85"
GRID = "#e6ebf2"

EXAMPLES = [
    ("Total revenue", "What is the total revenue?"),
    ("Top product", "Which product generated the highest revenue?"),
    ("Monthly trend", "What is the monthly revenue trend?"),
    ("Top region", "Which region generated the highest sales?"),
    ("Month comparison", "How did revenue change between May and June?"),
]

FAILURE_TITLES = {
    "empty_question": "Please ask a question",
    "malformed_request": "The request could not be read",
    "unsupported_question": "This question is not supported",
    "ambiguous_question": "This question could mean more than one thing",
    "invalid_parameters": "The months in the question need correcting",
    "database_unavailable": "The sales database is not available",
    "backend_unreachable": "The backend is not running",
    "backend_timeout": "The backend did not respond in time",
    "internal_error": "Something went wrong on the server",
}

PAGE_CSS = f"""
<style>
html, body, [class*="css"], .stApp {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}}
footer {{ visibility: hidden; }}
.block-container {{ max-width: 1180px; padding-top: 2.2rem; padding-bottom: 3rem; }}

/* header */
h1 {{ color: {NAVY}; font-weight: 700; letter-spacing: -0.02em; font-size: 2.1rem !important;
     padding-bottom: 0.1rem; }}
.app-subtitle {{ color: {SLATE}; font-size: 1.05rem; margin: 0 0 1.4rem 0; }}
.section-label {{ color: {NAVY}; font-weight: 600; font-size: 0.95rem; margin: 0.4rem 0 0.4rem 0; }}

/* sidebar */
section[data-testid="stSidebar"] {{ background: #f8fafc; border-right: 1px solid {GRID}; }}
section[data-testid="stSidebar"] h2 {{ color: {NAVY}; font-size: 1.05rem; font-weight: 700; }}

/* buttons: suggested questions and Ask share one height, radius and weight */
div.stButton > button {{
    min-height: 2.75rem; border-radius: 10px; font-weight: 500;
    border: 1px solid #cfd8e6; background: #ffffff; color: {NAVY};
    transition: border-color 0.15s, color 0.15s;
}}
div.stButton > button:hover {{ border-color: {BLUE}; color: {BLUE}; background: #f5f8ff; }}
div.stButton > button[kind="primary"], div.stButton > button[data-testid="baseButton-primary"] {{
    background: {BLUE}; border-color: {BLUE}; color: #ffffff; font-weight: 600;
}}
div.stButton > button[kind="primary"]:hover, div.stButton > button[data-testid="baseButton-primary"]:hover {{
    background: #1d4ed8; border-color: #1d4ed8; color: #ffffff;
}}

/* question input */
div[data-baseweb="input"] {{ border-radius: 10px; border: 1px solid #cfd8e6; background: #ffffff;
    min-height: 2.75rem; }}
div[data-baseweb="input"]:focus-within {{ border-color: {BLUE}; }}
div[data-baseweb="input"] input {{ min-height: 2.6rem; }}

/* KPI cards: equal height, spacing and type */
[data-testid="stMetric"] {{
    background: #ffffff; border: 1px solid #e3e8f0; border-radius: 12px;
    padding: 14px 18px; min-height: 108px;
    box-shadow: 0 1px 2px rgba(15, 42, 92, 0.05);
}}
[data-testid="stMetricLabel"] {{ color: {SLATE}; font-size: 0.82rem; }}
[data-testid="stMetricValue"] {{ color: {NAVY}; font-weight: 700; font-size: 1.6rem; }}
[data-testid="stMetricValue"] > div {{ white-space: normal; overflow-wrap: anywhere; }}

/* panels, alerts, tables */
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 14px; border-color: #e3e8f0; }}
div[data-testid="stAlert"], div[data-testid="stAlertContainer"] {{ border-radius: 12px; }}
div[data-testid="stExpander"] {{ border-radius: 12px; border-color: #e3e8f0; }}
div[data-testid="stDataFrame"] {{ border: 1px solid #e3e8f0; border-radius: 10px; overflow: hidden; }}

/* interpretation badge */
.rsg-badge {{ display: inline-block; padding: 3px 12px; border-radius: 999px;
    font-size: 0.78rem; font-weight: 600; color: #ffffff; letter-spacing: 0.01em; }}
.rsg-badge-llm {{ background: #15803d; }}
.rsg-badge-fallback {{ background: #475569; }}
</style>
"""

VEGA_CONFIG = {
    "view": {"stroke": None},
    "axis": {"gridColor": GRID, "domainColor": "#cbd5e1", "tickColor": "#cbd5e1",
             "labelColor": SLATE, "titleColor": "#334155", "labelFontSize": 12,
             "titleFontSize": 12, "titleFontWeight": 500},
    "title": {"color": NAVY, "fontSize": 15, "fontWeight": 600, "anchor": "start", "offset": 12},
}


def _use_example(question: str) -> None:
    st.session_state["question"] = question
    st.session_state["last_result"] = None


def _table_height(rows: int) -> int:
    """Pixel height that shows every row without an inner scrollbar (layout only)."""
    return 38 + 35 * max(rows, 1)


# ----------------------------------------------------------------------------- sidebar

def render_sidebar(base_url: str) -> None:
    st.sidebar.header("System status")
    st.sidebar.caption("Backend address")
    st.sidebar.code(base_url, language=None)
    health = ui_client.health(base_url)
    if health is not None:
        st.sidebar.success("Backend connected")
    level, text = ui_client.interpreter_summary(health)
    getattr(st.sidebar, level)(text)
    info = (health or {}).get("interpretation") or {}
    if info.get("mode") == "llm":
        st.sidebar.caption(
            f"Provider: {info.get('provider') or 'unknown'} · Model: {info.get('model') or 'unknown'}"
        )
    st.sidebar.caption(
        "The sidebar shows what is configured. Each answer states which interpreter it actually used."
    )
    if health is None:
        st.sidebar.caption(
            "Start the backend in a separate PowerShell window with: "
            f"`{ui_client.START_COMMAND}`"
        )


# ----------------------------------------------------------------------------- failures

def render_failure(result: ui_client.ApiResult) -> None:
    title = FAILURE_TITLES.get(result.error_code or "", "The question could not be answered")
    severity = st.warning if result.error_code in (
        "empty_question", "malformed_request", "unsupported_question",
        "ambiguous_question", "invalid_parameters",
    ) else st.error
    severity(f"**{title}.** {result.message}")
    if result.status is not None:
        st.caption(f"Backend response: HTTP {result.status} ({result.error_code})")


# ----------------------------------------------------------------------------- charts

def _money_tooltip(field: str, title: str) -> dict:
    return {"field": field, "type": "quantitative", "title": title, "format": ",.2f"}


def _bar_chart(frame: pd.DataFrame, category: str, value: str, title: str,
               x_title: str, sort: str | None, highlight: str | None = None) -> None:
    """Bar chart drawn only from backend values.

    sort: "-y" puts the largest bar first, None keeps the order the backend returned.
    highlight: category name drawn in navy (the backend's rank 1); the others use the lighter blue.
    """
    color: dict = {"value": BLUE}
    if highlight is not None:
        color = {"condition": {"test": {"field": category, "equal": highlight}, "value": NAVY},
                 "value": BLUE_SOFT}
    spec = {
        "title": title,
        "height": 300,
        "config": VEGA_CONFIG,
        "mark": {"type": "bar", "cornerRadiusTopLeft": 4, "cornerRadiusTopRight": 4,
                 "color": BLUE, "size": 42},
        "encoding": {
            "x": {"field": category, "type": "nominal", "sort": sort, "title": x_title,
                  "axis": {"labelAngle": 0}},
            "y": {"field": value, "type": "quantitative", "title": "Net revenue",
                  "axis": {"format": ",.0f"}},
            "color": color,
            "tooltip": [
                {"field": category, "type": "nominal", "title": x_title},
                _money_tooltip(value, "Net revenue"),
            ],
        },
    }
    st.vega_lite_chart(frame, spec, use_container_width=True)


def _line_chart(frame: pd.DataFrame, title: str) -> None:
    spec = {
        "title": title,
        "height": 300,
        "config": VEGA_CONFIG,
        "mark": {"type": "line", "color": BLUE, "strokeWidth": 3,
                 "point": {"filled": True, "size": 80, "color": BLUE}},
        "encoding": {
            "x": {"field": "month", "type": "ordinal", "sort": None, "title": "Month",
                  "axis": {"labelAngle": 0}},
            "y": {"field": "revenue", "type": "quantitative", "title": "Net revenue",
                  "axis": {"format": ",.0f"}},
            "tooltip": [
                {"field": "month", "type": "ordinal", "title": "Month"},
                _money_tooltip("revenue", "Net revenue"),
            ],
        },
    }
    st.vega_lite_chart(frame, spec, use_container_width=True)


def _revenue_table(frame: pd.DataFrame) -> None:
    st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        height=_table_height(len(frame)),
        column_config={"Net revenue": st.column_config.NumberColumn(format="%.2f")},
    )


def _ranking_section(ranking: list[dict], label: str) -> None:
    chart_frame = pd.DataFrame(
        [{"name": row["name"], "revenue": row["revenue"]} for row in ranking]
    )
    top_name = ranking[0]["name"] if ranking else None
    left, right = st.columns([3, 2], gap="large")
    with left:
        _bar_chart(chart_frame, "name", "revenue", f"Net revenue by {label.lower()}",
                   label, "-y", highlight=top_name)
    with right:
        st.markdown(f"**{label} ranking (highest first)**")
        frame = pd.DataFrame(ranking).rename(columns={
            "name": label, "revenue": "Net revenue", "transactions": "Transactions", "units": "Units",
        })
        _revenue_table(frame)


# ----------------------------------------------------------------------------- answers

def render_source(source: str | None) -> None:
    label = ui_client.source_label(source)
    css = "rsg-badge-llm" if source == "llm" else "rsg-badge-fallback"
    st.markdown(f'<span class="rsg-badge {css}">{label}</span>', unsafe_allow_html=True)
    st.caption(f"Interpreted by: {label}")


def render_success(data: dict) -> None:
    op = data["operation"]
    result = data["result"]
    supporting = data["supporting_figures"]

    with st.container(border=True):
        st.markdown('<div class="section-label">Answer</div>', unsafe_allow_html=True)
        st.info(data["answer"])
        render_source(data["interpretation_source"])

    if op == "total_revenue":
        col1, col2 = st.columns(2, gap="medium")
        col1.metric("Total net revenue", ui_client.format_money(result["total_revenue"]))
        col2.metric("Eligible transactions", supporting["eligible_transactions"])

    elif op in ("top_product", "top_region"):
        label = "Product" if op == "top_product" else "Region"
        if result.get(label.lower()) is None:
            st.caption("No eligible transactions, so there is no ranking.")
        else:
            col1, col2, col3 = st.columns(3, gap="medium")
            col1.metric(f"Highest-revenue {label.lower()}", result[label.lower()])
            col2.metric("Net revenue", ui_client.format_money(result["revenue"]))
            top_row = supporting["ranking"][0] if supporting["ranking"] else {}
            col3.metric("Supporting transactions", top_row.get("transactions", "—"))
            _ranking_section(supporting["ranking"], label)

    elif op == "monthly_trend":
        months = supporting["monthly_revenue"]
        if not months:
            st.caption("No stored transactions, so there is no monthly trend.")
        else:
            left, right = st.columns([3, 2], gap="large")
            with left:
                chart_frame = pd.DataFrame(
                    [{"month": ui_client.month_label(m["month"]), "revenue": m["revenue"]}
                     for m in months]
                )
                _line_chart(chart_frame, "Monthly net revenue")
            with right:
                st.markdown("**Monthly net revenue (chronological)**")
                frame = pd.DataFrame([
                    {"Month": ui_client.month_label(m["month"]), "Net revenue": m["revenue"],
                     "Transactions": m["transactions"]}
                    for m in months
                ])
                _revenue_table(frame)

    elif op == "compare_months":
        pct = result["percentage_change"]
        col1, col2, col3 = st.columns(3, gap="medium")
        col1.metric(ui_client.month_label(supporting["month_a"]),
                    ui_client.format_money(supporting["revenue_a"]))
        col2.metric(ui_client.month_label(supporting["month_b"]),
                    ui_client.format_money(supporting["revenue_b"]))
        # The delta text is the backend's percentage, formatted only; Streamlit colours it by sign.
        col3.metric("Absolute change", f"{result['absolute_change']:+,.2f}",
                    delta=None if pct is None else f"{pct:+.2f}%")
        st.markdown(
            f"**Direction:** {result['direction']}  \n"
            f"**Percentage change:** {ui_client.format_percentage(pct)}"
        )
        chart_frame = pd.DataFrame([
            {"month": ui_client.month_label(supporting["month_a"]), "revenue": supporting["revenue_a"]},
            {"month": ui_client.month_label(supporting["month_b"]), "revenue": supporting["revenue_b"]},
        ])
        left, _ = st.columns([3, 2], gap="large")
        with left:
            _bar_chart(chart_frame, "month", "revenue", "Net revenue in the two months",
                       "Month", None)
        st.caption(
            f"Supporting transactions: {supporting['transactions_a']} in "
            f"{ui_client.month_label(supporting['month_a'])}, {supporting['transactions_b']} in "
            f"{ui_client.month_label(supporting['month_b'])}."
        )

    if data.get("notes"):
        with st.expander("Calculation notes and method"):
            for note in data["notes"]:
                st.markdown(f"- {note}")


# ----------------------------------------------------------------------------- page

def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📊", layout="wide")
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    base_url = ui_client.api_base_url()

    st.session_state.setdefault("question", "")
    st.session_state.setdefault("last_result", None)
    render_sidebar(base_url)

    st.title(APP_TITLE)
    st.markdown(f'<div class="app-subtitle">{APP_SUBTITLE}</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-label">Suggested questions</div>', unsafe_allow_html=True)
    columns = st.columns(len(EXAMPLES), gap="small")
    for column, (label, question) in zip(columns, EXAMPLES):
        column.button(label, key=f"example_{label}", on_click=_use_example, args=(question,),
                      use_container_width=True)

    st.markdown('<div class="section-label">Your question</div>', unsafe_allow_html=True)
    input_col, button_col = st.columns([6, 1], gap="small", vertical_alignment="bottom")
    input_col.text_input("Your question", key="question", label_visibility="collapsed",
                         placeholder="For example: How did revenue change between May and June?")
    asked = button_col.button("Ask", type="primary", key="ask", use_container_width=True)

    if asked:
        with st.spinner("Asking the backend..."):
            st.session_state["last_result"] = ui_client.ask(st.session_state["question"], base_url)

    result = st.session_state.get("last_result")
    if result is None:
        st.caption("Choose a suggested question or type your own to see the answer, charts and figures.")
    else:
        st.markdown("<div style='height: 0.6rem'></div>", unsafe_allow_html=True)
        if result.ok:
            render_success(result.data)
        else:
            render_failure(result)


main()
