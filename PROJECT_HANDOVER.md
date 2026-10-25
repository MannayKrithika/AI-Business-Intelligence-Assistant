# PROJECT_HANDOVER.md

Read this file first when continuing this project in a new conversation. It records the assignment,
every approved decision, the status of each phase, the test results, the Windows PowerShell
commands for running the project, and the exact next step.

---

## 1. Current status

| Phase | Content | Status |
|---|---|---|
| 0 | Requirement analysis and design | Approved |
| 1 | CSV import, schema, validation, duplicate handling | Approved (25 tests) |
| 2 | Analytics engine: five operations, fixed parameterized SQL | Approved (45 tests) |
| 3 | FastAPI backend: `POST /ask`, error handling | Approved (68 tests) |
| 4 | AI interpreter (OpenAI-compatible adapter), deterministic fallback, `.env` configuration | Approved (75 tests) |
| 5 | Streamlit user interface | Approved (38 tests) |
| 6 | Integration testing, error paths, clean install | Verified by the owner on Windows: **299 passed, 0 failed, 2 deprecation warnings, 144.24 s** |
| 7 | Dashboard, Groq configuration, documentation, final ZIP | **Implemented. New tests not yet run by the owner. See 1.1.** |

### 1.0 UI polish pass (25 October 2026, after Phase 7)

Presentation only (`app/ui.py`, new `.streamlit/config.toml` forcing a light theme, new
`tests/test_ui_design.py` with 6 static tests, title assertions in `tests/test_ui.py` updated).
The page title and browser-tab title are exactly "AI Business Intelligence Assistant" (no RSG).
Backend, SQL, API contracts, `ui_client.py` and all widget keys are unchanged. Expected total is now
348 passed, 1 skipped (unconfirmed until run on Windows). The owner's own `.env` is not part of the ZIP.

### 1.1 Phase 7 final status (25 October 2026)

**Dashboard (`app/ui.py`).** Wide layout, professional title, status sidebar (backend connection,
AI interpreter status, provider and model), five suggested questions, question box and Ask button,
spinner, answer card, key-figure metrics with supporting transaction counts, charts (monthly trend
line, product and region bar charts sorted by revenue, two-bar month comparison), supporting
tables, and a "Calculation notes and method" expander. Each answer shows a badge and caption for
`interpretation_source`: **AI model (LLM)** or **Deterministic fallback**. Charts use only lists
returned by the backend. The UI performs no analytics. Widget keys and the answer card remain
compatible with the Phase 5/6 UI tests, except that the page title changed from "Sales Question
Assistant" to "RSG Business Intelligence Assistant" (one assertion updated).

**Groq.** `LLM_PROVIDER=groq` uses the existing OpenAI-compatible `urllib` adapter with the Groq
endpoint `https://api.groq.com/openai/v1` and default model `llama-3.1-8b-instant` filled in
(both overridable with `LLM_BASE_URL` and `LLM_MODEL`). The base URL and model ID were checked
against Groq's published documentation (production models list) on the date above. Prices,
limits and any free allowance were not verified and are not claimed. `LLM_PROVIDER=none` remains
the default. The adapter now sends a descriptive `User-Agent`, maps HTTP 400/422 to a "check
LLM_MODEL" message, and rejects the `.env.example` placeholders. `.env` is in `.gitignore`.
`python -m app.verify_llm --yes` sends one real request for the owner to verify the provider.

**Small fix.** The importer CLI ignored `RSG_DB_PATH` (confirmed in `app/importer.py`: `--db`
defaulted to the fixed path). It now uses `--db`, then `RSG_DB_PATH` (relative to the project folder),
then the default. Regression tests: `tests/test_importer_db_path.py`.

**Documentation.** `README.md`, `ARCHITECTURE.md`, `AI_DEVELOPMENT_NOTES.md` (new);
`docs/llm_providers.md`, `.env.example` and this file (updated).

**Tests.**
- Owner-verified baseline (Phase 6, Windows): 299 passed.
- Added in Phase 7: `tests/test_groq.py` (30), `tests/test_importer_db_path.py` (3),
  `tests/test_live_provider.py` (1, opt-in, skipped by default), 10 new dashboard tests in
  `tests/test_ui.py`. Expected total: 348 passed, 1 skipped. **This expected count has not been
  confirmed on Windows.** Please run `python -m pytest -q` and record the result here.
