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
    common_selectors = test_suite.get("common_selectors", {})
    test_data = test_suite.get("test_data", {})
    test_cases = test_suite.get("test_cases", [])

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

    return '\n'.join(lines)


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
        else:
            lines.append(f'page.get_by_role("button", name="{element_name}").click()')

    elif action_type == "fill":
        if selector and value:
            lines.append(f'{selector}.fill("{value}")')
        elif element_name.lower() in ["email", "username", "user"]:
            lines.append(f'page.get_by_label("Email").fill(TEST_EMAIL)')
        elif element_name.lower() in ["password", "pass"]:
            lines.append(f'page.get_by_label("Password").fill(TEST_PASSWORD)')
        else:
            lines.append(f'{selector or "page.locator(\"input\")"}.fill("{value or ""}")')

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
        lines.append(f'expect(page.locator(".toast, .Toastify, [role=\\"alert\\"]").first).to_contain_text("{expected_value}", timeout=10000)')

    elif playwright_assertion:
        # Use the provided playwright assertion directly
        lines.append(playwright_assertion)

    else:
        lines.append(f'# No specific assertion defined')
        lines.append('pass')

    return lines


def _get_best_selector(
    suggested_selectors: List[str],
    element_name: str,
    element_type: str,
    common_selectors: Dict[str, str]
) -> Optional[str]:
    """Get the best selector from available options."""

    # Try common selectors first
    if element_name and element_name.lower() in common_selectors:
        return common_selectors[element_name.lower()]

    # Try suggested selectors
    for selector in suggested_selectors:
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
            return selector
        elif selector.startswith("#") or selector.startswith(".") or selector.startswith("["):
            return f'page.locator("{selector}")'

    # Fallback based on element type
    if element_type == "button":
        return f'page.get_by_role("button", name="{element_name}")'
    elif element_type == "link":
        return f'page.get_by_role("link", name="{element_name}")'
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
        keys_to_check = ["value", "text", "input"]
        if element_name:
            keys_to_check.append(element_name.lower())
        for key in keys_to_check:
            if key in step_test_data:
                return str(step_test_data[key])

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
