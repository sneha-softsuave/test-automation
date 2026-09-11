"""
Enhanced Playwright Script Generator
Generates Python Playwright test scripts from enhanced test case format.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime


def generate_enhanced_playwright_script(
    test_case: Dict[str, Any],
    common_selectors: Dict[str, str] = None,
    test_data: Dict[str, Any] = None
) -> str:
    """
    Generate a Playwright Python script for a single test case.

    Args:
        test_case: Enhanced test case with steps, selector_hints, etc.
        common_selectors: Reusable selector mappings
        test_data: Test data values (credentials, etc.)

    Returns:
        Python script string
    """
    common_selectors = common_selectors or {}
    test_data = test_data or {}

    test_id = test_case.get("id", "TC_001")
    test_name = test_case.get("name", "Test Case")
    steps = test_case.get("steps", [])

    # Build script
    lines = [
        '"""',
        f'Playwright Test: {test_id} - {test_name}',
        f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        '"""',
        '',
        'import pytest',
        'from playwright.sync_api import Page, expect',
        '',
        '',
        f'def test_{test_id.lower().replace("-", "_").replace(" ", "_")}(page: Page):',
        '    """',
        f'    Test ID: {test_id}',
        f'    {test_name}',
        '    """',
        '',
    ]

    for step in steps:
        step_num = step.get("step_number", 0)
        instruction = step.get("instruction", "")
        action = step.get("action", {})
        action_type = action.get("type", "")
        selector_hints = step.get("selector_hints", {})
        step_test_data = step.get("test_data", {}) or {}
        assertions = step.get("assertions", []) or []

        # Add comment for step
        short_instruction = instruction[:60] + "..." if len(instruction) > 60 else instruction
        lines.append(f'    # Step {step_num}: {short_instruction}')

        # Generate action code
        action_code = _generate_action_code(
            action_type=action_type,
            selector_hints=selector_hints,
            step_test_data=step_test_data,
            test_data=test_data,
            common_selectors=common_selectors,
            instruction=instruction
        )

        for line in action_code:
            lines.append(f'    {line}')

        # Generate assertions
        for assertion in assertions:
            assertion_code = _generate_assertion_code(assertion, selector_hints)
            for line in assertion_code:
                lines.append(f'    {line}')

        lines.append('')

    return '\n'.join(lines)