- What the Phase 7 author actually executed (Linux sandbox without FastAPI, Streamlit or pytest):
  the standard-library-only test files (settings, LLM, interpreter, router, importer, analytics,
  Groq, importer path, hygiene) using a temporary stand-in runner: 204 passed, 0 failed, 1 skipped.
  The dashboard's render functions were smoke-tested against a stubbed Streamlit for all five
  operations. The API, integration and Streamlit AppTest suites could NOT be run there.
- **Live Groq testing was NOT completed.** No credentials were used and no request was sent.
  Mocked tests do not prove the real service accepts the request. Run
  `python -m app.verify_llm --yes` after setting your key.

**Owner checklist before submitting.**
1. `python -m pytest -q` (expect 348 passed, 1 skipped; report anything else).
2. Open the dashboard and click the five suggested questions; compare with the reference values in section 5.
3. Configure Groq in your own `.env`, run `python -m app.verify_llm --yes`, then ask
   "What is our overall sales income?" and confirm the card says AI model (LLM).
4. Confirm `git status` does not list `.env`.

## 2. Assignment summary

- **Challenge:** RSG "AI-Assisted Development Challenge for GET selection: Build a Mini AI Business
  Intelligence Assistant". Target effort 3–4 hours. A production-ready system is not expected.
- **Objective:** a business user asks questions about sales data in natural language and receives
  answers backed by real database queries.
- **Required questions (support at least four; the project targets all five):**
  1. What is the total revenue?
  2. Which product generated the highest revenue?
  3. What is the monthly revenue trend?
  4. Which region generated the highest sales?
  5. How did revenue change between two months?
- **Required deliverables:** source code in a Git repository, README with setup and run instructions,
  architecture diagram or explanation, automated tests (at least five), and AI development notes
  covering: tools used, how AI was used, problems encountered, how they were debugged, and what
  would be improved.
- **Evaluation areas:** working functionality; programming fundamentals; backend and database design;
  correctness and reliability; appropriate use of AI; testing and error handling; ability to explain
  and modify the implementation.
- **Owner's main goal:** a complete, working project that can be downloaded, extracted, opened in
  VS Code, run on a Windows laptop, and inspected or corrected manually.

---

## 3. Approved decisions

### Technology
- Python 3, FastAPI, SQLite (standard `sqlite3` module), Streamlit (Phase 5), Pytest.
- The UI talks to the backend over HTTP. It does not import the analytics code.
- The LLM call uses Python's standard library (`urllib`). No AI SDK is installed.
- pandas is **not** used by the application. It was used only for ad-hoc verification outside the project.
- No LangChain, vector database, Docker, authentication, or other frameworks.
- Dependencies are pinned in `requirements.txt`.

### Data and revenue policy
- Source CSV: `data/sales.csv`, copied unchanged from the supplied file (51 rows, 10 columns).
- Dates are `DD-MM-YYYY` in the source and stored as ISO `YYYY-MM-DD`, with `order_month` as `YYYY-MM`.
- **Net revenue** per transaction = `quantity × unit_price − discount_amount`. The discount is a
  transaction-level amount and is subtracted **once**.
- **Eligible for analytics** = `status = 'Completed' AND unit_price IS NOT NULL`. Defined once in
  `app/db.py` (`REVENUE_ELIGIBLE_SQL`) and used by every operation.
- Returned transactions and transactions with a missing unit price are **stored** but **excluded**.
  Nothing is imputed.
- Zero-quantity transactions are valid and contribute 0.
- **Negative net revenue is allowed** (a discount larger than the gross amount). It is kept and
  included in all calculations.
- Blank `Unit_price` is stored as NULL. A nonblank non-numeric or negative price rejects the row.
  A blank or invalid discount, a negative quantity, a non-integer quantity, an invalid date, or a
  blank required text field also rejects the row.
- Whitespace is trimmed and the number of trimmed fields is reported.
- Source data is never modified. The CSV is opened read-only.

### Duplicate handling
- `Transaction_Id` is the primary key. Re-running the import does not duplicate rows.
- Identical duplicates in one file: one is stored, the rest are skipped and reported.
- Conflicting duplicates in one file: all copies are rejected.
- A copy of a record from an earlier run: identical copies are skipped and reported. Conflicting
  copies are skipped, the stored record is kept, and the differing fields are reported.
- Every rejection, skip, and conflict is written to `output/import_issues.csv`.

### Analytics rules
- Rankings: revenue descending, then name ascending (alphabetical tie-break).
- Monthly trend: every month from the first to the last stored month, chronological. A month with
  no eligible rows is shown as 0.00 with 0 transactions.
