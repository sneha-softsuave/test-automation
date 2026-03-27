"""
TestCaseGeneratorAgent
Generates an EnhancedTestSuite from a crawled page structure + user intent.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.agents.base_agent import BaseAgent, LLMProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


def _trim_history(history: list, max_turns: int = 8, max_chars_per_msg: int = 600) -> list:
    """Cap history to last max_turns, truncate long messages."""
    trimmed = history[-max_turns:]
    return [
        {"role": m["role"], "content": m["content"][:max_chars_per_msg]}
        for m in trimmed
    ]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Compact page summary (token-friendly, used for LLM intro/confirm context)
# ---------------------------------------------------------------------------

def compact_page_elements(page_structure: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reduce full DOM extraction to a comprehensive but token-friendly dict.

    Captures all element types present on any kind of website:
    - Inputs (text, email, password, search, checkbox, radio, date, file, number, tel, textarea, select)
    - Buttons (native + role=button/menuitem/tab custom components)
    - Headings (h1-h6 with tag level)
    - Links (navigation + action links, deduplicated)
    - Forms (structure context)
    - Elements with data-testid (high-value for reliable selectors)

    Strips raw selector variants (byId, byClass, xpath, etc.) to stay token-friendly.
    """
    def _clean(val: Any) -> Optional[str]:
        if not val:
            return None
        s = str(val).strip()
        return s or None

    def _pick_input(el: Dict) -> Dict:
        d: Dict[str, Any] = {}
        t = _clean(el.get("type"))
        if t and t != "hidden":
            d["type"] = t
        for field, key in [("placeholder", "placeholder"), ("name", "name"),
                            ("label", "ariaLabel"), ("id", "id"), ("testId", "dataTestId"),
                            ("role", "role")]:
            v = _clean(el.get(key))
            if v:
                d[field] = v[:80]
        return d

    def _pick_button(el: Dict) -> Dict:
        d: Dict[str, Any] = {}
        text = _clean(el.get("text"))
        if text and len(text) <= 80:
            d["text"] = text
        for field, key in [("label", "ariaLabel"), ("id", "id"),
                            ("testId", "dataTestId"), ("type", "type"), ("role", "role")]:
            v = _clean(el.get(key))
            if v:
                d[field] = v[:80]
        return d

    raw_inputs       = page_structure.get("inputs", [])
    raw_buttons      = page_structure.get("buttons", [])
    raw_headings     = page_structure.get("headings", [])
    raw_links        = page_structure.get("links", [])
    raw_forms        = page_structure.get("forms", [])
    raw_interactive  = page_structure.get("interactive", [])
    raw_aria_widgets = page_structure.get("aria_widgets", [])
    raw_testid       = page_structure.get("elements_with_testid", [])

    # ── Inputs: all types, no hidden, deduplicated ────────────────────────
    inputs: List[Dict] = []
    seen_inputs: set = set()
    for el in raw_inputs:
        if el.get("type") == "hidden":
            continue
        d = _pick_input(el)
        if not d:
            continue
        key = (el.get("type"), el.get("placeholder"), el.get("name"), el.get("ariaLabel"))
        if key in seen_inputs:
            continue
        seen_inputs.add(key)
        inputs.append(d)
        if len(inputs) >= 30:
            break

    # Also capture <select> and <textarea> from interactive (they're not in raw_inputs)
    for el in raw_interactive:
        tag = el.get("tag", "")
        if tag in ("select", "textarea"):
            if el.get("type") == "hidden":
                continue
            d = _pick_input(el)
            if d:
                d["tag"] = tag
                inputs.append(d)

    # ── Buttons: native + role-based custom components ────────────────────
    buttons: List[Dict] = []
    seen_buttons: set = set()

    for el in raw_buttons:
        d = _pick_button(el)
        label = d.get("text") or d.get("label")
        if not label:
            continue
        if label in seen_buttons:
            continue
        seen_buttons.add(label)
        buttons.append(d)
        if len(buttons) >= 25:
            break

    # Capture divs/spans acting as buttons (role=button/menuitem/tab/option)
    for el in raw_interactive:
        if el.get("role") in ("button", "menuitem", "tab", "option", "link") \
                and el.get("tag") not in ("button", "input", "a"):
            d = _pick_button(el)
            label = d.get("text") or d.get("label")
            if label and label not in seen_buttons:
                seen_buttons.add(label)
                buttons.append(d)
                if len(buttons) >= 25:
                    break

    # ── Headings: include tag level (h1 vs h2 vs h3) ─────────────────────
    headings: List[Dict] = []
    for el in raw_headings:
        text = _clean(el.get("text"))
        if text and len(text) > 1:
            entry: Dict[str, Any] = {"tag": el.get("tag", "h?"), "text": text[:120]}
            if el.get("id"):
                entry["id"] = el["id"]
            headings.append(entry)
        if len(headings) >= 12:
            break

    # ── Links: navigation + actions, deduplicated, skip javascript: ───────
    links: List[Dict] = []
    seen_links: set = set()
    for el in raw_links:
        text = _clean(el.get("text"))
        href = _clean(el.get("href"))
        if not text or len(text) < 2:
            continue
        if text in seen_links:
            continue
        seen_links.add(text)
        entry = {"text": text[:80]}
        if href and not href.startswith("javascript:"):
            entry["href"] = href[:120]
        if el.get("ariaLabel"):
            entry["label"] = el["ariaLabel"][:60]
        links.append(entry)
        if len(links) >= 25:
            break

    # ── Forms: structure context (id/name useful for multi-form pages) ────
    forms: List[Dict] = []
    for el in raw_forms:
        entry = {}
        for f in ("id", "name", "role"):
            v = _clean(el.get(f))
            if v:
                entry[f] = v
        if entry:
            forms.append(entry)
        if len(forms) >= 6:
            break

    # ── data-testid elements: high-value anchors for reliable selectors ───
    testid_elements: List[Dict] = []
    seen_testids: set = set()
    for el in raw_testid:
        tid = _clean(el.get("dataTestId"))
        if not tid or tid in seen_testids:
            continue
        seen_testids.add(tid)
        entry = {"testId": tid, "tag": el.get("tag", "")}
        text = _clean(el.get("text"))
        if text and len(text) <= 80:
            entry["text"] = text
        if el.get("role"):
            entry["role"] = el["role"]
        testid_elements.append(entry)
        if len(testid_elements) >= 20:
            break

    # ── ARIA widgets: switch, checkbox, combobox, tab, slider, etc. ──────
    # These are custom interactive elements (divs/spans) with ARIA roles.
    # They are never captured in inputs/buttons and are easily missed.
    aria_widgets: List[Dict] = []
    seen_widgets: set = set()
    for el in raw_aria_widgets:
        role = _clean(el.get("role"))
        if not role:
            continue
        entry: Dict[str, Any] = {"role": role}
        text = _clean(el.get("text"))
        if text and len(text) <= 80:
            entry["text"] = text
        for field, key in [("label", "ariaLabel"), ("id", "id"), ("testId", "dataTestId")]:
            v = _clean(el.get(key))
            if v:
                entry[field] = v[:80]
        # Preserve ARIA state (e.g. aria-checked="false" for a switch)
        for state_key in ("ariaChecked", "ariaExpanded", "ariaSelected"):
            val = el.get(state_key)
            if val is not None:
                entry[state_key] = val
        dedup_key = (role, entry.get("text"), entry.get("label"), entry.get("id"))
        if dedup_key in seen_widgets:
            continue
        seen_widgets.add(dedup_key)
        aria_widgets.append(entry)
        if len(aria_widgets) >= 20:
            break

    # ── Assemble result ───────────────────────────────────────────────────
    result: Dict[str, Any] = {
        "title":   page_structure.get("title", ""),
        "url":     page_structure.get("url", ""),
        "inputs":  inputs,
        "buttons": buttons,
        "headings": headings,
        "links":   links,
    }
    if forms:
        result["forms"] = forms
    if aria_widgets:
        result["aria_widgets"] = aria_widgets
    if testid_elements:
        result["testid_elements"] = testid_elements

    # ── Custom div-based dropdowns (label + adjacent clickable div) ───────
    raw_custom_dropdowns = page_structure.get("custom_dropdowns", [])
    custom_dropdowns = []
    for cd in raw_custom_dropdowns[:10]:
        label = (cd.get("label") or "").strip()
        if not label:
            continue
        entry: Dict[str, Any] = {
            "label": label,
            "currentValue": (cd.get("currentValue") or "").strip(),
        }
        if cd.get("id"):
            entry["id"] = cd["id"]
        custom_dropdowns.append(entry)
    if custom_dropdowns:
        result["custom_dropdowns"] = custom_dropdowns

    return result


