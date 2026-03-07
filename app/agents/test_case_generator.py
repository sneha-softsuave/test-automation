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

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

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
        buttons = page_structure.get("buttons", [])
        headings = page_structure.get("headings", [])
        links = page_structure.get("links", [])

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