def generate_enhanced_pytest_script(test_suite: Dict[str, Any]) -> str:
    """
    Generate a combined pytest script for all test cases in the suite.

    Args:
        test_suite: Complete test suite with project info and test cases

    Returns:
        Combined Python pytest script string
    """
    project = test_suite.get("project", "Test Suite")
    base_url = test_suite.get("base_url", "")
    raw_common_selectors = test_suite.get("common_selectors", {})
    test_data = test_suite.get("test_data", {}) or {}
    test_cases = test_suite.get("test_cases", [])

    # Flatten nested common_selectors (LLM returns nested dicts like {"login": {...}})
    common_selectors = _flatten_common_selectors(raw_common_selectors)

    # Flatten nested test_data (LLM may nest under "default_credentials")
    def _flatten_test_data(td: dict) -> dict:
        flat = {}
        for k, v in td.items():
            if isinstance(v, str):
                flat[k] = v
            elif isinstance(v, dict):
                flat.update(v)  # merge nested dict up one level
        return flat
    test_data = _flatten_test_data(test_data)

    # Extract test data values for constants
    email = test_data.get("email") or test_data.get("test_email") or "test@example.com"
    password = test_data.get("password") or test_data.get("test_password") or "password123"

    # Build combined script
    lines = [
        '"""',
        f'Playwright Test Suite: {project}',
        f'Base URL: {base_url}',
        f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'Total Test Cases: {len(test_cases)}',
        '"""',
        '',
        'import pytest',
        'from playwright.sync_api import Page, expect',
        '',
        '',
        '# Test Data',
        f'BASE_URL = "{base_url}"',
        f'TEST_EMAIL = "{email}"',
        f'TEST_PASSWORD = "{password}"',
        '',
        '',
        '@pytest.fixture(scope="session")',
        'def browser_context_args(browser_context_args):',
        '    return {',
        '        **browser_context_args,',
        '        "viewport": {"width": 1920, "height": 1080},',
        '    }',
        '',
        '',
    ]

    # Generate each test case
    for test_case in test_cases:
        test_id = test_case.get("id", "TC_001")
        test_name = test_case.get("name", "Test Case")
        steps = test_case.get("steps", [])

        func_name = f'test_{test_id.lower().replace("-", "_").replace(" ", "_")}'

        lines.extend([
            f'def {func_name}(page: Page):',
            '    """',
            f'    Test ID: {test_id}',
            f'    {test_name}',
            '    """',
            '',
        ])

        for step in steps:
            step_num = step.get("step_number", 0)
            instruction = step.get("instruction", "")
            action = step.get("action", {})
            action_type = action.get("type", "")
            selector_hints = step.get("selector_hints", {})
            step_test_data = step.get("test_data", {}) or {}
            assertions = step.get("assertions", []) or []

            # Add comment
            short_instruction = instruction[:60] + "..." if len(instruction) > 60 else instruction
            lines.append(f'    # Step {step_num}: {short_instruction}')

            # Generate action code
            action_code = _generate_action_code(
                action_type=action_type,
                selector_hints=selector_hints,
                step_test_data=step_test_data,
                test_data=test_data,
                common_selectors=common_selectors,
                instruction=instruction
            )

            for line in action_code:
                lines.append(f'    {line}')

            # Generate assertions
            for assertion in assertions:
                assertion_code = _generate_assertion_code(assertion, selector_hints)
                for line in assertion_code:
                    lines.append(f'    {line}')

            lines.append('')

        lines.append('')

    script = '\n'.join(lines)
    # Append __main__ block so the script can be run with `python script.py`
    # --browser chromium is required by pytest-playwright to provide the `page` fixture
    if 'if __name__ == "__main__"' not in script:
        script += (
            '\n\nif __name__ == "__main__":\n'
            '    import pytest as _pytest, sys as _sys, os as _os\n'
            '    _args = [__file__, "-v", "--tb=short", "--browser", "chromium"]\n'
            '    if _os.environ.get("PLAYWRIGHT_HEADLESS", "1") == "0":\n'
            '        _args.append("--headed")\n'
            '    _sys.exit(_pytest.main(_args))\n'
        )
    return script


