"""
Enhanced JSON Parser Agent - Generates rich test case structure with Playwright hints.
Outputs comprehensive test suite with selectors, assertions, and test data.
"""
import json
from typing import List, Dict, Any, Optional

from app.agents.base_agent import BaseAgent, LLMProvider


ENHANCED_PARSER_PROMPT = '''Convert the test case data into Playwright-optimized JSON structure.

⚠️ **CRITICAL: You must ONLY output valid JSON. Do NOT write code, explanations, or any text outside the JSON structure.**

INPUT DATA:
{content}

PROJECT: {project_name}
BASE URL: {base_url}

⚠️ **CRITICAL INSTRUCTION - HANDLING SEPARATE INPUT DATA COLUMN:**

The input JSON may contain a separate "Input data" or "Input Values" field with key-value pairs that provide actual test values.

**YOUR TASK:**
1. First, check if there is an "Input data" field in the input
2. If present, parse it to extract all key-value pairs (format: "Key: Value")
3. When processing each test step, check if the step references any key from Input data
4. Use the value from Input data instead of any placeholder or generic text in the step

**KEY MATCHING RULES:**
- Match keys case-insensitively (e.g., "Application URL" matches "application url" in step)
- Keys commonly found in steps:
  * "Application URL" or "URL" → navigation URLs
  * "Expected URL" → assertion URLs
  * "Email" → email addresses
  * "Password" → passwords
  * "Expected Toast Message" → toast message text
  * "Expected heading" or "Expected dashboard heading" → page heading text
  * "Project Name" → dropdown selection values
  * "Test data" → large text inputs (incident descriptions, etc.)
  * "Expected status" or "incident status" → status values
  * Button names, element text, any labeled data

**MATCHING EXAMPLES:**

Example 1 - Simple URL:
```
Step: "Launch the web application using the application URL:"
Input data: "Application URL: https://dev-emergex.zapptor.com/"
→ Extract: test_data = {{"url": "https://dev-emergex.zapptor.com/"}}
```

Example 2 - Credentials:
```
Step: "Enter a valid email address in the Email field"
Input data: "Email: Naif.Otaibi@aramcooverseas.com"
→ Extract: test_data = {{"email": "Naif.Otaibi@aramcooverseas.com"}}
```

Example 3 - Assertion Value:
```
Step: "Verify that a success toast message is displayed with the Expected Toast Message"
Input data: "Expected Toast Message: 'Login successful'"
→ Extract: assertions = [{{"type": "toast", "expected_value": "Login successful"}}]
```

Example 4 - Multiple Keys:
```
Step 1: "Verify URL with Expected URL:"
Step 2: "Verify heading with Expected dashboard heading"
Input data: "Expected URL: https://dev-emergex.zapptor.com/login\nExpected dashboard heading: 'Dashboard'"
→ Step 1 gets: assertions = [{{"type": "url", "expected_value": "https://dev-emergex.zapptor.com/login"}}]
→ Step 2 gets: assertions = [{{"type": "heading", "expected_value": "Dashboard"}}]
```

Example 5 - Multi-line Values:
```
Step: "Enter valid input data in the field with test data"
Input data: "Test data: 'An equipment malfunction occurred on September 24, 2025...'"
→ Extract: test_data = {{"text": "An equipment malfunction occurred on September 24, 2025..."}}
```

**BACKWARD COMPATIBILITY:**
If "Input data" field is missing or empty, extract values from step text as you currently do.

---

OUTPUT THIS EXACT JSON STRUCTURE:

{{
  "project": "{project_name}",
  "base_url": "{base_url}",
  "common_selectors": {{
    "login": {{
      "email_field": "page.getByLabel('Email') or page.locator('input[type=\"email\"]')",
      "password_field": "page.getByLabel('Password') or page.locator('input[type=\"password\"]')",
      "login_button": "page.getByRole('button', {{ name: 'Login' }})"
    }},
    "navigation": {{
      "sidebar": "page.locator('.sidebar') or page.getByRole('navigation')",
      "dashboard_heading": "page.getByRole('heading', {{ name: 'Dashboard' }})"
    }},
    "common_elements": {{
      "toast_message": "page.locator('.toast, .Toastify, [role=\"alert\"]')",
      "loader": "page.locator('.loader, .loading, [class*=\"spinner\"]')",
      "popup": "page.locator('.modal, [role=\"dialog\"]')",
      "continue_button": "page.getByRole('button', {{ name: 'Continue' }})",
      "submit_button": "page.getByRole('button', {{ name: 'Submit' }})",
      "add_button": "page.getByRole('button', {{ name: /add/i }})"
    }}
  }},
  "test_data": {{
    "default_credentials": {{
      "email": "EXTRACT_FROM_INPUT",
      "password": "EXTRACT_FROM_INPUT"
    }}
  }},
  "test_cases": [
    {{
      "id": "TC_001",
      "name": "Test Case Name from input",
      "steps": [
        {{
          "step_number": 1,
          "instruction": "Original step text from input",
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
            "url": "https://example.com/"
          }},
          "assertions": null
        }},
        {{
          "step_number": 2,
          "instruction": "Verify URL step",
          "action": {{
            "type": "assert",
            "playwright_method": "expect()"
          }},
          "selector_hints": {{
            "element_name": null,
            "element_type": null,
            "suggested_selectors": []
          }},
          "test_data": {{
            "url": "https://example.com/login"
          }},
          "assertions": [
            {{
              "type": "url",
              "expected_value": "https://example.com/login",
              "playwright_assertion": "expect(page).toHaveURL()"
            }}
          ]
        }},
        {{
          "step_number": 3,
          "instruction": "Enter email in Email field",
          "action": {{
            "type": "fill",
            "playwright_method": "page.fill() / locator.fill()"
          }},
          "selector_hints": {{
            "element_name": "Email",
            "element_type": "input",
            "suggested_selectors": [
              "page.getByLabel('Email')",
              "page.getByPlaceholder('Email')",
              "page.locator('input[name=\"email\"]')"
            ]
          }},
          "test_data": {{
            "email": "user@example.com"
          }},
          "assertions": null
        }},
        {{
          "step_number": 4,
          "instruction": "Click Login button",
          "action": {{
            "type": "click",
            "playwright_method": "page.click() / locator.click()"
          }},
          "selector_hints": {{
            "element_name": "Login",
            "element_type": "button",
            "suggested_selectors": [
              "page.getByRole('button', {{ name: 'Login' }})",
              "page.getByText('Login')",
              "page.locator('button:has-text(\"Login\")')"
            ]
          }},
          "test_data": null,
          "assertions": null
        }},
        {{
          "step_number": 5,
          "instruction": "Verify toast message",
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
              "type": "toast",
              "expected_value": "Login successful",
              "playwright_assertion": "expect(page.locator('.toast')).toContainText()"
            }}
          ]
        }},
        {{
          "step_number": 6,
          "instruction": "Verify heading",
          "action": {{
            "type": "assert",
            "playwright_method": "expect()"
          }},
          "selector_hints": {{
            "element_name": "Dashboard",
            "element_type": "heading",
            "suggested_selectors": [
              "page.getByRole('heading', {{ name: 'Dashboard' }})",
              "page.getByText('Dashboard')"
            ]
          }},
          "test_data": null,
          "assertions": [
            {{
              "type": "heading",
              "expected_value": "Dashboard",
              "playwright_assertion": "expect(page.getByRole('heading')).toContainText()"
            }}
          ]
        }}
      ],
      "expected_results": [
        "Result 1 from input",
        "Result 2 from input"
      ]
    }}
  ]
}}

ACTION TYPES:
- goto: page.goto()
- fill: page.fill() / locator.fill()
- click: page.click() / locator.click()
- assert: expect()
- wait: page.waitForSelector() / page.waitForTimeout()
- select: page.selectOption()
- upload: page.setInputFiles()
- capture: locator.textContent() / page.url()

ASSERTION TYPES: url, text, heading, toast, status, element, visible, enabled

RULES:
1. Parse EVERY step from input - do not skip any
2. **Check for "Input data" or "Input Values" field first**
3. **Parse Input data into key-value pairs (format: "Key: Value")**
4. **For each step, check if it references any key from Input data**
5. **Use values from Input data when matching keys are found - this takes priority over values in step text**
6. Extract credentials into test_data.default_credentials (prioritize Input data)
7. For fill/click actions, provide 2-3 suggested_selectors using getByLabel, getByRole, getByPlaceholder, locator
8. Use null for fields that don't apply
9. Keep original instruction text
10. **CRITICAL: Return ONLY valid JSON - no Python code, no markdown blocks, no explanations, no extra text. Start directly with {{ and end with }}**

**KEY-VALUE MATCHING EXAMPLES:**

Example 1 - URL Navigation:
- Step: "Launch the web application using the application URL:"
- Input data: "Application URL: https://dev-emergex.zapptor.com/"
- Result: test_data = {{"url": "https://dev-emergex.zapptor.com/"}}

Example 2 - Form Fill:
- Step: "Enter email in Email field"
- Input data: "Email: Naif.Otaibi@aramcooverseas.com"
- Result: test_data = {{"email": "Naif.Otaibi@aramcooverseas.com"}}

Example 3 - Assertion:
- Step: "Verify toast message with Expected Toast Message"
- Input data: "Expected Toast Message: Login successful"
- Result: assertions = [{{"type": "toast", "expected_value": "Login successful"}}]

Example 4 - Multiple Similar Keys:
- Step 1: "Verify URL with Expected URL"
- Step 2: "Verify toast with Expected Toast Message"
- Input data: "Expected URL: https://.../login\nExpected Toast Message: Success"
- Match "Expected URL" to step 1, "Expected Toast Message" to step 2 (exact key match)

---

⚠️ **FINAL REMINDER: Output ONLY the JSON object. Do NOT include:
- Python code or any programming language code
- Markdown code blocks or backticks
- Explanatory text before or after the JSON
- Comments or notes
START your response with {{ and END with }}**

⚠️ **CRITICAL JSON SYNTAX:**
- ALWAYS add commas between object properties: {{"key1": "value1", "key2": "value2"}}
- ALWAYS add commas between array elements: ["item1", "item2", "item3"]
- NEVER forget commas after closing }} or ]] when followed by another property
- Check every closing bracket: }}, then comma if more properties follow

JSON:'''


