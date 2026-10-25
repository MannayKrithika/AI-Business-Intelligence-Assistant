# AI development notes

## Transparency statement

This project was built with the help of an AI coding assistant (Claude, used in chat sessions),
working phase by phase from a written handover file (`PROJECT_HANDOVER.md`). The owner set the
requirements and decisions, ran the project on Windows, and approved each phase. The assistant
wrote and revised code, tests and documentation. All AI-written code was run through the test
suite, and the owner is responsible for understanding and being able to explain it.
(Owner: add here any other tools you used, for example an editor assistant.)

The application also uses an AI model at run time, but only for one narrow job: choosing which of
five supported operations a question means. That is a different use of AI from the coding assistance above.

## How AI assisted

| Area | What the assistant did |
|---|---|
| Design | Turned the assignment into phases, a revenue policy, and edge-case rules (returned sales, missing prices, zero quantity, duplicate rows, zero or negative baselines). |
| Implementation | Wrote the importer, analytics SQL, rule-based matcher, FastAPI backend, LLM adapter and Streamlit pages. |
| Debugging | Found and fixed defects from tests and review (below). |
| Tests | Wrote 340+ pytest tests, including an independent pure-Python reference calculator that cross-checks the SQL results. |
| Documentation | Drafted this documentation, the README and the handover. |

## Division of responsibility

- **AI model at run time:** reads the question and names one operation (and two months for a comparison).
- **Deterministic code:** validates that choice, runs fixed parameterized SQL, and produces every number and the answer text.
- The model never writes SQL and never supplies a figure. A test uses a fake model that returns an invented total and checks that it is ignored.

## How model output is validated

The reply must be a JSON object (bare or in a code fence); prose around it is rejected. `operation`
must be on the allow-list, months must be `YYYY-MM`, and extra fields are ignored. Months are then
range-checked by the analytics layer. Anything unusable triggers the deterministic fallback. A model
answer of `unsupported` is final. Tests cover prose-wrapped JSON, SQL text, unknown operations, bad
months, empty and null replies, and provider failures (401, 429, 5xx, timeout, network error).

## Important problems and fixes

1. **Cross-thread SQLite connection (Phase 6).** Under 40 parallel requests, FastAPI opened a read-only connection in one thread and closed it in another, raising `ProgrammingError`. A concurrency test exposed it; the connection now allows cross-thread use, safe because each serves one request.
2. **Importer crashed on a damaged database file (Phase 6).** It now prints a short message, exits with code 1, and never deletes the file.
3. **Inconsistent error shape for unknown routes (Phase 6).** 404 and 405 now use the same `{"error": {...}}` shape as every other error.
4. **`RSG_DB_PATH` ignored by the importer (Phase 7).** The backend honoured it but `python -m app.importer` always used `data/sales.db`, so a custom path would import into one file and serve another. The importer now follows the same rule, with regression tests.
5. **Possible rejection of the default Python user agent (Phase 7).** Some hosted APIs block the default `Python-urllib` user agent. The adapter now sends a descriptive `User-Agent`. This is a precaution; it was not observed against Groq, because no live request was made.
6. **Placeholder settings (Phase 7).** Copying `.env.example` and only changing the provider would have sent a request with the placeholder key. Placeholders are now reported as configuration problems, and no request is made.
7. **Dashboard chart ordering (Phase 7).** Streamlit's built-in bar chart sorts text categories alphabetically, which would put the ranking out of order. The charts use Vega-Lite specs that keep the backend's order (or sort by value), using only backend values.

## Verification limits

- The development sandbox could not install the third-party packages, so the Phase 7 changes could not be run under the real FastAPI and Streamlit there. Tests that need only the standard library were executed with a temporary stand-in runner, and the dashboard render functions were smoke-tested against a stubbed Streamlit module. The full suite, including the new dashboard tests, must be run by the owner (`python -m pytest -q`).
- No live Groq request was made. Mocked tests prove request format, validation and fallback, not that the service accepts the request.

## Known limitations

- Five question types only; the fallback does not understand paraphrases.
- Small dataset, one year; months outside it are refused.
- No authentication, meant for local use.
- The model's choice of operation is only as good as the model; spot-check AI answers.
- The dashboard has not been viewed on screen by the author.

## Future improvements

- More analytics (by category or sales channel) and a date-range filter.
- Few-shot examples in the prompt and JSON-mode or tool-calling where the provider supports it.
- Caching and request logging for the interpreter, with a small evaluation set of paraphrased questions.
- Authentication, and packaging with Docker for deployment.
