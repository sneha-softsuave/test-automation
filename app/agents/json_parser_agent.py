import json
from typing import List, Dict, Any

from app.agents.base_agent import BaseAgent, LLMProvider
from app.models.test_case import TestCase


class JsonParserAgent(BaseAgent):
    """Agent for parsing Excel/JSON data into structured test case JSON."""

    def execute(self, rows_data: List[List[Any]], headers: List[str] = None) -> List[Dict]:
        """
        Execute the agent to parse Excel data to test cases.

        Args:
            rows_data: List of rows from Excel
            headers: Optional list of header names

        Returns:
            List of test case dictionaries
        """
        return self.parse_excel_to_test_cases(rows_data, headers)

    def _get_prompt(self, content: str) -> str:
        """Generate the prompt for parsing data."""
        return f"""You are a test case JSON parser agent. Your task is to analyze the provided data and convert it into a structured JSON format for automated testing.

The data contains test case information. Parse it and create JSON in the following exact format:

```json
[
  {{
    "test_id": "TC_01",
    "test_name": "Test case name/title",
    "base_url": "https://example.com",
    "actions": [
      {{
        "step": 1,
        "action": "navigate|click|type|verify_url|verify_text|verify_element|wait",
        "selector": "{{{{element_name}}}}",
        "value": "value or URL or text to verify",
        "description": "Description of what this step does"
      }}
    ]
  }}
]
```

Action types to use:
- "navigate": For opening URLs (value = URL, selector = null)
- "click": For clicking elements (selector = element placeholder, value = null)
- "type": For entering text (selector = element placeholder, value = text to enter)
- "verify_url": For URL verification (value = expected URL, selector = null)
- "verify_text": For text verification (selector = element placeholder, value = expected text)
- "verify_element": For checking element exists (selector = element placeholder, value = null)
- "wait": For waiting (selector = optional loader element, value = null)

For selectors, use placeholder format like {{{{email_field}}}}, {{{{login_button}}}}, {{{{dashboard_heading}}}} etc.

Here is the data to parse:

{content}

IMPORTANT:
1. Return ONLY valid JSON array, no markdown, no explanation, just the JSON.
2. Parse each test case from the data.
3. Break down test steps into individual actions based on the "Test Case Steps" field.
4. Use meaningful selector placeholders based on the element being interacted with.
5. Extract base_url from the navigation URLs if possible.
6. Use "T.C.No" field to create test_id like "TC_01", "TC_02" etc.
7. Use "Test Case" field as test_name.

Return the JSON array:"""

    def _clean_json_response(self, response_text: str) -> str:
        """Clean up response if it contains markdown code blocks."""
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```json") or line.startswith("```"):
                    in_json = not in_json if not line.startswith("```json") else True
                    continue
                if in_json or (not line.startswith("```") and json_lines):
                    json_lines.append(line)
            response_text = "\n".join(json_lines)

        # Also try to extract JSON array if there's text around it
        if not response_text.strip().startswith("["):
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start != -1 and end > start:
                response_text = response_text[start:end]

        return response_text.strip()

    def _format_excel_data(self, rows_data: List[List[Any]], headers: List[str] = None) -> str:
        """Format Excel data into a readable string for the prompt."""
        output = []

        if headers:
            output.append(f"Headers: {headers}")
            output.append("-" * 50)

        for i, row in enumerate(rows_data):
            if i == 0 and not headers:
                output.append(f"Row {i + 1} (Headers): {row}")
            else:
                output.append(f"Row {i + 1}: {row}")

        return "\n".join(output)

    def _format_raw_json_data(self, raw_data: List[Dict[str, Any]]) -> str:
        """Format raw JSON data into a readable string for the prompt."""
        return json.dumps(raw_data, indent=2)

    def parse_excel_to_test_cases(self, rows_data: List[List[Any]], headers: List[str] = None) -> List[Dict]:
        """Parse Excel rows and convert them to structured test case JSON using LLM."""
        excel_content = self._format_excel_data(rows_data, headers)
        prompt = self._get_prompt(excel_content)

        response_text = self.call_llm(prompt)
        response_text = self._clean_json_response(response_text)

        try:
            test_cases = json.loads(response_text)
            return test_cases
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error: {e}")
            print(f"Response was: {response_text[:500]}...")
            raise ValueError(f"Failed to parse JSON response: {e}")

    def parse_raw_json_to_test_cases(self, raw_data: List[Dict[str, Any]]) -> List[Dict]:
        """
        Parse raw JSON test case data and convert to structured test case JSON using LLM.

        Args:
            raw_data: List of raw test case dictionaries from Excel/JSON

        Returns:
            List of structured test case dictionaries
        """
        json_content = self._format_raw_json_data(raw_data)
        prompt = self._get_prompt(json_content)

        response_text = self.call_llm(prompt)
        response_text = self._clean_json_response(response_text)

        try:
            test_cases = json.loads(response_text)
            return test_cases
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error: {e}")
            print(f"Response was: {response_text[:500]}...")
            raise ValueError(f"Failed to parse JSON response: {e}")

    def validate_test_cases(self, test_cases: List[Dict]) -> List[TestCase]:
        """Validate and convert dict test cases to Pydantic models."""
        validated = []
        for tc in test_cases:
            try:
                test_case = TestCase(**tc)
                validated.append(test_case)
            except Exception as e:
                print(f"Validation error for test case {tc.get('test_id', 'unknown')}: {e}")
                raise
        return validated