class EnhancedJsonParserAgent(BaseAgent):
    """
    Enhanced JSON Parser Agent - Generates comprehensive test case structure.
    """

    def __init__(self, provider: LLMProvider = LLMProvider.GROQ, model: str = None):
        from app.core.config import settings
        super().__init__(
            provider=provider,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            openai_api_key=settings.OPENAI_API_KEY,
            groq_api_key=settings.GROQ_API_KEY,
            openai_model=model if provider == LLMProvider.OPENAI else None,
            groq_model=model if provider == LLMProvider.GROQ else None,
            anthropic_model=model if provider == LLMProvider.ANTHROPIC else None,
        )

    def execute(self, raw_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """Execute the agent's main task."""
        return self.parse_to_enhanced_structure(
            raw_data=raw_data,
            project_name=kwargs.get("project_name", "Automation Project"),
            base_url=kwargs.get("base_url")
        )

    def parse_to_enhanced_structure(
        self,
        raw_data: List[Dict[str, Any]],
        project_name: str = "Automation Project",
        base_url: str = None
    ) -> Dict[str, Any]:
        """Parse raw test case data into enhanced structure."""
        if not base_url:
            base_url = self._extract_base_url(raw_data)

        content = json.dumps(raw_data, indent=2)

        prompt = ENHANCED_PARSER_PROMPT.format(
            content=content,
            project_name=project_name,
            base_url=base_url or "https://example.com"
        )

        response_text = self.call_llm(prompt)
        response_text = self._clean_json_response(response_text)

        try:
            result = json.loads(response_text)
            result = self._post_process(result, project_name, base_url)
            return result
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error (first attempt): {e}")
            # Try fixing invalid escape sequences
            try:
                fixed_text = self._fix_invalid_escapes(response_text)
                print("Attempting to parse with fixed escape sequences...")
                result = json.loads(fixed_text)
                result = self._post_process(result, project_name, base_url)
                print("Successfully parsed after fixing escapes!")
                return result
            except json.JSONDecodeError as e2:
                print(f"JSON Parse Error (after fix attempt): {e2}")
                # Try repairing truncated JSON
                try:
                    repaired_text = self._repair_truncated_json(fixed_text)
                    print("Attempting to parse with truncation repair...")
                    result = json.loads(repaired_text)
                    result = self._post_process(result, project_name, base_url)
                    print("Successfully parsed after truncation repair!")
                    return result
                except json.JSONDecodeError as e3:
                    print(f"JSON Parse Error (after repair attempt): {e3}")
                    print(f"Response was: {response_text[:1500]}...")
                    raise ValueError(f"Failed to parse JSON response: {e3}")

    def _extract_base_url(self, raw_data: List[Dict[str, Any]]) -> Optional[str]:
        """Try to extract base URL from test data."""
        import re
        for item in raw_data:
            steps = item.get("Test Case Steps", "") or item.get("steps", "")
            if isinstance(steps, str):
                urls = re.findall(r'https?://[^\s<>"]+', steps)
                if urls:
                    url = urls[0].rstrip('/')
                    parts = url.split('/')
                    if len(parts) >= 3:
                        return '/'.join(parts[:3])
        return None

    def _fix_invalid_escapes(self, text: str) -> str:
        """Fix invalid escape sequences in JSON string.

        LLMs often produce invalid escapes like \s, \d, \w which are
        valid in regex but not in JSON. This fixes them.

        Also fixes unescaped quotes inside strings (common LLM mistake).
        """
        import re

        # First, try to fix unescaped quotes inside attribute selectors
        # Pattern: 'input[type="something"]' -> 'input[type=\"something\"]'
        # This is a common LLM mistake in selector strings
        text = self._fix_unescaped_quotes_in_selectors(text)

        # Valid JSON escape sequences
        valid_escapes = {'\\n', '\\r', '\\t', '\\b', '\\f', '\\"', '\\\\', '\\/'}

        # Fix invalid escapes by doubling the backslash or removing it
        # This regex finds backslash followed by a character that's not a valid escape
        def fix_escape(match):
            escape_seq = match.group(0)
            if escape_seq in valid_escapes:
                return escape_seq
            # Check for unicode escapes like \uXXXX
            if len(escape_seq) >= 2 and escape_seq[1] == 'u':
                return escape_seq
            # For invalid escapes, double the backslash to escape it
            return '\\\\' + escape_seq[1:]

        # Find all escape sequences and fix invalid ones
        result = re.sub(r'\\[^"\\\/bfnrtu]', fix_escape, text)
        return result

    def _fix_unescaped_quotes_in_selectors(self, text: str) -> str:
        """
        Fix unescaped quotes inside CSS/XPath selectors in JSON strings.

        LLMs often generate:
          "selector": "input[type="email"]"
        which should be:
          "selector": "input[type=\"email\"]"

        This method attempts to fix these by identifying attribute selectors
        and escaping the inner quotes.
        """
        import re

        # Pattern to find attribute selectors with unescaped quotes
        # Matches: [attr="value"] or [attr='value'] inside a larger string
        # We need to be careful not to break already escaped quotes

        def fix_attr_selector(match):
            """Fix a single attribute selector match."""
            full_match = match.group(0)
            attr_name = match.group(1)
            quote_char = match.group(2)
            attr_value = match.group(3)

            # If it's a double quote, escape it
            if quote_char == '"':
                return f'[{attr_name}=\\"{attr_value}\\"]'
            return full_match

        # Pattern: [attribute="value"] where the quotes are not escaped
        # Negative lookbehind to avoid already escaped quotes
        pattern = r'\[(\w+(?:-\w+)*)=(?<!\\)"([^"\\]*)"(?<!\\)\]'
        result = re.sub(pattern, fix_attr_selector, text)

        # Also try a more aggressive fix for patterns like:
        # page.locator('input[type="email"]')
        # These appear inside JSON strings and the " needs to be \"

        # Find strings that look like selectors with attribute values
        def fix_selector_string(line):
            """Fix a single line with potential unescaped quotes."""
            # Pattern: word[attr="value"]
            # We need to escape the inner quotes
            fixed = re.sub(
                r'(\w+\[\w+)="([^"]*)"(\])',
                r'\1=\\"\2\\"\3',
                line
            )
            return fixed

        # Process line by line to avoid breaking the overall JSON structure
        lines = result.split('\n')
        fixed_lines = []
        for line in lines:
            # Only fix lines that look like they contain selectors
            if '[type=' in line or '[name=' in line or '[id=' in line or '[class=' in line:
                # Check if the line has unescaped quotes in selectors
                if re.search(r'\[\w+="[^"]*"(?!\\)\]', line):
                    line = fix_selector_string(line)
            fixed_lines.append(line)

        return '\n'.join(fixed_lines)

    def _repair_truncated_json(self, text: str) -> str:
        """
        Attempt to repair truncated JSON by closing open strings, arrays, and objects.
        This handles cases where the LLM output was cut off mid-response.
        """
        print(f"Attempting truncation repair on {len(text)} chars...")

        # Step 1: Try to find the last complete test_case and truncate there
        # Look for the pattern of a complete test case ending
        import re

        # Find the last occurrence of a complete step (ends with }])
        # Pattern: a step object followed by ] which closes the steps array
        last_complete_step = text.rfind('"assertions": []')
        if last_complete_step == -1:
            last_complete_step = text.rfind('"assertions": [')

        if last_complete_step > 0:
            # Find the closing of this step object
            pos = last_complete_step
            brace_count = 0
            in_string = False
            escape_next = False

            # First, find where we are in the structure
            for i in range(pos, len(text)):
                char = text[i]
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                    elif char == ']' and brace_count == 0:
                        # Found end of steps array, look for end of test_case
                        end_pos = text.find('}', i)
                        if end_pos > i:
                            # Check if we can close properly
                            remaining = text[end_pos + 1:].lstrip()
                            if remaining.startswith(',') or remaining.startswith(']'):
                                # Find the last complete test case
                                last_tc_end = text.rfind('}', 0, end_pos + 100)
                                if last_tc_end > 0:
                                    print(f"Found potential truncation point at char {last_tc_end}")

        # Step 2: Count unclosed brackets and braces
        open_braces = 0
        open_brackets = 0
        in_string = False
        escape_next = False
        last_valid_pos = 0

        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char == '{':
                    open_braces += 1
                elif char == '}':
                    open_braces -= 1
                    if open_braces >= 0:
                        last_valid_pos = i
                elif char == '[':
                    open_brackets += 1
                elif char == ']':
                    open_brackets -= 1
                    if open_brackets >= 0:
                        last_valid_pos = i

        # Step 3: If we're in an unclosed string, try to close it
        if in_string:
            # Find the last unclosed quote and close the string
            text = text.rstrip()
            if not text.endswith('"'):
                text += '"'
            in_string = False

        # Step 4: Recount after string fix
        open_braces = 0
        open_brackets = 0
        in_string = False
        escape_next = False

        for char in text:
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char == '{':
                    open_braces += 1
                elif char == '}':
                    open_braces -= 1
                elif char == '[':
                    open_brackets += 1
                elif char == ']':
                    open_brackets -= 1

        # Step 5: Close unclosed brackets and braces
        closing = ''

        # Remove trailing comma if present
        text = text.rstrip()
        if text.endswith(','):
            text = text[:-1]

        # Add null if we ended mid-value
        if text.endswith(':'):
            text += ' null'
        if text.endswith(': '):
            text += 'null'

        # Close brackets and braces in correct order
        # We need to be smart about the order
        for _ in range(open_brackets):
            closing += ']'
        for _ in range(open_braces):
            closing += '}'

        repaired = text + closing
        print(f"Repair: closed {open_brackets} brackets and {open_braces} braces")
        return repaired

    def _clean_json_response(self, response_text: str) -> str:
        """Clean up response - extract valid JSON."""
        response_text = response_text.strip()

        # Remove markdown code blocks
        if "```" in response_text:
            lines = response_text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_json = not in_json
                    continue
                if in_json:
                    json_lines.append(line)
            if json_lines:
                response_text = "\n".join(json_lines)

        response_text = response_text.strip()

        # Find start of JSON
        if not response_text.startswith("{"):
            start = response_text.find("{")
            if start != -1:
                response_text = response_text[start:]

        # Find matching closing brace
        if response_text.startswith("{"):
            brace_count = 0
            end_pos = 0
            in_string = False
            escape_next = False

            for i, char in enumerate(response_text):
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end_pos = i + 1
                            break

            if end_pos > 0:
                response_text = response_text[:end_pos]

        return response_text.strip()

    def _fix_action_types(self, result: Dict) -> Dict:
        """Fix incorrectly assigned action types based on instruction keywords.

        LLMs sometimes assign 'goto' to verification steps that should be 'assert'.
        This post-processes the result to correct these misassignments.
        """
        assertion_keywords = ['verify', 'confirm', 'check', 'validate', 'ensure', 'assert', 'should']
        navigation_keywords = ['navigate', 'go to', 'open', 'visit', 'launch']

        for tc in result.get("test_cases", []):
            for step in tc.get("steps", []):
                instruction = (step.get("instruction") or "").lower()
                action = step.get("action", {})
                action_type = action.get("type", "")

                # If instruction contains assertion keywords but action is 'goto'
                if action_type == "goto" and any(kw in instruction for kw in assertion_keywords):
                    # Make sure it's not actually a navigation step
                    is_navigation = any(kw in instruction for kw in navigation_keywords)

                    if not is_navigation:
                        # This is a verification step, not navigation - fix the action type
                        action["type"] = "assert"
                        action["playwright_method"] = "expect()"

                        # Ensure assertions array exists with appropriate type
                        if not step.get("assertions"):
                            if "url" in instruction:
                                step["assertions"] = [{
                                    "type": "url",
                                    "expected_value": "",
                                    "playwright_assertion": "expect(page).toHaveURL()"
                                }]
                            elif "heading" in instruction or "title" in instruction:
                                step["assertions"] = [{
                                    "type": "heading",
                                    "expected_value": "",
                                    "playwright_assertion": "expect(page.getByRole('heading')).toContainText()"
                                }]
                            elif "text" in instruction or "message" in instruction:
                                step["assertions"] = [{
                                    "type": "text",
                                    "expected_value": "",
                                    "playwright_assertion": "expect(page.locator('body')).toContainText()"
                                }]
                            else:
                                # Default to element visibility assertion
                                step["assertions"] = [{
                                    "type": "visible",
                                    "expected_value": "",
                                    "playwright_assertion": "expect(locator).toBeVisible()"
                                }]

                        print(f"    [Parser] Fixed action type: goto -> assert for step: {instruction[:50]}...")

        return result

    def _post_process(self, result: Dict, project_name: str, base_url: str) -> Dict:
        """Post-process and validate the result."""
        if "project" not in result:
            result["project"] = project_name
        if "base_url" not in result:
            result["base_url"] = base_url or "https://example.com"
        if "common_selectors" not in result:
            result["common_selectors"] = {
                "login": {},
                "navigation": {},
                "common_elements": {}
            }
        if "test_data" not in result:
            result["test_data"] = {}
        if "test_cases" not in result:
            result["test_cases"] = []

        for idx, tc in enumerate(result.get("test_cases", [])):
            # Ensure each test case has a consistent ID
            if "id" not in tc or not tc["id"]:
                tc["id"] = f"TC_{idx + 1:03d}"
            else:
                # Normalize ID format to TC_XXX
                existing_id = tc["id"]
                # Extract number and reformat
                nums = ''.join(filter(str.isdigit, existing_id))
                if nums:
                    tc["id"] = f"TC_{int(nums):03d}"
                else:
                    tc["id"] = f"TC_{idx + 1:03d}"

            if "steps" not in tc:
                tc["steps"] = []
            if "expected_results" not in tc:
                tc["expected_results"] = []

            for step in tc.get("steps", []):
                if "action" not in step:
                    step["action"] = {"type": "custom", "playwright_method": "custom"}
                if "selector_hints" not in step:
                    step["selector_hints"] = {"element_name": None, "element_type": None, "suggested_selectors": []}

        # Fix incorrectly assigned action types (e.g., goto -> assert for verification steps)
        result = self._fix_action_types(result)

        return result

    def get_statistics(self, result: Dict) -> Dict[str, Any]:
        """Get statistics about the parsed test suite."""
        total_steps = sum(len(tc.get("steps", [])) for tc in result.get("test_cases", []))
        total_assertions = sum(
            len(step.get("assertions", []) or [])
            for tc in result.get("test_cases", [])
            for step in tc.get("steps", [])
        )

        action_types = {}
        for tc in result.get("test_cases", []):
            for step in tc.get("steps", []):
                action_type = step.get("action", {}).get("type", "unknown")
                action_types[action_type] = action_types.get(action_type, 0) + 1

        return {
            "total_test_cases": len(result.get("test_cases", [])),
            "total_steps": total_steps,
            "total_assertions": total_assertions,
            "action_type_breakdown": action_types,
            "has_common_selectors": bool(result.get("common_selectors")),
            "has_test_data": bool(result.get("test_data"))
        }