- Month comparison: `absolute_change = revenue(month_b) − revenue(month_a)`. Direction is
  `increased`, `decreased`, or `unchanged`, from the 2-dp rounded change.
- Percentage change = `absolute_change / |revenue(month_a)| × 100`, rounded to 2 dp.
  - **Zero baseline:** `percentage_change` is `null` with a note. No division by zero.
  - **Negative baseline:** calculated against the absolute baseline, with a note that it is a size
    relative to the baseline, not a growth rate.
  - Details and limitations: `docs/analytics_policy.md`.
- Every number comes from fixed SQL or from a deterministic calculation. **No model ever produces a number.**

### Month input
- Natural-language months: "May and June", "between May and June", "from May 2026 to June 2026",
  "2026-05 vs 2026-06".
- "may" is a month only after words such as *in, of, from, between, and, to, vs*. Otherwise it is the verb.
- A missing year is filled from the stored data **only** when the data spans one year, and the answer
  says so (here, 2026).
- Months must be inside the stored range (2026-01 to 2026-06). Identical months are rejected.
- The UI uses a single text box, with no month dropdowns.

### Question handling and AI (Phase 4)
- Five supported operations: `total_revenue`, `top_product`, `monthly_trend`, `top_region`,
  `compare_months`.
- **Interpretation order:**
  1. If an LLM is configured and active, it chooses one operation (or `unsupported`) and, for a
     comparison, two `YYYY-MM` months. Response `interpretation_source` = `"llm"`.
  2. If the LLM is not configured, times out, errors, or gives a bad reply, the **deterministic
     fallback** is used. Response `interpretation_source` = `"fallback"`, and the `notes` say why.
  3. If the model says `unsupported`, that refusal is final and no fallback is tried.
- The LLM's output is validated: operation must be one of the five (or `unsupported`); months must be
  `YYYY-MM`. Extra fields such as numbers are ignored. Months are range-checked by analytics.
- **The model never writes SQL and never supplies numbers.** Its reply is data, not instructions.
- Secrets live only in environment variables or `.env`. `.env.example` contains placeholders.
  The key is never printed, logged, or returned. A test checks this across all responses.
- The core test suite needs no API key and no network.
- **Default:** `LLM_PROVIDER=none`, so the fallback is used and the app works fully offline.

### LLM provider (decision status)
- **Phase 7 decision:** Groq (`LLM_PROVIDER=groq`) is the supported hosted provider. Live use unverified.
- **Implemented:** one adapter for any **OpenAI-compatible** chat endpoint. This covers a hosted
  OpenAI-style API or gateway, and a local Ollama or LM Studio server.
- **Not implemented:** the Anthropic Claude API, which has a different request format. It can be
  added as a separate adapter if chosen.
- **Owner's choice still pending:** which provider to use, or none. See `docs/llm_providers.md` for
  options, key requirements, and cost estimates. Cost figures are estimates; live prices were not verified.

### Process
- Phase-by-phase approval. Each checkpoint is reported, and work stops until the owner approves.
- Project files are updated in place. Working modules are preserved. Chat is not a substitute for files.
- Every checkpoint includes exact Windows PowerShell commands (section 6).
- At the end, a complete, verified, downloadable ZIP is delivered (Phase 7), with README instructions.

---

## 4. Project structure (Phase 7 additions marked NEW)

