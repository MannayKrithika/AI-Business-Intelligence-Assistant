# AI interpreter: provider options, keys, and cost

The application works without any AI provider. By default it uses a deterministic rule-based
fallback that works offline and costs nothing. An LLM is optional and only improves how questions
are understood. It never produces numbers.

## Options

| Option | Key needed | Billing | Cost | Setup effort | Notes |
|---|---|---|---|---|---|
| **D. No LLM (default)** | none | none | free | none | Recognises the five question types and common wording. Cannot understand paraphrases. |
| **A. Hosted OpenAI-compatible API** (OpenAI, or a gateway such as OpenRouter or Groq) | yes, a secret API key | prepaid balance or card | per request, typically a small fraction of a cent for a small model (estimate, check current prices) | create account, copy key | Same adapter as option C. |
| **B. Anthropic Claude API** | yes, a secret API key | prepaid balance or card | per request, same order of magnitude (estimate, check current prices) | create console account and key | Different request format. **Not implemented in Phase 4.** Can be added as a separate adapter if you choose it. |
| **C. Local model** (Ollama or LM Studio, OpenAI-compatible server on your laptop) | none (any placeholder text works) | none | free | install server, download a model (several GB), enough RAM | Slower on a laptop. The model must be running before you start the app. |

**Cost estimate.** Each question sends roughly 300–500 input tokens and receives about 20 output
tokens. I could not verify live prices, so please check the provider's current price list before
relying on any figure.

**Key safety.** A hosted key is a billable secret. Keep it only in `.env` (ignored by Git) or in
your PowerShell session. Never paste it into chat, a screenshot, or a file that is committed.
If a key is exposed, revoke it in the provider's dashboard and create a new one.

## What the app does with the LLM

1. It sends your question and the list of five operations to the model.
2. The model must reply with one JSON object naming an operation and, for a comparison, two months.
3. The reply is validated. Unknown operations, malformed months, or non-JSON replies are rejected.
4. If the model is unavailable, times out, or replies badly, the app uses the rule-based fallback
   and tells you why in the response `notes`.
5. Every number is calculated from the database by the analytics functions.

## Configuration values

| Variable | Required | Meaning |
|---|---|---|
| `LLM_PROVIDER` | yes | `none` (default), `groq`, or `openai_compatible` |
| `LLM_API_KEY` | for `groq` and `openai_compatible` | the secret key (for local servers, any non-empty text) |
| `LLM_BASE_URL` | optional for `groq` (default `https://api.groq.com/openai/v1`); needed for local servers | API root, for example `https://api.openai.com/v1` or `http://localhost:11434/v1` |
| `LLM_MODEL` | optional for `groq` (default `llama-3.1-8b-instant`); required for `openai_compatible` | model name exactly as your provider lists it |
| `LLM_TIMEOUT_SECONDS` | no (default 15) | seconds to wait before falling back |
| `RSG_DB_PATH` | no | database location, relative to the project folder |

Real environment variables override `.env`. `.env` overrides the defaults.

## Windows PowerShell: configure without an LLM (default)

```powershell
cd C:\path\to\rsg-bi-assistant
Copy-Item .env.example .env
```

Leave `LLM_PROVIDER=none` in `.env`. The app then uses the fallback.

## Groq (supported preset)

Groq offers an OpenAI-compatible API at `https://api.groq.com/openai/v1`. `LLM_PROVIDER=groq`
uses the same adapter with that endpoint and the default model `llama-3.1-8b-instant` (listed under
Groq's production models when this was written; check console.groq.com/docs/models, because model
names change). Plans, rate limits and any free allowance are set by Groq: check them in your own
console. This project does not assume or promise any.

In your own `.env` (never in `.env.example`):

```
LLM_PROVIDER=groq
LLM_API_KEY=<paste your own key here>
```

One-request check after configuring: `python -m app.verify_llm --yes`.
Failures (wrong key, rate limit, retired model, timeout) never stop the app: it falls back to the rule-based matcher and the
response `notes` say why. **Live Groq behaviour was not verified by the author.**

## Windows PowerShell: configure with a hosted key (option A)

Edit `.env` in VS Code or Notepad:

```
LLM_PROVIDER=openai_compatible
LLM_API_KEY=<paste your key here>
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=<a model name from your provider's list>
```

Or set them only for the current PowerShell window (they disappear when the window closes):

```powershell
$env:LLM_PROVIDER = "openai_compatible"
$env:LLM_API_KEY = Read-Host "Paste your API key"
$env:LLM_BASE_URL = "https://api.openai.com/v1"
$env:LLM_MODEL = "<a model name from your provider's list>"
```

`Read-Host` keeps the key out of your command history.

## Windows PowerShell: configure with a local model (option C)

Install Ollama for Windows from its official website, start it, and download a model in a
separate PowerShell window:

```powershell
ollama pull <model-name>
```

Then in `.env`:

```
LLM_PROVIDER=openai_compatible
LLM_API_KEY=local-placeholder
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=<the same model-name you pulled>
```

## Checking which mode is active

Start the server, then open a second PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json -Depth 5
```

`"mode": "llm"` means the AI interpreter is active. `"mode": "fallback"` means the rule-based
fallback is used. If `problem` is not null, it explains why the AI interpreter is not in use.
The key is never shown.
