"""
RecorderAgent
Converts a natural language command into a Playwright action dict,
then executes it on a live page inside a RecorderSession.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.agents.base_agent import BaseAgent, LLMProvider
from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

MULTI_STEP_PROMPT = """You are a Playwright test recorder assistant.
Your job is to split a natural language paragraph describing browser interactions into an ORDERED LIST of atomic Playwright actions.

─────────────────────────────────────────────────────────────
CURRENT PAGE CONTEXT
─────────────────────────────────────────────────────────────
URL: {current_url}
Title: {page_title}

INPUTS ({input_count}):
{inputs_text}

BUTTONS ({button_count}):
{buttons_text}

LINKS ({link_count}):
{links_text}

VISIBLE DROPDOWN / LIST ITEMS ({dropdown_count}):
{dropdown_text}

TABLE HEADERS ({table_count}):
{tables_text}

OPEN MODALS/DIALOGS ({modal_count}):
{modals_text}

─────────────────────────────────────────────────────────────
PREVIOUS TEST CASES (for context — do NOT re-execute these)
─────────────────────────────────────────────────────────────
{context_summary}

─────────────────────────────────────────────────────────────
USER PARAGRAPH
─────────────────────────────────────────────────────────────
{paragraph}

─────────────────────────────────────────────────────────────
OUTPUT FORMAT — return ONLY a JSON array, no extra text
─────────────────────────────────────────────────────────────
Split the paragraph into individual atomic actions. Each action = one JSON object.
Return ONLY a JSON array starting with [ and ending with ]:

[
  {{
    "action_type": "fill",
    "selector": "page.get_by_label('Email')",
    "value": "test@example.com",
    "instruction": "Fill the Email field with test@example.com",
    "playwright_method": "locator.fill()",
    "element_name": "Email",
    "element_type": "input",
    "test_data": {{"email": "test@example.com"}}
  }},
  {{
    "action_type": "click",
    "selector": "page.get_by_role('button', name='Login')",
    "value": "",
    "instruction": "Click the Login button",
    "playwright_method": "locator.click()",
    "element_name": "Login",
    "element_type": "button",
    "test_data": null
  }}
]

Allowed action_type values:
  — NAVIGATION —
  "goto"           — navigate to a URL
  "back"           — browser back button
  "forward"        — browser forward button
  "reload"         — reload/refresh the page

  — MOUSE —
  "click"          — single left click on an element
  "double_click"   — double click on an element
  "right_click"    — right-click (context menu) on an element
  "hover"          — hover the mouse over an element

  — FORM INPUT —
  "fill"           — clear field then type text (fastest)
  "type"           — type text character-by-character (for OTP/autocomplete fields)
  "select"         — choose from a native <select> dropdown
  "check"          — check a checkbox or radio button
  "uncheck"        — uncheck a checkbox
  "clear"          — clear an input field
  "press"          — press a keyboard key (Enter, Tab, Escape, ArrowDown, etc.)
  "upload"         — upload a file; value = file path

  — DRAG & SCROLL —
  "drag"           — drag element (selector) to a target (value = target selector)
  "scroll"         — scroll page or element; value = "down"/"up"/"top"/"bottom" or pixels like "500"

  — ASSERTIONS —
  "assert_visible"   — verify element is visible on page
  "assert_hidden"    — verify element is NOT visible
  "assert_text"      — verify element contains specific text (value = expected text)
  "assert_value"     — verify input field has a specific value (value = expected value)
  "assert_url"       — verify page URL contains/matches (value = expected url or pattern)
  "assert_title"     — verify page title contains (value = expected title text)
  "assert_count"     — verify number of matching elements (value = expected count as integer)
  "assert_enabled"   — verify element is enabled (not disabled)
  "assert_disabled"  — verify element is disabled
  "assert_checked"   — verify checkbox/radio is checked
  "assert_attribute" — verify element has attribute=value (value = "attr=expected_val")
  "assert_table"     — verify table headers are visible; selector = table locator, value = comma-separated expected column names

  — OTHER —
  "wait"           — wait for element or time; value = ms number OR state like "visible"
  "screenshot"     — capture a screenshot

SELECTOR RULES — MANDATORY:
- Each input/button in the page context above has a "→ USE: ..." suggested selector
- You MUST use the suggested selector exactly as shown when it is available — do NOT invent your own
- Only create your own selector if no suggested selector is provided for that element

For elements without a suggested selector, prefer this priority order:
  1. page.get_by_label('...')
  2. page.get_by_placeholder('...')
  3. page.get_by_role('...', name='...')
  4. page.get_by_text('...', exact=True)   ← use for custom dropdown items visible in the list above
  5. page.locator('input[name="..."]') or similar attribute selector
  6. page.locator('.class-name') only as last resort

IMPORTANT — Custom dropdown / list items:
- If the user says "select X", "choose X", or "click X" AND X appears in the VISIBLE DROPDOWN / LIST ITEMS section above,
  use action_type "click" with selector page.get_by_text('X', exact=True).
- Do NOT use action_type "select" for custom (non-native) dropdowns — use "click" instead.
- For native <select> elements still use action_type "select".

