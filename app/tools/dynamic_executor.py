"""
Dynamic Test Executor - Maps selectors at runtime as it navigates through pages.
Uses asyncio.to_thread() to run Playwright sync API without blocking.
"""
import re
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
from playwright.sync_api import sync_playwright, Page, expect


def _run_dynamic_execution(test_cases: List[Dict], headless: bool = False, timeout: int = 30000) -> Dict[str, Any]:
    """
    Internal function that runs Playwright synchronously.
    Called via asyncio.to_thread() to avoid blocking the event loop.
    """
    print(f"\n{'='*60}")
    print("DYNAMIC EXECUTOR - Running in thread")
    print(f"Test cases: {len(test_cases)}")
    print(f"Headless: {headless}")
    print(f"Timeout: {timeout}ms")
    print(f"{'='*60}\n")

    results = []
    passed = 0
    failed = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        for test_case in test_cases:
            result = _execute_single_test(browser, test_case, timeout)
            results.append(result)

            if result["status"] == "PASSED":
                passed += 1
            else:
                failed += 1

        browser.close()

    return {
        "total": len(test_cases),
        "passed": passed,
        "failed": failed,
        "results": results,
        "executed_at": datetime.now().isoformat()
    }


def _execute_single_test(browser, test_case: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    """Execute a single test case with dynamic selector mapping."""
    test_id = test_case.get("test_id", "TC_01")
    test_name = test_case.get("test_name", "Test Case")
    actions = test_case.get("actions", [])

    print(f"\n--- Test: {test_id} - {test_name} ---")
    print(f"Total Steps: {len(actions)}")

    result = {
        "test_id": test_id,
        "test_name": test_name,
        "status": "PASSED",
        "steps": [],
        "selector_mappings": {},
        "screenshots": [],
        "started_at": datetime.now().isoformat(),
        "error": None
    }

    context = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = context.new_page()

    try:
        for action in actions:
            step_num = action.get("step", 0)
            action_type = action.get("action", "")
            selector = action.get("selector")
            original_selector = selector
            value = action.get("value")
            description = action.get("description", "")

            print(f"\n  Step {step_num}: {description}")
            print(f"    Action: {action_type}, Selector: {selector}, Value: {value}")

            step_result = {
                "step": step_num,
                "action": action_type,
                "description": description,
                "status": "PASSED",
                "original_selector": original_selector,
                "selector_used": selector,
                "error": None
            }

            try:
                # Map placeholder selectors at runtime
                if selector and "{{" in selector and "}}" in selector:
                    mapped = _map_selector(page, selector)
                    if mapped:
                        print(f"    Mapped: {selector} -> {mapped}")
                        step_result["selector_used"] = mapped
                        selector = mapped
                        # Store mapping
                        placeholder_name = re.search(r'\{\{(\w+)\}\}', original_selector)
                        if placeholder_name:
                            result["selector_mappings"][placeholder_name.group(1)] = mapped
                    else:
                        print(f"    WARNING: Could not map {selector}")

                # Execute action
                _execute_action(page, action_type, selector, value, timeout)
                print(f"    [PASSED]")

            except Exception as e:
                error_msg = str(e)
                print(f"    [FAILED]: {error_msg}")
                step_result["status"] = "FAILED"
                step_result["error"] = error_msg
                result["status"] = "FAILED"
                result["error"] = f"Step {step_num}: {error_msg}"

                # Screenshot on failure
                try:
                    path = f"error_{test_id}_step{step_num}.png"
                    page.screenshot(path=path)
                    result["screenshots"].append(path)
                except:
                    pass

                result["steps"].append(step_result)
                break

            result["steps"].append(step_result)

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)

    finally:
        context.close()

    result["finished_at"] = datetime.now().isoformat()

    status_icon = "[OK]" if result["status"] == "PASSED" else "[FAIL]"
    print(f"\n  {status_icon} Test {test_id}: {result['status']}")

    return result