# ---------------------------------------------------------------------------
# Intent classifier prompt
# ---------------------------------------------------------------------------

INTENT_CLASSIFIER_PROMPT = """You are an intent classifier for a test automation chatbot.

Classify the USER MESSAGE into ONE intent:
execute | edit | informational | approve | generate | clarify

CONTEXT
Page: {page_url}
Test Cases: {test_cases_list}
Recent Conversation: {history}
User Message: "{user_message}"

INTENTS

EXECUTE (highest priority)
- Intent: User wants to run tests in a browser
- Indicators: phrases meaning "run this test" or "start executing tests", with numbers, test names, or "all"
- Examples: "run test 1", "execute all tests", "start login test", "play TC_003", "go ahead and run it"

EDIT
- Intent: User wants to modify existing test cases (steps, selectors, names, expected results)
- Indicators: phrases meaning change/update a test
- Examples: "update step 2 to click submit", "rename test case", "change expected result"
⚠ If Test Cases list is empty AND the message contains data values (dates, names, descriptions)
  or uses "enter", "fill", "input", "type" — classify as GENERATE, not EDIT.
  Edit requires existing test cases to modify.

INFORMATIONAL
- Intent: User asks questions or wants info; no execution
- Indicators: words/phrases like "what", "how", "which", "show me", "list", "explain", "describe"
- Examples: "show me step 3", "how many tests exist?", "what test cases are available?"

APPROVE
- Intent: User wants to save/confirm results to Excel
- Indicators: phrases meaning approve, confirm, export, save executed steps
- Modes:
    - individual (default)
    - group → combine a range of steps in one row
    - multi_group → multiple ranges, each in a separate row
    - list_unadded → list steps not yet added
- Examples: "approve step 1", "add steps 1 to 5 in one row", "export all results"
⚠ Special case: "click approve button" = EXECUTE

GENERATE
- Intent: User wants to create new test cases
- Indicators: phrases meaning generate, add, write, or create tests
- Examples: "generate tests for checkout", "add a test for password reset", "write a signup test"

CLARIFY (default fallback)
- Intent: Message is ambiguous or unclear
- Model should guess the most likely intent and ask for confirmation if needed

PRIORITY
0. execute keyword + (number/all/name) → EXECUTE
1. any clear run action → EXECUTE
2. approve/export → APPROVE
3. question → INFORMATIONAL
3.5. "enter/fill/input/type" + Test Cases list is empty → GENERATE
4. modify → EDIT
5. create → GENERATE
6. else → CLARIFY

OUTPUT
Return ONLY valid JSON:

{{
  "intent": "execute|edit|informational|approve|generate|clarify",
  "confidence": 0.0,
  "reasoning": "one short sentence",
  "clarify_message": "only if intent=clarify, suggest likely intent and options",
  "metadata": {{
    "execute_targets": null,
    "approve_targets": null,
    "approve_mode": null,
    "approve_range": null,
    "approve_ranges": null
  }}
}}

Notes:
- Prioritize semantic understanding; do NOT rely on exact keywords alone
- Use examples to infer intent even with phrasing variations
- Stop at first match according to PRIORITY rules"""