def _generate_action_code(
    action_type: str,
    selector_hints: Dict[str, Any],
    step_test_data: Dict[str, Any],
    test_data: Dict[str, Any],
    common_selectors: Dict[str, str],
    instruction: str
) -> List[str]:
    """Generate Playwright action code for a step."""

    lines = []
    element_name = selector_hints.get("element_name", "")
    element_type = selector_hints.get("element_type", "")
    suggested_selectors = selector_hints.get("suggested_selectors", [])

    # Get the best selector
    selector = _get_best_selector(suggested_selectors, element_name, element_type, common_selectors)

    # Get value for fill actions
    value = _get_value(element_name, step_test_data, test_data)

    if action_type == "goto":
        url = step_test_data.get("url") or test_data.get("base_url") or "BASE_URL"
        if url.startswith("http"):
            lines.append(f'page.goto("{url}")')
        else:
            lines.append(f'page.goto({url})')
        lines.append('page.wait_for_load_state("networkidle")')

    elif action_type == "click":
        if selector:
            lines.append(f'{selector}.click()')
        elif element_type == "button" and element_name:
            # Use exact=False so "Log in" matches "Login" and vice versa
            lines.append(f'page.get_by_role("button", name="{element_name}", exact=False).click()')
        elif element_name:
            lines.append(f'page.get_by_role("button", name="{element_name}", exact=False).click()')
        else:
            lines.append('page.get_by_role("button").first.click()')

    elif action_type == "fill":
        if selector and value:
            lines.append(f'{selector}.fill("{value}")')
        elif element_name.lower() in ["email", "username", "user", "email_field"]:
            # Use actual value from step_test_data if present, else fall back to constant
            actual_email = (step_test_data or {}).get("email") or (step_test_data or {}).get("value")
            # Prefer type-based selector — works regardless of label/placeholder text
            fill_selector = selector or 'page.locator("input[type=\\"email\\"]")'
            if actual_email:
                lines.append(f'{fill_selector}.fill("{actual_email}")')
            else:
                lines.append(f'{fill_selector}.fill(TEST_EMAIL)')
        elif element_name.lower() in ["password", "pass", "password_field"]:
            actual_password = (step_test_data or {}).get("password") or (step_test_data or {}).get("value")
            fill_selector = selector or 'page.locator("input[type=\\"password\\"]")'
            if actual_password:
                lines.append(f'{fill_selector}.fill("{actual_password}")')
            else:
                lines.append(f'{fill_selector}.fill(TEST_PASSWORD)')
        else:
            default_selector = 'page.locator("input")'
            default_value = ""
            lines.append(f'{selector or default_selector}.fill("{value or default_value}")')

    elif action_type == "select":
        select_value = step_test_data.get("value", "")
        if selector:
            lines.append(f'{selector}.select_option("{select_value}")')
        else:
            lines.append(f'page.locator("select").select_option("{select_value}")')

    elif action_type == "check":
        if selector:
            lines.append(f'{selector}.check()')
        else:
            lines.append(f'page.get_by_role("checkbox").check()')

    elif action_type == "hover":
        if selector:
            lines.append(f'{selector}.hover()')

    elif action_type == "wait":
        timeout = step_test_data.get("timeout", 1000)
        lines.append(f'page.wait_for_timeout({timeout})')

    elif action_type == "screenshot":
        filename = step_test_data.get("filename", "screenshot.png")
        lines.append(f'page.screenshot(path="{filename}")')

    elif action_type == "press":
        key = step_test_data.get("key", "Enter")
        if selector:
            lines.append(f'{selector}.press("{key}")')
        else:
            lines.append(f'page.keyboard.press("{key}")')

    elif action_type in ["verify_url", "assert_url"]:
        expected_url = step_test_data.get("expected_url") or step_test_data.get("url", "")
        if expected_url:
            lines.append(f'expect(page).to_have_url("{expected_url}")')
        else:
            lines.append('# No specific URL assertion defined')

    elif action_type in ["verify_text", "assert_text"]:
        expected_text = step_test_data.get("expected_text") or step_test_data.get("text", "")
        if selector and expected_text:
            lines.append(f'expect({selector}).to_contain_text("{expected_text}")')
        elif expected_text:
            lines.append(f'expect(page.locator("body")).to_contain_text("{expected_text}")')
        else:
            lines.append('# No specific text assertion defined')

    elif action_type in ["verify_element", "assert_visible"]:
        if selector:
            lines.append(f'expect({selector}).to_be_visible()')
        else:
            lines.append('# No specific element assertion defined')

    else:
        # Fallback: add comment for unknown action
        lines.append(f'# {action_type}: {instruction[:50]}...')
        lines.append('pass')

    return lines


def _generate_assertion_code(assertion: Dict[str, Any], selector_hints: Dict[str, Any]) -> List[str]:
    """Generate Playwright assertion code."""
    lines = []

    assertion_type = assertion.get("type", "")
    expected_value = assertion.get("expected_value", "")
    playwright_assertion = assertion.get("playwright_assertion", "")

    suggested_selectors = selector_hints.get("suggested_selectors", [])
    selector = _get_best_selector(suggested_selectors, "", "", {})

    if assertion_type == "url_contains":
        lines.append(f'expect(page).to_have_url(re.compile(r".*{expected_value}.*"))')

    elif assertion_type == "text_visible":
        if selector:
            lines.append(f'expect({selector}).to_contain_text("{expected_value}")')
        else:
            lines.append(f'expect(page.get_by_text("{expected_value}")).to_be_visible()')

    elif assertion_type == "element_visible":
        if selector:
            lines.append(f'expect({selector}).to_be_visible()')

    elif assertion_type == "toast_message":
        lines.append(f'# Wait for toast message')
        toast_selector = '.toast, .Toastify, [role="alert"]'
        lines.append(f'expect(page.locator("{toast_selector}").first).to_contain_text("{expected_value}", timeout=10000)')

    elif playwright_assertion:
        # Use the provided playwright assertion — convert JS→Python if needed
        converted = _js_to_python_playwright(playwright_assertion)
        # Skip assertions that need a value argument but have none
        # e.g. expect(page).to_have_url()  or  expect(loc).to_contain_text()
        import re as _re2
        _needs_arg = ('to_have_url', 'to_have_title', 'to_contain_text', 'to_have_text',
                      'to_have_value', 'to_have_attribute', 'to_have_class', 'to_have_count')
        _is_empty_call = _re2.search(r'\.(' + '|'.join(_needs_arg) + r')\(\s*\)', converted)
        if _is_empty_call:
            lines.append(f'# Assertion skipped (no expected value provided): {converted}')
            lines.append('pass')
        else:
            lines.append(converted)

    else:
        lines.append(f'# No specific assertion defined')
        lines.append('pass')

    return lines