def _map_selector(page: Page, placeholder: str) -> Optional[str]:
    """Map placeholder to actual selector by inspecting current page."""
    name = re.search(r'\{\{(\w+)\}\}', placeholder)
    if not name:
        return None

    name = name.group(1).lower()

    # Extract page elements
    try:
        elements = page.evaluate("""
        () => {
            const data = { inputs: [], buttons: [] };

            document.querySelectorAll('input, textarea').forEach(el => {
                data.inputs.push({
                    id: el.id || '',
                    name: el.name || '',
                    type: el.type || '',
                    placeholder: el.placeholder || ''
                });
            });

            document.querySelectorAll('button, input[type="submit"]').forEach(el => {
                data.buttons.push({
                    id: el.id || '',
                    type: el.type || '',
                    text: (el.innerText || el.value || '').trim()
                });
            });

            return data;
        }
        """)
    except:
        return None

    # Map based on placeholder name
    inputs = elements.get("inputs", [])
    buttons = elements.get("buttons", [])

    # Email field
    if "email" in name:
        for inp in inputs:
            if inp["type"] == "email" or "email" in inp["placeholder"].lower() or "email" in inp["name"].lower():
                if inp["id"]:
                    return f'#{inp["id"]}'
                if inp["name"]:
                    return f'[name="{inp["name"]}"]'
                return 'input[type="email"]'

    # Password field
    if "password" in name:
        for inp in inputs:
            if inp["type"] == "password" or "password" in inp["placeholder"].lower():
                if inp["id"]:
                    return f'#{inp["id"]}'
                if inp["name"]:
                    return f'[name="{inp["name"]}"]'
                return 'input[type="password"]'

    # Username field
    if "user" in name:
        for inp in inputs:
            if "user" in inp["placeholder"].lower() or "user" in inp["name"].lower() or "user" in inp["id"].lower():
                if inp["id"]:
                    return f'#{inp["id"]}'
                if inp["name"]:
                    return f'[name="{inp["name"]}"]'
        # Fallback: first text input
        for inp in inputs:
            if inp["type"] == "text":
                if inp["id"]:
                    return f'#{inp["id"]}'
                if inp["name"]:
                    return f'[name="{inp["name"]}"]'

    # Submit/Login button
    if any(w in name for w in ["submit", "login", "button", "signin"]):
        for btn in buttons:
            text_lower = btn["text"].lower()
            if any(w in text_lower for w in ["log", "sign", "submit"]) or btn["type"] == "submit":
                if btn["id"]:
                    return f'#{btn["id"]}'
                if btn["text"]:
                    return f'button:has-text("{btn["text"]}")'
                return 'button[type="submit"]'

    return None


def _execute_action(page: Page, action_type: str, selector: str, value: str, timeout: int):
    """Execute a single Playwright action."""

    if action_type == "navigate":
        page.goto(value or "", wait_until="networkidle", timeout=timeout)

    elif action_type == "click":
        if not selector:
            raise ValueError("No selector for click")
        page.locator(selector).click(timeout=timeout)

    elif action_type == "type":
        if not selector:
            raise ValueError("No selector for type")
        page.locator(selector).fill(value or "", timeout=timeout)

    elif action_type == "verify_url":
        expect(page).to_have_url(value or "", timeout=timeout)

    elif action_type == "verify_text":
        text = (value or "").strip('"').strip("'")
        expect(page.get_by_text(text, exact=False)).to_be_visible(timeout=timeout)

    elif action_type == "verify_element":
        if selector:
            expect(page.locator(selector)).to_be_visible(timeout=timeout)

    elif action_type == "wait":
        page.wait_for_timeout(int(value) if value else 2000)

    elif action_type == "screenshot":
        page.screenshot(path=value or "screenshot.png")


async def execute_dynamic(test_cases: List[Dict], headless: bool = False, timeout: int = 30000) -> Dict[str, Any]:
    """
    Execute test cases with dynamic runtime selector mapping.
    Runs Playwright in a thread pool to avoid blocking async.
    """
    return await asyncio.to_thread(_run_dynamic_execution, test_cases, headless, timeout)