# Conversational-brain version of the classifier — used by classify_intent()
# History + user message are passed as real messages, not text injection.
INTENT_CLASSIFIER_SYSTEM = """You are a conversational intent classifier for a test automation chatbot.

You will receive a conversation between a user and the assistant. Classify the LATEST user message.

CURRENT PAGE: {page_url}
EXISTING TEST CASES:
{test_cases_list}

INTENTS

EXECUTE (highest priority)
- User wants to run/play tests in a browser
- Examples: "run test 1", "execute all", "play TC_003", "go ahead and run it"

EDIT
- User wants to modify existing test cases
- Examples: "update step 2", "rename test case", "change the selector"
⚠ If test cases list is empty AND message has data values or uses "enter/fill/input/type" → GENERATE

INFORMATIONAL
- User asks questions about the page or test cases
- Examples: "show me step 3", "how many tests?", "what selectors are used?"

APPROVE
- User wants to save/export results to Excel
- Modes: individual | group | multi_group | list_unadded
- Examples: "approve step 1", "add steps 1 to 5 in one row", "export all results"
⚠ "click approve button" = EXECUTE

GENERATE
- User wants to create new test cases (including filling forms with specific data)
- Examples: "generate a login test", "write a signup test", "test the form with name=John date=2025-01-01"
- Also: "enter the below value", "fill the form with", "test with this data" → GENERATE

CLARIFY
- Message is ambiguous — guess most likely intent and ask for confirmation

PRIORITY
0. execute keyword + number/all → EXECUTE
1. clear run action → EXECUTE
2. approve/export → APPROVE
3. question → INFORMATIONAL
3.5. enter/fill/input/type + no existing tests → GENERATE
4. modify existing → EDIT
5. create/generate → GENERATE
6. else → CLARIFY

OUTPUT — return ONLY this JSON, no extra text:
{{
  "intent": "execute|edit|informational|approve|generate|clarify",
  "confidence": 0.95,
  "reasoning": "one short sentence",
  "clarify_message": "only if intent=clarify",
  "metadata": {{
    "execute_targets": null,
    "approve_targets": null,
    "approve_mode": null,
    "approve_range": null,
    "approve_ranges": null,
    "form_data": {{}}
  }}
}}

form_data: extract any specific field values the user wants to fill (dates, names, descriptions,
locations, IDs). Leave as {{}} if no specific data values are present.
Examples: {{"Date": "03/08/2027", "Employee Name": "Vijay Kumar", "Description": "ankle sprain"}}"""


# ---------------------------------------------------------------------------
# Intro / confirm prompts
# ---------------------------------------------------------------------------

INFORMATIONAL_PROMPT = """You are an AI test assistant embedded in a test case generation tool.

The user has asked an INFORMATIONAL question about the web page or testing — they are NOT asking you to generate test cases.

PAGE SUMMARY (JSON):
{compact_json}

USER QUESTION:
{question}

Answer the question directly and helpfully. If relevant, reference specific elements visible on the page.
Do NOT generate test cases. Do NOT output JSON.
Use 1-2 suitable professional emojis where natural — keep it subtle and professional.
Return ONLY the Markdown answer."""


EDIT_PROMPT = """You are an AI test assistant. The user wants to make a specific edit to an existing test suite.

CURRENT TEST SUITE (JSON):
{suite_json}

USER EDIT INSTRUCTION:
{instruction}

Rules:
- Apply ONLY the change requested. Do not add, remove, or regenerate test cases unless explicitly asked.
- Return the COMPLETE updated test suite as valid JSON in the exact same schema.
- If the instruction is ambiguous, make the most reasonable interpretation.
- Do NOT include any explanation text outside the JSON.

Return ONLY the updated JSON starting with {{ and ending with }}."""


PAGE_INTRO_PROMPT = """You are an AI test assistant. A web page has been scraped and its key elements are summarised below.

PAGE SUMMARY (JSON):
{compact_json}

Write 2-3 sentences in plain, friendly English:
1. Describe what this page is and what the user can do on it.
2. Mention ALL key interactive elements you found: inputs, buttons, links, and any ARIA widgets such as toggles (role=switch), checkboxes, tabs, dropdowns (role=combobox), or sliders — include their labels if available (e.g. "Remember me toggle", "Dark mode switch").
3. End by asking the user what they would like to test.

Tone: concise, conversational, helpful.
Use 1-2 suitable professional emojis to make the message friendly — never overdo it.
Use Markdown formatting. Return ONLY the message text. No JSON. No preamble."""