def _js_to_python_playwright(code: str) -> str:
    """
    Convert JavaScript-style Playwright API calls to Python.

    LLMs trained mostly on JS Playwright docs sometimes emit JS syntax even
    when asked for Python. This handles the most common patterns.

    Examples:
        page.getByLabel('Email')            → page.get_by_label("Email")
        page.getByRole('button', {name:'X'})→ page.get_by_role("button", name="X")
        expect(page).toHaveURL('...')       → expect(page).to_have_url("...")
        expect(loc).toContainText('x')      → expect(loc).to_contain_text("x")
        expect(loc).toBeVisible()           → expect(loc).to_be_visible()
    """
    import re as _re

    # camelCase Playwright locator methods → snake_case
    _method_map = {
        'getByLabel': 'get_by_label',
        'getByRole': 'get_by_role',
        'getByText': 'get_by_text',
        'getByPlaceholder': 'get_by_placeholder',
        'getByTestId': 'get_by_test_id',
        'getByTitle': 'get_by_title',
        'getByAltText': 'get_by_alt_text',
        'frameLocator': 'frame_locator',
        'locator': 'locator',
        'waitForLoadState': 'wait_for_load_state',
        'waitForURL': 'wait_for_url',
        'waitForSelector': 'wait_for_selector',
        'waitForTimeout': 'wait_for_timeout',
        # expect assertion methods
        'toHaveURL': 'to_have_url',
        'toHaveTitle': 'to_have_title',
        'toContainText': 'to_contain_text',
        'toHaveText': 'to_have_text',
        'toBeVisible': 'to_be_visible',
        'toBeHidden': 'to_be_hidden',
        'toBeEnabled': 'to_be_enabled',
        'toBeDisabled': 'to_be_disabled',
        'toBeChecked': 'to_be_checked',
        'toHaveValue': 'to_have_value',
        'toHaveAttribute': 'to_have_attribute',
        'toHaveClass': 'to_have_class',
        'toHaveCount': 'to_have_count',
        'toBeFocused': 'to_be_focused',
    }
    for js_name, py_name in _method_map.items():
        code = code.replace(f'.{js_name}(', f'.{py_name}(')

    # Convert JS object argument {name: 'X'} or { name: "X" } → name="X"
    # e.g. get_by_role("button", { name: 'Login' }) → get_by_role("button", name="Login")
    def _convert_js_obj(m: '_re.Match') -> str:
        inner = m.group(1).strip()
        # key: 'value' or key: "value"  →  key="value"
        inner = _re.sub(r"(\w+)\s*:\s*'([^']*)'", r'\1="\2"', inner)
        inner = _re.sub(r'(\w+)\s*:\s*"([^"]*)"', r'\1="\2"', inner)
        return inner
    code = _re.sub(r'\{\s*([^}]+)\s*\}', _convert_js_obj, code)

    # Convert single-quoted strings to double-quoted ONLY when they don't contain double quotes
    # (to avoid breaking CSS selectors like input[type="email"])
    code = _re.sub(r"(?<![\\])'([^'\"]*)'", r'"\1"', code)

    return code


def _flatten_common_selectors(common_selectors: Dict) -> Dict[str, str]:
    """
    Flatten the potentially nested common_selectors dict into a flat key→selector mapping.

    The LLM produces a nested structure like:
      {"login": {"email_field": "page.getByLabel('Email')", "login_button": "..."}, ...}

    We flatten it so element lookups like "login_button" → "page.get_by_role(...)" work.
    Only string leaf values (actual selectors) are kept.
    """
    flat: Dict[str, str] = {}
    for key, value in common_selectors.items():
        if isinstance(value, str):
            flat[key.lower()] = value
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, str):
                    flat[sub_key.lower()] = sub_value
    return flat


