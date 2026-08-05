# Digital Wealth Management Assistant (ADK Take-Home)

A prototype AI assistant for a digital brokerage platform, built with Google's
Agent Development Kit (ADK). Handles general portfolio queries directly and
gates sensitive actions (fund transfers) behind a state-aware identity
verification flow.

## Project structure

```
wealth_agent/
  __init__.py       # exposes root_agent (ADK discovery convention)
  agent.py          # the Agent definition + instructions
  tools.py          # get_portfolio_balance, get_security_question,
                     # validate_security_answer, execute_transfer
  state_machine.py  # the identity-verification gate (unit-testable, ADK-independent)
  database.py       # SQLite mock DB (users, accounts) + seed data
  .env              # GOOGLE_API_KEY + NLTK_DISABLE_IMPORT_SECURITY (gitignored, create locally)
evalset/
  blocked_transfer.evalset.json     # required scenario 1: Blocked Transfer (Unauthenticated)
  successful_transfer.evalset.json  # required scenario 2: Successful Transfer (Authenticated)
  test_config.json                  # eval criteria (tool_trajectory_avg_score = 1.0)
tests/
  test_tools.py       # unit tests: DB, state machine, tool logic (no LLM/key needed)
  test_evalsets.py    # runs the two evalset scenarios via pytest (needs a live Gemini key)
  build_evalsets.py   # regenerates the evalset JSON via ADK's own pydantic models
  conftest.py         # auto-loads wealth_agent/.env before tests run
docs/
  observability_design_doc.md  # monitoring + reliability/security design (required doc)
  AI_USAGE.md                  # how AI was used to build this (required doc)
demos/
  success_demo.mov  # successful verification + transfer, via adk web
  Failed_demo.mov   # failed verification flow (3 wrong answers → locked), via adk web
  pytest.mov        # full test suite (unit tests + evalsets) via pytest
```

## Documentation

- [`docs/observability_design_doc.md`](docs/observability_design_doc.md) — production monitoring, reliability, and security design (required deliverable).
- [`docs/AI_USAGE.md`](docs/AI_USAGE.md) — how AI was used to build this project, with concrete examples (required deliverable).

## Demos

- [`demos/success_demo.mov`](demos/success_demo.mov) — successful verification + transfer, via `adk web`.
- [`demos/Failed_demo.mov`](demos/Failed_demo.mov) — failed verification flow (3 wrong answers → session locked to `FAILED`), via `adk web`.
- [`demos/pytest.mov`](demos/pytest.mov) — full test suite (unit tests + the two required live evalsets) running via `pytest`.

## Setup

1. Python 3.10+ required. Create and activate a virtual environment **in the
   project root** (this matters — see the `.env` note below):
   ```
   cd tangerine_wealth_agent
   python3 -m venv .venv
   source .venv/bin/activate      # Windows: .venv\Scripts\activate
   ```
  
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Get a free Gemini API key: https://aistudio.google.com/apikey
4. Create a new file at `wealth_agent/.env` (this exact path — same folder as
   `agent.py`, not the project root) containing exactly these two lines:
   ```
   GOOGLE_API_KEY=your-key-here
   NLTK_DISABLE_IMPORT_SECURITY=1
   ```
   - `GOOGLE_API_KEY` — the key from step 3. `adk web`, `adk eval`, and
     `pytest` (via `tests/conftest.py`) all auto-load it from here, so it
     only needs to be set once.
   - `NLTK_DISABLE_IMPORT_SECURITY=1` — required, not optional. `nltk` (a
     transitive dependency) ships a security guard that blocks imports
     resolving to inside the current working directory; since `.venv` sits
     inside the project root, this trips on legitimate pip packages and
     breaks `pytest`/`adk eval` without this line. 

   This file is gitignored — it's never committed, and you'll need to
   recreate it yourself on any fresh clone.
5. Initialize the mock database:
   ```
   python3 -m wealth_agent.database
   ```

## Running the agent

```
adk web
```
Opens ADK's local dev UI to chat with the agent directly.

Seed users:
| user_id  | security_question           | answer  | checking | savings  |
|----------|------------------------------|---------|----------|----------|
| user_001 | What city were you born in? | Toronto | 2500.00  | 10000.00 |
| user_002 | What is your pet's name?    | Biscuit | 800.00   | 3200.00  |

## Running the tests

```
pytest tests/ -v
```
Runs everything: deterministic unit tests (instant, no API key) plus the two
required live trajectory evals (needs `GOOGLE_API_KEY`, real Gemini calls).
To run just the free/instant part: `pytest tests/test_tools.py -v`.

Equivalent CLI form for the evalsets:
```
adk eval wealth_agent evalset/blocked_transfer.evalset.json --config_file_path evalset/test_config.json
adk eval wealth_agent evalset/successful_transfer.evalset.json --config_file_path evalset/test_config.json
```

Gemini free-tier daily quotas are low (as little as 20 requests/day per
model) — a `429` mid-run is quota, not a bug. 