Rules:
- ONLY generate actions that are EXPLICITLY described in the user paragraph — never add, infer, or assume extra steps
- If the paragraph says "click X", return ONE click action — do NOT add fill steps or navigation before it
- If the paragraph says "fill email as X", return ONE fill action — do NOT add clicks or other fills
- For "goto": set selector to "" and value to the FULL URL (must start with http:// or https://) — NEVER use "goto" for module names, page names, or menu items
- For "click": set value to ""
- NEVER generate a "goto" action to reload or revisit the CURRENT URL shown above — only "goto" when navigating to a DIFFERENT page
- NEVER produce a "goto" action whose value is a module name, section name, or anything that is not a real URL — use "click" instead to navigate via the UI
- NEVER produce a "click" action with an empty selector — if you cannot find the element in the page context, use page.get_by_text('button label from the command', exact=False) as the selector
- If the paragraph says "Navigate to the X module" or "go to the X section", use action_type "click" with the sidebar/menu element, NOT "goto"
- For assert_* actions: use the most specific assert type that matches the intent
  - assert_table: selector = page.locator('table') or specific table locator, value = comma-separated expected column header names from the TABLE HEADERS section above
  - assert_text: selector = element containing the text, value = exact expected text
  - assert_visible: selector = element to check, value = ""
  - assert_url: selector = "", value = URL fragment or full URL
- instruction must be a human-readable description of what this specific atomic step does
- test_data should capture any user-supplied values (email, name, etc.) or null if none
- Use REAL selectors from the page context above whenever possible
- Return ONLY the JSON array, no markdown, no explanation
"""

RECORDER_PROMPT = """You are a Playwright test recorder assistant.
Your job is to convert a natural language browser command into ONE Playwright action.

─────────────────────────────────────────────────────────────
CURRENT PAGE CONTEXT
─────────────────────────────────────────────────────────────
URL: {current_url}
Title: {page_title}

INPUTS ({input_count}):
{inputs_text}

BUTTONS ({button_count}):
{buttons_text}

LINKS ({link_count}):
{links_text}

VISIBLE DROPDOWN / LIST ITEMS ({dropdown_count}):
{dropdown_text}

TABLE HEADERS ({table_count}):
{tables_text}

OPEN MODALS/DIALOGS ({modal_count}):
{modals_text}

─────────────────────────────────────────────────────────────
USER COMMAND
─────────────────────────────────────────────────────────────
{command}

─────────────────────────────────────────────────────────────
OUTPUT FORMAT — return ONLY this JSON, no extra text
─────────────────────────────────────────────────────────────
Pick exactly ONE of these action_type values:
  "goto"           — navigate to a URL
  "back"           — browser back
  "forward"        — browser forward
  "reload"         — reload page
  "click"          — single left click
  "double_click"   — double click
  "right_click"    — right-click (context menu)
  "hover"          — hover mouse over element
  "fill"           — clear + type text into input
  "type"           — type character-by-character (OTP/autocomplete)
  "select"         — native <select> dropdown
  "check"          — check a checkbox/radio
  "uncheck"        — uncheck a checkbox
  "clear"          — clear an input field
  "press"          — keyboard key (Enter, Tab, Escape, ArrowDown…)
  "upload"         — file upload; value = file path
  "drag"           — drag to target; value = target selector
  "scroll"         — scroll; value = "down"/"up"/"top"/"bottom" or pixels
  "assert_visible"   — element is visible
  "assert_hidden"    — element is not visible
  "assert_text"      — element contains text (value = expected)
  "assert_value"     — input has value (value = expected)
  "assert_url"       — page URL matches (value = expected pattern)
  "assert_title"     — page title contains (value = expected)
  "assert_count"     — N elements exist (value = integer count)
  "assert_enabled"   — element is enabled
  "assert_disabled"  — element is disabled
  "assert_checked"   — checkbox is checked
  "assert_attribute" — has attribute (value = "attr=expected_val")
  "assert_table"     — table headers visible; value = comma-separated column names
  "wait"           — wait for element/time
  "screenshot"     — capture screenshot

SELECTOR RULES — MANDATORY:
- Each input/button in the page context above has a "→ USE: ..." suggested selector
- You MUST use the suggested selector exactly as shown when it is available — do NOT invent your own
- Only create your own selector if no suggested selector is provided for that element

For elements without a suggested selector, prefer this priority order:
  1. page.get_by_label('...')
  2. page.get_by_placeholder('...')
  3. page.get_by_role('...', name='...')
  4. page.get_by_text('...', exact=True)   ← use for custom dropdown items visible in the list above
  5. page.locator('input[name="..."]') or similar attribute selector
  6. page.locator('.class-name') only as last resort

IMPORTANT — Custom dropdown / list items:
- If the command says "select X", "choose X", or "click X" AND X appears in VISIBLE DROPDOWN / LIST ITEMS above,
  use action_type "click" with selector page.get_by_text('X', exact=True).
- Do NOT use action_type "select" for custom (non-native) dropdowns — use "click" instead.
- For native <select> elements still use action_type "select".

Return ONLY valid JSON starting with {{ and ending with }}:
{{
  "action_type": "fill",
  "selector": "page.get_by_label('Email')",
  "value": "test@example.com",
  "instruction": "Fill the Email field with test@example.com",
  "playwright_method": "locator.fill()",
  "element_name": "Email",
  "element_type": "input",
  "test_data": {{"email": "test@example.com"}}
}}

Rules:
- ONLY perform the EXACT action described in the command — never add, infer, or assume extra steps
- If the command says "click X", return a click action only — do NOT add fills or navigation
- For "goto": set selector to "" and value to the full URL
- For "click": set value to ""
- NEVER generate a "goto" action to reload or revisit the CURRENT URL shown above — only "goto" when navigating to a DIFFERENT page
- NEVER produce a "click" action with an empty selector — if you cannot find the element in the page context, use page.get_by_text('button label from the command', exact=False) as the selector
- For assert_* actions: pick the most specific type (assert_visible, assert_text, assert_table, etc.)
  - assert_table: selector = page.locator('table'), value = comma-separated expected column headers
  - assert_text: selector = element containing the text, value = expected text string
  - assert_visible / assert_hidden: selector = element, value = ""
  - assert_url: selector = "", value = URL pattern
- For "wait": set selector to element selector or "" if waiting for time, value to ms or selector text
- For "press": set selector to the focused element or "" and value to the key name
- For "drag": set selector = source element, value = target selector expression
- For "scroll": set selector = "" for whole page or element selector, value = "down"/"up"/"top"/"bottom" or pixel amount
- instruction must be a human-readable description of what this step does
- test_data should capture any user-supplied values (email, name, etc.) or null if none
- Use REAL selectors from the page context above whenever possible
"""




def _scrape_page_context(page: Any) -> Dict[str, Any]:
    """
    Extract lightweight page context (inputs, buttons, links, tables, modals) from a live Playwright page.
    Does NOT use SelectorExtractor (which opens a new browser) — instead uses page.evaluate().
    Each input/button also gets a pre-computed `suggested_selector` so the LLM doesn't have to guess.
    """
    try:
        context = page.evaluate("""() => {
            function bestSelector(el) {
                // 1. Label association
                if (el.labels && el.labels[0]) {
                    const labelText = el.labels[0].innerText.trim();
                    if (labelText) return "page.get_by_label('" + labelText.replace(/'/g, "\\\\'") + "')";
                }
                // 2. aria-label
                const ariaLabel = el.getAttribute('aria-label');
                if (ariaLabel) return "page.get_by_label('" + ariaLabel.replace(/'/g, "\\\\'") + "')";
                // 3. placeholder
                const ph = el.getAttribute('placeholder');
                if (ph) return "page.get_by_placeholder('" + ph.replace(/'/g, "\\\\'") + "')";
                // 4. role + name for buttons
                const role = el.getAttribute('role') || (el.tagName === 'BUTTON' ? 'button' : '');
                const name = (el.innerText || el.value || '').trim().substring(0, 40);
                if (role && name) return "page.get_by_role('" + role + "', name='" + name.replace(/'/g, "\\\\'") + "')";
                // 5. name attribute
                if (el.getAttribute('name')) return "page.locator('[name=\"" + el.getAttribute('name') + "\"]')";
                // 6. id
                if (el.id) return "page.locator('#" + el.id + "')";
                // 7. type-based
                const type = el.getAttribute('type');
                if (type) return "page.locator('input[type=\"" + type + "\"]')";
                return '';
            }

            const getAttrs = (el) => ({
                id: el.id || '',
                name: el.getAttribute('name') || '',
                type: el.getAttribute('type') || el.tagName.toLowerCase(),
                placeholder: el.getAttribute('placeholder') || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                text: (el.innerText || el.value || '').trim().substring(0, 60),
                role: el.getAttribute('role') || '',
                forLabel: el.labels && el.labels[0] ? el.labels[0].innerText.trim().substring(0, 40) : '',
                suggested_selector: bestSelector(el)
            });

            const inputs = Array.from(document.querySelectorAll('input, textarea, select'))
                .filter(el => !['hidden', 'submit', 'reset'].includes(el.type))
                .slice(0, 20)
                .map(getAttrs);

            const buttons = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'))
                .slice(0, 20)
                .map(getAttrs);

            const links = Array.from(document.querySelectorAll('a[href]'))
                .slice(0, 15)
                .map(el => ({
                    text: (el.innerText || '').trim().substring(0, 60),
                    href: el.href || ''
                }));

            // Dropdown / listbox items — custom menus, selects, comboboxes
            const dropdownItems = Array.from(document.querySelectorAll(
                '[role="option"], [role="listitem"], [role="menuitem"], ' +
                '.dropdown-item, .select-option, [class*="option"], [class*="item"]'
            ))
                .filter(el => {
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
                })
                .slice(0, 30)
                .map(el => ({
                    text: (el.innerText || el.textContent || '').trim().substring(0, 80),
                    role: el.getAttribute('role') || '',
                    classes: el.className || ''
                }))
                .filter(el => el.text.length > 0);

            // Tables — extract headers and row count
            const tables = Array.from(document.querySelectorAll('table')).slice(0, 5).map(tbl => {
                const headers = Array.from(tbl.querySelectorAll('th')).map(th => (th.innerText || '').trim()).filter(t => t.length > 0);
                const rows = tbl.querySelectorAll('tbody tr').length;
                const caption = (tbl.querySelector('caption') ? tbl.querySelector('caption').innerText.trim() : '');
                return { caption, headers, row_count: rows };
            }).filter(t => t.headers.length > 0);

            // Open modals / dialogs
            const modals = Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"], .modal, [class*="modal"], [class*="dialog"]'))
                .filter(el => {
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
                })
                .slice(0, 3)
                .map(el => {
                    const heading = el.querySelector('h1,h2,h3,h4,[class*="title"],[class*="header"]');
                    const title = heading ? (heading.innerText || '').trim() : (el.getAttribute('aria-label') || '');
                    return { title };
                })
                .filter(m => m.title.length > 0);

            return {
                url: window.location.href,
                title: document.title,
                inputs,
                buttons,
                links,
                dropdownItems,
                tables,
                modals,
            };
        }""")
        return context
    except Exception as e:
        logger.warning(f"Page context scrape failed: {e}")
        return {
            "url": page.url,
            "title": "",
            "inputs": [],
            "buttons": [],
            "links": [],
            "dropdownItems": [],
            "tables": [],
            "modals": [],
        }


def _format_inputs(inputs: List[Dict]) -> str:
    if not inputs:
        return "  (none)"
    lines = []
    for i, el in enumerate(inputs[:15]):
        parts = []
        if el.get("forLabel"):
            parts.append(f"label='{el['forLabel']}'")
        if el.get("placeholder"):
            parts.append(f"placeholder='{el['placeholder']}'")
        if el.get("id"):
            parts.append(f"id='{el['id']}'")
        if el.get("name"):
            parts.append(f"name='{el['name']}'")
        if el.get("type"):
            parts.append(f"type={el['type']}")
        sel = el.get("suggested_selector", "")
        sel_str = f"  → USE: {sel}" if sel else ""
        lines.append(f"  [{i+1}] {', '.join(parts) or 'unnamed input'}{sel_str}")
    return "\n".join(lines)


def _format_buttons(buttons: List[Dict]) -> str:
    if not buttons:
        return "  (none)"
    lines = []
    for i, el in enumerate(buttons[:15]):
        text = el.get("text") or el.get("ariaLabel") or el.get("value") or "unnamed"
        extra = []
        if el.get("id"):
            extra.append(f"id='{el['id']}'")
        if el.get("type"):
            extra.append(f"type={el['type']}")
        sel = el.get("suggested_selector", "")
        sel_str = f"  → USE: {sel}" if sel else ""
        lines.append(f"  [{i+1}] '{text}' {' '.join(extra)}{sel_str}")
    return "\n".join(lines)


def _format_links(links: List[Dict]) -> str:
    if not links:
        return "  (none)"
    lines = []
    for i, link in enumerate(links[:10]):
        lines.append(f"  [{i+1}] '{link.get('text','?')}' → {link.get('href','')[:80]}")
    return "\n".join(lines)


def _format_dropdown_items(items: List[Dict]) -> str:
    if not items:
        return "  (none visible)"
    lines = []
    for i, item in enumerate(items[:25]):
        text = item.get("text", "")
        role = item.get("role", "")
        role_str = f" [{role}]" if role else ""
        lines.append(f"  [{i+1}] '{text}'{role_str}")
    return "\n".join(lines)


def _format_tables(tables: List[Dict]) -> str:
    if not tables:
        return "  (none)"
    lines = []
    for i, tbl in enumerate(tables):
        caption = tbl.get("caption", "")
        headers = tbl.get("headers", [])
        rows = tbl.get("row_count", 0)
        cap_str = f" '{caption}'" if caption else ""
        hdr_str = ", ".join(f"'{h}'" for h in headers) if headers else "(no headers)"
        lines.append(f"  [{i+1}] Table{cap_str}: columns=[{hdr_str}], rows={rows}")
    return "\n".join(lines)


def _format_modals(modals: List[Dict]) -> str:
    if not modals:
        return "  (none open)"
    return "\n".join(f"  [{i+1}] '{m.get('title', 'unnamed')}'" for i, m in enumerate(modals))


class RecorderAgent(BaseAgent):
    """
    Converts a natural language browser command to a Playwright action dict,
    then executes it on a live page.
    """

    def __init__(
        self,
        provider: LLMProvider = LLMProvider.GROQ,
        model: Optional[str] = None,
    ):
        super().__init__(
            provider=provider,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            openai_api_key=settings.OPENAI_API_KEY,
            groq_api_key=settings.GROQ_API_KEY,
            groq_model=model or settings.GROQ_MODEL,
            openai_model=model or settings.OPENAI_MODEL,
            anthropic_model=model or settings.ANTHROPIC_MODEL,
            # RecorderAgent generates large JSON arrays for multi-step commands;
            # ensure token limit is high enough to avoid truncated responses.
            openai_max_tokens=max(settings.OPENAI_MAX_TOKENS, 16000),
        )

    def execute(self, *args, **kwargs) -> Any:
        """Required by BaseAgent ABC — delegates to parse_command()."""
        return self.parse_command(*args, **kwargs)

    def _build_prompt_context(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Build common format kwargs for MULTI_STEP_PROMPT / RECORDER_PROMPT."""
        return dict(
            current_url=ctx.get("url", ""),
            page_title=ctx.get("title", ""),
            input_count=len(ctx.get("inputs", [])),
            inputs_text=_format_inputs(ctx.get("inputs", [])),
            button_count=len(ctx.get("buttons", [])),
            buttons_text=_format_buttons(ctx.get("buttons", [])),
            link_count=len(ctx.get("links", [])),
            links_text=_format_links(ctx.get("links", [])),
            dropdown_count=len(ctx.get("dropdownItems", [])),
            dropdown_text=_format_dropdown_items(ctx.get("dropdownItems", [])),
            table_count=len(ctx.get("tables", [])),
            tables_text=_format_tables(ctx.get("tables", [])),
            modal_count=len(ctx.get("modals", [])),
            modals_text=_format_modals(ctx.get("modals", [])),
        )

    def parse_multi_step_command(self, paragraph: str, page: Any, context_summary: str = "") -> List[Dict[str, Any]]:
        """
        Parse a natural language paragraph into an ordered list of atomic Playwright actions.
        """
        ctx = _scrape_page_context(page)

        context_section = context_summary.strip() if context_summary.strip() else "(none — this is the first test case)"

        prompt = MULTI_STEP_PROMPT.format(
            **self._build_prompt_context(ctx),
            context_summary=context_section,
            paragraph=paragraph,
        )

        logger.info(f"RecorderAgent parsing multi-step: {paragraph!r}")
        raw = self.call_llm(prompt)
        return self._parse_json_array_response(raw)

    def parse_command(self, command: str, page: Any) -> Dict[str, Any]:
        """
        Parse a natural language command using the live page context.
        """
        ctx = _scrape_page_context(page)

        prompt = RECORDER_PROMPT.format(
            **self._build_prompt_context(ctx),
            command=command,
        )

        logger.info(f"RecorderAgent parsing: {command!r}")
        raw = self.call_llm(prompt)
        return self._parse_json_response(raw)

    def execute_action(self, action: Dict[str, Any], page: Any, screenshot_b64: str = "") -> None:
        """
        Execute the parsed action dict on the live Playwright page.

        Args:
            action: Parsed action dict from parse_command / parse_multi_step_command.
            page: Live Playwright page object.
            screenshot_b64: Base64 screenshot taken just before execution (used by image
                            analysis fallback when IMAGE_ANALYSIS_ENABLED=True).

        Raises:
            Exception: if action fails (caller handles screenshot + error logging)
        """
        action_type = action.get("action_type", "")
        selector_expr = action.get("selector", "")
        value = action.get("value", "") or ""

        logger.info(f"Executing {action_type}: selector={selector_expr!r} value={value!r}")

        if action_type == "goto":
            url = value or selector_expr
            # Guard: skip goto if value is not a real URL (LLM sometimes puts module names here)
            if not url or not (url.startswith("http://") or url.startswith("https://")):
                logger.warning(f"Skipping goto — value is not a URL: {url!r}. Use 'click' for UI navigation.")
                return
            # Skip goto if the target is the same as the current page (LLM hallucination guard)
            try:
                current_url = page.url
                if current_url and url and current_url.rstrip("/") == url.rstrip("/"):
                    logger.info(f"Skipping goto — target URL matches current page: {url!r}")
                    return
            except Exception:
                pass
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        elif action_type == "fill":
            self._fill_smart(page, selector_expr, value, action.get("element_name", "") or "", action.get("instruction", ""), screenshot_b64)

        elif action_type == "click":
            instruction = action.get("instruction", "")
            self._click_with_fallback(page, selector_expr, value, instruction, screenshot_b64)

        elif action_type == "select":
            locator = self._resolve_locator(page, selector_expr)
            locator.select_option(value, timeout=10_000)

        elif action_type == "clear":
            locator = self._resolve_locator(page, selector_expr)
            locator.clear(timeout=10_000)

        elif action_type == "press":
            if selector_expr:
                locator = self._resolve_locator(page, selector_expr)
                locator.press(value, timeout=10_000)
            else:
                page.keyboard.press(value)

        elif action_type == "wait":
            if selector_expr:
                locator = self._resolve_locator(page, selector_expr)
                locator.wait_for(timeout=15_000)
            else:
                ms = int(value) if value and value.isdigit() else 1000
                page.wait_for_timeout(ms)

        elif action_type == "assert":
            # Skip useless empty asserts — LLM sometimes emits assert with no selector and no value
            if not selector_expr and not value:
                logger.info("Skipping assert — both selector and value are empty (no-op)")
                return
            from playwright.sync_api import expect  # type: ignore
            instruction = action.get("instruction", "")
            if "url" in instruction.lower():
                if value:
                    expect(page).to_have_url(re.compile(re.escape(value)), timeout=10_000)
                else:
                    logger.info("Skipping URL assert — expected value is empty")
                    return
            elif selector_expr:
                # ── Strategy: extract keywords from the user's instruction, scan
                # the live page for toast/alert/success messages, and match keywords
                # against actual visible text.  This avoids searching for the user's
                # exact prompt wording (which is never on the page).

                # 1. Extract meaningful keywords from instruction
                _skip = {"verify", "check", "assert", "confirm", "ensure", "that",
                         "the", "is", "was", "has", "been", "are", "a", "an", "it",
                         "should", "be", "displayed", "shown", "visible", "page",
                         "popup", "dialog", "modal", "message", "notification"}
                _keywords = [
                    w.strip("'\".,!") for w in instruction.lower().split()
                    if w.strip("'\".,!") not in _skip and len(w.strip("'\".,!")) > 2
                ]
                logger.info(f"Assert keywords from instruction: {_keywords}")

                # 2. Scan the live page for toast/alert/success/popup messages
                _page_messages = self._scan_page_messages(page)
                logger.info(f"Assert scan found {len(_page_messages)} message(s) on page: {_page_messages}")

                # 3. Try to find a page message that matches the keywords
                _matched_text = None
                if _keywords and _page_messages:
                    best_score = 0
                    for msg in _page_messages:
                        msg_lower = msg.lower()
                        score = sum(1 for kw in _keywords if kw in msg_lower)
                        if score > best_score:
                            best_score = score
                            _matched_text = msg
                    if best_score == 0:
                        _matched_text = None

                # 4a. If we matched actual page text, use it
                if _matched_text:
                    try:
                        text_locator = page.get_by_text(_matched_text, exact=False)
                        expect(text_locator.first).to_be_visible(timeout=8_000)
                        logger.info(f"Assert passed via matched page message: {_matched_text!r}")
                        return
                    except Exception:
                        pass

                # 4b. Fall back to value or text extracted from the LLM selector
                _selector_text_match = re.search(r"get_by_text\(['\"](.+?)['\"]", selector_expr)
                _selector_text = _selector_text_match.group(1) if _selector_text_match else None
                if _selector_text:
                    _selector_text = re.sub(
                        r"^(verify|check|assert|confirm|ensure)\s+", "",
                        _selector_text, flags=re.IGNORECASE
                    ).strip()
                _assert_text = value or _selector_text

                if _assert_text:
                    try:
                        text_locator = page.get_by_text(_assert_text, exact=False)
                        expect(text_locator.first).to_be_visible(timeout=8_000)
                        logger.info(f"Assert passed via text search: {_assert_text!r}")
                        return
                    except Exception:
                        pass

                # 4c. Try each keyword individually as a partial text match
                for kw in _keywords:
                    try:
                        text_locator = page.get_by_text(kw, exact=False)
                        if text_locator.count() > 0:
                            expect(text_locator.first).to_be_visible(timeout=3_000)
                            logger.info(f"Assert passed via keyword match: {kw!r}")
                            return
                    except Exception:
                        continue

                # 4d. If any success-like message was found on page at all, pass
                if _page_messages:
                    logger.info(f"Assert passed — success message found on page: {_page_messages[0]!r}")
                    return

                # 4e. Last resort: try the LLM selector directly
                try:
                    locator = self._resolve_locator(page, selector_expr)
                    if value:
                        expect(locator).to_contain_text(value, ignore_case=True, timeout=8_000)
                    else:
                        expect(locator).to_be_visible(timeout=8_000)
                except Exception as assert_err:
                    raise Exception(
                        f"Assert failed: no matching text found on page. "
                        f"Keywords={_keywords}, scanned_messages={_page_messages}, "
                        f"selector={selector_expr!r}. Error: {assert_err}"
                    )

        elif action_type == "screenshot":
            pass  # Caller always takes screenshot; this is a no-op

        # ── Navigation ──────────────────────────────────────────────────────
        elif action_type == "back":
            page.go_back(wait_until="domcontentloaded", timeout=15_000)

        elif action_type == "forward":
            page.go_forward(wait_until="domcontentloaded", timeout=15_000)

        elif action_type == "reload":
            page.reload(wait_until="domcontentloaded", timeout=15_000)

        # ── Mouse ────────────────────────────────────────────────────────────
        elif action_type == "double_click":
            locator = self._resolve_locator(page, selector_expr)
            locator.scroll_into_view_if_needed(timeout=3_000)
            locator.dbl_click(timeout=10_000)

        elif action_type == "right_click":
            locator = self._resolve_locator(page, selector_expr)
            locator.scroll_into_view_if_needed(timeout=3_000)
            locator.click(button="right", timeout=10_000)

        elif action_type == "hover":
            locator = self._resolve_locator(page, selector_expr)
            locator.scroll_into_view_if_needed(timeout=3_000)
            locator.hover(timeout=10_000)

        elif action_type == "drag":
            # selector = source element, value = target selector expression
            source = self._resolve_locator(page, selector_expr)
            target = self._resolve_locator(page, value)
            source.drag_to(target, timeout=15_000)

        elif action_type == "scroll":
            # value = "down"/"up"/"top"/"bottom" or pixel amount or element selector
            _scroll_map = {
                "down": (0, 500), "up": (0, -500),
                "top": None, "bottom": None,
            }
            v_lower = value.lower().strip() if value else "down"
            if v_lower in ("top", "bottom"):
                page.evaluate(f"window.scrollTo(0, {'0' if v_lower == 'top' else 'document.body.scrollHeight'})")
            elif v_lower in ("down", "up"):
                dx, dy = _scroll_map[v_lower]
                page.mouse.wheel(dx, dy)
            elif value and value.lstrip("-").isdigit():
                page.mouse.wheel(0, int(value))
            elif selector_expr:
                self._resolve_locator(page, selector_expr).scroll_into_view_if_needed(timeout=8_000)
            else:
                page.mouse.wheel(0, 500)

        # ── Form controls ────────────────────────────────────────────────────
        elif action_type == "type":
            # press_sequentially — types character by character (good for OTP/autocomplete)
            locator = self._resolve_locator(page, selector_expr)
            locator.clear(timeout=5_000)
            locator.press_sequentially(value, delay=50)

        elif action_type == "check":
            locator = self._resolve_locator(page, selector_expr)
            locator.check(timeout=10_000)

        elif action_type == "uncheck":
            locator = self._resolve_locator(page, selector_expr)
            locator.uncheck(timeout=10_000)

        elif action_type == "upload":
            locator = self._resolve_locator(page, selector_expr)
            locator.set_input_files(value, timeout=10_000)

        # ── Targeted assertions ───────────────────────────────────────────────
        elif action_type in ("assert_visible", "assert_hidden", "assert_text",
                             "assert_value", "assert_url", "assert_title",
                             "assert_count", "assert_enabled", "assert_disabled",
                             "assert_checked", "assert_attribute", "assert_table"):
            # When the LLM couldn't determine a selector for a general "verify X succeeded"
            # prompt, fall back to the robust keyword-scan assert handler instead of failing.
            if not selector_expr and action_type in ("assert_visible", "assert_text"):
                logger.info(f"{action_type} has empty selector — falling back to keyword-scan assert")
                fallback = dict(action)
                fallback["action_type"] = "assert"
                self.execute_action(fallback, page, screenshot_b64)
                return
            self._execute_targeted_assert(page, action_type, selector_expr, value)

        else:
            raise ValueError(f"Unknown action_type: {action_type!r}")

        # Small wait after action for page to settle
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _execute_ir_suggestion(self, page: Any, suggestion: dict, value: str) -> None:
        """
        Central dispatcher: apply the correct Playwright interaction based on
        the widget_type/interaction returned by the vision model.
        """
        selector = suggestion["selector"]
        interaction = suggestion.get("interaction", "fill")
        loc = self._resolve_locator(page, selector)

        if interaction == "fill":
            loc.fill(value, timeout=8_000)

        elif interaction == "type_and_select":
            loc.click(timeout=5_000)
            loc.type(value, delay=60)
            option_sel = (
                f"[role='option']:has-text('{value}')"
                f", [role='listbox'] :has-text('{value}')"
                f", li:has-text('{value}')"
                f", div[class*='option']:has-text('{value}')"
            )
            page.locator(option_sel).first.wait_for(state="visible", timeout=5_000)
            page.locator(option_sel).first.click(timeout=5_000)
            page.wait_for_timeout(500)

        elif interaction == "select_option":
            loc.select_option(label=value, timeout=8_000)

        elif interaction == "click":
            loc.click(timeout=8_000)

        else:
            loc.fill(value, timeout=8_000)

        logger.info(
            f"IR succeeded: {selector!r} via '{interaction}' — {suggestion.get('reasoning', '')}"
        )

    def _fill_smart(self, page: Any, selector_expr: str, value: str, element_name: str = "", instruction: str = "", screenshot_b64: str = "") -> None:
        """Fill a field. Falls back to digits-only on tel inputs for phone fields.
        If all DOM-based attempts fail and image analysis is enabled, uses vision AI
        to suggest alternative selectors + interaction types from the page screenshot."""
        locator = self._resolve_locator(page, selector_expr)
        last_error: Exception = Exception("fill failed")
        try:
            locator.fill(value, timeout=10_000)
            return
        except Exception as e:
            last_error = e

        # Detect phone/tel context
        is_phone = any(kw in (selector_expr + element_name).lower()
                       for kw in ("phone", "tel", "mobile"))
        if is_phone:
            import re as _re
            # Keep all digits from whatever value is given (including country code).
            # Do NOT strip country code — the field adds + automatically.
            # Clear first to remove any pre-filled + sign, then fill with raw digits.
            digits = _re.sub(r'\D', '', value.strip())
            for sel in ["input[type='tel']", "input[type='number']",
                        "input[inputmode='numeric']", "input[inputmode='tel']",
                        "input[placeholder*='phone' i]", "input[placeholder*='number' i]"]:
                try:
                    cand = page.locator(sel).first
                    if cand.count() > 0:
                        cand.clear(timeout=3_000)
                        cand.fill(digits, timeout=8_000)
                        logger.info(f"Phone fill: digits {digits!r} (from {value!r}) on {sel}")
                        return
                except Exception:
                    continue

        # Combobox / autocomplete fallback — for custom dropdowns (Country, Designation, etc.)
        # that look like text inputs but are not fillable via .fill() directly.
        # Strategy: resolve the locator, type the value character-by-character to trigger
        # the dropdown, wait briefly, then click the first matching option.
        try:
            combo = self._resolve_locator(page, selector_expr)
            combo.click(timeout=5_000)
            combo.type(value, delay=60)
            # Wait for a listbox / option list to appear
            option_sel = (
                f"[role='option']:has-text('{value}')"
                f", [role='listbox'] :has-text('{value}')"
                f", li:has-text('{value}')"
                f", div[class*='option']:has-text('{value}')"
                f", div[class*='item']:has-text('{value}')"
            )
            option_locator = page.locator(option_sel).first
            option_locator.wait_for(state="visible", timeout=5_000)
            option_locator.click(timeout=5_000)
            # Wait for dropdown overlay to fully close before next action
            page.wait_for_timeout(500)
            logger.info(f"Combobox fill: typed {value!r} and selected matching option")
            return
        except Exception:
            pass

        # Also try native <select> element in case it has that appearance
        try:
            locator.select_option(label=value, timeout=5_000)
            logger.info(f"Combobox fill: select_option(label={value!r}) succeeded")
            return
        except Exception:
            pass

        # Image-analysis fallback — only when enabled and a screenshot is available
        from app.core.config import settings as _settings
        if _settings.IMAGE_ANALYSIS_ENABLED and screenshot_b64:
            logger.info("Fill failed — trying IR visual reasoning fallback")
            from app.agents.image_analyzer import analyze_screenshot_for_selector
            suggestions = analyze_screenshot_for_selector(
                screenshot_b64=screenshot_b64,
                action_type="fill",
                instruction=instruction or f"Fill {element_name or 'field'} with {value!r}",
                selector=selector_expr,
                error=str(last_error),
            )
            for suggestion in suggestions:
                try:
                    self._execute_ir_suggestion(page, suggestion, value)
                    return
                except Exception:
                    continue

        # Re-raise if nothing worked
        locator.fill(value, timeout=10_000)

    def _scan_page_errors(self, page: Any) -> list:
        """Scan DOM for inline validation/error text. Returns list of strings."""
        try:
            return page.evaluate("""() => {
                const sels = [
                    '[class*="error"]:not(script):not(style)',
                    '[class*="invalid"]:not(script)',
                    '[aria-invalid="true"]',
                    '[role="alert"]',
                    '[class*="danger"]:not(script)',
                    '[class*="help"]:not(script)',
                ];
                const seen = new Set();
                const out = [];
                for (const s of sels) {
                    try {
                        document.querySelectorAll(s).forEach(el => {
                            const t = (el.innerText || '').trim();
                            if (t && t.length > 2 && t.length < 200 && !seen.has(t)) {
                                seen.add(t); out.push(t);
                            }
                        });
                    } catch {}
                }
                return out;
            }""")
        except Exception:
            return []

    def _scan_page_messages(self, page: Any) -> list:
        """Scan DOM for toast/alert/success/popup messages. Returns list of visible text strings."""
        try:
            return page.evaluate("""() => {
                const sels = [
                    '[role="alert"]',
                    '[role="status"]',
                    '[class*="toast"]:not(script):not(style)',
                    '[class*="success"]:not(script):not(style)',
                    '[class*="notification"]:not(script):not(style)',
                    '[class*="snackbar"]:not(script):not(style)',
                    '[class*="message"]:not(script):not(style)',
                    '[class*="popup"]:not(script):not(style)',
                    '[class*="alert"]:not(script):not(style)',
                    '[class*="banner"]:not(script):not(style)',
                    '[class*="modal-body"]:not(script):not(style)',
                    '[class*="dialog"]:not(script):not(style)',
                    '[class*="confirm"]:not(script):not(style)',
                    '[aria-live="polite"]',
                    '[aria-live="assertive"]',
                ];
                const seen = new Set();
                const out = [];
                for (const s of sels) {
                    try {
                        document.querySelectorAll(s).forEach(el => {
                            const style = window.getComputedStyle(el);
                            if (style.display === 'none' || style.visibility === 'hidden') return;
                            const t = (el.innerText || '').trim();
                            if (t && t.length > 2 && t.length < 300 && !seen.has(t)) {
                                seen.add(t); out.push(t);
                            }
                        });
                    } catch {}
                }
                return out;
            }""")
        except Exception:
            return []

    def _execute_targeted_assert(self, page: Any, action_type: str, selector_expr: str, value: str) -> None:
        """
        Execute one of the targeted assert_* action types using Playwright expect() API.
        Each type maps to a specific assertion rather than the generic text-search assert.
        """
        from playwright.sync_api import expect  # type: ignore

        timeout = 8_000

        if action_type == "assert_url":
            pattern = value or selector_expr
            if pattern:
                expect(page).to_have_url(re.compile(re.escape(pattern), re.IGNORECASE), timeout=timeout)
                logger.info(f"assert_url passed: {pattern!r}")
            return

        if action_type == "assert_title":
            expect(page).to_have_title(re.compile(re.escape(value or selector_expr), re.IGNORECASE), timeout=timeout)
            logger.info(f"assert_title passed: {value!r}")
            return

        if action_type == "assert_table":
            # value = comma-separated expected column header names
            # Verify each expected header is visible somewhere in a <th>
            expected_headers = [h.strip() for h in (value or "").split(",") if h.strip()]
            if not expected_headers:
                # Just verify a table exists
                tbl = page.locator("table").first
                expect(tbl).to_be_visible(timeout=timeout)
                logger.info("assert_table passed: table is visible")
                return
            for header in expected_headers:
                try:
                    th_loc = page.locator(f"th:has-text('{header}')").first
                    expect(th_loc).to_be_visible(timeout=timeout)
                    logger.info(f"assert_table header visible: {header!r}")
                except Exception:
                    # Fallback: generic get_by_text
                    expect(page.get_by_text(header, exact=False).first).to_be_visible(timeout=timeout)
                    logger.info(f"assert_table header visible (text fallback): {header!r}")
            return

        # assert_visible handles its own locator internally (with fallback chain)
        # All other assert_* types need a locator resolved here
        if action_type != "assert_visible":
            if not selector_expr:
                raise Exception(f"{action_type}: selector is required but was empty")
            locator = self._resolve_locator(page, selector_expr)

        if action_type == "assert_visible":
            if not selector_expr:
                raise Exception("assert_visible: selector is required but was empty")
            primary_err: Exception = Exception("primary selector failed")

            # Primary: resolve locator + check visibility (both inside try so any failure is caught)
            try:
                _vis_locator = self._resolve_locator(page, selector_expr)
                expect(_vis_locator).to_be_visible(timeout=timeout)
                logger.info(f"assert_visible passed: {selector_expr!r}")
                return
            except Exception as _e:
                primary_err = _e
                logger.warning(f"assert_visible primary selector failed ({selector_expr!r}): {_e}")

            # Fallback 1: extract quoted text from selector and search by visible text
            _txt_match = re.search(r"['\"]([^'\"]{2,})['\"]", selector_expr)
            if _txt_match:
                _txt = _txt_match.group(1)
                _txt = re.sub(r"^(dialog|button|heading|modal|popup|alert)\s*", "", _txt, flags=re.IGNORECASE).strip()
                if _txt:
                    try:
                        expect(page.get_by_text(_txt, exact=False).first).to_be_visible(timeout=timeout)
                        logger.info(f"assert_visible passed via text fallback: {_txt!r}")
                        return
                    except Exception:
                        pass

            # Fallback 2: if selector/instruction mentions modal/dialog/popup, check any open dialog
            _sel_lower = selector_expr.lower()
            if any(kw in _sel_lower for kw in ("dialog", "modal", "popup", "alertdialog")):
                for _modal_sel in ('[role="dialog"]', '[role="alertdialog"]',
                                   '[class*="modal"]', '[class*="dialog"]'):
                    try:
                        expect(page.locator(_modal_sel).first).to_be_visible(timeout=3_000)
                        logger.info(f"assert_visible passed via modal fallback: {_modal_sel!r}")
                        return
                    except Exception:
                        continue

            # Fallback 3: any toast/success message on page counts as a pass
            _msgs = self._scan_page_messages(page)
            if _msgs:
                logger.info(f"assert_visible passed — page message visible: {_msgs[0]!r}")
                return

            raise Exception(
                f"assert_visible: element not found. selector={selector_expr!r}. "
                f"Original error: {primary_err}"
            )

        elif action_type == "assert_hidden":
            expect(locator).to_be_hidden(timeout=timeout)
            logger.info(f"assert_hidden passed: {selector_expr!r}")

        elif action_type == "assert_text":
            expect(locator).to_contain_text(value, ignore_case=True, timeout=timeout)
            logger.info(f"assert_text passed: {value!r} in {selector_expr!r}")

        elif action_type == "assert_value":
            expect(locator).to_have_value(value, timeout=timeout)
            logger.info(f"assert_value passed: {value!r}")

        elif action_type == "assert_count":
            count = int(value) if value and value.isdigit() else 0
            expect(locator).to_have_count(count, timeout=timeout)
            logger.info(f"assert_count passed: {count}")

        elif action_type == "assert_enabled":
            expect(locator).to_be_enabled(timeout=timeout)
            logger.info(f"assert_enabled passed: {selector_expr!r}")

        elif action_type == "assert_disabled":
            expect(locator).to_be_disabled(timeout=timeout)
            logger.info(f"assert_disabled passed: {selector_expr!r}")

        elif action_type == "assert_checked":
            expect(locator).to_be_checked(timeout=timeout)
            logger.info(f"assert_checked passed: {selector_expr!r}")

        elif action_type == "assert_attribute":
            # value format: "attr=expected_value"
            if "=" in value:
                attr_name, _, attr_val = value.partition("=")
                expect(locator).to_have_attribute(attr_name.strip(), attr_val.strip(), timeout=timeout)
                logger.info(f"assert_attribute passed: {attr_name}={attr_val!r}")
            else:
                # Just check attribute exists (non-empty)
                actual = locator.get_attribute(value)
                if actual is None:
                    raise Exception(f"assert_attribute: attribute {value!r} not found on element")
                logger.info(f"assert_attribute passed: {value!r} = {actual!r}")

    def _click_with_fallback(self, page: Any, selector_expr: str, value: str = "", instruction: str = "", screenshot_b64: str = "") -> None:
        """
        Try to click using the primary selector. If it fails (e.g. custom dropdown item
        not matched by role/label), fall back to get_by_text() with the element's display text.

        Fallback chain:
          1. Primary selector from LLM (skipped if empty)
          2. page.get_by_text(value, exact=True/False)  — when value holds the item label
          3. page.get_by_text(display_text)              — extracted from selector expression
          4. page.get_by_text / get_by_role              — keywords extracted from instruction
          5. JS page scan for title/alt/aria-label attrs — handles icon-only buttons
          6. Image analysis (vision AI) — only when IMAGE_ANALYSIS_ENABLED=True
        """
        last_primary_error: Exception = Exception("click failed")

        # Dismiss any open overlays/dropdowns before clicking a button
        # This prevents the click from landing on a stale dropdown overlay
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3_000)
        except Exception:
            pass
        try:
            page.wait_for_timeout(300)
        except Exception:
            pass

        # Step 1: try the primary selector (skip if empty to avoid css parse error)
        if selector_expr and selector_expr.strip():
            try:
                locator = self._resolve_locator(page, selector_expr)
                locator.wait_for(state="visible", timeout=8_000)
                # Scroll into view to ensure element is not behind a sticky header/overlay
                locator.scroll_into_view_if_needed(timeout=3_000)
                locator.click(timeout=10_000)
                return
            except Exception as primary_err:
                last_primary_error = primary_err
                logger.warning(f"Primary click failed ({selector_expr!r}): {primary_err}")
        else:
            logger.warning(f"Empty selector received for click — going straight to fallbacks (instruction={instruction!r})")

        # Fallback 1: use value as text if provided (common for dropdown item clicks)
        if value and value.strip():
            try:
                page.get_by_text(value.strip(), exact=True).first.click(timeout=8_000)
                logger.info(f"Click succeeded via get_by_text(exact) for value={value!r}")
                return
            except Exception:
                pass
            try:
                page.get_by_text(value.strip()).first.click(timeout=8_000)
                logger.info(f"Click succeeded via get_by_text for value={value!r}")
                return
            except Exception:
                pass

        # Fallback 2: extract display text from selector expression itself
        if selector_expr and selector_expr.strip():
            text_match = re.search(r"['\"]([^'\"]{2,})['\"]", selector_expr)
            if text_match:
                display_text = text_match.group(1)
                if display_text.lower() not in ("button", "link", "option", "true", "false"):
                    # Prefer button/link roles before raw text to avoid clicking non-interactive elements
                    try:
                        page.get_by_role("button", name=re.compile(re.escape(display_text), re.IGNORECASE)).first.click(timeout=8_000)
                        logger.info(f"Click succeeded via fallback get_by_role(button) for {display_text!r}")
                        return
                    except Exception:
                        pass
                    try:
                        page.get_by_text(display_text, exact=True).first.click(timeout=8_000)
                        logger.info(f"Click succeeded via fallback get_by_text(exact) for {display_text!r}")
                        return
                    except Exception:
                        pass
                    try:
                        page.get_by_text(display_text).first.click(timeout=8_000)
                        logger.info(f"Click succeeded via fallback get_by_text for {display_text!r}")
                        return
                    except Exception:
                        pass

        # Fallback 3: extract meaningful keywords from instruction and try as text/role selectors
        # e.g. instruction="Click select project dropdown button" → try "select project", "project", etc.
        _skip_words = {"click", "press", "tap", "open", "close", "the", "a", "an", "on",
                       "button", "link", "element", "icon", "menu", "dropdown", "select",
                       "in", "to", "at", "of", "for", "with", "by", "as", "or", "and"}
        if instruction:
            words = [w.strip("'\".,") for w in instruction.lower().split()]
            # Build candidate phrases: pairs of consecutive meaningful words, then singles
            meaningful = [w for w in words if w and w not in _skip_words and len(w) > 2]
            candidates = []
            # Try 3-word, 2-word, then 1-word phrases
            for n in (3, 2, 1):
                for i in range(len(meaningful) - n + 1):
                    phrase = " ".join(meaningful[i:i+n])
                    if phrase not in candidates:
                        candidates.append(phrase)

            for phrase in candidates:
                # Try button role FIRST — avoids falsely "clicking" non-interactive
                # text elements like modal titles that contain the same keyword
                try:
                    page.get_by_role("button", name=re.compile(phrase, re.IGNORECASE)).first.click(timeout=5_000)
                    logger.info(f"Click succeeded via instruction keyword get_by_role(button) for {phrase!r}")
                    return
                except Exception:
                    pass
                try:
                    page.get_by_role("link", name=re.compile(phrase, re.IGNORECASE)).first.click(timeout=5_000)
                    logger.info(f"Click succeeded via instruction keyword get_by_role(link) for {phrase!r}")
                    return
                except Exception:
                    pass
                # get_by_text as last resort for this phrase (may match non-interactive elements)
                try:
                    page.get_by_text(phrase, exact=True).first.click(timeout=5_000)
                    logger.info(f"Click succeeded via instruction keyword get_by_text(exact) for {phrase!r}")
                    return
                except Exception:
                    pass

        # Fallback 4: JavaScript page scan — match by title/alt/aria-label attributes
        # Handles icon buttons that have no visible text (e.g. sidebar Collapse button)
        try:
            buttons = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('button, [role="button"]'))
                    .filter(el => {
                        const s = window.getComputedStyle(el);
                        return s.display !== 'none' && s.visibility !== 'hidden' && el.offsetParent !== null;
                    })
                    .map(el => ({
                        title: (el.getAttribute('title') || '').trim(),
                        ariaLabel: (el.getAttribute('aria-label') || '').trim(),
                        alt: (el.querySelector('img') ? el.querySelector('img').getAttribute('alt') || '' : '').trim(),
                        text: (el.innerText || '').trim()
                    }));
            }""")
            # Reuse `meaningful` computed in Fallback 3; if instruction was empty, build it now
            if not instruction:
                meaningful = []
            for btn in buttons:
                attrs = {
                    'title': btn.get('title', ''),
                    'ariaLabel': btn.get('ariaLabel', ''),
                    'alt': btn.get('alt', ''),
                    'text': btn.get('text', ''),
                }
                all_lower = ' '.join(attrs.values()).lower()
                # Check if any meaningful keyword from instruction matches any attribute
                if meaningful and any(kw in all_lower for kw in meaningful):
                    if attrs['title']:
                        try:
                            page.locator(f'button[title="{attrs["title"]}"]').first.click(timeout=5_000)
                            logger.info(f"Click succeeded via title attribute: title={attrs['title']!r}")
                            return
                        except Exception:
                            pass
                    if attrs['ariaLabel']:
                        try:
                            page.get_by_role('button', name=attrs['ariaLabel']).first.click(timeout=5_000)
                            logger.info(f"Click succeeded via aria-label: {attrs['ariaLabel']!r}")
                            return
                        except Exception:
                            pass
                    if attrs['alt']:
                        try:
                            page.locator(f'button:has(img[alt="{attrs["alt"]}"])').first.click(timeout=5_000)
                            logger.info(f"Click succeeded via img alt: {attrs['alt']!r}")
                            return
                        except Exception:
                            pass
        except Exception as scan_err:
            logger.debug(f"JS button scan failed: {scan_err}")

        # Fallback 5: common submit/login button text variants
        # Handles apps where the button is "Log In", "Log in", "Sign In", "Submit", etc.
        _instruction_lower = (instruction or "").lower()
        _submit_variants: list[str] = []
        if any(kw in _instruction_lower for kw in ("login", "log in", "sign in", "signin")):
            _submit_variants = ["Log In", "Log in", "log in", "LOGIN", "Login",
                                 "Sign In", "Sign in", "SIGN IN", "signin", "Submit"]
        elif any(kw in _instruction_lower for kw in ("submit", "save", "confirm", "create", "add")):
            _submit_variants = ["Submit", "Save", "Confirm", "Create", "Add",
                                 "submit", "save", "confirm", "create", "add"]
        for variant in _submit_variants:
            try:
                page.get_by_role("button", name=variant).first.click(timeout=5_000)
                logger.info(f"Click succeeded via submit variant: {variant!r}")
                return
            except Exception:
                pass
            try:
                page.get_by_text(variant, exact=True).first.click(timeout=5_000)
                logger.info(f"Click succeeded via submit text variant: {variant!r}")
                return
            except Exception:
                pass

        # Fallback 6: image analysis — ask vision AI to identify the element
        from app.core.config import settings as _settings
        if _settings.IMAGE_ANALYSIS_ENABLED and screenshot_b64:
            logger.info("Click failed — trying IR visual reasoning fallback")
            from app.agents.image_analyzer import analyze_screenshot_for_selector
            suggestions = analyze_screenshot_for_selector(
                screenshot_b64=screenshot_b64,
                action_type="click",
                instruction=instruction or selector_expr,
                selector=selector_expr,
                error=str(last_primary_error),
            )
            for suggestion in suggestions:
                try:
                    # Vision may return interaction="click" or override to something smarter
                    # Always use the dispatcher so it logs reasoning
                    self._execute_ir_suggestion(page, suggestion, value or "")
                    return
                except Exception:
                    continue

        # All fallbacks exhausted — raise descriptive error
        raise Exception(f"Click failed for selector {selector_expr!r} (instruction={instruction!r}). All fallbacks exhausted.")

    def _resolve_locator(self, page: Any, selector_expr: str) -> Any:
        """
        Convert a selector expression string to a real Playwright locator.
        Supports expressions like:
          page.get_by_label('Email')
          page.get_by_placeholder('Enter password')
          page.get_by_role('button', name='Login')
          page.locator('input[type="email"]')
          input[type="email"]   (bare CSS selector)
        """
        expr = selector_expr.strip()

        # Try to parse known patterns
        # 1. page.get_by_label('...')
        m = re.match(r"page\.get_by_label\(['\"](.+?)['\"]\)", expr)
        if m:
            return page.get_by_label(m.group(1))

        # 2. page.get_by_placeholder('...')
        m = re.match(r"page\.get_by_placeholder\(['\"](.+?)['\"]\)", expr)
        if m:
            return page.get_by_placeholder(m.group(1))

        # 3. page.get_by_role('role', name='text')
        m = re.match(r"page\.get_by_role\(['\"](\w+)['\"](?:,\s*name=['\"](.+?)['\"])?\)", expr)
        if m:
            role, name = m.group(1), m.group(2)
            if name:
                return page.get_by_role(role, name=name)
            return page.get_by_role(role)

        # 4. page.get_by_text('...') or page.get_by_text('...', exact=True/False)
        m = re.match(r"page\.get_by_text\(['\"](.+?)['\"](?:,\s*exact=(True|False))?\)", expr)
        if m:
            text = m.group(1)
            exact_str = m.group(2)
            if exact_str is not None:
                return page.get_by_text(text, exact=(exact_str == "True"))
            return page.get_by_text(text)

        # 5. page.locator('...')
        m = re.match(r"page\.locator\(['\"](.+?)['\"]\)", expr)
        if m:
            return page.locator(m.group(1))

        # 6. Bare CSS / XPath selector fallback
        return page.locator(expr)

    def _parse_json_response(self, raw: str) -> Dict[str, Any]:
        """Extract and parse JSON object from LLM response."""
        raw = raw.strip()

        # Strip markdown code fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        # Find JSON object boundaries
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}\nRaw: {raw[:300]}")
            # Return a safe fallback
            return {
                "action_type": "wait",
                "selector": "",
                "value": "1000",
                "instruction": f"Paused (could not parse: {raw[:60]})",
                "playwright_method": "page.wait_for_timeout()",
                "element_name": None,
                "element_type": None,
                "test_data": None,
            }

    def _parse_json_array_response(self, raw: str) -> List[Dict[str, Any]]:
        """Extract and parse JSON array from LLM response. Falls back to single-item list."""
        raw = raw.strip()

        # Strip markdown code fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        # Try to find a JSON array first
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start != -1 and end > start:
            candidate = raw[start:end]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass

        # Try to parse as a single JSON object and wrap in list
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            candidate = raw[start:end]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    logger.warning("Multi-step LLM returned a single object, wrapping in list")
                    return [parsed]
            except json.JSONDecodeError:
                pass

        logger.error(f"Could not parse JSON array from response:\n{raw[:300]}")
        # Return a safe fallback — a single wait step
        return [{
            "action_type": "wait",
            "selector": "",
            "value": "1000",
            "instruction": "Paused (could not parse LLM response)",
            "playwright_method": "page.wait_for_timeout()",
            "element_name": None,
            "element_type": None,
            "test_data": None,
        }]