```
rsg-bi-assistant/
├── app/
│   ├── __init__.py
│   ├── config.py             paths, the 10 CSV column names
│   ├── db.py                 schema, read-write and read-only connections, REVENUE_ELIGIBLE_SQL
│   ├── importer.py           CSV validation, duplicate policy, import report, CLI
│   ├── analytics.py          the five operations (fixed parameterized SQL)
│   ├── question_router.py    rule-based interpreter = the deterministic FALLBACK
│   ├── llm.py                LLM prompt, OpenAI-compatible client, output parsing and validation
│   ├── interpreter.py        LLM first when active, otherwise fallback; labels the source
│   ├── settings.py           environment and .env configuration, secret-safe
│   ├── service.py            question → interpretation → analytics → response payload
│   ├── schemas.py            request and response models
│   ├── main.py               FastAPI backend: POST /ask, GET /health, uniform error shape
│   ├── ui_client.py          UI's HTTP client to the backend, and display formatting (no analytics)
│   ├── ui.py                 Streamlit dashboard (layout, charts; python -m streamlit run app/ui.py)
│   └── verify_llm.py         NEW: owner-run one-request provider check (python -m app.verify_llm --yes)
├── tests/
│   ├── __init__.py
│   ├── helpers.py            importer-built test databases; FakeLLMClient (no network)
│   ├── reference.py          independent pure-Python reference calculator
│   ├── test_importer.py          25 tests
│   ├── test_analytics.py         45 tests
│   ├── test_question_router.py   30 tests
│   ├── test_api.py               38 tests
│   ├── test_settings.py          12 tests
│   ├── test_llm.py               39 tests
│   ├── test_interpreter.py       14 tests
│   ├── test_llm_api.py           10 tests
│   ├── test_ui_client.py         26 tests (mock HTTP transport)
│   ├── test_ui.py                12 tests (Streamlit AppTest against a live backend thread)
│   ├── test_integration.py       42 tests (end to end: CLI import, backend, UI, error paths)
│   ├── test_groq.py              NEW: 30 tests (Groq config, request format, failures, verify helper)
│   ├── test_importer_db_path.py  NEW: 3 tests (RSG_DB_PATH regression)
│   ├── test_live_provider.py     NEW: 1 opt-in live test (skipped by default)
│   └── test_project_hygiene.py    6 tests (no secrets, no machine paths, ignore rules, pinned deps)
├── data/
│   └── sales.csv             supplied dataset (data/sales.db is generated, not source)
├── docs/
│   ├── analytics_policy.md   revenue, ranking, comparison, and percentage rules
│   └── llm_providers.md      provider options, keys, cost, PowerShell configuration
├── output/                   generated import issues report (not source)
├── .env.example              configuration template with placeholders only
├── pytest.ini
├── requirements.txt          pinned: pytest, fastapi, uvicorn, pydantic, httpx, streamlit, pandas
├── .gitignore                ignores .env, .venv, data/sales.db, output/, caches
└── PROJECT_HANDOVER.md       this file
```

Phase 7 added `README.md`, `ARCHITECTURE.md` and `AI_DEVELOPMENT_NOTES.md` at the project root.

## 5. Completed phases and results

### Phase 1: import (25 tests)
- Supplied CSV: 51 rows read, 51 accepted, 0 rejected, 51 stored.
- Excluded from revenue: 2 (TXN0033 Returned, TXN0051 missing price). Zero-quantity: 1 (TXN0034).
- Revenue-eligible rows: 49.
- Re-running the import: 0 accepted, 51 skipped as identical.
- Field-by-field check against an independent pandas read: 0 mismatches.

### Phase 2: analytics (45 tests)
- Total net revenue **1,439,200.00** (49 eligible transactions).
- Highest-revenue product **Monitor**, 473,000.00. Highest-sales region **South**, 411,200.00.
- Monthly: Jan 210,250 · Feb 234,600 · Mar 223,900 · Apr 240,700 · May 318,500 · Jun 211,250.
- May → June: −107,250.00, −33.67%, decreased.
- SQL results matched the reference calculator and a separate pandas check.

### Phase 3: FastAPI backend (68 tests)
- `POST /ask` returns `question, operation, interpretation_source, answer, result, supporting_figures, notes`.
- `GET /health` and `/docs` (interactive API documentation).
- Errors share one shape: `{"error": {"code": "...", "message": "..."}}`.

| HTTP | Code | When |
|---|---|---|
| 400 | `malformed_request` | invalid JSON, non-object body, missing/empty/blank/too-long/non-string `question` |
| 422 | `unsupported_question` | no supported operation recognised (or the model said so) |
| 422 | `ambiguous_question` | more than one operation recognised |
| 422 | `invalid_parameters` | wrong number of months, invalid month, outside data range, identical months |
| 503 | `database_unavailable` | database missing, uninitialised, or unreadable (path not exposed) |
| 500 | `internal_error` | unexpected error (generic message; traceback logged on the server only) |

### Phase 4: AI interpreter and configuration (75 new tests; 213 total)

**Changes to earlier behaviour (approved as part of Phase 4):**
- `interpretation_source` was `"temporary_router"`. It is now `"llm"` or `"fallback"`.
- `GET /health` now returns `{"status": "ok", "interpretation": {...}}`, with `mode` (`llm` or
  `fallback`), `provider`, `model`, and `problem` (why the LLM is not in use, or null). It never
  shows the key.
- `app/question_router.py` is now the labelled fallback rather than a temporary router. Its
  behaviour is unchanged.

**Tests added:**
- `test_settings.py` (12): defaults, validation problems, `.env` parsing (comments, quotes, `export`),
  precedence (environment over `.env`), key never in `repr`, `os.environ` never modified.
