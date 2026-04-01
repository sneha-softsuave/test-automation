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

⚠️ **CRITICAL INSTRUCTION - COLUMN ROLES:**

The input JSON has these columns with STRICTLY defined roles:
- **"Test Case Steps"** → These are the ONLY source of steps. Convert each line into a step object.
- **"Input data" / "Input Values"** → Provides actual values (credentials, URLs, etc.) to inject into steps.
- **"Expected Result"** → This is METADATA ONLY. Its lines must go into `expected_results[]` array. **NEVER turn Expected Result lines into step objects.**

⚠️ **HANDLING SEPARATE INPUT DATA COLUMN:**

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
      "email_field": "page.locator('input[type=\"email\"]')",
      "password_field": "page.locator('input[type=\"password\"]')",
      "login_button": "page.get_by_role('button', name='Log in', exact=False)"
    }},
    "navigation": {{
      "sidebar": "page.locator('.sidebar')",
      "dashboard_heading": "page.get_by_role('heading').first()"
    }},
    "common_elements": {{
      "toast_message": "page.locator('.toast, .Toastify, [role=\"alert\"]')",
      "loader": "page.locator('.loader, .loading, [class*=\"spinner\"]')",
      "popup": "page.locator('.modal, [role=\"dialog\"]')",
      "continue_button": "page.get_by_role('button', name='Continue', exact=False)",
      "submit_button": "page.get_by_role('button', name='Submit', exact=False)",
      "add_button": "page.get_by_role('button', name='Add', exact=False)"
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
              "page.locator('input[type=\"email\"]')",
              "page.get_by_placeholder('Enter your email')",
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
            "element_name": "Log in",
            "element_type": "button",
            "suggested_selectors": [
              "page.get_by_role('button', name='Log in', exact=False)",
              "page.locator('button[type=\"submit\"]')",
              "page.get_by_role('button').filter(has_text='login')"
            ]
          }},
          "test_data": null,
          "assertions": null
        }},
        {{
          "step_number": 4,
          "instruction": "Select 'MyProject' from the Project dropdown",
          "action": {{
            "type": "select",
            "playwright_method": "page.selectOption() / locator.click()"
          }},
          "selector_hints": {{
            "element_name": "Project",
            "element_type": "dropdown",
            "suggested_selectors": [
              "page.locator('select[name=\"project\"]')",
              "page.get_by_role('combobox', name='Project')",
              "page.locator('label:has-text(\"Project\") ~ div button')"
            ]
          }},
          "test_data": {{
            "value": "MyProject"
          }},
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
- capture: read and STORE a value from an element, table column, or URL for use in subsequent steps
- date_picker: click calendar widget and select a specific date
- assert_all_rows: validate a specific column across ALL visible table rows

ASSERTION TYPES: url, text, heading, toast, status, element, visible, enabled

**assert_all_rows ACTION — USE THIS for any step that:**
- "Capture all rows", "For each row", "For every row", "Iterate rows"
- "Validate value is not null/empty", "Validate each row", "Check all rows"
- "Fetch column value for each row", "Verify all records", "All rows should have"

For assert_all_rows steps, use this structure:
{{
  "step_number": N,
  "instruction": "original step text",
  "action": {{
    "type": "assert_all_rows",
    "playwright_method": "page.locator('table tbody tr')"
  }},
  "selector_hints": {{"element_name": null, "element_type": "table", "suggested_selectors": ["table", "[role='grid']"]}},
  "test_data": {{
    "column_name": "COLUMN HEADER TEXT",
    "validation": "not_empty",
    "min_rows": 1
  }},
  "assertions": null
}}

validation values:
- "not_empty" → cell must not be blank/null (use for "not null", "not empty", "has value")
- "contains"  → cell must contain expected_value (add "expected_value": "text" to test_data)
- "equals"    → cell must exactly equal expected_value
- "matches_pattern" → cell must match regex pattern in expected_value (e.g. "INC\\d+")
- "unique"    → all cells in column must have distinct values (no duplicates)

**date_picker ACTION — USE THIS for any step that:**
- "Select date", "Click on date", "Choose date from date picker", "Select specific date"
- "Apply date filter", "Click date filter", "Pick a date"

For date_picker steps, use this structure:
{{
  "step_number": N,
  "instruction": "original step text",
  "action": {{"type": "date_picker", "playwright_method": "locator.click() + calendar navigation"}},
  "selector_hints": {{"element_name": "Date", "element_type": "input", "suggested_selectors": [...]}},
  "test_data": {{"date": "07/03/2026", "date_format": "MM/DD/YYYY"}},
  "assertions": null
}}

**capture ACTION — USE THIS for steps that say "capture", "obtain", "fetch", "get the value of", "store", "note down", "read the":**
Set test_data.source="column" + test_data.column_name if reading from a table column.
Set test_data.source="url" if reading the page URL.
Otherwise set test_data.source="element" and provide selector_hints.
Set test_data.capture_key to a short variable name (e.g., "case_id", "incident_id").

**unique VALIDATION — USE THIS for assert_all_rows steps that say:**
- "No duplicate", "All unique", "unique values", "no duplicates", "each.*unique", "must be unique"
Set validation="unique" in test_data.

**GROUPING RULE for assert_all_rows:**
Steps like "Capture all rows", "For each row fetch X", "Validate value is not null" are ONE logical operation.
Collapse them into a SINGLE assert_all_rows step — do NOT emit separate steps for each part.
Extract the column name from "fetch X column value" or "EmergeX Case ID column".
If validation intent is "not null" or "not empty", use validation="not_empty".

RULES:
1. Parse EVERY step from the "Test Case Steps" column ONLY - do not skip any
2. **CRITICAL: The "Expected Result" column is NOT a source of test steps. Its content must ONLY go into the "expected_results" array. NEVER convert Expected Result lines into steps.**
3. Steps come EXCLUSIVELY from the "Test Case Steps" field. Expected Result text is metadata only.
4. **Check for "Input data" or "Input Values" field first**
5. **Parse Input data into key-value pairs (format: "Key: Value")**
6. **For each step, check if it references any key from Input data**
7. **Use values from Input data when matching keys are found - this takes priority over values in step text**
8. Extract credentials into test_data.default_credentials (prioritize Input data)
9. For fill/click actions, provide 2-3 suggested_selectors using getByLabel, getByRole, getByPlaceholder, locator
10. Use null for fields that don't apply
11. Keep original instruction text
12. **CRITICAL: Return ONLY valid JSON - no Python code, no markdown blocks, no explanations, no extra text. Start directly with {{ and end with }}**
13. **CRITICAL for select actions: `element_name` in selector_hints MUST be the FIELD LABEL (e.g. "Project", "Status", "Category") — NEVER the value being selected. The value to select goes in test_data.value. Example: selecting "MyProject" from a "Project" dropdown → element_name="Project", test_data={{"value":"MyProject"}}**
14. **CRITICAL for fill-from-table steps: When a fill step says "enter a value FROM a column" or "use a value FROM the [X] column" or "enter a valid value from 'X' column", set action.type="fill", test_data.column_name=<the column name>, test_data.source="table". Do NOT set a literal value in test_data.value. Do NOT use action.type="assert_all_rows" for these steps.**
15. **CRITICAL for capture/fetch/obtain steps: When a step says "capture", "obtain", "fetch", "get the value of", "store", "note down", "read the", use action.type="capture". Set test_data.source="column" + test_data.column_name if reading from a table column. Set test_data.source="url" if reading the page URL. Otherwise set test_data.source="element". Set test_data.capture_key to a short variable name (e.g., "case_id", "incident_id").**
16. **CRITICAL for unique validation: When a step says "no duplicate", "all unique", "unique values", "no duplicates", "must be unique", use action.type="assert_all_rows" with test_data.validation="unique".**
17. **CRITICAL for date picker steps: When a step says "select date", "click date", "choose date", "apply date filter", "date picker", use action.type="date_picker" and put the target date in test_data.date (MM/DD/YYYY format).**

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

Example 4 - Dropdown Selection:
- Step: "Select project from the Project dropdown"
- Input data: "Project Name: Project_Test_001"
- Result: action.type="select", selector_hints.element_name="Project", selector_hints.element_type="dropdown", test_data={{"value":"Project_Test_001"}}
- NOTE: element_name is "Project" (the field label), NOT "Project_Test_001" (the value)

Example 5 - Multiple Similar Keys:
- Step 1: "Verify URL with Expected URL"
- Step 2: "Verify toast with Expected Toast Message"
- Input data: "Expected URL: https://.../login\nExpected Toast Message: Success"
- Match "Expected URL" to step 1, "Expected Toast Message" to step 2 (exact key match)

Example 6 - Contextual Fill from Table Column:
- Step: "Enter a valid value from 'EmergeX Case ID' column into Search field"
- Input data: (none relevant)
- Result: action.type="fill", selector_hints.element_name="Search", selector_hints.element_type="input", test_data={{"column_name": "EmergeX Case ID", "source": "table"}}
- NOTE: Do NOT use action.type="assert_all_rows" here — this is a fill action where the value comes from a live table column

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
            waymore_api_key=settings.WAYMORE_API_KEY,
            openai_model=model if provider == LLMProvider.OPENAI else None,
            groq_model=model if provider == LLMProvider.GROQ else None,
            anthropic_model=model if provider == LLMProvider.ANTHROPIC else None,
            waymore_model=model if provider == LLMProvider.WAYMORE else None,
        )

    def execute(self, raw_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """Execute the agent's main task."""
        return self.parse_to_enhanced_structure(
            raw_data=raw_data,
            project_name=kwargs.get("project_name", "Automation Project"),
            base_url=kwargs.get("base_url")
        )

    # Maximum number of test cases to send in one LLM call.
    # Keeps the prompt + response well within token limits.
    BATCH_SIZE = 3

    def parse_to_enhanced_structure(
        self,
        raw_data: List[Dict[str, Any]],
        project_name: str = "Automation Project",
        base_url: str = None
    ) -> Dict[str, Any]:
        """
        Parse raw test case data into enhanced structure.
        When there are more than BATCH_SIZE test cases, splits into batches,
        parses each batch separately, then merges the results.
        """
        if not base_url:
            base_url = self._extract_base_url(raw_data)

        if len(raw_data) <= self.BATCH_SIZE:
            return self._parse_batch(raw_data, project_name, base_url)

        # ── Batch mode ────────────────────────────────────────────────────
        print(f"[Parser] {len(raw_data)} test cases — splitting into batches of {self.BATCH_SIZE}")
        merged_test_cases: List[Dict] = []
        merged_raw_items: List[Dict] = []   # parallel list: raw_data item for each parsed TC
        merged_result: Dict = {}

        for batch_start in range(0, len(raw_data), self.BATCH_SIZE):
            batch = raw_data[batch_start: batch_start + self.BATCH_SIZE]
            batch_num = batch_start // self.BATCH_SIZE + 1
            print(f"[Parser] Parsing batch {batch_num} ({len(batch)} test case(s))...")
            try:
                batch_result = self._parse_batch(batch, project_name, base_url)
            except Exception as e:
                print(f"[Parser] Batch {batch_num} failed: {e} — skipping")
                continue

            parsed_tcs = batch_result.get("test_cases", [])

            if not merged_result:
                merged_result = batch_result
                merged_test_cases = parsed_tcs
            else:
                merged_test_cases.extend(parsed_tcs)

            # Track which raw item each parsed TC came from (by position in batch)
            for i in range(len(parsed_tcs)):
                raw_idx = batch_start + i
                if raw_idx < len(raw_data):
                    merged_raw_items.append(raw_data[raw_idx])
                else:
                    merged_raw_items.append({})

        if not merged_result:
            raise ValueError("All parsing batches failed — could not parse any test cases")

        # Assign IDs from original T.C.No (preserves TC_011, TC_012 etc.
        # when a subset of tests is selected).  Fall back to sequential numbering
        # only when no T.C.No is available.
        for idx, tc in enumerate(merged_test_cases):
            raw_item = merged_raw_items[idx] if idx < len(merged_raw_items) else {}
            tc_no = raw_item.get("T.C.No") or raw_item.get("tc_no") or raw_item.get("id")
            if tc_no:
                nums = ''.join(filter(str.isdigit, str(tc_no)))
                tc["id"] = f"TC_{int(nums):03d}" if nums else f"TC_{idx + 1:03d}"
            else:
                tc["id"] = f"TC_{idx + 1:03d}"

        merged_result["test_cases"] = merged_test_cases
        return merged_result

    def _strip_expected_result_steps(self, result: Dict, raw_data: List[Dict]) -> Dict:
        """
        Post-parse safeguard: remove any steps whose instruction text originates from
        the 'Expected Result' column.  The LLM (especially weaker models like Groq)
        sometimes converts Expected Result lines into steps even when explicitly told not to.

        Matching strategy (any of these triggers removal):
          1. Exact match:   instruction == expected_result_line
          2. Containment:   expected_result_line is contained within instruction
          3. Starts-with:   instruction starts with an expected_result_line (≥10 chars)
        All comparisons are case-insensitive after normalising whitespace and quotes.
        Short lines (<4 chars) are skipped to avoid false positives on words like "URL".
        """
        # Build a list of normalised expected-result lines from the raw input
        expected_lines: list = []
        for row in raw_data:
            er = row.get("Expected Result") or row.get("expected_result") or ""
            if isinstance(er, str):
                for line in er.splitlines():
                    normalised = line.strip().strip('"').strip("'").strip().lower()
                    if len(normalised) >= 4:
                        expected_lines.append(normalised)

        if not expected_lines:
            return result

        def _is_expected_result_step(instruction: str) -> bool:
            inst = instruction.strip().strip('"').strip("'").strip().lower()
            for er_line in expected_lines:
                if inst == er_line:                          # exact
                    return True
                if er_line in inst:                          # ER line contained in instruction
                    return True
                if len(er_line) >= 10 and inst.startswith(er_line):  # instruction starts with ER
                    return True
            return False

        for tc in result.get("test_cases", []):
            original_steps = tc.get("steps", [])
            filtered = []
            for step in original_steps:
                instruction = step.get("instruction") or ""
                if _is_expected_result_step(instruction):
                    print(f"    [Parser] Removed Expected Result step: '{instruction[:70]}'")
                else:
                    filtered.append(step)
            if len(filtered) != len(original_steps):
                for i, s in enumerate(filtered, 1):
                    s["step_number"] = i
                tc["steps"] = filtered

        return result

    def _parse_batch(
        self,
        raw_data: List[Dict[str, Any]],
        project_name: str,
        base_url: str,
    ) -> Dict[str, Any]:
        """Parse a single batch of test cases (≤ BATCH_SIZE rows)."""
        content = json.dumps(raw_data, indent=2)

        prompt = ENHANCED_PARSER_PROMPT.format(
            content=content,
            project_name=project_name,
            base_url=base_url or "https://example.com"
        )

        response_text = self.call_llm(prompt)
        response_text = self._clean_json_response(response_text)

        # Fast path: try json_repair first — handles most LLM JSON quirks instantly
        try:
            from json_repair import repair_json
            repaired = repair_json(response_text, return_objects=True)
            if isinstance(repaired, dict) and repaired.get("test_cases"):
                result = self._post_process(repaired, project_name, base_url, raw_data)
                result = self._strip_expected_result_steps(result, raw_data)
                return result
        except Exception:
            pass

        try:
            result = json.loads(response_text)
            result = self._post_process(result, project_name, base_url, raw_data)
            result = self._strip_expected_result_steps(result, raw_data)
            return result
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error (first attempt): {e}")
            # Try fixing invalid escape sequences
            try:
                fixed_text = self._fix_invalid_escapes(response_text)
                print("Attempting to parse with fixed escape sequences...")
                result = json.loads(fixed_text)
                result = self._post_process(result, project_name, base_url, raw_data)
                result = self._strip_expected_result_steps(result, raw_data)
                print("Successfully parsed after fixing escapes!")
                return result
            except json.JSONDecodeError as e2:
                print(f"JSON Parse Error (after fix attempt): {e2}")
                # Try repairing truncated JSON
                try:
                    repaired_text = self._repair_truncated_json(fixed_text)
                    print("Attempting to parse with truncation repair...")
                    result = json.loads(repaired_text)
                    result = self._post_process(result, project_name, base_url, raw_data)
                    result = self._strip_expected_result_steps(result, raw_data)
                    print("Successfully parsed after truncation repair!")
                    return result
                except json.JSONDecodeError as e3:
                    print(f"JSON Parse Error (after repair attempt): {e3}")
                    # Final fallback: use json_repair library
                    try:
                        from json_repair import repair_json
                        print("Attempting json_repair library...")
                        repaired = repair_json(response_text, return_objects=True)
                        if isinstance(repaired, dict) and repaired.get("test_cases"):
                            result = self._post_process(repaired, project_name, base_url, raw_data)
                            result = self._strip_expected_result_steps(result, raw_data)
                            print("Successfully parsed with json_repair!")
                            return result
                    except Exception as e4:
                        print(f"json_repair also failed: {e4}")
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

        # Keywords that signal a row-iteration step — never reclassify these
        row_iteration_keywords = [
            "for each row", "for every row", "each row", "all rows", "every row",
            "capture all", "iterate row", "fetch.*column", "validate.*row",
        ]

        for tc in result.get("test_cases", []):
            for step in tc.get("steps", []):
                instruction = (step.get("instruction") or "").lower()
                action = step.get("action", {})
                action_type = action.get("type", "")

                # Never reclassify assert_all_rows steps
                if action_type == "assert_all_rows":
                    continue

                # Auto-detect row-iteration steps that the LLM may have misclassified
                # Guard: if the instruction says "enter/type/fill/input ... from column",
                # it's a fill-from-table step, NOT an assert_all_rows step.
                import re as _re_fix
                _fill_keywords = ["enter", "type ", "fill", "input "]
                _is_fill_from_table = (
                    any(kw in instruction for kw in _fill_keywords)
                    and _re_fix.search(r"from\s+['\"]?[\w\s]+['\"]?\s*column", instruction)
                )
                if _is_fill_from_table and action_type == "fill":
                    # Already correctly typed as fill — just ensure source:table is set
                    col_match = _re_fix.search(r'["\']([^"\']+)["\']', instruction)
                    if col_match:
                        td = step.setdefault("test_data", {})
                        td.setdefault("column_name", col_match.group(1).strip())
                        td["source"] = "table"
                    print(f"    [Parser] Confirmed fill-from-table (kept fill): {instruction[:60]}...")
                    continue
                if _is_fill_from_table and action_type not in ("assert_all_rows", "fill"):
                    # LLM classified this as something else — correct to fill
                    action["type"] = "fill"
                    col_match = _re_fix.search(r'["\']([^"\']+)["\']', instruction)
                    if col_match:
                        td = step.setdefault("test_data", {})
                        td.setdefault("column_name", col_match.group(1).strip())
                        td["source"] = "table"
                    print(f"    [Parser] Reclassified to fill-from-table: {instruction[:60]}...")
                    continue
                if action_type not in ("assert_all_rows",) and not _is_fill_from_table and any(
                    _re_fix.search(kw, instruction) for kw in row_iteration_keywords
                ):
                    action["type"] = "assert_all_rows"
                    action["playwright_method"] = "page.locator('table tbody tr')"
                    # Try to extract column name from instruction
                    col_match = _re_fix.search(r'["\']?([A-Za-z][A-Za-z0-9 _-]{2,})["\']?\s*column', instruction)
                    if col_match and not step.get("test_data", {}).get("column_name"):
                        td = step.setdefault("test_data", {})
                        td.setdefault("column_name", col_match.group(1).strip())
                        td.setdefault("validation", "not_empty")
                        td.setdefault("min_rows", 1)
                    print(f"    [Parser] Auto-detected assert_all_rows: {instruction[:60]}...")
                    continue

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
                                    "playwright_assertion": "expect(page).to_have_url(page.url)"
                                }]
                            elif "heading" in instruction or "title" in instruction:
                                step["assertions"] = [{
                                    "type": "heading",
                                    "expected_value": "",
                                    "playwright_assertion": "expect(page.get_by_role('heading').first()).to_be_visible()"
                                }]
                            elif "text" in instruction or "message" in instruction:
                                step["assertions"] = [{
                                    "type": "text",
                                    "expected_value": "",
                                    "playwright_assertion": "expect(page.locator('body')).to_be_visible()"
                                }]
                            else:
                                step["assertions"] = [{
                                    "type": "visible",
                                    "expected_value": "",
                                    "playwright_assertion": "# page is visible"
                                }]

                        print(f"    [Parser] Fixed action type: goto -> assert for step: {instruction[:50]}...")

                # Detect date picker steps
                _date_keywords = ["select date", "click on date", "date picker", "date filter",
                                  "pick a date", "choose date", "apply date", "click date"]
                if action_type not in ("date_picker",) and any(kw in instruction for kw in _date_keywords):
                    action["type"] = "date_picker"
                    action["playwright_method"] = "locator.click() + calendar navigation"
                    print(f"    [Parser] Auto-detected date_picker: {instruction[:60]}...")
                    continue

                # Detect unique/no-duplicate validation steps
                import re as _re_fix2
                _unique_keywords = ["no duplicate", "all unique", "unique values", "no duplicates",
                                    "must be unique", "case id.*unique", "each.*unique"]
                if action_type not in ("assert_all_rows",) and any(
                    _re_fix2.search(kw, instruction) for kw in _unique_keywords
                ):
                    action["type"] = "assert_all_rows"
                    action["playwright_method"] = "page.locator('table tbody tr')"
                    step_test_data_u = step.get("test_data") or {}
                    step_test_data_u["validation"] = "unique"
                    step["test_data"] = step_test_data_u
                    print(f"    [Parser] Auto-detected unique assert_all_rows: {instruction[:60]}...")
                    continue

                # Detect capture/obtain/fetch steps
                _capture_keywords = ["capture", "obtain", "fetch the", "get the value", "store the",
                                     "note down", "read the", "grab the"]
                if action_type not in ("assert_all_rows", "assert", "capture") and any(
                    kw in instruction for kw in _capture_keywords
                ):
                    action["type"] = "capture"
                    print(f"    [Parser] Auto-detected capture: {instruction[:60]}...")
                    continue

        return result

    def _post_process(self, result: Dict, project_name: str, base_url: str, raw_data: List[Dict] = None) -> Dict:
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
            # Try to get the original T.C.No from raw_data by position first.
            # This preserves TC_011, TC_012 etc. when a subset of tests is selected.
            raw_tc_no = None
            if raw_data and idx < len(raw_data):
                raw_tc_no = raw_data[idx].get("T.C.No") or raw_data[idx].get("tc_no")

            # Ensure each test case has a consistent ID
            if raw_tc_no:
                nums = ''.join(filter(str.isdigit, str(raw_tc_no)))
                tc["id"] = f"TC_{int(nums):03d}" if nums else f"TC_{idx + 1:03d}"
            elif "id" not in tc or not tc["id"]:
                tc["id"] = f"TC_{idx + 1:03d}"
            else:
                # Normalize ID format to TC_XXX (e.g. T.C.11 → TC_011)
                existing_id = tc["id"]
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

        # Drop trailing assert step from workflow TCs (never end a TC with assert)
        for _tc in result.get("test_cases", []):
            _steps = _tc.get("steps", [])
            if len(_steps) < 2:
                continue
            if all(_s.get("action", {}).get("type") == "assert" for _s in _steps):
                continue  # pure-verification TC — leave untouched
            if _steps[-1].get("action", {}).get("type") == "assert":
                _tc["steps"] = _steps[:-1]
                for _i, _s in enumerate(_tc["steps"], 1):
                    _s["step_number"] = _i

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