PAGE_CONFIRM_PROMPT = """You are an AI test assistant. You just generated the following test suite.

TEST SUITE SUMMARY:
- Total test cases: {tc_count}
- Test case names: {tc_names}

Write 1-2 sentences (max 30 words) confirming what you created.
Use **bold** for test case names. You may use a short bullet list if more than 3 cases.
Start the message with a suitable professional emoji.
Example: "✅ I've created 3 test cases: **Valid Login**, **Invalid Credentials**, and **Forgot Password**."
Return ONLY the sentence or list. Use Markdown formatting. No JSON. No extra text."""


GENERATOR_PROMPT = """You are an expert Playwright test case generator.

You will receive:
1. PAGE STRUCTURE — real elements extracted from a live web page (inputs, buttons, headings, links)
2. USER INTENT — what the user wants to test (in plain English)
3. Optional context: app name, base URL, credentials

Your job: generate a complete, executable EnhancedTestSuite JSON using ONLY the real selectors
from the page structure. Do NOT invent selectors that are not in the page data.

─────────────────────────────────────────────────────────────
PAGE INFORMATION
─────────────────────────────────────────────────────────────
URL: {url}
Page Title: {title}

INPUTS ({input_count}):
{inputs_text}

CUSTOM DROPDOWNS ({custom_dropdown_count}):
{custom_dropdowns_text}

BUTTONS ({button_count}):
{buttons_text}

HEADINGS ({heading_count}):
{headings_text}

LINKS ({link_count}):
{links_text}

─────────────────────────────────────────────────────────────
USER INTENT
─────────────────────────────────────────────────────────────
{intent}

─────────────────────────────────────────────────────────────
OPTIONAL CONTEXT
─────────────────────────────────────────────────────────────
App Name: {app_name}
Base URL: {base_url}
Test Email: {test_email}
Test Password: {test_password}

─────────────────────────────────────────────────────────────
INLINE TEST DATA EXTRACTION
─────────────────────────────────────────────────────────────
The USER INTENT may contain specific data values the user wants to enter into a form.
If EXTRACTED TEST DATA is present below, use those values directly in fill steps.

Extract and USE any of the following from the user message or EXTRACTED TEST DATA:
- Dates / times       → fill date/time fields with that value
- Names / people      → fill name fields (reporter, employee, assignee, etc.)
- Descriptions / text → fill description, notes, details, or comments fields
- Locations / places  → fill location fields
- Numbers / IDs       → fill corresponding numeric or ID fields

RULES:
- When the user provides specific data AND the page has matching input fields,
  generate fill steps for EACH data item — not just navigation clicks.
- Put extracted values in the step's test_data (key = field label, value = the data).
- If the form appears after a button click (e.g. "Report EmergeX Case"), generate:
    1. click to open the form
    2. fill each field with the provided data
    3. assert/verify success
- If an input field for a value is NOT in the page structure, still generate the fill
  step using a label-based selector: page.get_by_label('X') or page.get_by_placeholder('X').
  Do NOT skip data the user explicitly provided.

─────────────────────────────────────────────────────────────
FEASIBILITY & SELECTION RULES
─────────────────────────────────────────────────────────────
Only generate test cases that are fully executable using the given PAGE STRUCTURE.
Every step must map to a real element or valid page state.
Do not invent UI elements, selectors, flows, or pages.
Skip any part of the USER INTENT that is not supported by the page.
Generate only high-value, realistic scenarios.
Include positive/negative cases only if they are possible with existing elements.

─────────────────────────────────────────────────────────────
ELEMENT TYPE PRIORITY RULES — MANDATORY
─────────────────────────────────────────────────────────────
When the user explicitly names an element type, you MUST honor it. The user's stated type
overrides any text match you find in the page structure.

  DROPDOWN / SELECT / COMBOBOX
  - If the user says "dropdown", "select [element]", "combo box", or "combobox":
      • action_type MUST be "select" (for native <select>) or "click" on a combobox trigger
      • element_type MUST be "dropdown" or "select"
      • Prefer selectors in this order:
          1. page.get_by_role('combobox', name='<label>')
          2. page.get_by_label('<label>')
          3. page.locator('select[name="<name>"]')
          4. locator('label:has-text("<label>") ~ * select')
          5. locator('label:has-text("<label>") ~ * button') — only for custom dropdowns
      • NEVER target a sidebar or navigation button when the user says "dropdown"
      • Sidebar/navigation items (e.g., "Our Project", "Incident", "Dashboard") are
        navigation links — skip them entirely when the user mentions "dropdown", "filter",
        "select from dropdown", or similar.

  BUTTON
  - If the user says "button", target only <button> or role="button" elements.
  - Do NOT pick a <select>, <input>, or navigation link when the user says "button".

  TEXT BOX / INPUT
  - If the user says "text box", "input", or "field", target <input> or <textarea>.
  - element_type MUST be "input".

  ICON / IMAGE
  - If the user says "icon" or "image", use role="img" or an <img> selector.

DISAMBIGUATION — Dropdown trigger vs. navigation button:
  - When the user says "select project dropdown", "click the project dropdown", or
    "open the project dropdown", they mean the DROPDOWN FORM CONTROL (a <select> or
    custom combobox labeled "Select Project"), NOT a sidebar/nav button named "Our Project"
    or any other navigation item.
  - Always prefer a label-matched dropdown selector over a text-matched button.

  CUSTOM DIV-BASED DROPDOWNS (most important — check CUSTOM DROPDOWNS section first):
  - If the user mentions a dropdown that appears in the CUSTOM DROPDOWNS list above,
    use EXACTLY the selector shown: locator('label:has-text("LABEL") ~ div button').first()
  - These require TWO steps:
      Step 1 (open): click  locator('label:has-text("LABEL") ~ div button').first()
                     element_type="dropdown"
      Step 2 (pick):  click  page.get_by_text('VALUE', exact=True)
                     element_type="option"
  - Do NOT use action_type "select" for these — they are custom components, use "click".

  COLLAPSE / EXPAND / TOGGLE SIDEBAR:
  - If the user says "collapse button", "expand button", or "toggle sidebar":
      • Only target buttons whose aria-label, title, or text contains
        "collapse", "expand", "toggle", "sidebar", or "menu".
      • NEVER pick a password-toggle, eye icon, or any unrelated button.
      • Prefer: page.get_by_role('button', name=/collapse|expand|toggle/i)
        or page.locator('button[aria-label*="collapse" i]')

─────────────────────────────────────────────────────────────
SELF-CHECK BEFORE OUTPUT
─────────────────────────────────────────────────────────────
Before returning JSON, ensure:
- Every test case is executable using the given PAGE STRUCTURE.
- Every step maps to a real selector or valid page state.
- No steps depend on missing elements, pages, or hidden functionality.
- No unsupported USER INTENT scenarios are included.
- All selectors are grounded in the provided page data (no invention).

If any test case fails these checks, remove or fix it before output.

─────────────────────────────────────────────────────────────
OUTPUT FORMAT — return ONLY this JSON, no extra text
─────────────────────────────────────────────────────────────

ACTION TYPES: goto, fill, click, assert, wait, select, upload, capture
ASSERTION TYPES: url, text, heading, toast, status, element, visible, enabled

Generate test cases that cover the user's intent. For a login page:
- TC_001: Valid login flow (positive case)
- TC_002: Invalid credentials (negative case)
- TC_003: Any other scenario the intent mentions

Use REAL selectors from the page data above. For each fill/click step provide 2-3 fallback selectors.

Return ONLY valid JSON starting with {{ and ending with }}:
{{
  "project": "{app_name} Tests",
  "base_url": "{base_url}",
  "common_selectors": {{
    "login": {{
      "email_field": "page.locator('input[type=\\"email\\"]')",
      "password_field": "page.locator('input[type=\\"password\\"]')",
      "login_button": "page.get_by_role('button', name='Login', exact=False)"
    }},
    "navigation": {{
      "sidebar": "page.locator('.sidebar')",
      "dashboard_heading": "page.get_by_role('heading').first()"
    }},
    "common_elements": {{
      "toast_message": "page.locator('.toast, .Toastify, [role=\\"alert\\"]')",
      "loader": "page.locator('.loader, .loading, [class*=\\"spinner\\"]')",
      "popup": "page.locator('.modal, [role=\\"dialog\\"]')"
    }}
  }},
  "test_data": {{
    "default_credentials": {{
      "email": "{test_email}",
      "password": "{test_password}"
    }}
  }},
  "test_cases": [
    {{
      "id": "TC_001",
      "name": "Valid Login",
      "steps": [
        {{
          "step_number": 1,
          "instruction": "Navigate to the login page",
          "action": {{
            "type": "goto",
            "playwright_method": "page.goto()"
          }},
          "selector_hints": {{
            "element_name": null,
            "element_type": null,
            "suggested_selectors": []
          }},
          "test_data": {{
            "url": "{url}"
          }},
          "assertions": null
        }},
        {{
          "step_number": 2,
          "instruction": "Enter valid email address",
          "action": {{
            "type": "fill",
            "playwright_method": "page.fill()"
          }},
          "selector_hints": {{
            "element_name": "Email",
            "element_type": "input",
            "suggested_selectors": [
              "page.locator('input[type=\\"email\\"]')",
              "page.get_by_placeholder('Enter your email')",
              "page.locator('input[name=\\"email\\"]')"
            ]
          }},
          "test_data": {{
            "email": "{test_email}"
          }},
          "assertions": null
        }},
        {{
          "step_number": 3,
          "instruction": "Enter valid password",
          "action": {{
            "type": "fill",
            "playwright_method": "page.fill()"
          }},
          "selector_hints": {{
            "element_name": "Password",
            "element_type": "input",
            "suggested_selectors": [
              "page.locator('input[type=\\"password\\"]')",
              "page.get_by_placeholder('Enter password')",
              "page.locator('input[name=\\"password\\"]')"
            ]
          }},
          "test_data": {{
            "password": "{test_password}"
          }},
          "assertions": null
        }},
        {{
          "step_number": 4,
          "instruction": "Click the Login button",
          "action": {{
            "type": "click",
            "playwright_method": "locator.click()"
          }},
          "selector_hints": {{
            "element_name": "Login",
            "element_type": "button",
            "suggested_selectors": [
              "page.get_by_role('button', name='Login', exact=False)",
              "page.locator('button[type=\\"submit\\"]')"
            ]
          }},
          "test_data": null,
          "assertions": null
        }},
        {{
          "step_number": 5,
          "instruction": "Verify successful login by checking URL or dashboard heading",
          "action": {{
            "type": "assert",
            "playwright_method": "expect()"
          }},
          "selector_hints": {{
            "element_name": null,
            "element_type": null,
            "suggested_selectors": []
          }},
          "test_data": null,
          "assertions": [
            {{
              "type": "url",
              "expected_value": "/dashboard",
              "playwright_assertion": "expect(page).toHaveURL(/dashboard/)"
            }}
          ]
        }}
      ],
      "expected_results": [
        "User is redirected to the dashboard after successful login"
      ]
    }}
  ]
}}

IMPORTANT:
- Replace the example test cases above with real ones based on the PAGE STRUCTURE and USER INTENT
- Use the actual selectors found in the page data (inputs, buttons, headings above)
- Generate as many test cases as needed to cover the user intent
- Keep selectors accurate to what exists on the real page
- HONOR the user's stated element type: if they say "dropdown" → use dropdown/select selectors and element_type="dropdown"; if they say "button" → use button selectors; if they say "text box" → use input selectors
- NEVER use a navigation/sidebar button (e.g., "Our Project") when the user explicitly says "dropdown", "select from dropdown", or similar — use a label-matched combobox or select element instead

{browser_context_note}
"""