- `test_llm.py` (39): prompt contents, parsing of bare and fenced JSON, validation of operations and
  months, extra fields ignored, client request format, bearer header, HTTP error mapping
  (401/403/404/429/5xx/other), timeouts, network errors, malformed provider responses. No network.
- `test_interpreter.py` (14): LLM used and labelled; paraphrase handled by LLM only; fallback on
  timeout, auth error, malformed or invalid reply; model refusal is final; configuration problem
  gives a fallback with a reason; the API key never appears in `describe()`.
- `test_llm_api.py` (10): LLM answers a paraphrase with numbers from the database (fake model's
  invented number ignored); LLM outage falls back; secret never in any response; real client with a
  401 falls back and does not leak the key.

**Live checks run on the sandbox (real HTTP, real uvicorn):**
- **A.** Local OpenAI-compatible stand-in, correct key: `/health` shows `mode: llm`. A paraphrase
  ("What is our overall sales income?") is answered with source `llm`, and the database total is correct.
- **B.** Wrong key: falls back, notes say "authentication failed; check LLM_API_KEY", key absent from
  the response and the server log.
- **C.** Unreachable provider (closed port): falls back, notes say "network error".
- **D.** No key (default): `mode: fallback`, works offline.
- **E.** `.env` file (temporary, copied from `.env.example`, then deleted): configuration read
  correctly with no environment variables set.

**Limitations:**
- The stand-in is a local test server, not a real provider. A live hosted or local-model run has
  **not** been verified. That is for the owner to check on the laptop.
- Live prices and model names were not verified. `LLM_MODEL` must be set to a name the provider lists.
- The LLM can choose a supported operation for a question the fallback would refuse. This is intended,
  but it means an LLM answer should be checked by the owner on real questions.
- The Anthropic Claude API is not supported by this adapter.

---

### Phase 5: Streamlit user interface (38 new tests; 251 total)
- `app/ui.py` is a single page: title, five example-question buttons, one question box, an **Ask**
  button, the answer, and a sidebar with backend status and interpreter mode.
- `app/ui_client.py` does all HTTP work and display formatting. It calls `POST /ask` and
  `GET /health`. It performs no analytics and never computes a figure.
- Shown for each answer: the answer text; the interpretation source ("AI model (LLM)" or
  "Deterministic fallback (rule-based, no AI model used)"); metrics and ranking tables for each
  operation; a notes panel with the method and any explanation from the backend.
- Shown for each failure: a clear title and the backend's message. Unsupported, ambiguous, invalid,
  and empty questions appear as yellow warnings. Backend unreachable, timeout, and database problems
  appear as red errors. No failure shows a made-up figure.
- The backend address comes from `RSG_API_URL` (environment or `.env`), with default
  `http://127.0.0.1:8000`.
- Backend integration: the UI never imports analytics. It sends the question and displays what the
  backend returns.

**Tests added:**
- `test_ui_client.py` (26): successful answer passed through unchanged and question trimmed before
  sending; every backend error code mapped to a message; incomplete or non-JSON replies rejected;
  connection refused gives the start command; timeout reported separately; blank input never sent;
  health parsing; URL precedence (environment over `.env` over default); money, percentage, month,
  source, and sidebar-summary formatting.
- `test_ui.py` (12): Streamlit's `AppTest` runs the real page against a real backend on a free port.
  Checks: clean render; total revenue with source label; ranking table of seven products; six-month
  trend; region ranking; month comparison with −33.67%; unsupported, invalid-month, and identical-month
  warnings; empty question prompt; example button fills the box; unreachable backend gives a clear error.

**Live checks (real uvicorn and real Streamlit server):**
- Backend `/health` returned mode `fallback`.
- The Streamlit server answered `/_stcore/health` with `ok`, and the page returned HTTP 200.
- The backend answer that the page displays was verified: South, 411,200.00, source `fallback`.

**Limitations:**
- The page was tested with Streamlit's test runner and the server's health and page endpoints, not
  in a real browser on a screen. Visual layout has not been inspected by eye.
- Charts were deliberately not added (the assignment asks for a clean interface, not a dashboard).
- Streamlit 1.41.1 and pandas 2.2.3 are pinned. Newer versions have different APIs and were not tested.

---

### Phase 6: integration, error paths, and clean install (48 new tests; 299 total)

**Defects found by the review and fixed (all in application code, with tests):**
1. **Cross-thread database connection (serious).** Under parallel load, FastAPI can open a request's
   read-only connection in one worker thread and close it in another. SQLite then raises
   `ProgrammingError`. The concurrency test found this (40 parallel requests). Fixed in `app/db.py`:
   the connection allows cross-thread use. This is safe because each connection serves one request only.