def _get_best_selector(
    suggested_selectors: List[str],
    element_name: str,
    element_type: str,
    common_selectors: Dict[str, str]
) -> Optional[str]:
    """Get the best selector from available options."""

    # Flatten nested common_selectors (LLM returns nested dicts)
    flat_selectors = _flatten_common_selectors(common_selectors) if common_selectors else {}

    # Try common selectors first — look up by element_name
    if element_name:
        match = flat_selectors.get(element_name.lower())
        if match and isinstance(match, str):
            # Convert JS→Python and take only the first alternative (before " or ")
            match = match.split(" or ")[0].strip()
            return _js_to_python_playwright(match)

    # Normalise: LLM sometimes returns a dict instead of a list
    if isinstance(suggested_selectors, dict):
        suggested_selectors = list(suggested_selectors.values())
    if not isinstance(suggested_selectors, list):
        suggested_selectors = []

    # Try suggested selectors
    for selector in suggested_selectors:
        if not isinstance(selector, str):
            continue
        if selector.startswith("get_by_"):
            # Convert our format to Playwright
            if "::" in selector:
                parts = selector.split("::")
                method = parts[0]
                args = parts[1:]

                if method == "get_by_label":
                    return f'page.get_by_label("{args[0]}")'
                elif method == "get_by_role":
                    if len(args) >= 2:
                        return f'page.get_by_role("{args[0]}", name="{args[1]}")'
                    return f'page.get_by_role("{args[0]}")'
                elif method == "get_by_text":
                    return f'page.get_by_text("{args[0]}")'
                elif method == "get_by_placeholder":
                    return f'page.get_by_placeholder("{args[0]}")'
                elif method == "get_by_test_id":
                    return f'page.get_by_test_id("{args[0]}")'
            return f'page.{selector}()'
        elif selector.startswith("page."):
            converted = _js_to_python_playwright(selector)
            # Sanity check: if it's a text= selector but the text doesn't match element_name,
            # it's likely a stale/wrong LLM suggestion — skip it and use fallback below
            if element_name and "text=" in converted:
                import re as _re
                text_match = _re.search(r"text=['\"]([^'\"]+)['\"]", converted)
                if text_match:
                    suggested_text = text_match.group(1).lower()
                    name_lower = element_name.lower()
                    # If the suggested text shares no words with element_name, skip
                    name_words = set(name_lower.split())
                    text_words = set(suggested_text.split())
                    if not name_words.intersection(text_words):
                        continue  # skip this bad selector, try next or fall through to fallback
            return converted
        elif selector.startswith("#") or selector.startswith(".") or selector.startswith("["):
            return f'page.locator("{selector}")'

    # Fallback based on element type
    if element_type == "button":
        return f'page.get_by_role("button", name="{element_name}")'
    elif element_type == "link":
        return f'page.get_by_role("link", name="{element_name}")'
    elif element_type in ("menu item", "menuitem", "tab", "navigation item"):
        # Use text or role-based selector for nav/menu items
        return f'page.get_by_text("{element_name}", exact=False)'
    elif element_type == "input":
        return f'page.get_by_label("{element_name}")'
    elif element_type == "heading":
        return f'page.get_by_role("heading", name="{element_name}")'

    return None


def _get_value(
    element_name: str,
    step_test_data: Dict[str, Any],
    test_data: Dict[str, Any]
) -> str:
    """Get the value to fill from test data."""

    # Handle None element_name
    element_name = element_name or ""

    # Check step-level test data first
    if step_test_data:
        # Try element_name as key first (highest priority)
        if element_name and element_name.lower().replace(" ", "_") in step_test_data:
            return str(step_test_data[element_name.lower().replace(" ", "_")])
        if element_name and element_name.lower() in step_test_data:
            return str(step_test_data[element_name.lower()])
        # Try known generic keys
        keys_to_check = ["value", "text", "input", "email", "password", "username", "url"]
        for key in keys_to_check:
            if key in step_test_data:
                return str(step_test_data[key])
        # Fallback: return the first non-empty value in the dict (covers first_name, phone_number, etc.)
        for v in step_test_data.values():
            if v is not None and str(v).strip():
                return str(v)

    # Check global test data
    if test_data and element_name:
        # Try exact match
        if element_name.lower() in test_data:
            return str(test_data[element_name.lower()])

        # Try common mappings
        name_lower = element_name.lower()
        if name_lower in ["email", "username", "user", "email_field"]:
            return test_data.get("email") or test_data.get("test_email") or ""
        if name_lower in ["password", "pass", "password_field"]:
            return test_data.get("password") or test_data.get("test_password") or ""

    return ""