def _format_custom_dropdowns(dropdowns: List[Dict]) -> str:
    """Format custom div-based dropdowns for the generator prompt."""
    if not dropdowns:
        return "  (none found)"
    lines = []
    for cd in dropdowns:
        label = cd.get("label", "")
        val = cd.get("currentValue", "")
        lines.append(
            f'  label="{label}" currentValue="{val}"'
            f' → USE: locator(\'label:has-text("{label}") ~ div button\').first()'
        )
    return "\n".join(lines)


def _format_elements(elements: List[Dict], max_items: int = 15) -> str:
    """Format element list into readable text for the prompt."""
    if not elements:
        return "  (none found)"
    lines = []
    for i, el in enumerate(elements[:max_items]):
        parts = []
        if el.get("id"):
            parts.append(f"id={el['id']}")
        if el.get("placeholder"):
            parts.append(f"placeholder=\"{el['placeholder']}\"")
        if el.get("text"):
            parts.append(f"text=\"{el['text'][:40]}\"")
        if el.get("type"):
            parts.append(f"type={el['type']}")
        if el.get("role"):
            parts.append(f"role={el['role']}")
        if el.get("ariaLabel"):
            parts.append(f"aria-label=\"{el['ariaLabel']}\"")
        if el.get("name"):
            parts.append(f"name={el['name']}")

        selectors = el.get("selectors", {})
        best_selectors = []
        for key in ["byId", "byTestId", "byPlaceholder", "byRole", "byText", "byClass"]:
            if selectors.get(key):
                best_selectors.append(selectors[key])
        selector_str = " | ".join(best_selectors[:3]) if best_selectors else selectors.get("xpath", "")

        attr_str = ", ".join(parts) if parts else "no attrs"
        lines.append(f"  [{i+1}] {el.get('tag','?').upper()} ({attr_str})\n       selectors: {selector_str}")
    if len(elements) > max_items:
        lines.append(f"  ... and {len(elements) - max_items} more elements")
    return "\n".join(lines)