2. **Importer crashed with a traceback on a damaged database file.** It now prints a short message,
   exits with code 1, and states that nothing was deleted. It never deletes the file itself.
3. **Unknown routes and wrong methods returned a different error shape** (`{"detail": ...}`).
   They now return the same `{"error": {"code", "message"}}` shape as every other error:
   `not_found` (404) and `method_not_allowed` (405).

**Reviewed and confirmed correct (no change needed):**
- Malformed JSON, non-object bodies, and missing, empty, blank, too-long, or non-text questions → 400.
- Emoji and unrelated questions → 422 `unsupported_question`.
- Invalid months, identical months, months outside 2026-01 to 2026-06, malformed `2026-13`, and a
  single month → 422 `invalid_parameters`, with an explanation the user can act on.
- Missing database, damaged database file, and a database with no tables → 503 `database_unavailable`.
  The file path is never disclosed.
- Empty but initialised database → zero total, no top product or region, empty monthly trend.
- Backend stopped during use → the page shows a red "Cannot reach the backend" error, and no stale
  answer remains on screen.
- Backend started with a missing database → the page shows a red "not available" error.
- Unexpected server errors → generic 500 `internal_error`; no traceback or SQL in the response.
- SQL text typed into a question is never executed (the row count is unchanged afterwards).
- With no key and `LLM_PROVIDER=none`, no network call is attempted (a test blocks `urlopen`).
- The importer's command-line run reports errors cleanly (no traceback) for a damaged file.

**Integration tests (`tests/test_integration.py`, 42 tests):**
- Import through the real command line (`python -m app.importer`), then five question types checked
  over HTTP against values from the independent reference calculator (not hard-coded).
- Each of the five example buttons is clicked in the real Streamlit page and the displayed answer is
  checked against the reference.
- Unsupported questions, invalid months, and an ambiguous question are checked over HTTP and in the UI.
- Malformed requests, unknown routes, wrong methods, and the unexpected-error path.
- Backend not running, backend stopped during use, missing database, damaged database, empty database.
- Default configuration with no key, a stray key with `LLM_PROVIDER=none`, and no network use.
- 40 parallel requests (8 threads) with identical answers.

**Project hygiene tests (`tests/test_project_hygiene.py`, 6 tests):** `.env.example` contains only
placeholders and the default provider is `none`; no API-key-like strings and no machine-specific paths in
shipped files (test files are excluded on purpose, because they contain deliberately fake keys);
`.gitignore` excludes secrets, databases, caches, and outputs; every dependency is pinned; the sample data
is present.

**Test runs:**
- *Existing development environment:* 299 passed, 0 failed.
- *Clean install (fresh virtual environment built from the extracted ZIP):* `pip install -r requirements.txt`
  succeeded, `pip check` reported no broken requirements, the importer loaded 51 rows, and pytest reported
  299 passed.
- *Live run from the clean install (real backend and real Streamlit, `LLM_PROVIDER` unset, no `.env`):*
  health reported `mode: fallback`; all five questions returned the expected operations and figures; an
  unsupported question returned 422; an invalid month returned 422 with the available range; the Streamlit
  health check returned `ok`; the page returned HTTP 200, and still returned HTTP 200 after the backend was
  stopped; neither log contained a traceback.

**Limitations (Phase 6):**
- PowerShell was not run, and the page was not inspected visually in a browser.
- Dependencies are pinned directly. Their own dependencies (for example numpy and pyarrow) are resolved at
  install time. Windows wheel availability for these was not verified from Linux.
- A request without a `Content-Type` header is still accepted (FastAPI parses JSON anyway). This is
  lenient, not a defect, and it is documented.
- The concurrency test checks correctness at 8 threads and 40 requests. It is not a load test.

---


## 6. Running the project on Windows (PowerShell)

Use **three separate PowerShell windows**. Each block says which window to use.
Replace `C:\path\to\rsg-bi-assistant` with the folder you extracted the ZIP to.

| Window | Purpose | Keep open? |
|---|---|---|
| **Window 1** | Setup, database, tests (run once, then reuse) | No |
| **Window 2** | Backend (FastAPI) | Yes, while using the app |
| **Window 3** | Streamlit user interface | Yes, while using the app |

### 6.1 Window 1: one-time setup

