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

    return result


# ---------------------------------------------------------------------------
# Intro / confirm prompts
# ---------------------------------------------------------------------------

INFORMATIONAL_PROMPT = """You are an AI test assistant embedded in a test case generation tool.

The user has asked an INFORMATIONAL question about the web page or testing — they are NOT asking you to generate test cases.

PAGE SUMMARY (JSON):
{compact_json}

USER QUESTION:
{question}

Answer the question directly and helpfully in 2-4 sentences. If relevant, reference specific elements visible on the page.
Do NOT generate test cases. Do NOT output JSON.
Return ONLY the plain text answer."""


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
Return ONLY the message text. No JSON. No markdown headings. No preamble."""

PAGE_CONFIRM_PROMPT = """You are an AI test assistant. You just generated the following test suite.

TEST SUITE SUMMARY:
- Total test cases: {tc_count}
- Test case names: {tc_names}

Write 1 short sentence (max 20 words) confirming what you created.
Example: "I've created 3 test cases covering valid login, invalid credentials, and forgot password."
Return ONLY the sentence. No JSON. No extra text."""


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
"""


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
            raw = self.call_llm_chat(system, messages)
            return self._parse_json_response(raw)
        except Exception as e:
            logger.warning(f"[generate_edit] multi-turn failed ({e}), falling back to single-turn")
            try:
                prompt = EDIT_PROMPT.format(
                    suite_json=_json.dumps(test_suite, indent=2),
                    instruction=instruction,
                )
                raw = self.call_llm(prompt)
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
    ) -> Dict[str, Any]:
        """
        Generate a complete EnhancedTestSuite from page structure and user intent.

        Args:
            page_structure: Output from SelectorExtractor.extract_selectors()
            intent: Natural language description of what to test
            app_name: Name of the application
            base_url: Base URL of the application
            test_email: Test email credential
            test_password: Test password credential

        Returns:
            EnhancedTestSuite dict ready for execution
        """
        url = page_structure.get("url", base_url or "")
        title = page_structure.get("title", "Unknown Page")
        inputs = page_structure.get("inputs", [])
        headings = page_structure.get("headings", [])
        links = page_structure.get("links", [])

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

        prompt = GENERATOR_PROMPT.format(
            url=url,
            title=title,
            input_count=len(inputs),
            inputs_text=_format_elements(inputs),
            button_count=len(buttons),
            buttons_text=_format_elements(buttons),
            heading_count=len(headings),
            headings_text=_format_elements(headings),
            link_count=len(links),
            links_text=_format_elements(links, max_items=10),
            intent=intent,
            app_name=app_name,
            base_url=base_url,
            test_email=test_email,
            test_password=test_password,
        )

        logger.info(
            f"Generating test cases | provider={self.provider} | url={url} | intent={intent[:80]}"
        )

        raw = self.call_llm(prompt)
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
