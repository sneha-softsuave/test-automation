# Test Automation System - Flow Documentation

> **Two Modes:**
> - **Agent Mode** — Run functional tests from Excel data using a multi-agent AI system
> - **Record Mode** — Record browser interactions via natural language to generate test cases

---

## Table of Contents
1. [Agent Mode — Functional Test Executor](#1-agent-mode--functional-test-executor)
2. [Record Mode — Generate Test Case](#2-record-mode--generate-test-case)
3. [Shared: Selector Fallback Chain](#3-shared-selector-fallback-chain)
4. [Where AI Is Used](#4-where-ai-is-used)
5. [Configuration Quick Reference](#5-configuration-quick-reference)

---

## 1. Agent Mode — Functional Test Executor

### How It Starts

```
User uploads Excel file in UI
  → Selects LLM provider (Groq / OpenAI / Anthropic)
  → Clicks "Run Tests"
  → Frontend calls: POST /api/v1/deep-agent/run-multi-agent
```

**What's passed in:** raw Excel data, session_id, llm_provider, headless, timeout, max_retries

---

### Big Picture Flow

```
Excel Data
    │
    ▼
┌─────────────┐
│ PARSER AGENT│  ← AI: converts raw rows → structured test steps
└─────────────┘
    │ Parsed test suite (steps + selectors + test data + assertions)
    ▼
┌──────────────┐
│EXECUTOR AGENT│  ← Playwright browser runs each step (no AI here)
└──────────────┘
    │ Results (passed/failed per step)
    ▼
┌───────────────┐
│VALIDATOR AGENT│  ← Pure logic: should we retry or report?
└───────────────┘
    │
    ├─── All passed ──────────────────────────┐
    │                                         ▼
    ├─── Retryable + retries left ──► Error Recovery → back to Executor
    │
    └─── Failed / no retries left ───────────┐
                                             ▼
                                    ┌───────────────┐
                                    │REPORTER AGENT │  ← AI: generate HTML report + Playwright script
                                    └───────────────┘
                                             │
                                             ▼
                                        Final Result
```

**Supervisor LLM** sits above all agents, deciding which agent to call next. It uses the same LLM provider as configured.

---

### Agent Details

| Agent | File | Uses AI? | What It Does |
|-------|------|----------|--------------|
| **Supervisor** | `multi_agent_orchestrator.py` | Yes | Orchestrates flow, routes between agents |
| **ParserAgent** | `sub_agents/parser_agent.py` | Yes | Converts raw test data → structured steps with selectors |
| **ExecutorAgent** | `sub_agents/executor_agent.py` | No | Runs Playwright browser, executes steps |
| **ValidatorAgent** | `sub_agents/validator_agent.py` | No | Checks pass/fail, decides retry or done |
| **ReporterAgent** | `sub_agents/reporter_agent.py` | Yes | Generates HTML report and runnable Playwright script |

---

### Execution: Step-by-Step Detail

The **ExecutorAgent** calls `enhanced_executor.py` which runs each step in a subprocess. Here's what happens for a single step:

```
Step begins
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│                    RETRY LOOP (max 4 attempts)               │
│                                                             │
│  Attempt 0 (first try)                                      │
│  ├── Use selectors from parser (suggested_selectors[])      │
│  ├── Timeout: base (default 30s)                            │
│  └── If fails → go to Attempt 1                             │
│                                                             │
│  Attempt 1                                                  │
│  ├── Generate heuristic alternatives:                       │
│  │     • Text variations (lower/upper/title case)           │
│  │     • Role-based: get_by_role('button', name='...')      │
│  │     • Attribute: [aria-label*="..."], [title*="..."]     │
│  │     • Data attrs: [data-testid="..."], [data-cy="..."]   │
│  ├── Dynamic page JS scan for matching elements             │
│  ├── Timeout: base × 1.3                                    │
│  └── If fails → go to Attempt 2                             │
│                                                             │
│  Attempt 2                                                  │
│  ├── More alternative selectors (same generation strategy)  │
│  ├── Timeout: base × 1.3²                                   │
│  └── If fails → go to Attempt 3                             │
│                                                             │
│  Attempt 3 (final DOM attempt)                              │
│  ├── Action-specific fallbacks:                             │
│  │     Fill: input:visible:first, textarea:visible:first    │
│  │     Click: button:visible:first, a:visible:first         │
│  ├── 🤖 LIVE SELECTOR RESCUE (LLM)                          │
│  │     → Scrape live DOM (inputs, buttons, links)           │
│  │     → Send to LLM: "suggest Playwright selectors"        │
│  │     → LLM returns up to 3 selector strings               │
│  │     → Try them first before action-specific fallbacks    │
│  ├── Timeout: base × 1.3³                                   │
│  └── If still fails → IR Vision Rescue                      │
│                                                             │
│  🖼️ IR VISION RESCUE (only for fill/click/select actions)   │
│  ├── Enabled only if IMAGE_ANALYSIS_ENABLED=True            │
│  ├── Capture screenshot as base64 PNG                       │
│  ├── Send to vision model with instruction + failed selector │
│  ├── Vision model returns up to 3 element suggestions       │
│  ├── Each suggestion: selector + widget_type + interaction  │
│  └── Try each suggestion → if any succeeds → PASSED        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
    │
    ├── Any attempt succeeded → Step: PASSED ✅
    │
    ├── User clicked "Next" during wait → Step: PASSED ✅
    ├── User clicked "Skip" during wait → Step: SKIPPED ⏭️
    │
    └── All attempts failed → Step: FAILED ❌
         (execution continues to next step — doesn't stop the test)
```

---

### Test-Level Retry (Validator Logic)

After all steps run, the ValidatorAgent checks:

```
Are there any failures?
    │
    ├── No → Report PASSED ✅
    │
    └── Yes → Are the failures "retryable"?
                │
                ├── Retryable patterns (yes):
                │     timeout, timed out, element not found,
                │     network error, page crashed, not visible
                │
                └── Non-retryable patterns:
                      assertion failed, expected X got Y,
                      missing test data, configuration error
                          │
                          ├── Retryable + retries left → Re-run all tests
                          │     (up to max_retries, default 2 extra runs)
                          │
                          └── Non-retryable or exhausted → Report FAILED ❌
```

---

### Real-Time Updates (SSE Events)

The frontend connects to `/api/v1/sse/{session_id}` and receives live events:

| Event | When |
|-------|------|
| `agent_phase` | Phase changes (parsing → executing → validating) |
| `execution_started` | Tests begin |
| `test_started` | Each test case starts |
| `step_started` | Each step begins |
| `screenshot` | Live browser screenshot (base64 PNG) |
| `step_retry` | Step failed, trying alternative selectors |
| `step_retry_exhausted` | Step gave up after all retries |
| `step_completed` | Step finished (PASSED / FAILED / SKIPPED) |
| `test_completed` | Test case finished |
| `execution_completed` | All tests done |
| `deep_agent_complete` | Full workflow finished with results |

---

### Output

- **Response JSON:** status, summary (total/passed/failed), step-by-step results
- **HTML Report:** per-test results, screenshots, retry details
- **Playwright Script:** runnable Python/pytest script for CI/CD

---

## 2. Record Mode — Generate Test Case

### How It Starts

```
User enters target URL in UI
  → Clicks "Start Recording"
  → Frontend calls: POST /recorder/start
  → Browser opens at the URL
  → User starts issuing natural language commands
```

---

### Big Picture Flow

```
Start Recording
    │
    ▼
Browser launched (Playwright Chromium)
    │
    ▼
┌──────────────────────────────────────────┐
│        RECORDING LOOP                    │  ← Repeats for each command
│                                          │
│  User types: "Login with admin@test.com  │
│               and password secret123"    │
│       │                                  │
│       ▼                                  │
│  Scrape live page context:               │
│    • All visible inputs (label/placeholder/name) │
│    • All buttons (text/role)             │
│    • All links, dropdowns, tables        │
│    • Pre-compute suggested selectors     │
│       │                                  │
│       ▼                                  │
│  🤖 RECORDER AGENT (LLM)                 │
│    • Receives: command + page context    │
│    • Returns: JSON array of actions      │
│       [                                  │
│         {fill, selector, value},         │
│         {fill, selector, value},         │
│         {click, selector}                │
│       ]                                  │
│       │                                  │
│       ▼                                  │
│  Execute each action on live browser     │
│    └── If selector fails:                │
│         → Try selector fallbacks         │
│         → Live Selector Rescue (LLM)     │
│         → IR Vision Rescue (if enabled)  │
│       │                                  │
│  Capture screenshot after each action    │
│  Append step to session._current_steps[] │
│       │                                  │
│  Wait for next command ──────────────────┘
│
└──────────────────────────────────────────┘
    │
    ▼
User clicks "Complete" or "Export"
    │
    ▼
POST /recorder/complete
    │
    ▼
Finalize test case → Build EnhancedTestSuite JSON
    │
    ▼
Export: JSON file (or display in UI for import into Agent Mode)
```

---

### Recorder Agent (LLM) Detail

**File:** `app/agents/recorder_agent.py`

The Recorder Agent is the AI brain that converts your words into Playwright actions.

**Input to LLM:**
```
COMMAND: "Click the Submit button"

PAGE CONTEXT:
  Inputs: [Email (label), Password (label), Username (placeholder)]
  Buttons: [Submit (suggested: page.get_by_role('button', name='Submit')),
            Cancel (suggested: page.get_by_role('button', name='Cancel'))]
  Links: [Forgot Password, Register]
```

**Output from LLM:**
```json
[
  {
    "action_type": "click",
    "selector": "page.get_by_role('button', name='Submit')",
    "value": "",
    "instruction": "Click the Submit button",
    "element_name": "Submit",
    "element_type": "button"
  }
]
```

**Supported Action Types:**

| Category | Actions |
|----------|---------|
| Navigation | `goto`, `back`, `forward`, `reload` |
| Mouse | `click`, `double_click`, `right_click`, `hover` |
| Form | `fill`, `type`, `select`, `check`, `uncheck`, `clear`, `press` |
| Assertions | `assert_visible`, `assert_text`, `assert_value`, `assert_url`, `assert_table`, and more |
| Other | `wait`, `screenshot`, `upload`, `drag`, `scroll` |

**LLM Selector Priority (for suggestions):**
1. `page.get_by_label('...')` — best for form fields
2. `page.get_by_placeholder('...')`
3. `page.get_by_role('button', name='...')` — best for buttons
4. `page.get_by_text('...', exact=True)`
5. `page.locator('[aria-label="..."]')` or attribute selector
6. `.class-name` — last resort

---

### Why a Dedicated Background Thread?

The recorder uses Playwright's sync API inside an async FastAPI server. These conflict — Playwright sync can't run in asyncio's thread pool.

**Solution:** Each recording session gets its own dedicated background thread with a job queue. All Playwright calls are marshaled through `session.run_in_pw_thread(fn)`. This is invisible to the user but critical to stability.

---

### Session State

```
RecorderSession
├── session_id
├── base_url
├── _playwright_thread (background thread, persistent)
├── _browser / _context / _page (Playwright objects)
├── _current_steps[] (steps being recorded right now)
├── test_cases[] (finalized test cases)
└── final_storage_state (cookies/localStorage for auth continuity)
```

**Auth Continuity:** Browser session (cookies, localStorage) persists across all commands in a session. Log in once → all subsequent steps run authenticated.

---

### Context Summary for Multi-Case Recording

When you record multiple test cases in one session, the LLM receives a summary of all previous cases:

```
Previous context:
  Test Case 1 — Login:
    • Navigate to /login
    • Fill email [email=admin@test.com]
    • Fill password [password=secret]
    • Click Login button

  Test Case 2 — Create Project:
    • Click "New Project"
    • Fill project name [name=Demo Project]
```

This lets the LLM understand references like: *"verify the project I just created is visible"*.

---

### Generated Test Suite Format

```json
{
  "project": "My Application",
  "base_url": "https://example.com",
  "test_cases": [
    {
      "id": "TC_001",
      "name": "Login Test",
      "steps": [
        {
          "step_number": 1,
          "instruction": "Navigate to application",
          "action": { "type": "goto", "url": "https://example.com/login" },
          "selector_hints": {},
          "test_data": {}
        },
        {
          "step_number": 2,
          "instruction": "Fill email field with {Email}",
          "action": { "type": "fill" },
          "selector_hints": {
            "suggested_selectors": ["page.get_by_label('Email')"],
            "element_name": "Email",
            "element_type": "input"
          },
          "test_data": { "value": "admin@test.com" }
        }
      ]
    }
  ]
}
```

Note: Literal values are replaced with `{Email}`, `{Password}` references — making the test data-driven.

---

## 3. Shared: Selector Fallback Chain

Both modes use the same three-tier fallback system when a selector doesn't match.

```
Tier 1 — Heuristic Alternatives (generated automatically on retry)
    Text variations: lowercase, UPPERCASE, Title Case
    Role patterns:   get_by_role('button', name='Submit')
    Aria attributes: [aria-label*="submit"], [title*="submit"]
    Data test attrs: [data-testid="submit"], [data-cy="submit"]
         │
         ▼ (still failing after all retries)

Tier 2 — 🤖 Live Selector Rescue (LLM, text-based)
    1. Scrape live DOM:
         inputs: id, name, placeholder, aria-label, label-text
         buttons: text, role, aria-label
         links: text, href
    2. Ask LLM (same provider as configured):
         "Here's the live page. Find the selector for: [instruction]"
    3. LLM returns JSON array of up to 3 selector strings
    4. Try each one
         │
         ▼ (still failing)

Tier 3 — 🖼️ IR Vision Rescue (Vision AI, image-based)
    Only triggered if: IMAGE_ANALYSIS_ENABLED=True in .env
    Only for actions: fill, click, select (not goto/assert/screenshot)

    1. Capture screenshot as base64 PNG
    2. Send to vision model with:
         - The instruction ("Click Submit button")
         - The failed selector
         - The error message
    3. Vision model looks at the actual rendered page image
    4. Returns up to 3 suggestions:
         {
           "selector": "page.get_by_role('button', name='Submit')",
           "widget_type": "button",
           "interaction": "click",
           "reasoning": "I can see a blue Submit button at bottom of form"
         }
    5. Try each suggestion → success = PASSED ✅
```

**IR Vision Providers:**

| Setting | Provider | Model |
|---------|----------|-------|
| `VISION_PROVIDER=groq` | Groq | `meta-llama/llama-4-scout-17b-16e-instruct` |
| `VISION_PROVIDER=openai` | OpenAI | `gpt-4o-mini` |

> IR Vision has a **daily usage counter** that resets at midnight (tracks API costs).

---

## 4. Where AI Is Used

### Agent Mode

| Point | What Happens | AI Provider | Model |
|-------|-------------|-------------|-------|
| **Parse step** | Raw Excel rows → structured steps + selectors + assertions | Configured | Configured |
| **Supervisor routing** | Decides which agent to call next | Configured | Configured |
| **Live Selector Rescue** | Scrapes DOM, asks LLM to suggest working selectors | Configured | Configured |
| **IR Vision Rescue** | Screenshot → vision model → element location | Vision provider | Vision model |
| **Report generation** | Creates HTML report and standalone Playwright script | Configured | Configured |

### Record Mode

| Point | What Happens | AI Provider | Model |
|-------|-------------|-------------|-------|
| **Command parsing** | Natural language → Playwright action JSON | Configured | Configured |
| **Live Selector Rescue** | Same as Agent Mode | Configured | Configured |
| **IR Vision Rescue** | Same as Agent Mode | Vision provider | Vision model |

### No AI Used

| Component | Why No AI |
|-----------|-----------|
| **ExecutorAgent** | Pure Playwright execution — speed matters, deterministic |
| **ValidatorAgent** | Pure logic — pattern matching on error strings |
| **Browser thread** | Pure Playwright API calls |

---

## 5. Configuration Quick Reference

### LLM Providers (set in `.env`)

```env
DEFAULT_LLM_PROVIDER=groq          # groq | openai | anthropic

GROQ_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
```

### Default Models (in `app/core/config.py`)

| Provider | Default Model |
|----------|--------------|
| Groq | `llama-3.1-8b-instant` |
| OpenAI | `gpt-4o-mini` |
| Anthropic | `claude-sonnet-4-5-20250929` |

### Vision / IR Settings

```env
IMAGE_ANALYSIS_ENABLED=false       # Set to true to enable IR vision rescue
VISION_PROVIDER=groq               # groq | openai
GROQ_VISION_API_KEY=your_key       # Can reuse GROQ_API_KEY if same key
```

### Execution Tuning

```env
STEP_MAX_RETRIES=3                 # 3 retries = 4 total attempts per step
RETRY_TIMEOUT_MULTIPLIER=1.3       # Each retry: timeout × 1.3
DEFAULT_ACTION_TIMEOUT=30000       # 30s per action (ms)
WAIT_TIMEOUT=10000                 # 10s for wait operations (ms)
NAVIGATION_TIMEOUT=30000           # 30s for page navigation (ms)
```

### Provider Selection Priority

```
1. User selects in UI dropdown  (highest priority)
2. API query param: ?llm_provider=anthropic
3. DEFAULT_LLM_PROVIDER from .env
4. Groq (fallback)              (lowest priority)
```

---

## Key Files Reference

```
app/
├── api/routes/
│   ├── agent_chat.py                → Chat UI: intent detection + command dispatch
│   ├── deep_agent.py                → Agent Mode API endpoints + step control
│   └── recorder.py                  → Record Mode API endpoints
│
├── agents/
│   ├── deep_agent/
│   │   ├── multi_agent_orchestrator.py  → Supervisor + full orchestration loop
│   │   └── sub_agents/
│   │       ├── parser_agent.py          → AI: parse raw data
│   │       ├── executor_agent.py        → Run Playwright tests (no AI)
│   │       ├── validator_agent.py       → Check results (no AI)
│   │       └── reporter_agent.py        → AI: generate report
│   │
│   ├── enhanced_json_parser.py      → LLM prompt for parsing
│   ├── image_analyzer.py            → Vision AI: screenshot → selector
│   ├── recorder_agent.py            → LLM: natural language → Playwright actions
│   └── base_agent.py                → Base class, LLM provider enum
│
├── tools/
│   └── enhanced_executor.py         → Playwright execution + all retry/fallback logic
│
├── services/
│   └── recorder_session_manager.py  → Browser thread, session lifecycle
│
└── core/
    ├── config.py                    → All settings: models, timeouts, API keys
    └── sse_manager.py               → Real-time event broadcasting
```