```powershell
cd "C:\path\to\rsg-bi-assistant"
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Your prompt should now start with `(.venv)`. If `Activate.ps1` is blocked, run this once in
Window 1, answer `Y`, then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### 6.2 Window 1: create the database and run the tests

```powershell
python -m app.importer
python -m pytest -q
```

Expected: the importer reports `CSV rows read: 51`. Pytest should end with **`348 passed, 1 skipped`** (Phase 6 was 299 passed).
Warnings may be printed; they are not failures.

### 6.3 Optional configuration (Window 1)

For Groq set `LLM_PROVIDER=groq` and `LLM_API_KEY=<your key>` in `.env` (see README.md), then run
`python -m app.verify_llm --yes` for a one-request check.

Skip this to use the offline fallback, which needs no key and no cost.

```powershell
Copy-Item .env.example .env
notepad .env
```

- Leave `LLM_PROVIDER=none` for the offline fallback.
- To use an AI model, follow `docs/llm_providers.md`.
- Save the file as `.env`, not `.env.txt` (in Notepad choose **Save as type: All files**).
- Optional: set `RSG_API_URL` in `.env` only if the backend runs on another address.

### 6.4 Window 2: start the backend (keep open)

```powershell
cd "C:\path\to\rsg-bi-assistant"
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
```

Wait for `Uvicorn running on http://127.0.0.1:8000`.

### 6.5 Window 3: start the Streamlit interface (keep open)

```powershell
cd "C:\path\to\rsg-bi-assistant"
.\.venv\Scripts\Activate.ps1
python -m streamlit run app/ui.py
```

Streamlit usually opens your browser at **http://localhost:8501**. If it does not, open that
address yourself. If port 8501 is busy, add `--server.port 8502` and use that port instead.

### 6.6 Testing the complete application

**Browser (Window 3 must be running, and Window 2 too):** open http://localhost:8501 and:
1. Check the sidebar: "Offline fallback in use" (or "AI interpreter active" if you configured a model).
2. Click **Total revenue**, then **Ask**. Expected: `1,439,200.00` and "Interpreted by: Deterministic fallback".
3. Click **Top product**, then **Ask**. Expected: Monitor, with a ranking table of seven products.
4. Click **Monthly trend**, then **Ask**. Expected: six months, January to June 2026.
5. Click **Top region**, then **Ask**. Expected: South, 411,200.00.
6. Click **Month comparison**, then **Ask**. Expected: decreased, −107,250.00, −33.67%.
7. Type `What is the weather today?` and **Ask**. Expected: a yellow "not supported" message and no figures.
8. Type `How did revenue change between May and July?` and **Ask**. Expected: a message that the
   months are outside the available range (2026-01 to 2026-06).