class TestCaseGeneratorAgent(BaseAgent):
    """Generates EnhancedTestSuite from page structure + user intent."""

    def __init__(
        self,
        provider: LLMProvider = LLMProvider.GROQ,
        model: Optional[str] = None,
    ):
        # Resolve API keys from settings
        super().__init__(
            provider=provider,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            openai_api_key=settings.OPENAI_API_KEY,
            groq_api_key=settings.GROQ_API_KEY,
            groq_model=model or settings.GROQ_MODEL,
            openai_model=model or settings.OPENAI_MODEL,
            anthropic_model=model or settings.ANTHROPIC_MODEL,
        )

    def execute(self, *args, **kwargs) -> Any:
        """Required by BaseAgent ABC — delegates to generate()."""
        return self.generate(*args, **kwargs)

    def generate_intro(self, compact: Dict[str, Any]) -> str:
        """
        Call LLM with the compact page summary and return a greeting message
        that describes the page and asks the user what to test.
        """
        import json as _json
        prompt = PAGE_INTRO_PROMPT.format(compact_json=_json.dumps(compact, indent=2))
        try:
            return self.call_llm(prompt).strip()
        except Exception as e:
            logger.warning(f"[generate_intro] LLM call failed: {e}")
            title = compact.get("title") or compact.get("url") or "this page"
            return (
                f"I've analysed {title}. "
                f"What would you like to test?"
            )

    def answer_question(self, compact: Dict[str, Any], question: str, history: list = None) -> str:
        """
        Answer an informational question about the page without generating test cases.
        """
        import json as _json
        system = (
            "You are an expert test assistant. The following is the structure of the page "
            "currently being analysed:\n\n"
            + _json.dumps(compact, indent=2)
        )
        messages = _trim_history(history or []) + [{"role": "user", "content": question}]
        try:
            return self.call_llm_chat(system, messages).strip()
        except Exception as e:
            logger.warning(f"[answer_question] LLM call failed: {e}")
            try:
                prompt = INFORMATIONAL_PROMPT.format(
                    compact_json=_json.dumps(compact, indent=2),
                    question=question,
                )
                return self.call_llm(prompt).strip()
            except Exception:
                return "I can see the page has been analysed. Could you clarify what you'd like to know?"

    def classify_approve_intent(self, user_message: str, test_cases: list) -> dict:
        """
        Returns {"approve": True, "targets": "all"|[ints]|[names], "response": str}
        or      {"approve": False}
        Uses the LLM so it handles any natural-language phrasing or name reference.
        """
        import json as _json
        tc_lines = "\n".join(
            f"{i + 1}. {tc.get('name', f'Test {i + 1}')}"
            for i, tc in enumerate(test_cases)
        ) or "(no test cases generated yet)"

        prompt = (
            f"Available test cases:\n{tc_lines}\n\n"
            f'User message: "{user_message}"\n\n'
            "Is the user asking to add, approve, save, confirm, include, or export "
            "test case results to Excel or a spreadsheet?\n\n"
            "Reply ONLY with valid JSON — no other text:\n"
            '- If YES: {"approve": true, "targets": "all" | [1, 2] | ["Exact Name"], '
            '"response": "brief one-line confirmation"}\n'
            "  - Use \"all\" if they want everything\n"
            "  - Use 1-based integer array if they reference by number\n"
            "  - Use name strings (exactly from the list above) if they reference by name\n"
            '- If NO:  {"approve": false}'
        )
        try:
            result = self.call_llm(prompt).strip()
            # strip markdown code fences if present
            if result.startswith("```"):
                result = result.split("```")[1]
                if result.startswith("json"):
                    result = result[4:]
            return _json.loads(result)
        except Exception as e:
            logger.warning(f"[classify_approve_intent] failed: {e}")
            return {"approve": False}

    def classify_intent(
        self,
        user_message: str,
        test_cases: list,
        page_url: str = "",
        history: list = None,
    ) -> dict:
        """
        Conversational intent classifier — uses call_llm_chat() so history is
        passed as real messages, not text injection.
        Classifies into: execute | edit | informational | approve | generate | clarify
        Falls back to {"intent": "generate"} on any error.
        """
        import json as _json

        tc_lines = "\n".join(
            f"{i + 1}. {tc.get('name', f'Test {i + 1}')}"
            for i, tc in enumerate(test_cases)
        ) or "(no test cases yet)"

        system = INTENT_CLASSIFIER_SYSTEM.format(
            page_url=page_url or "unknown",
            test_cases_list=tc_lines,
        )

        # Pass history as real messages + current user message as final turn.
        # Drop leading assistant messages — API requires first message to be "user".
        trimmed = _trim_history(history or [])
        while trimmed and trimmed[0]["role"] != "user":
            trimmed = trimmed[1:]
        messages = trimmed + [{"role": "user", "content": user_message}]

        try:
            raw = self.call_llm_chat(system, messages, markdown=False).strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = _json.loads(raw)
            # Ensure metadata always has form_data key
            if "metadata" not in result:
                result["metadata"] = {}
            result["metadata"].setdefault("form_data", {})
            return result
        except Exception as e:
            logger.warning(f"[classify_intent] failed: {e}")
            return {"intent": "generate", "confidence": 0.0, "metadata": {"form_data": {}}}

    def generate_edit(self, test_suite: Dict[str, Any], instruction: str, history: list = None) -> Dict[str, Any]:
        """
        Apply a surgical edit to an existing test suite based on user instruction.
        Returns the updated test suite dict.
        """
        import json as _json
        system = (
            "You are a Playwright test case editor. Edit the test suite below according "
            "to the user's instruction. Return valid JSON only.\n\n"
            "Current test suite:\n" + _json.dumps(test_suite, indent=2)
        )
        messages = _trim_history(history or []) + [{"role": "user", "content": instruction}]
        try:
            raw = self.call_llm_chat(system, messages, markdown=False)
            return self._parse_json_response(raw)
        except Exception as e:
            logger.warning(f"[generate_edit] multi-turn failed ({e}), falling back to single-turn")
            try:
                prompt = EDIT_PROMPT.format(
                    suite_json=_json.dumps(test_suite, indent=2),
                    instruction=instruction,
                )
                raw = self.call_llm(prompt, markdown=False)
                return self._parse_json_response(raw)
            except Exception as e2:
                logger.error(f"[generate_edit] Failed: {e2}")
                raise

    def generate_confirm(self, test_suite: Dict[str, Any], compact: Dict[str, Any]) -> str:
        """
        Call LLM to produce a short confirmation message after test cases are generated.
        """
        test_cases = test_suite.get("test_cases", [])
        tc_count = len(test_cases)
        tc_names = ", ".join(tc.get("name", tc.get("id", "")) for tc in test_cases[:5])
        prompt = PAGE_CONFIRM_PROMPT.format(tc_count=tc_count, tc_names=tc_names)
        try:
            return self.call_llm(prompt).strip()
        except Exception as e:
            logger.warning(f"[generate_confirm] LLM call failed: {e}")
            return f"I've created {tc_count} test case(s) for you."

    def generate(
        self,
        page_structure: Dict[str, Any],
        intent: str,
        app_name: str = "My App",
        base_url: Optional[str] = None,
        test_email: str = "test@example.com",
        test_password: str = "password123",
        browser_already_on_page: bool = False,
        history: Optional[list] = None,
        form_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a complete EnhancedTestSuite from page structure and user intent.
        Uses call_llm_chat() with full conversation history for truly conversational generation.

        Args:
            page_structure: Output from SelectorExtractor.extract_selectors()
            intent: Natural language description of what to test (current user message only)
            app_name: Name of the application
            base_url: Base URL of the application
            test_email: Test email credential
            test_password: Test password credential
            history: Full conversation history (passed as real messages to LLM)
            form_data: Extracted field values from classifier (e.g. {"Date": "2027-03-08"})

        Returns:
            EnhancedTestSuite dict ready for execution
        """
        url = page_structure.get("url", base_url or "")
        title = page_structure.get("title", "Unknown Page")
        inputs = page_structure.get("inputs", [])
        headings = page_structure.get("headings", [])
        links = page_structure.get("links", [])
        custom_dropdowns = page_structure.get("custom_dropdowns", [])

        # Supplement native <button> elements with custom interactive components
        # (e.g. <div role="button">, <span role="menuitem">) that only appear in
        # the "interactive" list, not in "buttons". Without this, the LLM never
        # sees them and hallucinates multi-step flows (e.g. open menu → click logout).
        buttons = list(page_structure.get("buttons", []))
        _seen_btn_labels = {(el.get("text") or el.get("ariaLabel") or "").strip().lower()
                            for el in buttons}
        for el in page_structure.get("interactive", []):
            if el.get("role") in ("button", "menuitem", "tab", "option", "link") \
                    and el.get("tag") not in ("button", "input", "a"):
                label = (el.get("text") or el.get("ariaLabel") or "").strip()
                if label and label.lower() not in _seen_btn_labels:
                    _seen_btn_labels.add(label.lower())
                    buttons.append(el)

        if not base_url:
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

        if browser_already_on_page:
            browser_context_note = (
                f"BROWSER SESSION: The browser is ALREADY OPEN on this page ({url}). "
                f"This is a continuous test session — do NOT add a goto step to navigate "
                f"to {url}. The browser is already there. Start each test case directly "
                f"from the first real interaction (click, fill, assert) on the elements "
                f"listed above. Only add a goto step if the test explicitly needs to "
                f"navigate to a DIFFERENT page (e.g. a sub-page or external URL)."
            )
        else:
            browser_context_note = (
                f"BROWSER SESSION: The browser starts fresh. Add a goto step as the "
                f"first step of each test case to navigate to the test page ({url}). "
                f"Use the full URL in the goto step's test_data.url field."
            )

        # Build the user's intent message, appending any extracted form_data
        intent_message = intent
        if form_data:
            intent_message += "\n\nEXTRACTED TEST DATA (use these values in fill steps):\n"
            for _k, _v in form_data.items():
                intent_message += f"  {_k}: {_v}\n"

        # Page structure + rules go in system context (stable across turns).
        # The {intent} placeholder in GENERATOR_PROMPT is filled with a static
        # instruction — the actual intent comes from the messages array so the
        # LLM sees full conversation history for truly conversational generation.
        _intent_instruction = (
            "(Implement the intent provided in the user message below. "
            "Use the page structure above to generate accurate test steps.)"
        )
        system_prompt = GENERATOR_PROMPT.format(
            url=url,
            title=title,
            input_count=len(inputs),
            inputs_text=_format_elements(inputs),
            custom_dropdown_count=len(custom_dropdowns),
            custom_dropdowns_text=_format_custom_dropdowns(custom_dropdowns),
            button_count=len(buttons),
            buttons_text=_format_elements(buttons),
            heading_count=len(headings),
            headings_text=_format_elements(headings),
            link_count=len(links),
            links_text=_format_elements(links, max_items=10),
            intent=_intent_instruction,
            app_name=app_name,
            base_url=base_url,
            test_email=test_email,
            test_password=test_password,
            browser_context_note=browser_context_note,
        )

        # Build messages: trimmed history (must start with user role) + current intent
        trimmed = _trim_history(history or [])
        # Drop leading assistant messages — Anthropic API requires first message to be "user"
        while trimmed and trimmed[0]["role"] != "user":
            trimmed = trimmed[1:]
        messages = trimmed + [{"role": "user", "content": intent_message}]

        logger.info(
            f"Generating test cases | provider={self.provider} | url={url} | "
            f"browser_already_on_page={browser_already_on_page} | intent={intent[:80]} | "
            f"history_turns={len(trimmed)} | form_data_keys={list((form_data or {}).keys())}"
        )

        raw = self.call_llm_chat(system_prompt, messages, markdown=False)

        return self._parse_json_response(raw)

    def _parse_json_response(self, raw: str) -> Dict[str, Any]:
        """Extract and parse JSON from LLM response."""
        raw = raw.strip()

        # Strip ALL markdown code fences (```json ... ``` or ``` ... ```)
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
        raw = raw.strip()

        # Find the outermost JSON object by tracking brace depth
        # This correctly handles trailing text after the closing }
        start = raw.find("{")
        if start != -1:
            depth = 0
            end = start
            in_string = False
            escape_next = False
            for i, ch in enumerate(raw[start:], start=start):
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\" and in_string:
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            raw = raw[start:end]

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}\nRaw (first 500): {raw[:500]}")
            raise ValueError(f"LLM returned invalid JSON: {e}")