**Backend check (Window 1 is fine for this; Window 2 must be running):**

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$body = @{ question = "What is the total revenue?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/ask" -ContentType "application/json" -Body $body
```

**Automated tests (Window 1):**

```powershell
python -m pytest -q
```

Expected: `348 passed, 1 skipped`.

### 6.7 Stopping the application

Press `Ctrl+C` in Window 2 and in Window 3. To leave the virtual environment, type `deactivate`.

### 6.8 What the assistant could not verify

- PowerShell itself was not run. The commands use Windows PowerShell 5.1 and PowerShell 7 syntax,
  and the same steps were run on Linux.
- The browser page was not opened on a screen. The page was tested with Streamlit's test runner and
  the Streamlit server's health endpoint answered with HTTP 200.
- A real hosted AI provider or local model was not tested.
- The owner should confirm: the three-window start-up, the browser checks in 6.6, and `251 passed`.

### 6.9 Common errors and fixes

| Symptom | Fix |
|---|---|
| `py` is not recognised | Install Python 3.10 or newer from python.org and tick **Add python.exe to PATH**. Try `python --version`. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer `Y`, activate again. |
| `(.venv)` is missing from the prompt | Run `.\.venv\Scripts\Activate.ps1` from the project folder. |
| `No module named app` / `No module named pytest` / `No module named streamlit` | Run from the project folder (the one with `app\`). Activate the venv, then `python -m pip install -r requirements.txt`. |
| `uvicorn` or `streamlit` not recognised | Activate the venv and use `python -m uvicorn ...` / `python -m streamlit ...`. |
| Streamlit page says **"The backend is not running"** | Start Window 2 (`python -m uvicorn app.main:app --reload`) and wait for "Uvicorn running". Then click **Ask** again. |
| Port 8000 busy | Start the backend with `--port 8001`, then set `RSG_API_URL=http://127.0.0.1:8001` in `.env` (or in the window: `$env:RSG_API_URL = "http://127.0.0.1:8001"`) before starting Streamlit. |
| Port 8501 busy | `python -m streamlit run app/ui.py --server.port 8502` and open http://localhost:8502. |
| Browser does not open automatically | Open http://localhost:8501 yourself. |
| Sidebar shows **Offline fallback in use** after setting a key | Check `.env` is saved as `.env` in the project folder, and clear any session variable: `Remove-Item Env:LLM_PROVIDER` (and the others), then restart Window 2 and Window 3. |
| `"code":"database_unavailable"` / "sales database is not available" | Run `python -m app.importer` in Window 1, then restart Window 2. |
| "Please type a question first" | Type a question into the box before clicking **Ask**. |
| "This question is not supported" | Use one of the five example questions; the message lists what is supported. |
| "The months in the question need correcting" | Name two different months inside the data range (January to June 2026). |
| "The sales database..." or other red error after a code change | Stop Window 2 and Window 3 with `Ctrl+C`, then start them again. |
| `DeprecationWarning` during pytest | Harmless. It comes from a third-party library. |

### 6.10 Clean-install check (Window 1)

Use this to confirm the project installs from scratch. It removes the existing virtual environment.

```powershell
cd "C:\path\to\rsg-bi-assistant"
Remove-Item -Recurse -Force .venv
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
python -m app.importer
python -m pytest -q
```

Expected: `No broken requirements found.`, 51 rows imported, and `348 passed, 1 skipped`.

### 6.11 Phase 6 manual checks (Windows 2 and Windows 3 running)

1. Click each of the five example buttons, then **Ask**. Compare with section 6.6.
2. Type `Tell me a joke` and **Ask**. Expected: yellow "not supported" message, no figures.
3. Type `How did revenue change between May and July?` and **Ask**. Expected: the months are outside
   the available range (2026-01 to 2026-06).
4. In Window 2 press `Ctrl+C` (backend stopped). Click **Ask** in the browser. Expected: red
   "Cannot reach the backend" message with the start command. The page itself keeps working.
5. Start the backend again in Window 2. Click **Ask**. Expected: answers return.


## 7. Known limitations (so far)

- The rule-based fallback handles the five required question types and common phrasings. It is not
  general language understanding. With no LLM, unusual wording is rejected rather than guessed.
- "May" and "between" are heuristics. An unusual phrasing can be rejected as unsupported or ambiguous.
- Percentage change against a negative or near-zero baseline can look misleading (documented).
- The importer accepts a discount larger than the gross amount, by design.
- The supplied data has no negative revenue and no zero or negative monthly baseline. Those rules are
  verified only with hand-built fixtures.
- An LLM may choose an operation for a question the fallback would refuse. This is intended, and
  answers should be spot-checked.
- Live AI providers were not tested. Only a local stand-in and fake clients were used.
- The API has no authentication (not required by the assignment).

---

## 8. Pending work and the exact next step

### Status
Phase 7 is implemented (see section 1.1). Remaining items are the owner checklist in 1.1.
The text below is the original Phase 7 plan, kept for history.

### Phase 7 scope (original plan)
- `README.md`: the complete setup, run, test, and troubleshooting guide in plain steps, including the
  PowerShell commands from section 6, a description of each question type, and the configuration options.
- `ARCHITECTURE.md`: a diagram (Mermaid) and written data flow from CSV import through the database,
  the question, the interpreter, validation, analytics, the API, and the UI, with the responsibilities of
  each component.
- `AI_DEVELOPMENT_NOTES.md`: the AI tools used, how they were used, the problems encountered and how they
  were debugged (using the real findings above where they fit), what would be improved with another day,
  and the division of responsibility between AI interpretation and deterministic calculation.
- A final ZIP of the entire project (dataset, source, `requirements.txt`, `.env.example`, `.gitignore`,
  tests, README, ARCHITECTURE, AI notes, and this handover), with a verification pass after extraction
  into a clean virtual environment.

### Exact next step
Owner runs the checklist in section 1.1, then submits.

## 9. How to continue in a new conversation

1. Upload `PROJECT_HANDOVER.md` and the most recent project ZIP.
2. Ask: "Read PROJECT_HANDOVER.md, extract the ZIP, run the tests, and continue from section 8."
3. The new session must run `python -m pytest -q` before changing anything and report the count.
   The owner-verified count at the end of Phase 6 was **299 passed**; the expected count after Phase 7 is 348 passed, 1 skipped.
4. Preserve existing modules. Make targeted changes. Do not rebuild the project.
5. Give exact Windows PowerShell commands at every checkpoint (section 6 is the model).
