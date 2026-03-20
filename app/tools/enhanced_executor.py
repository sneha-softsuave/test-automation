"""
Enhanced Executor - Executes Playwright tests from the enhanced test case format.
Works with selector_hints, test_data, and assertions structure.
Uses multiprocessing to avoid Windows asyncio subprocess limitations.
"""
import os
import re
import asyncio
import multiprocessing
from typing import Dict, Any, List, Optional
from datetime import datetime

# Load environment variables for timeout configuration
# These can be configured in .env file
STEP_MAX_RETRIES = int(os.getenv("STEP_MAX_RETRIES", "3"))  # 3 retries = 4 total attempts per step
RETRY_TIMEOUT_MULTIPLIER = float(os.getenv("RETRY_TIMEOUT_MULTIPLIER", "1.3"))  # Increase timeout each retry
DEFAULT_ACTION_TIMEOUT = int(os.getenv("DEFAULT_ACTION_TIMEOUT", "30000"))  # Default timeout in ms
WAIT_TIMEOUT = int(os.getenv("WAIT_TIMEOUT", "10000"))  # Wait operations timeout
NAVIGATION_TIMEOUT = int(os.getenv("NAVIGATION_TIMEOUT", "30000"))  # Navigation timeout


class _StepControlSignal(Exception):
    """
    Raised inside _execute_action_sync when the user clicks Next or Skip
    during a navigation/loader wait loop.
    .action is either 'next' (mark step complete) or 'skip' (mark step skipped).
    """
    def __init__(self, action: str):
        self.action = action  # 'next' or 'skip'
        super().__init__(f"Step control: {action}")


def _parse_multi_value_assertion(value: str) -> list:
    """
    Parse an assertion expected_value that may contain multiple items into a clean list.

    Handles any format an LLM might produce:
      - Python list repr:  "['EmergeX Case ID', 'Reported by']"
      - JSON array:        '["EmergeX Case ID", "Reported by"]'
      - Unquoted list:     "[EmergeX Case ID, Reported by]"
      - Plain CSV:         "EmergeX Case ID, Reported by, Date Reported"
      - Semicolon-sep:     "EmergeX Case ID; Reported by"
      - Newline-sep:       "EmergeX Case ID\nReported by"

    Returns a list of stripped, non-empty strings.
    Single-value strings are returned as a one-element list.
    """
    value = value.strip()

    # Remove outer list brackets if present: [...] or (...)
    if (value.startswith('[') and value.endswith(']')) or \
       (value.startswith('(') and value.endswith(')')):
        value = value[1:-1].strip()

    # Try JSON parse first (handles ["a","b"] and ['a','b'] after quote normalisation)
    try:
        import json
        # Normalise single quotes to double quotes for JSON parser
        normalised = value.replace("'", '"')
        parsed = json.loads(f'[{normalised}]')
        if isinstance(parsed, list):
            items = [str(i).strip() for i in parsed if str(i).strip()]
            if items:
                return items
    except Exception:
        pass

    # Detect separator: prefer the one that appears most
    newline_count = value.count('\n')
    semicolon_count = value.count(';')
    comma_count = value.count(',')

    if newline_count > 0 and newline_count >= comma_count:
        raw_items = value.split('\n')
    elif semicolon_count > 0 and semicolon_count >= comma_count:
        raw_items = value.split(';')
    else:
        raw_items = value.split(',')

    # Strip whitespace and surrounding quotes from each item
    items = []
    for part in raw_items:
        part = part.strip().strip('"').strip("'").strip()
        if part:
            items.append(part)
    return items


def _run_in_process(test_suite: Dict, headless: bool, timeout: int, result_queue, update_queue=None, signal_file=None, initial_storage_state=None, keep_browser_open: bool = True):
    """
    Run Playwright tests in a separate process.
    This avoids Windows asyncio subprocess limitations.
    Sends real-time updates via update_queue for SSE streaming.
    """
    # Import Playwright inside the process
    from playwright.sync_api import sync_playwright, expect as sync_expect

    def send_update(update_type: str, data: Dict):
        """Send update to the queue for SSE broadcasting."""
        if update_queue:
            try:
                update_queue.put({
                    "type": update_type,
                    **data
                })
            except Exception:
                pass  # Don't fail execution if update fails

    print(f"\n{'='*60}")
    print("ENHANCED EXECUTOR - Running in separate process")
    print(f"Project: {test_suite.get('project', 'Unknown')}")
    print(f"Base URL: {test_suite.get('base_url', 'N/A')}")
    print(f"Test cases: {len(test_suite.get('test_cases', []))}")
    print(f"Headless: {headless}")
    print(f"Keep browser open: {keep_browser_open}")
    print(f"Timeout: {timeout}ms")
    print(f"{'='*60}\n")

    # Send execution started update
    send_update("execution_started", {
        "message": f"Starting execution of {len(test_suite.get('test_cases', []))} tests",
        "project": test_suite.get('project', 'Unknown'),
        "base_url": test_suite.get('base_url', 'N/A'),
        "total_tests": len(test_suite.get('test_cases', [])),
        "headless": headless
    })

    test_cases = test_suite.get("test_cases", [])
    common_selectors = test_suite.get("common_selectors", {})
    test_data = test_suite.get("test_data", {})

    results = []
    passed = 0
    failed = 0
    shared_storage_state = initial_storage_state  # None on first run

    try:
        print("Starting Playwright...")
        send_update("browser_status", {
            "message": "Starting Playwright browser...",
            "status": "launching"
        })

        with sync_playwright() as p:
            def _launch_browser():
                print("Launching browser...")
                b = p.chromium.launch(headless=headless, slow_mo=500)
                print(f"Browser launched successfully (headless={headless}, slow_mo=500ms)")
                send_update("browser_status", {
                    "message": "Browser launched successfully",
                    "status": "ready",
                    "headless": headless
                })
                return b

            def _close_browser(b):
                b.close()
                print("Browser closed successfully")
                send_update("browser_status", {
                    "message": "Browser closed",
                    "status": "closed"
                })

            # keep_browser_open=True  → one browser + one shared context + one page for ALL test cases
            #                           page state (URL, cookies, modals) persists between TCs
            # keep_browser_open=False → fresh browser + context + page per test case
            browser = _launch_browser() if keep_browser_open else None

            # Create one shared context+page up front when keeping the session alive
            shared_context = None
            shared_page = None
            if keep_browser_open and browser:
                ctx_kwargs = {"viewport": {"width": 1920, "height": 1080}}
                if initial_storage_state is not None:
                    ctx_kwargs["storage_state"] = initial_storage_state
                shared_context = browser.new_context(**ctx_kwargs)
                shared_page = shared_context.new_page()
                print("Shared browser context + page created — session persists across all test cases")

            for idx, test_case in enumerate(test_cases):
                test_id = test_case.get("id", f"TC_{idx+1}")
                test_name = test_case.get("name", "Test Case")

                # Per-test-case browser lifecycle when keep_browser_open is OFF
                if not keep_browser_open:
                    browser = _launch_browser()

                # Send test started update
                send_update("test_started", {
                    "message": f"Starting test: {test_name}",
                    "test_id": test_id,
                    "test_name": test_name,
                    "test_index": idx + 1,
                    "total_tests": len(test_cases)
                })

                result = _execute_single_test_sync(
                    browser=browser,
                    test_case=test_case,
                    common_selectors=common_selectors,
                    suite_test_data=test_data,
                    timeout=timeout,
                    sync_expect=sync_expect,
                    send_update=send_update,
                    signal_file=signal_file,
                    initial_storage_state=shared_storage_state,
                    shared_page=shared_page,
                )
                results.append(result)

                # Carry forward auth state (cookies + localStorage) to next test
                if result.get("final_storage_state") is not None:
                    shared_storage_state = result["final_storage_state"]

                if result["status"] == "PASSED":
                    passed += 1
                    send_update("test_completed", {
                        "message": f"Test passed: {test_name}",
                        "test_id": test_id,
                        "test_name": test_name,
                        "status": "PASSED",
                        "passed_count": passed,
                        "failed_count": failed
                    })
                else:
                    failed += 1
                    send_update("test_completed", {
                        "message": f"Test failed: {test_name}",
                        "test_id": test_id,
                        "test_name": test_name,
                        "status": "FAILED",
                        "error": result.get("error", "Unknown error"),
                        "passed_count": passed,
                        "failed_count": failed
                    })

                # Close browser after each test case when keep_browser_open is OFF
                if not keep_browser_open:
                    _close_browser(browser)
                    browser = None

            # Close shared page → context → browser after all TCs complete
            if keep_browser_open:
                if shared_page:
                    try:
                        shared_page.close()
                    except Exception:
                        pass
                if shared_context:
                    try:
                        shared_context.close()
                        print("Shared browser context closed")
                    except Exception:
                        pass
                if browser:
                    _close_browser(browser)

        final_result = {
            "project": test_suite.get("project", "Unknown"),
            "base_url": test_suite.get("base_url", ""),
            "total": len(test_cases),
            "passed": passed,
            "failed": failed,
            "results": results,
            "executed_at": datetime.now().isoformat(),
            "final_storage_state": shared_storage_state,
            "final_url": results[-1].get("final_url", test_suite.get("base_url", "")) if results else test_suite.get("base_url", ""),
        }

        # Send execution completed update
        send_update("execution_completed", {
            "message": f"Execution completed: {passed}/{len(test_cases)} tests passed",
            "total": len(test_cases),
            "passed": passed,
            "failed": failed,
            "status": "success" if failed == 0 else "completed"
        })

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Browser error: {error_details}")
        final_result = {
            "project": test_suite.get("project", "Unknown"),
            "base_url": test_suite.get("base_url", ""),
            "total": len(test_cases),
            "passed": 0,
            "failed": len(test_cases),
            "results": [{"error": f"Browser launch failed: {str(e)}", "traceback": error_details}],
            "executed_at": datetime.now().isoformat()
        }

        # Send execution error update
        send_update("execution_completed", {
            "message": f"Execution failed: {str(e)}",
            "total": len(test_cases),
            "passed": 0,
            "failed": len(test_cases),
            "status": "error",
            "error": str(e)
        })

    result_queue.put(final_result)


def _check_step_control(signal_file) -> str | None:
    """Read and clear the step-control signal file. Returns 'next', 'skip', or None."""
    if not signal_file:
        return None
    try:
        with open(signal_file, 'r') as f:
            val = f.read().strip()
        if val in ("next", "skip"):
            # Clear the file immediately so the signal is consumed
            open(signal_file, 'w').close()
            return val
    except Exception:
        pass
    return None


def _execute_single_test_sync(
    browser,
    test_case: Dict[str, Any],
    common_selectors: Dict,
    suite_test_data: Dict,
    timeout: int,
    sync_expect,
    send_update=None,
    signal_file=None,
    initial_storage_state=None,
    shared_page=None,
) -> Dict[str, Any]:
    """Execute a single test case from enhanced format (sync version).

    shared_page: when provided (keep_browser_open=True), reuse this existing
    page instead of creating a new context. The page retains its URL, cookies,
    and any open modals from the previous test case — session continues seamlessly.
    The context is NOT closed at the end of this function in that case.
    """
    test_id = test_case.get("id", "TC_001")
    test_name = test_case.get("name", "Test Case")
    steps = test_case.get("steps", [])

    # Helper for sending updates
    def step_update(update_type: str, data: Dict):
        if send_update:
            send_update(update_type, {"test_id": test_id, "test_name": test_name, **data})

    # Helper for capturing and sending screenshots
    def capture_and_send_screenshot(page, step_num: int, status: str):
        """Capture screenshot and send via SSE for live browser view."""
        if not send_update:
            return
        try:
            import base64
            # Capture screenshot as bytes
            screenshot_bytes = page.screenshot(type="png")
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

            # Send screenshot via SSE
            send_update("screenshot", {
                "test_id": test_id,
                "step": step_num,
                "status": status,
                "image": screenshot_base64,
                "url": page.url,
                "title": page.title() if hasattr(page, 'title') else ""
            })
        except Exception as e:
            print(f"    Screenshot capture failed: {e}")

    print(f"\n--- Test: {test_id} - {test_name} ---")
    print(f"Total Steps: {len(steps)}")

    # Emit live Excel row data for frontend grid
    try:
        from app.services.excel_export_service import (
            _steps_to_text, _steps_to_input_data, _expected_results_text
        )
        try:
            tc_no = int("".join(filter(str.isdigit, test_id)))
        except Exception:
            tc_no = 0
        step_update("excel_row_init", {
            "tc_no": tc_no,
            "test_name": test_name,
            "steps_text": _steps_to_text(steps),
            "expected_result": _expected_results_text(test_case),
            "input_data": _steps_to_input_data(steps, suite_test_data or {}),
            "total_steps": len(steps),
        })
    except Exception:
        pass  # Never block execution for view-layer side effects

    result = {
        "test_id": test_id,
        "test_name": test_name,
        "status": "PASSED",
        "steps": [],
        "selector_mappings": {},
        "screenshots": [],
        "started_at": datetime.now().isoformat(),
        "error": None,
        # New fields for step-level retry tracking
        "steps_failed": 0,
        "steps_retried": 0,
        "final_storage_state": None,
    }

    if shared_page is not None:
        # Reuse the caller-managed page — browser session continues from where last TC left off
        page = shared_page
        context = page.context
        owns_context = False
        print(f"  Reusing shared page (current URL: {page.url})")
    else:
        # Fresh context + page for this test case (keep_browser_open=False)
        context_kwargs = {"viewport": {"width": 1920, "height": 1080}}
        if initial_storage_state is not None:
            context_kwargs["storage_state"] = initial_storage_state
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        owns_context = True

    try:
        total_steps = len(steps)
        # Mutable context dict shared across all steps in this test run.
        # Used to pass information between consecutive steps (e.g. last fill value
        # used by a subsequent assert_all_rows step).
        run_context: Dict = {}
        # Track current URL for navigation detection
        _current_url = [page.url]
        for step in steps:
            step_num = step.get("step_number", 0)
            instruction = step.get("instruction", "")
            action = step.get("action", {})
            action_type = action.get("type", "")
            selector_hints = step.get("selector_hints", {}) or {}
            step_test_data = step.get("test_data", {}) or {}
            assertions = step.get("assertions", []) or []

            import time as step_time
            step_start = step_time.time()

            # Drain any stale step-control signals from the previous step before starting
            _check_step_control(signal_file)

            print(f"\n  Step {step_num}: {instruction[:60]}...")
            print(f"    Action: {action_type}")

            # Send step started update
            step_update("step_started", {
                "message": f"Step {step_num}: {instruction[:60]}...",
                "step_number": step_num,
                "total_steps": total_steps,
                "action": action_type,
                "instruction": instruction
            })

            # Capture screenshot at step start to show current browser state
            capture_and_send_screenshot(page, step_num, "running")

            step_result = {
                "step": step_num,
                "action": action_type,
                "instruction": instruction,
                "status": "PASSED",
                "selector_used": None,
                "error": None,
                # New fields for retry tracking
                "retry_count": 0,
                "retry_attempts": [],
            }

            # Step-level retry loop
            max_step_retries = STEP_MAX_RETRIES
            retry_attempts = []
            step_passed = False
            failed_selectors = []
            current_selector_hints = selector_hints.copy()

            for attempt in range(max_step_retries + 1):
                attempt_start = step_time.time()

                try:
                    # Increase timeout on retries
                    current_timeout = int(timeout * (RETRY_TIMEOUT_MULTIPLIER ** attempt))

                    # Get alternative selectors on retry (attempt > 0)
                    if attempt > 0:
                        print(f"    [RETRY {attempt}/{max_step_retries}] Generating alternative selectors...")

                        # Generate alternatives
                        alternatives = _generate_alternative_selectors(
                            page=page,
                            selector_hints=selector_hints,
                            action_type=action_type,
                            attempt=attempt,
                            failed_selectors=failed_selectors
                        )

                        # On last retry, try live DOM + LLM selector rescue
                        if attempt == max_step_retries and page:
                            step_update("step_retry", {
                                "message": f"Step {step_num}: trying live selector rescue...",
                                "step_number": step_num,
                                "attempt": attempt,
                                "live_rescue": True,
                            })
                            live_selectors = _live_selector_rescue(
                                page=page,
                                element_name=selector_hints.get("element_name", ""),
                                element_type=selector_hints.get("element_type", ""),
                                action_type=action_type,
                                instruction=instruction,
                                failed_selectors=failed_selectors,
                            )
                            if live_selectors:
                                print(f"    [LiveSelectorRescue] LLM suggested {len(live_selectors)} selectors: {live_selectors}")
                                # Prepend LLM selectors so they're tried FIRST
                                alternatives = live_selectors + [a for a in alternatives if a not in live_selectors]

                        if alternatives:
                            current_selector_hints["alternative_selectors"] = alternatives
                            print(f"    Generated {len(alternatives)} alternative selectors")

                        # Send retry SSE event
                        step_update("step_retry", {
                            "message": f"Step {step_num} failed, retrying ({attempt}/{max_step_retries})...",
                            "step_number": step_num,
                            "attempt": attempt,
                            "max_retries": max_step_retries,
                            "alternative_selectors": len(alternatives) if alternatives else 0,
                        })

                        # Capture screenshot for retry attempt
                        capture_and_send_screenshot(page, step_num, "running")

                    # Execute the action
                    selector_used = _execute_action_sync(
                        page=page,
                        action_type=action_type,
                        selector_hints=current_selector_hints,
                        step_test_data=step_test_data,
                        assertions=assertions,
                        suite_test_data=suite_test_data,
                        timeout=current_timeout,
                        sync_expect=sync_expect,
                        instruction=instruction,
                        signal_file=signal_file,
                        run_context=run_context,
                    )

                    # Success!
                    step_passed = True
                    step_result["selector_used"] = selector_used
                    step_result["retry_count"] = attempt

                    if selector_used:
                        result["selector_mappings"][f"step_{step_num}"] = selector_used

                    step_elapsed = step_time.time() - step_start
                    attempt_duration = step_time.time() - attempt_start

                    if attempt > 0:
                        print(f"    [RETRY SUCCESS] Step passed on attempt {attempt + 1}")
                        result["steps_retried"] += 1

                        # Send retry success SSE event
                        step_update("step_retry_success", {
                            "message": f"Step {step_num} succeeded on retry {attempt}",
                            "step_number": step_num,
                            "attempt": attempt,
                            "selector_used": selector_used,
                            "duration": round(attempt_duration, 2),
                        })
                    else:
                        print(f"    [PASSED] (took {step_elapsed:.2f}s)")

                    # Capture and send screenshot after successful step
                    capture_and_send_screenshot(page, step_num, "passed")

                    # Send step completed update (success)
                    step_update("step_completed", {
                        "message": f"Step {step_num} passed" + (f" (retry {attempt})" if attempt > 0 else ""),
                        "step_number": step_num,
                        "status": "PASSED",
                        "duration": round(step_elapsed, 2),
                        "selector_used": selector_used,
                        "retry_count": attempt,
                        "instruction": instruction,
                    })

                    break  # Exit retry loop on success

                except _StepControlSignal as ctrl_sig:
                    # User clicked Next or Skip — break out of retry loop immediately
                    step_elapsed = step_time.time() - step_start
                    if ctrl_sig.action == "next":
                        # Mark as PASSED (user confirmed step is complete)
                        step_passed = True
                        step_result["status"] = "PASSED"
                        print(f"    [NEXT] User marked step {step_num} as complete")
                        capture_and_send_screenshot(page, step_num, "passed")
                        step_update("step_completed", {
                            "message": f"Step {step_num} marked complete by user (Next)",
                            "step_number": step_num,
                            "status": "PASSED",
                            "duration": round(step_elapsed, 2),
                            "retry_count": attempt,
                        })
                    else:
                        # Mark as SKIPPED
                        step_passed = True  # Don't count as failure
                        step_result["status"] = "SKIPPED"
                        step_result["error"] = "Skipped by user"
                        print(f"    [SKIP] User skipped step {step_num}")
                        capture_and_send_screenshot(page, step_num, "failed")
                        step_update("step_completed", {
                            "message": f"Step {step_num} skipped by user",
                            "step_number": step_num,
                            "status": "SKIPPED",
                            "duration": round(step_elapsed, 2),
                            "retry_count": attempt,
                        })
                    break  # Exit retry loop

                except Exception as e:
                    attempt_duration = step_time.time() - attempt_start
                    error_msg = str(e) if str(e) else f"Unknown error in step {step_num}"

                    # Track failed selector if available
                    if "selector" in str(e).lower():
                        for sel in current_selector_hints.get("suggested_selectors", []):
                            if sel not in failed_selectors:
                                failed_selectors.append(sel)

                    # Record retry attempt
                    retry_attempts.append({
                        "attempt": attempt,
                        "error": error_msg[:200],
                        "duration": round(attempt_duration, 2),
                        "selectors_tried": len(current_selector_hints.get("suggested_selectors", [])),
                    })

                    if attempt < max_step_retries:
                        print(f"    [ATTEMPT {attempt + 1} FAILED] {error_msg[:60]}... (will retry)")
                        # Capture screenshot for failed attempt
                        capture_and_send_screenshot(page, step_num, "failed")
                    else:
                        print(f"    [FINAL ATTEMPT FAILED] {error_msg}")
                        # Final attempt failed — try IR vision fallback for UI actions
                        if action_type in ("fill", "click", "select"):
                            print(f"    [IR-Rescue] All DOM-based attempts failed, trying vision fallback...")
                            ir_success = _ir_selector_rescue(
                                page=page,
                                action_type=action_type,
                                instruction=instruction,
                                selector_hints=current_selector_hints,
                                failed_selectors=failed_selectors,
                                step_test_data=step_test_data,
                                suite_test_data=suite_test_data,
                                timeout=current_timeout,
                                sync_expect=sync_expect,
                                run_context=run_context,
                            )
                            if ir_success:
                                step_passed = True
                                step_result["selector_used"] = "ir_vision_rescue"
                                step_result["retry_count"] = attempt
                                capture_and_send_screenshot(page, step_num, "passed")
                                step_update("step_completed", {
                                    "message": f"Step {step_num} succeeded via IR vision fallback",
                                    "step_number": step_num,
                                    "status": "PASSED",
                                    "duration": round(step_time.time() - step_start, 2),
                                    "retry_count": attempt,
                                })
                                break

            # After retry loop
            if step_passed:
                step_result["retry_attempts"] = retry_attempts
            else:
                # Step failed after all retries
                step_elapsed = step_time.time() - step_start
                last_error = retry_attempts[-1]["error"] if retry_attempts else "Unknown error"

                step_result["status"] = "FAILED"
                step_result["error"] = last_error
                step_result["retry_count"] = max_step_retries
                step_result["retry_attempts"] = retry_attempts

                result["steps_failed"] += 1

                # Only mark test as failed if at least one step failed
                if result["status"] != "FAILED":
                    result["status"] = "FAILED"
                    result["error"] = f"Step {step_num}: {last_error}"

                # Capture final failure screenshot
                capture_and_send_screenshot(page, step_num, "failed")

                # Send step retry exhausted SSE event
                step_update("step_retry_exhausted", {
                    "message": f"Step {step_num} failed after {max_step_retries + 1} attempts, continuing to next step...",
                    "step_number": step_num,
                    "total_attempts": max_step_retries + 1,
                    "error": last_error[:100],
                })

                # Send step completed update (failed)
                step_update("step_completed", {
                    "message": f"Step {step_num} failed after {max_step_retries + 1} attempts",
                    "step_number": step_num,
                    "status": "FAILED",
                    "duration": round(step_elapsed, 2),
                    "error": last_error,
                    "retry_count": max_step_retries,
                    "instruction": instruction,
                })

                try:
                    path = f"error_{test_id}_step{step_num}.png"
                    page.screenshot(path=path)
                    result["screenshots"].append(path)
                    print(f"    Screenshot saved: {path}")
                except Exception:
                    pass

                # IMPORTANT: Continue to next step instead of breaking!
                # This is the key change - we don't break anymore

            result["steps"].append(step_result)

            # Detect page navigation after each step
            try:
                new_url = page.url
                if new_url and new_url != _current_url[0] and not new_url.startswith("about:"):
                    _current_url[0] = new_url
                    import base64 as _b64
                    try:
                        btns = page.locator("button:visible").count()
                        inp = page.locator("input:visible, textarea:visible, select:visible").count()
                        links = page.locator("a:visible").count()
                        title = ""
                        try:
                            title = page.title()
                        except Exception:
                            pass
                        elements_summary = (
                            f"Browser navigated to: {new_url}\n\n"
                            f"Page title: {title or 'N/A'}\n"
                            f"Available elements: {btns} button(s), {inp} form field(s), {links} link(s)."
                        )
                        nav_screenshot = page.screenshot(type="png")
                        nav_screenshot_b64 = _b64.b64encode(nav_screenshot).decode("utf-8")
                    except Exception:
                        elements_summary = f"Browser navigated to: {new_url}"
                        nav_screenshot_b64 = ""
                    step_update("page_navigated", {
                        "url": new_url,
                        "elements_summary": elements_summary,
                        "image": nav_screenshot_b64,
                    })
            except Exception:
                pass  # Never block execution for navigation detection
            # Loop continues to next step naturally

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e) if str(e) else "Unknown test error"

    finally:
        try:
            result["final_url"] = page.url
        except Exception:
            pass
        try:
            result["final_storage_state"] = context.storage_state()
        except Exception:
            pass  # Carry-forward simply won't happen for next test
        # Only close the context when we created it (keep_browser_open=False)
        # When shared, _run_in_process closes it after all tests finish
        if owns_context:
            try:
                context.close()
            except Exception:
                pass

    result["finished_at"] = datetime.now().isoformat()

    status_icon = "[OK]" if result["status"] == "PASSED" else "[FAIL]"
    print(f"\n  {status_icon} Test {test_id}: {result['status']}")

    return result


def _get_best_selector_sync(page, selector_hints: Dict, step_test_data: Dict = None, action_type: str = None, instruction: str = "") -> Optional[str]:
    """
    Get the best working selector from hints (sync version).
    Validates element type matches the action (fill needs input/textarea, etc.)
    Passes instruction for keyword-based icon button matching when element_name is empty.
    """
    suggested = selector_hints.get("suggested_selectors", [])
    element_name = selector_hints.get("element_name")
    element_type = selector_hints.get("element_type", "")

    # For dropdown/select elements, try label-adjacent button patterns FIRST
    # This catches custom dropdown widgets like <label>Select Project</label><div><button>…</button></div>
    # before the LLM's suggested selectors (which may target the wrong element).
    if element_type and element_type.lower() in ("dropdown", "select") and element_name and action_type in ("click", "select", "fill"):
        label_candidates = [element_name]
        cleaned = element_name.lower().replace("dropdown", "").replace("select", "").strip()
        if cleaned and cleaned != element_name.lower():
            label_candidates.append(cleaned)

        for label_text in label_candidates:
            for lbl_sel in [
                f'label:has-text("{label_text}") ~ div button',
                f'label:has-text("{label_text}") + div button',
                f'label:has-text("{label_text}") ~ button',
                f'label:has-text("{label_text}") + button',
            ]:
                try:
                    loc = page.locator(lbl_sel)
                    if loc.count() > 0:
                        print(f"    [dropdown priority] Found via label-adjacent: {lbl_sel}")
                        return f'locator::{lbl_sel}'
                except Exception:
                    pass

    # Try each suggested selector
    for selector in suggested:
        try:
            py_selector = _convert_selector_to_python(selector)
            if py_selector:
                locator = _create_locator_sync(page, py_selector)
                if locator and locator.count() > 0:
                    # Validate element is appropriate for the action
                    if _validate_element_for_action(page, locator, action_type):
                        return py_selector
        except Exception:
            continue

    # NEW: Try alternative selectors (from retry logic)
    alternative_selectors = selector_hints.get("alternative_selectors", [])
    for alt_selector in alternative_selectors:
        try:
            py_selector = _convert_selector_to_python(alt_selector)
            if py_selector:
                locator = _create_locator_sync(page, py_selector)
                if locator and locator.count() > 0:
                    if _validate_element_for_action(page, locator, action_type):
                        print(f"    Alternative selector worked: {alt_selector}")
                        return py_selector
        except Exception:
            continue

    # Fallback: generate selector from element info
    if element_name and element_type:
        fallback_selectors = _generate_fallback_selectors(element_name, element_type)
        for selector in fallback_selectors:
            try:
                locator = _create_locator_sync(page, selector)
                if locator and locator.count() > 0:
                    if _validate_element_for_action(page, locator, action_type):
                        return selector
            except Exception:
                continue

    # Fallback 2: Infer from test_data keys
    if step_test_data:
        inferred_selectors = _infer_selectors_from_test_data(step_test_data)
        for selector in inferred_selectors:
            try:
                locator = _create_locator_sync(page, selector)
                if locator and locator.count() > 0:
                    if _validate_element_for_action(page, locator, action_type):
                        return selector
            except Exception:
                continue

    # Fallback 3: Dynamic page analysis (already returns correct element type)
    # Pass instruction for keyword-based icon button matching
    dynamic_selector = _find_selector_dynamically_sync(page, selector_hints, step_test_data, action_type, instruction)
    if dynamic_selector:
        return dynamic_selector

    return None


def _validate_element_for_action(page, locator, action_type: str) -> bool:
    """
    Validate that the found element is appropriate for the action type.
    For fill: must be input, textarea, select, or contenteditable
    For click: any visible element is fine
    """
    if not action_type:
        return True  # No validation needed

    try:
        # Get the tag name and attributes of the first matching element
        element_info = locator.first.evaluate("""
            el => ({
                tagName: el.tagName.toLowerCase(),
                type: el.type || '',
                contentEditable: el.contentEditable === 'true',
                role: el.getAttribute('role') || ''
            })
        """)

        tag = element_info.get("tagName", "")
        input_type = element_info.get("type", "")
        is_editable = element_info.get("contentEditable", False)
        role = element_info.get("role", "")

        if action_type == "fill":
            # For fill, element must be fillable
            fillable_tags = ["input", "textarea", "select"]
            if tag in fillable_tags:
                # But not button type inputs
                if tag == "input" and input_type in ["button", "submit", "reset", "image"]:
                    return False
                return True
            if is_editable:
                return True
            return False

        elif action_type == "click":
            # Any visible element can be clicked
            return True

        elif action_type == "select":
            # Must be a select element
            return tag == "select"

        # For other actions, accept any element
        return True

    except Exception:
        # If we can't validate, accept the element
        return True


def _find_selector_dynamically_sync(page, selector_hints: Dict, test_data: Dict = None, action_type: str = None, instruction: str = "") -> Optional[str]:
    """Dynamically analyze the page to find the right selector (sync version).

    Enhanced to support icon-only buttons by matching against title, aria-label, and alt attributes
    using keywords extracted from the instruction when element_name is empty.
    """
    try:
        element_name = selector_hints.get("element_name", "").lower() if selector_hints.get("element_name") else ""
        element_type = selector_hints.get("element_type", "").lower() if selector_hints.get("element_type") else ""

        looking_for = None
        if test_data:
            if "password" in test_data:
                looking_for = "password"
            elif "email" in test_data:
                looking_for = "email"
            elif "username" in test_data:
                looking_for = "username"

        elements = page.evaluate("""
        () => {
            const data = { inputs: [], textareas: [], buttons: [], links: [], headings: [] };

            document.querySelectorAll('input').forEach(el => {
                data.inputs.push({
                    id: el.id || '',
                    name: el.name || '',
                    type: el.type || '',
                    placeholder: el.placeholder || '',
                    'aria-label': el.getAttribute('aria-label') || '',
                    visible: el.offsetParent !== null
                });
            });

            document.querySelectorAll('textarea').forEach(el => {
                data.textareas.push({
                    id: el.id || '',
                    name: el.name || '',
                    placeholder: el.placeholder || '',
                    'aria-label': el.getAttribute('aria-label') || '',
                    class: el.className || '',
                    visible: el.offsetParent !== null
                });
            });

            document.querySelectorAll('button, input[type="submit"], [role="button"], a.btn, a[class*="button"]').forEach(el => {
                // Get alt text from child img or svg title (store both original and lowercase)
                var altTextOriginal = '';
                var childImg = el.querySelector('img');
                var childSvg = el.querySelector('svg');
                if (childImg) {
                    altTextOriginal = childImg.getAttribute('alt') || '';
                } else if (childSvg) {
                    var svgTitle = childSvg.querySelector('title');
                    if (svgTitle) {
                        altTextOriginal = svgTitle.textContent || '';
                    }
                }

                var titleOriginal = el.getAttribute('title') || '';
                var ariaLabelOriginal = el.getAttribute('aria-label') || '';

                // Better visibility check - offsetParent can be null for fixed/absolute positioned elements
                var rect = el.getBoundingClientRect();
                var style = window.getComputedStyle(el);
                var isVisible = (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.visibility !== 'hidden' &&
                    style.display !== 'none' &&
                    style.opacity !== '0'
                );

                data.buttons.push({
                    id: el.id || '',
                    type: el.type || el.tagName.toLowerCase(),
                    text: (el.innerText || el.value || '').trim().toLowerCase(),
                    'aria-label': ariaLabelOriginal.toLowerCase(),
                    'aria-label-original': ariaLabelOriginal,
                    'title': titleOriginal.toLowerCase(),
                    'title-original': titleOriginal,
                    'alt': altTextOriginal.toLowerCase(),
                    'alt-original': altTextOriginal,
                    class: el.className || '',
                    visible: isVisible
                });
            });

            document.querySelectorAll('a').forEach(el => {
                data.links.push({
                    id: el.id || '',
                    text: (el.innerText || '').trim().toLowerCase(),
                    href: el.href || '',
                    visible: el.offsetParent !== null
                });
            });

            document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(el => {
                data.headings.push({
                    tag: el.tagName.toLowerCase(),
                    text: (el.innerText || '').trim().toLowerCase(),
                    visible: el.offsetParent !== null
                });
            });

            return data;
        }
        """)

        inputs = elements.get("inputs", [])
        textareas = elements.get("textareas", [])
        buttons = elements.get("buttons", [])
        links = elements.get("links", [])
        headings = elements.get("headings", [])

        # Debug: print found elements
        print(f"      Dynamic search - element_name: '{element_name}', element_type: '{element_type}', action: '{action_type}', instruction: '{instruction[:50] if instruction else ''}'...")
        print(f"      Found {len(textareas)} textareas, {len(inputs)} inputs, {len(buttons)} buttons")

        # For fill actions, check textareas first with fuzzy matching
        if action_type == "fill":
            # Search textareas with fuzzy placeholder matching
            for ta in textareas:
                if ta.get("visible"):
                    placeholder = ta.get("placeholder", "").lower()
                    aria_label = ta.get("aria-label", "").lower()

                    # Fuzzy match: check if any word from element_name appears in placeholder
                    if element_name:
                        element_words = element_name.lower().split()
                        placeholder_match = any(word in placeholder for word in element_words if len(word) > 3)
                        label_match = any(word in aria_label for word in element_words if len(word) > 3)

                        if placeholder_match or label_match:
                            print(f"        Found textarea with placeholder: '{placeholder[:50]}...'")
                            if ta.get("id"):
                                return f'locator::#{ta["id"]}'
                            if ta.get("name"):
                                return f'locator::textarea[name="{ta["name"]}"]'
                            # Use placeholder for selector
                            if placeholder:
                                return f'locator::textarea[placeholder*="{placeholder[:30]}"]'
                            return 'locator::textarea'

            # If looking for text/value data, try to find any visible textarea
            if test_data and ("text" in test_data or "value" in test_data or "incident" in str(test_data).lower()):
                for ta in textareas:
                    if ta.get("visible"):
                        print(f"        Found visible textarea for text input")
                        if ta.get("id"):
                            return f'locator::#{ta["id"]}'
                        if ta.get("placeholder"):
                            return f'locator::textarea[placeholder*="{ta["placeholder"][:20]}"]'
                        return 'locator::textarea'

        # For dropdown/select elements: try label-adjacent button FIRST
        # This handles cases like <label>Select Project</label><div><button>...</button></div>
        # which are custom dropdown triggers that look like buttons in the DOM.
        if element_type in ("dropdown", "select") and element_name and action_type in ("click", "select", "fill"):
            # Build candidate label texts: full name + name without "dropdown"/"select" suffix
            label_candidates = [element_name]
            cleaned = element_name.replace("dropdown", "").replace("select", "").strip()
            if cleaned and cleaned != element_name:
                label_candidates.append(cleaned)

            for label_text in label_candidates:
                # Try sibling combinator: label ~ div button and label + div button
                for selector in [
                    f'label:has-text("{label_text}") ~ div button',
                    f'label:has-text("{label_text}") + div button',
                    f'label:has-text("{label_text}") ~ button',
                    f'label:has-text("{label_text}") + button',
                ]:
                    try:
                        loc = page.locator(selector)
                        if loc.count() > 0:
                            print(f"        Found dropdown via label-adjacent selector: {selector}")
                            return f'locator::{selector}'
                    except Exception:
                        pass

                # Also try: find the label, then look for the next sibling button-like element
                try:
                    label_loc = page.locator(f'label:has-text("{label_text}")')
                    if label_loc.count() > 0:
                        # Use evaluate to find sibling
                        sibling_sel = page.evaluate(f"""
                        () => {{
                            const label = document.evaluate(
                                '//label[contains(text(), "{label_text}")]',
                                document, null,
                                XPathResult.FIRST_ORDERED_NODE_TYPE, null
                            ).singleNodeValue;
                            if (!label) return null;
                            // Walk siblings
                            let sib = label.nextElementSibling;
                            while (sib) {{
                                const btn = sib.tagName === 'BUTTON' ? sib : sib.querySelector('button');
                                if (btn) {{
                                    if (btn.id) return '#' + btn.id;
                                    const cls = btn.className.split(' ').find(c => c.length > 3 && !c.includes(':'));
                                    if (cls) return 'label:has-text("{label_text}") ~ div button, label:has-text("{label_text}") + button';
                                    return null;
                                }}
                                sib = sib.nextElementSibling;
                            }}
                            return null;
                        }}
                        """)
                        if sibling_sel and sibling_sel.startswith('#'):
                            print(f"        Found dropdown via label sibling id: {sibling_sel}")
                            return f'locator::{sibling_sel}'
                except Exception:
                    pass

        # For button/click actions, search buttons first
        if element_type == "button" or action_type == "click":
            # Extract keywords from instruction for icon button matching
            # FIXED: Always extract keywords (not just when element_name is empty)
            # Keywords serve as a fallback when direct element_name match fails
            keywords = []
            if instruction:
                keywords = _extract_keywords_from_instruction(instruction)
                if keywords:
                    print(f"        Extracted keywords from instruction: {keywords}")
                    # Debug: Show buttons with title/alt attributes
                    for i, btn in enumerate(buttons):
                        if btn.get("visible") and (btn.get("title") or btn.get("alt")):
                            print(f"        Button[{i}]: title='{btn.get('title-original', '')}' alt='{btn.get('alt-original', '')}' text='{btn.get('text', '')[:20]}'")
            if not keywords:
                print(f"        No keywords extracted (instruction provided: {bool(instruction)})")

            for btn in buttons:
                if not btn.get("visible"):
                    continue

                btn_text = btn.get("text", "")
                btn_label = btn.get("aria-label", "")
                btn_title = btn.get("title", "")
                btn_alt = btn.get("alt", "")
                btn_id = btn.get("id", "")
                btn_class = btn.get("class", "")

                # Get original case values for selector generation
                btn_title_original = btn.get("title-original", btn_title)
                btn_alt_original = btn.get("alt-original", btn_alt)
                btn_label_original = btn.get("aria-label-original", btn_label)

                # Normalize for comparison
                btn_text_normalized = btn_text.replace(" ", "").lower()
                btn_label_normalized = btn_label.replace(" ", "").lower()

                # Combine all searchable attributes for keyword matching (lowercase)
                # Build lowercase version for matching, preserve original for selectors
                all_attrs = f"{btn_text} {btn_label} {btn_title} {btn_alt}"
                all_attrs_lower = all_attrs.lower()

                matched = False
                match_reason = ""

                # Priority 1: Match by element_name if available
                if element_name:
                    element_name_normalized = element_name.replace(" ", "").lower()
                    print(f"        Checking button: text='{btn_text}' title='{btn_title}' alt='{btn_alt}'")

                    if (element_name_normalized in btn_text_normalized or
                        element_name_normalized in btn_label_normalized or
                        element_name_normalized in btn_title.replace(" ", "").lower() or
                        element_name_normalized in btn_alt.replace(" ", "").lower()):
                        matched = True
                        match_reason = "element_name"

                # Priority 2: Match by keywords from instruction (for icon buttons OR as fallback)
                # FIXED: Changed 'elif' to 'if not matched and' to enable keyword fallback
                # when element_name exists but didn't match directly
                if not matched and keywords:
                    # Skip sidebar/nav buttons when looking for a dropdown — they are
                    # navigation items, not form controls.  A nav button has an alt that
                    # looks like a page name ("Our Project", "Incident", etc.) while its
                    # text is the same nav label.  Heuristic: if the button's text equals
                    # its alt and neither is empty, it is a nav item → skip for dropdowns.
                    if element_type == "dropdown":
                        nav_btn = (
                            btn_alt and btn_text and
                            btn_alt.lower().strip() == btn_text.lower().strip()
                        )
                        if nav_btn:
                            continue  # Skip sidebar nav buttons for dropdown searches

                    # Count how many keywords match (case-insensitive)
                    match_count = sum(1 for kw in keywords if kw in all_attrs_lower)
                    # Require ≥2 keywords for dropdown elements (tighter match needed)
                    # to avoid false positives like sidebar nav buttons
                    threshold = 2 if element_type == "dropdown" else 1
                    if match_count >= threshold:
                        matched = True
                        match_reason = f"keywords({match_count}/{len(keywords)})"
                        print(f"        Button matched via {match_reason}: title='{btn_title_original}' alt='{btn_alt_original}'")

                if matched:
                    # Build the best selector for this button (use ORIGINAL case for selectors)
                    if btn_id:
                        return f'locator::#{btn_id}'
                    elif btn_title_original:
                        # Use title attribute selector for icon buttons (original case)
                        return f'locator::button[title="{btn_title_original}"]'
                    elif btn_label_original:
                        return f'get_by_role::button::{btn_label_original}'
                    elif btn_alt_original:
                        # Use has() selector for button containing img with alt (original case)
                        return f'locator::button:has(img[alt="{btn_alt_original}"])'
                    elif btn_text.strip():
                        return f'get_by_role::button::{btn_text.strip().title()}'
                    elif btn_class:
                        # Use first meaningful class as fallback
                        classes = btn_class.split()
                        if classes:
                            return f'locator::button.{classes[0]}'

            # Also try links that look like buttons (only if element_name provided)
            if element_name:
                element_name_normalized = element_name.replace(" ", "").lower()
                for link in links:
                    link_text = link.get("text", "")
                    link_text_normalized = link_text.replace(" ", "").lower()
                    if link.get("visible") and element_name_normalized in link_text_normalized:
                        if link.get("id"):
                            return f'locator::#{link["id"]}'
                        return f'get_by_role::link::{link_text.title()}'

            # Last resort for login/submit-style actions: try type=submit button
            _login_keywords = {"login", "signin", "submit", "log in", "sign in"}
            _is_login_action = (
                (element_name and element_name.lower().replace(" ", "") in {k.replace(" ", "") for k in _login_keywords})
                or (instruction and any(kw in instruction.lower() for kw in _login_keywords))
            )
            if _is_login_action:
                try:
                    submit_btn = page.locator('button[type="submit"]')
                    if submit_btn.count() > 0 and submit_btn.first.is_visible():
                        print(f"        Fell back to button[type='submit'] for login/submit action")
                        return 'locator::button[type="submit"]'
                except Exception:
                    pass
                try:
                    submit_inp = page.locator('input[type="submit"]')
                    if submit_inp.count() > 0 and submit_inp.first.is_visible():
                        return 'locator::input[type="submit"]'
                except Exception:
                    pass

        # For heading assertions
        if element_type == "heading":
            if element_name:
                for heading in headings:
                    if heading.get("visible") and element_name in heading.get("text", ""):
                        return f'get_by_role::heading::{element_name.title()}'

        # For password inputs
        if looking_for == "password":
            for inp in inputs:
                if inp.get("type") == "password" and inp.get("visible"):
                    if inp.get("id"):
                        return f'locator::#{inp["id"]}'
                    if inp.get("name"):
                        return f'locator::input[name="{inp["name"]}"]'
                    return 'locator::input[type="password"]'

        # For email inputs
        if looking_for == "email":
            for inp in inputs:
                if (inp.get("type") == "email" or
                    "email" in inp.get("placeholder", "").lower() or
                    "email" in inp.get("name", "").lower()) and inp.get("visible"):
                    if inp.get("id"):
                        return f'locator::#{inp["id"]}'
                    if inp.get("name"):
                        return f'locator::input[name="{inp["name"]}"]'
                    if inp.get("type") == "email":
                        return 'locator::input[type="email"]'

        # For inputs by element name
        if element_name and element_type == "input":
            for inp in inputs:
                if (element_name in inp.get("placeholder", "").lower() or
                    element_name in inp.get("aria-label", "").lower() or
                    element_name in inp.get("name", "").lower()) and inp.get("visible"):
                    if inp.get("id"):
                        return f'locator::#{inp["id"]}'
                    if inp.get("name"):
                        return f'locator::input[name="{inp["name"]}"]'

    except Exception as e:
        print(f"      Dynamic selector search failed: {e}")

    return None


def _infer_selectors_from_test_data(test_data: Dict) -> List[str]:
    """Infer possible selectors from test_data keys."""
    selectors = []

    if "email" in test_data:
        selectors.extend([
            'get_by_label::Email',
            'get_by_placeholder::Email',
            'get_by_placeholder::Enter your email',
            'locator::input[type="email"]',
            'locator::input[name="email"]',
            'locator::#email',
        ])

    if "password" in test_data:
        selectors.extend([
            'get_by_label::Password',
            'get_by_placeholder::Password',
            'get_by_placeholder::Enter your password',
            'locator::input[type="password"]',
            'locator::input[name="password"]',
            'locator::#password',
        ])

    if "username" in test_data:
        selectors.extend([
            'get_by_label::Username',
            'get_by_placeholder::Username',
            'locator::input[name="username"]',
            'locator::#username',
        ])

    # For text/value data (usually goes into textarea)
    if "text" in test_data or "value" in test_data:
        selectors.extend([
            'locator::textarea',
            'locator::textarea:visible',
        ])

    return selectors


def _convert_selector_to_python(selector: str) -> Optional[str]:
    """Convert Playwright JS/Python selector syntax to our internal format.

    Handles both JS camelCase (getByRole) and Python snake_case (get_by_role)
    API styles that LLMs may generate.
    """
    if not selector:
        return None

    # Already in our internal format — return as-is
    if "::" in selector and any(selector.startswith(p) for p in ["get_by_", "locator::"]):
        return selector

    # ── Python snake_case API calls (page.get_by_role / page.get_by_label …) ─
    # get_by_role('button', name='Login') or get_by_role('button', name='Login', exact=False)
    if "get_by_role(" in selector:
        m = re.search(r"get_by_role\(\s*['\"](\w+)['\"](?:\s*,\s*name\s*=\s*['\"]([^'\"]+)['\"])?\s*(?:,\s*[^)]+)?\s*\)", selector)
        if m:
            role = m.group(1)
            name = m.group(2)
            return f'get_by_role::{role}::{name}' if name else f'get_by_role::{role}'

    # get_by_label('Email') or page.get_by_label("Email")
    if "get_by_label(" in selector:
        m = re.search(r"get_by_label\(\s*'([^']+)'\s*\)", selector) or \
            re.search(r'get_by_label\(\s*"([^"]+)"\s*\)', selector)
        if m:
            return f'get_by_label::{m.group(1)}'

    # get_by_placeholder('Enter email') or page.get_by_placeholder("Enter email")
    if "get_by_placeholder(" in selector:
        m = re.search(r"get_by_placeholder\(\s*'([^']+)'\s*\)", selector) or \
            re.search(r'get_by_placeholder\(\s*"([^"]+)"\s*\)', selector)
        if m:
            return f'get_by_placeholder::{m.group(1)}'

    # get_by_text('Login') or page.get_by_text("Login")
    if "get_by_text(" in selector:
        m = re.search(r"get_by_text\(\s*'([^']+)'\s*\)", selector) or \
            re.search(r'get_by_text\(\s*"([^"]+)"\s*\)', selector)
        if m:
            return f'get_by_text::{m.group(1)}'

    # ── JS camelCase API calls (getByRole / getByLabel …) ────────────────────
    if "getByLabel" in selector:
        match = re.search(r"getByLabel\(['\"]([^'\"]+)['\"]\)", selector)
        if match:
            return f'get_by_label::{match.group(1)}'

    if "getByRole" in selector:
        match = re.search(r"getByRole\(['\"](\w+)['\"],\s*\{\s*name:\s*['\"]([^'\"]+)['\"]\s*\}\)", selector)
        if match:
            return f'get_by_role::{match.group(1)}::{match.group(2)}'
        match = re.search(r"getByRole\(['\"](\w+)['\"]\)", selector)
        if match:
            return f'get_by_role::{match.group(1)}'

    if "getByPlaceholder" in selector:
        match = re.search(r"getByPlaceholder\(['\"]([^'\"]+)['\"]\)", selector)
        if match:
            return f'get_by_placeholder::{match.group(1)}'

    if "getByText" in selector:
        match = re.search(r"getByText\(['\"]([^'\"]+)['\"]\)", selector)
        if match:
            return f'get_by_text::{match.group(1)}'

    # ── page.locator('css') — use separate single/double quote passes so that
    # attribute selectors like button[type="submit"] are parsed correctly.
    # The old [^'\"]+ approach stopped at the first inner quote character.
    if "locator(" in selector:
        # Single-quoted argument: page.locator('button[type="submit"]')
        m = re.search(r"\.locator\(\s*'([^']*)'\s*\)", selector)
        if not m:
            # Double-quoted argument: page.locator("button[type='submit']")
            m = re.search(r'\.locator\(\s*"([^"]*)"\s*\)', selector)
        if m:
            return f'locator::{m.group(1)}'

    # ── Raw CSS / XPath shortcuts ─────────────────────────────────────────────
    if selector.startswith("#") or selector.startswith(".") or selector.startswith("[") or selector.startswith("//"):
        return f'locator::{selector}'

    if " or " in selector:
        first_selector = selector.split(" or ")[0].strip()
        return _convert_selector_to_python(first_selector)

    return None


def _create_locator_sync(page, selector: str):
    """Create a Playwright locator from our internal selector format (sync version)."""
    if not selector:
        return None

    if selector.startswith("get_by_label::"):
        label = selector.replace("get_by_label::", "")
        return page.get_by_label(label)

    elif selector.startswith("get_by_role::"):
        parts = selector.replace("get_by_role::", "").split("::")
        role = parts[0]
        if len(parts) > 1:
            # Try exact match first to avoid ambiguity
            exact_locator = page.get_by_role(role, name=parts[1], exact=True)
            if exact_locator.count() > 0:
                return exact_locator
            # Fallback to non-exact match
            return page.get_by_role(role, name=parts[1])
        return page.get_by_role(role)

    elif selector.startswith("get_by_placeholder::"):
        placeholder = selector.replace("get_by_placeholder::", "")
        return page.get_by_placeholder(placeholder)

    elif selector.startswith("get_by_text::"):
        text = selector.replace("get_by_text::", "")
        # Try exact match first to avoid strict mode violations
        exact_locator = page.get_by_text(text, exact=True)
        if exact_locator.count() == 1:
            return exact_locator
        # If exact match has multiple or none, try button/link role first
        button_locator = page.get_by_role("button", name=text, exact=True)
        if button_locator.count() == 1:
            return button_locator
        link_locator = page.get_by_role("link", name=text, exact=True)
        if link_locator.count() == 1:
            return link_locator
        # Fallback to first match if multiple elements
        non_exact_locator = page.get_by_text(text)
        if non_exact_locator.count() > 1:
            print(f"      Warning: Multiple elements match '{text}', using .first")
            return non_exact_locator.first
        return non_exact_locator

    elif selector.startswith("locator::"):
        css = selector.replace("locator::", "")
        return page.locator(css)

    return page.locator(selector)


def _generate_fallback_selectors(element_name: str, element_type: str) -> List[str]:
    """Generate fallback selectors based on element name and type."""
    selectors = []
    name_lower = element_name.lower() if element_name else ""

    if element_type == "input":
        selectors.extend([
            f'get_by_label::{element_name}',
            f'get_by_placeholder::{element_name}',
            f'locator::input[name="{name_lower}"]',
        ])
    elif element_type == "textarea":
        selectors.extend([
            f'get_by_label::{element_name}',
            f'get_by_placeholder::{element_name}',
            f'locator::textarea[name="{name_lower}"]',
            'locator::textarea',
        ])
    elif element_type == "button":
        # Common text variants for this button name
        name_title = element_name.title()
        name_upper = element_name.upper()
        selectors.extend([
            f'get_by_role::button::{element_name}',
            f'get_by_role::button::{name_title}',
            f'get_by_text::{element_name}',
            f'locator::button:has-text("{element_name}")',
        ])
        # For login/submit-style buttons also try type=submit
        _login_kw = {"login", "log in", "signin", "sign in", "submit", "continue", "next", "proceed"}
        if name_lower in _login_kw or any(kw in name_lower for kw in _login_kw):
            selectors.extend([
                'locator::button[type="submit"]',
                'locator::input[type="submit"]',
                f'locator::button:has-text("{name_title}")',
                f'locator::button:has-text("{name_upper}")',
            ])
    elif element_type == "heading":
        selectors.extend([
            f'get_by_role::heading::{element_name}',
            f'get_by_text::{element_name}',
        ])
    elif element_type == "link":
        selectors.extend([
            f'get_by_role::link::{element_name}',
            f'get_by_text::{element_name}',
        ])

    return selectors


def _generate_alternative_selectors(
    page,
    selector_hints: Dict,
    action_type: str,
    attempt: int,
    failed_selectors: List[str] = None
) -> List[str]:
    """
    Generate alternative selectors for retry attempts.
    Uses heuristics and dynamic page analysis to find new selectors.

    Args:
        page: Playwright page object
        selector_hints: Original selector hints from the step
        action_type: Type of action (click, fill, etc.)
        attempt: Current retry attempt number (1, 2, or 3)
        failed_selectors: List of selectors that have already failed

    Returns:
        List of alternative selectors to try
    """
    failed_selectors = failed_selectors or []
    alternatives = []

    element_name = selector_hints.get("element_name", "")
    element_type = selector_hints.get("element_type", "")

    # Tier 1: Heuristic variations (fast, no LLM)
    if element_name:
        name_lower = element_name.lower()
        name_upper = element_name.upper()
        name_title = element_name.title()

        # Text variations
        text_variations = [
            f'get_by_text::{name_lower}',
            f'get_by_text::{name_upper}',
            f'get_by_text::{name_title}',
        ]

        # Role-based alternatives
        role_variations = [
            f'get_by_role::button::{element_name}',
            f'get_by_role::link::{element_name}',
            f'get_by_role::menuitem::{element_name}',
        ]

        # Attribute-based alternatives
        attr_variations = [
            f'locator::[aria-label*="{name_lower}"]',
            f'locator::[aria-label="{element_name}"]',
            f'locator::[title*="{name_lower}"]',
            f'locator::[name*="{name_lower}"]',
            f'locator::[placeholder*="{name_lower}"]',
        ]

        # Data attribute fallbacks
        data_variations = [
            f'locator::[data-testid="{name_lower}"]',
            f'locator::[data-test="{name_lower}"]',
            f'locator::[data-cy="{name_lower}"]',
            f'locator::[data-automation-id="{name_lower}"]',
        ]

        alternatives.extend(text_variations)
        alternatives.extend(role_variations)
        alternatives.extend(attr_variations)
        alternatives.extend(data_variations)

    # Tier 2: Dynamic page analysis (on retry 2+)
    if attempt >= 2 and page:
        try:
            # Use JavaScript to find elements matching the element name/type
            dynamic_selectors = page.evaluate('''(args) => {
                const { elementName, elementType, actionType } = args;
                const selectors = [];
                const nameLower = elementName.toLowerCase();

                // Find elements by text content
                const allElements = document.querySelectorAll('button, a, input, textarea, [role="button"], [role="link"]');

                for (const el of allElements) {
                    // Check text content
                    const text = (el.textContent || el.innerText || '').trim().toLowerCase();
                    if (text && text.includes(nameLower)) {
                        // Build a unique selector for this element
                        if (el.id) {
                            selectors.push(`#${el.id}`);
                        } else if (el.name) {
                            selectors.push(`[name="${el.name}"]`);
                        } else if (el.className) {
                            const classes = el.className.split(' ').filter(c => c).slice(0, 2).join('.');
                            if (classes) {
                                selectors.push(`.${classes}`);
                            }
                        }
                    }

                    // Check aria-label
                    const ariaLabel = el.getAttribute('aria-label') || '';
                    if (ariaLabel.toLowerCase().includes(nameLower)) {
                        selectors.push(`[aria-label="${ariaLabel}"]`);
                    }

                    // Check value attribute for inputs
                    if (el.tagName === 'INPUT' && el.value && el.value.toLowerCase().includes(nameLower)) {
                        if (el.name) {
                            selectors.push(`input[name="${el.name}"]`);
                        }
                    }
                }

                return selectors.slice(0, 5);  // Limit to 5 selectors
            }''', {"elementName": element_name, "elementType": element_type, "actionType": action_type})

            # Convert to our selector format
            for sel in dynamic_selectors:
                alternatives.append(f'locator::{sel}')

        except Exception as e:
            print(f"    Dynamic page analysis failed: {e}")

    # Tier 3: Action-specific fallbacks (on retry 3)
    if attempt >= 3:
        if action_type == "click":
            # Try broader selectors for clickable elements
            alternatives.extend([
                'locator::button:visible:first',
                'locator::a:visible:first',
                'locator::[role="button"]:visible:first',
            ])
        elif action_type == "fill":
            # Try broader selectors for fillable elements
            alternatives.extend([
                'locator::input:visible:first',
                'locator::textarea:visible:first',
                'locator::[contenteditable="true"]:visible:first',
            ])

    # Filter out already-failed selectors
    alternatives = [s for s in alternatives if s not in failed_selectors]

    # Remove duplicates while preserving order
    seen = set()
    unique_alternatives = []
    for sel in alternatives:
        if sel not in seen:
            seen.add(sel)
            unique_alternatives.append(sel)

    return unique_alternatives


def _live_selector_rescue(
    page,
    element_name: str,
    element_type: str,
    action_type: str,
    instruction: str,
    failed_selectors: List[str],
) -> List[str]:
    """
    Last-resort selector recovery: scrape the live DOM, then ask the LLM
    to identify the best Playwright selector for this step.
    Returns a list of up to 3 selector strings (may be empty on any error).
    Always wrapped in try/except so it never blocks execution.
    """
    try:
        # 1. Scrape live page context
        page_context = page.evaluate("""() => {
            const getAttrs = (el) => ({
                id: el.id || '',
                name: el.getAttribute('name') || '',
                type: el.getAttribute('type') || el.tagName.toLowerCase(),
                placeholder: el.getAttribute('placeholder') || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                text: (el.innerText || el.value || '').trim().substring(0, 60),
                forLabel: el.labels && el.labels[0] ? el.labels[0].innerText.trim().substring(0, 40) : ''
            });
            return {
                url: window.location.href,
                inputs: Array.from(document.querySelectorAll('input,textarea,select'))
                    .filter(el => !['hidden','submit','reset'].includes(el.type))
                    .slice(0, 20).map(getAttrs),
                buttons: Array.from(document.querySelectorAll('button,[role="button"],input[type="submit"]'))
                    .slice(0, 20).map(getAttrs),
                links: Array.from(document.querySelectorAll('a[href]'))
                    .slice(0, 15)
                    .map(el => ({ text: (el.innerText||'').trim().substring(0,60), href: el.href||'' })),
            };
        }""")

        # 2. Build LLM prompt
        inputs_text = "\n".join(
            f"  - id={e['id']} name={e['name']} type={e['type']} placeholder={e['placeholder']} aria-label={e['ariaLabel']} label={e['forLabel']} text={e['text']}"
            for e in page_context.get("inputs", [])
        ) or "  (none)"
        buttons_text = "\n".join(
            f"  - id={e['id']} name={e['name']} aria-label={e['ariaLabel']} text={e['text']}"
            for e in page_context.get("buttons", [])
        ) or "  (none)"
        links_text = "\n".join(
            f"  - text={e['text']} href={e['href']}"
            for e in page_context.get("links", [])
        ) or "  (none)"
        failed_text = "\n".join(f"  - {s}" for s in failed_selectors) or "  (none)"

        prompt = f"""You are a Playwright selector expert. A test step failed because none of the pre-generated selectors matched.
Given the live page context below, return the best Playwright selector(s) for this step.

STEP INSTRUCTION: {instruction}
ELEMENT NAME: {element_name}
ELEMENT TYPE: {element_type}
ACTION TYPE: {action_type}
PAGE URL: {page_context.get('url', '')}

LIVE PAGE ELEMENTS:
INPUTS ({len(page_context.get('inputs', []))}):
{inputs_text}

BUTTONS ({len(page_context.get('buttons', []))}):
{buttons_text}

LINKS ({len(page_context.get('links', []))}):
{links_text}

FAILED SELECTORS (do NOT suggest these):
{failed_text}

Return ONLY a JSON array of up to 3 Playwright selector strings using our selector format.
Selector format options:
- "get_by_label::LabelText"
- "get_by_placeholder::PlaceholderText"
- "get_by_role::button::ButtonText"
- "get_by_role::link::LinkText"
- "get_by_text::VisibleText"
- "locator::#id" or "locator::[name=value]" or "locator::[aria-label=value]"

Example response: ["get_by_label::Email", "locator::#email", "get_by_placeholder::Enter email"]
Return ONLY the JSON array, no explanation."""

        # 3. Make a synchronous LLM call using settings
        import json as _json
        from app.core.config import settings
        from app.agents.base_agent import BaseAgent, LLMProvider

        provider_str = getattr(settings, 'DEFAULT_LLM_PROVIDER', 'groq').lower()
        provider = LLMProvider(provider_str)

        api_keys = {
            "anthropic_api_key": getattr(settings, 'ANTHROPIC_API_KEY', None),
            "openai_api_key": getattr(settings, 'OPENAI_API_KEY', None),
            "groq_api_key": getattr(settings, 'GROQ_API_KEY', None),
        }

        class _SelectorRescueAgent(BaseAgent):
            def execute(self, *args, **kwargs):
                return self.call_llm(kwargs.get('prompt', ''))

        agent = _SelectorRescueAgent(provider=provider, **api_keys)
        raw = agent.call_llm(prompt)

        # 4. Parse response — extract JSON array
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        selectors = _json.loads(raw)
        if isinstance(selectors, list):
            return [str(s) for s in selectors if s and str(s) not in failed_selectors][:3]
        return []

    except Exception as e:
        print(f"    [LiveSelectorRescue] Failed: {e}")
        return []


def _ir_selector_rescue(
    page,
    action_type: str,
    instruction: str,
    selector_hints: Dict,
    failed_selectors: List[str],
    step_test_data: Dict,
    suite_test_data: Dict,
    timeout: int,
    sync_expect,
    run_context: Dict = None,
) -> bool:
    """
    Last-resort IR fallback: capture a screenshot, ask the vision model to
    identify the element, then attempt the action with each suggestion.
    Returns True if any suggestion succeeded, False otherwise.
    Never raises — all failures are caught internally.
    """
    try:
        from app.core.config import settings
        if not settings.IMAGE_ANALYSIS_ENABLED:
            return False

        from app.agents.image_analyzer import analyze_screenshot_for_selector
        import base64

        # Capture screenshot as base64
        screenshot_bytes = page.screenshot(type="png")
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

        # Use the last failed selector as context for the vision model
        failed_selector = failed_selectors[-1] if failed_selectors else selector_hints.get("suggested_selectors", [""])[0]
        error_hint = f"Element not found after {len(failed_selectors)} selector attempt(s)"

        suggestions = analyze_screenshot_for_selector(
            screenshot_b64=screenshot_b64,
            action_type=action_type,
            instruction=instruction,
            selector=failed_selector,
            error=error_hint,
        )

        if not suggestions:
            print(f"    [IR-Rescue] Vision model returned no suggestions")
            return False

        print(f"    [IR-Rescue] Vision model returned {len(suggestions)} suggestion(s)")

        for suggestion in suggestions:
            sel = suggestion.get("selector", "")
            interaction = suggestion.get("interaction", action_type)
            reasoning = suggestion.get("reasoning", "")
            if not sel:
                continue

            print(f"    [IR-Rescue] Trying: {sel} (interaction={interaction}) — {reasoning}")

            # Build a minimal selector_hints dict for this suggestion
            ir_hints = {
                "suggested_selectors": [sel],
                "element_name": selector_hints.get("element_name", ""),
                "element_type": suggestion.get("widget_type", selector_hints.get("element_type", "")),
            }

            # Map vision interaction to our action_type if needed
            effective_action = action_type
            if action_type == "fill" and interaction in ("select_option", "click"):
                effective_action = interaction
            elif action_type == "click" and interaction == "fill":
                effective_action = "click"  # keep original intent

            try:
                _execute_action_sync(
                    page=page,
                    action_type=effective_action,
                    selector_hints=ir_hints,
                    step_test_data=step_test_data,
                    assertions=[],
                    suite_test_data=suite_test_data,
                    timeout=timeout,
                    sync_expect=sync_expect,
                    instruction=instruction,
                    signal_file=None,
                    run_context=run_context,
                )
                print(f"    [IR-Rescue] Succeeded via vision: {sel!r}")
                return True
            except Exception as ir_err:
                print(f"    [IR-Rescue] Suggestion failed: {ir_err}")
                continue

    except Exception as e:
        print(f"    [IR-Rescue] Vision fallback error: {e}")

    return False


def _extract_button_name_from_instruction(instruction: str) -> Optional[str]:
    """Extract button/element name from instruction text."""
    if not instruction:
        return None

    instruction_lower = instruction.lower()

    # Common patterns: "Click on the X button", "Click the X button", "Click X"
    patterns = [
        r'click\s+(?:on\s+)?(?:the\s+)?["\']?([^"\']+?)["\']?\s+button',
        r'click\s+(?:on\s+)?(?:the\s+)?([A-Z][A-Za-z\s]+?)(?:\s+button)?[.\n]',
        r'click\s+(?:on\s+)?["\']([^"\']+)["\']',
    ]

    for pattern in patterns:
        match = re.search(pattern, instruction_lower)
        if match:
            name = match.group(1).strip()
            if name and len(name) > 1:
                # Capitalize properly
                return name.title()

    # Try to find quoted text
    quoted = re.findall(r'["\']([^"\']+)["\']', instruction)
    for q in quoted:
        if len(q) > 1 and len(q) < 50:
            return q

    return None


def _extract_keywords_from_instruction(instruction: str) -> List[str]:
    """
    Extract meaningful keywords from instruction text for icon button matching.
    Used when element_name is empty but we need to match buttons by title/aria-label/alt.
    """
    if not instruction:
        return []

    # Common words to ignore
    stop_words = {
        'click', 'press', 'tap', 'select', 'choose', 'find', 'locate', 'hit', 'push',
        'the', 'a', 'an', 'on', 'in', 'at', 'to', 'for', 'of', 'and', 'or', 'with',
        'button', 'icon', 'link', 'element', 'field', 'should', 'must', 'will',
        'then', 'now', 'next', 'step', 'action', 'perform', 'execute'
    }

    # Extract words (letters only)
    words = re.findall(r'\b[a-zA-Z]+\b', instruction.lower())

    # Filter and return meaningful keywords
    keywords = [w for w in words if w not in stop_words and len(w) > 2]

    # Add synonyms for common UI actions to improve matching
    synonym_map = {
        'toggle': ['collapse', 'expand', 'sidebar', 'menu', 'panel'],
        'collapse': ['toggle', 'minimize', 'hide', 'close'],
        'expand': ['toggle', 'maximize', 'show', 'open'],
        'arrow': ['chevron', 'caret', 'toggle', 'collapse', 'expand'],
        'sidebar': ['menu', 'panel', 'nav', 'navigation', 'toggle'],
        'menu': ['hamburger', 'sidebar', 'nav', 'navigation'],
        'close': ['dismiss', 'cancel', 'exit', 'hide'],
        'open': ['show', 'expand', 'display'],
        'edit': ['modify', 'change', 'pencil', 'update'],
        'delete': ['remove', 'trash', 'bin'],
        'add': ['create', 'new', 'plus'],
        'search': ['find', 'magnifier', 'lookup'],
        'settings': ['gear', 'cog', 'config', 'preferences'],
        'refresh': ['reload', 'sync', 'update'],
        'back': ['previous', 'return', 'left'],
        'forward': ['next', 'right'],
    }

    # Add synonyms for matching keywords
    expanded_keywords = list(keywords)
    for kw in keywords:
        if kw in synonym_map:
            for synonym in synonym_map[kw]:
                if synonym not in expanded_keywords:
                    expanded_keywords.append(synonym)

    return expanded_keywords


def _extract_fill_value_from_instruction(instruction: str) -> Optional[str]:
    """
    Extract fill value from instruction text when test_data is missing.
    Handles patterns like:
    - Test Data:\n"Some text here..."
    - Test Data: "Some text"
    - Input: "Some text"
    - Value: "Some text"
    - Embedded quoted multi-line text
    """
    if not instruction:
        return None

    # Pattern 1: "Test Data:" followed by quoted text (possibly multi-line)
    # Match: Test Data:\n"..." or Test Data: "..."
    test_data_pattern = r'Test\s*Data\s*:\s*\n?\s*["\'](.+?)(?:["\'](?:\s*$|\s*\n|$))'
    match = re.search(test_data_pattern, instruction, re.DOTALL | re.IGNORECASE)
    if match:
        value = match.group(1).strip()
        if value:
            print(f"    Extracted fill value from 'Test Data:' pattern ({len(value)} chars)")
            return value

    # Pattern 2: Look for quoted text after common keywords
    keywords = ['test data', 'input', 'value', 'text', 'enter', 'fill']
    for keyword in keywords:
        # Pattern: keyword followed by colon and quoted text
        pattern = rf'{keyword}\s*:\s*\n?\s*["\'](.+?)["\']'
        match = re.search(pattern, instruction, re.DOTALL | re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value and len(value) > 5:
                print(f"    Extracted fill value from '{keyword}:' pattern ({len(value)} chars)")
                return value

    # Pattern 3: Find the longest quoted string in the instruction (likely the data to fill)
    # This handles cases where the value is just embedded in quotes
    quoted_strings = re.findall(r'["\']([^"\']{10,})["\']', instruction, re.DOTALL)
    if quoted_strings:
        # Get the longest quoted string (most likely the fill data)
        longest = max(quoted_strings, key=len)
        if len(longest) > 10:
            print(f"    Extracted fill value from quoted text ({len(longest)} chars)")
            return longest.strip()

    # Pattern 4: If instruction has multi-line content after a colon or newline,
    # and it looks like data (not an instruction), extract it
    lines = instruction.split('\n')
    if len(lines) > 2:
        # Skip the first line (usually the instruction) and join the rest
        potential_data = '\n'.join(lines[1:]).strip()
        # Remove leading "Test Data:" or similar if present
        potential_data = re.sub(r'^(Test\s*Data|Input|Value)\s*:\s*', '', potential_data, flags=re.IGNORECASE)
        # Remove surrounding quotes if present
        potential_data = potential_data.strip('"\'')
        if len(potential_data) > 10:
            print(f"    Extracted fill value from multi-line instruction ({len(potential_data)} chars)")
            return potential_data

    return None


# Words stripped from element_name before using it as a label search keyword.
# Keeps only the meaningful noun/identifier part (e.g. "Select Project dropdown" → "Project").
_DROPDOWN_LABEL_STOPWORDS = {
    'select', 'choose', 'pick', 'dropdown', 'field', 'input', 'the', 'a', 'an',
    'box', 'list', 'menu', 'option', 'value', 'item',
}

# Selectors for actual progress/loader indicator elements (used by wait action)
# Deliberately narrow — avoids matching CSS '%' values in raw HTML
_PROGRESS_SELECTORS = [
    '[role="progressbar"]',
    '[class*="progress"]',
    '[class*="loader"]',
    '[class*="loading"]',
    '[aria-label*="progress" i]',
    '[aria-valuenow]',
]

# Selectors for dropdown popup containers, ordered most-specific first.
# These are used to scope option searches so we don't match nav/sidebar elements.
_DROPDOWN_POPUP_SELECTORS = [
    'div.absolute.z-50',      # Tailwind: absolute + high z-index (most specific)
    'div.fixed.z-50',
    'div.absolute',           # Tailwind absolute-positioned overlay
    'div.fixed',              # Fixed overlay
    'div[class*="dropdown"]', # Explicit dropdown class
    'div[class*="menu"]',     # Menu overlay
    'ul[role="listbox"]',     # ARIA listbox
    'div[role="listbox"]',
    'div.z-50',               # High z-index overlay
    'div.overflow-y-auto',    # Scrollable list
    'div[class*="popover"]',
    'div[class*="popup"]',
]

# Option item selector used INSIDE a scoped popup container.
# cursor-pointer is safe here because we're already inside the dropdown element.
_DROPDOWN_OPTION_SELECTOR_SCOPED = (
    '[role="option"], '
    'div[class*="option"], '
    'li[class*="option"], '
    'li, '
    'div.cursor-pointer, '
    'div.hover\\:bg-green-50'
)

# Option item selector for page-wide use (no cursor-pointer — too broad on full page)
_DROPDOWN_OPTION_SELECTOR = (
    '[role="option"], '
    'div[class*="option"], '
    'li[class*="option"], '
    'div.hover\\:bg-green-50'
)


def _snapshot_option_count(page) -> int:
    """Count currently visible dropdown option elements across the whole page."""
    try:
        return page.locator(_DROPDOWN_OPTION_SELECTOR).count()
    except Exception:
        return 0


def _get_dropdown_popup_container(page):
    """Return the first visible popup container element, or None."""
    for container_sel in _DROPDOWN_POPUP_SELECTORS:
        try:
            container = page.locator(container_sel).first
            if container.is_visible(timeout=500):
                return container
        except Exception:
            continue
    return None


def _get_dropdown_popup_options(page) -> list:
    """Return option elements from the active dropdown popup.

    Searches inside the popup container first (scoped) using the broader
    scoped selector that includes cursor-pointer — safe because we're inside
    the dropdown, not the full page.  Falls back to full-page scan if no
    container is found.
    """
    container = _get_dropdown_popup_container(page)
    if container is not None:
        try:
            opts = container.locator(_DROPDOWN_OPTION_SELECTOR_SCOPED).all()
            if opts:
                return opts
        except Exception:
            pass
    # Full-page fallback (narrower selector, no cursor-pointer)
    try:
        return page.locator(_DROPDOWN_OPTION_SELECTOR).all()
    except Exception:
        return []


def _wait_for_dropdown_options(page, baseline: int = 0, timeout_ms: int = 8000, poll_ms: int = 200) -> None:
    """Wait until the dropdown popup container appears and contains options.

    Uses the popup container as the primary signal — more reliable than counting
    option elements page-wide (which are polluted by nav/sidebar elements).
    Falls back to baseline-delta check on the page-wide selector.

    Works for any custom dropdown, including API-loaded ones.
    """
    elapsed = 0
    while elapsed < timeout_ms:
        try:
            container = _get_dropdown_popup_container(page)
            if container is not None:
                opts = container.locator(_DROPDOWN_OPTION_SELECTOR_SCOPED).all()
                if opts:
                    print(f"    Dropdown options ready ({len(opts)} in popup after ~{elapsed}ms)")
                    return
        except Exception:
            pass
        # Secondary: page-wide delta check
        try:
            current = page.locator(_DROPDOWN_OPTION_SELECTOR).count()
            if current > baseline:
                print(f"    Dropdown options ready ({current} found, +{current - baseline} new, after ~{elapsed}ms)")
                return
        except Exception:
            pass
        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms
    print(f"    Dropdown options did not appear within {timeout_ms}ms, proceeding anyway")


def _execute_action_sync(
    page,
    action_type: str,
    selector_hints: Dict,
    step_test_data: Dict,
    assertions: List,
    suite_test_data: Dict,
    timeout: int,
    sync_expect,
    instruction: str = "",
    signal_file=None,
    run_context: Dict = None,
) -> Optional[str]:
    """Execute a single action from enhanced format (sync version)."""
    selector_used = None

    if action_type == "goto":
        url = step_test_data.get("url", "")
        if not url:
            raise ValueError("No URL provided for goto action")

        # Replace parser fallback placeholder URLs with the real base URL from the
        # current page. This happens when the parser couldn't extract the real URL
        # and fell back to "https://example.com" or similar generic domains.
        PLACEHOLDER_HOSTS = {"example.com", "your-app.com", "localhost", "your-domain.com"}
        try:
            from urllib.parse import urlparse as _urlparse
            parsed = _urlparse(url)
            if parsed.hostname in PLACEHOLDER_HOSTS:
                current = page.url
                current_parsed = _urlparse(current)
                if current_parsed.scheme and current_parsed.netloc:
                    # Keep the path from the placeholder URL (e.g. /dashboard)
                    # but use the real host from the currently authenticated session
                    real_base = f"{current_parsed.scheme}://{current_parsed.netloc}"
                    real_url = real_base + (parsed.path or "/")
                    print(f"    [goto] Replaced placeholder URL {url!r} → {real_url!r}")
                    url = real_url
        except Exception:
            pass  # Never block navigation over a URL-fix heuristic

        print(f"    Navigating to: {url}")
        # Use load (all resources) then try networkidle briefly.
        # domcontentloaded is too early for React SPA — the JS bundle hasn't
        # rendered yet and subsequent fill steps write into an empty DOM.
        page.goto(url, wait_until="load", timeout=timeout)
        # Wait for networkidle so React finishes rendering the first view.
        # Cap at 15s — apps with persistent WS/SSE never reach true networkidle.
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass  # Timeout is acceptable — page is rendered enough after load
        actual_url = page.url
        print(f"    Landed on: {actual_url}")

        # Detect auth-redirect: if the server sent us to a DIFFERENT path than
        # requested (e.g. already-logged-in user hitting /login → /dashboard),
        # clear cookies + storage and retry so subsequent fill steps work.
        try:
            from urllib.parse import urlparse as _up_goto
            _req = _up_goto(url)
            _act = _up_goto(actual_url)
            _same_host = _req.netloc == _act.netloc
            _req_path = _req.path.rstrip("/") or "/"
            _act_path = _act.path.rstrip("/") or "/"
            if _same_host and _req_path != _act_path:
                print(f"    [goto] Redirected {_req_path!r} → {_act_path!r}; clearing auth state and retrying")
                page.context.clear_cookies()
                page.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch(e) {} }")
                page.goto(url, wait_until="load", timeout=timeout)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                actual_url = page.url
                print(f"    [goto] After auth-clear, landed on: {actual_url}")
        except Exception as _redir_err:
            print(f"    [goto] Auth-redirect check failed (non-fatal): {_redir_err}")

    elif action_type == "fill":
        # Get value to fill first - check common keys and fallback to any string value
        value = ""

        # If test_data signals "read from table column", fetch the live cell value first
        if step_test_data.get("source") == "table" and step_test_data.get("column_name"):
            col_name = step_test_data["column_name"]
            live_value = _read_cell_value_from_column(page, col_name)
            if live_value:
                value = live_value
                print(f"    [fill] Using live table value '{live_value}' from column '{col_name}'")
                # Store in run_context so the subsequent assert_all_rows step can use it
                if run_context is not None:
                    run_context["last_fill_value"] = live_value
                    run_context["last_fill_column"] = col_name

        elif step_test_data.get("source") == "context":
            context_key = step_test_data.get("capture_key", "captured_value")
            live_value = (run_context or {}).get(f"captured_{context_key}") or (run_context or {}).get("captured_value")
            if live_value:
                value = live_value
                print(f"    [fill] Using captured context value '{live_value}' (key='{context_key}')")

        # Check common keys first (skipped if value already resolved from table)
        if not value:
            for key in ["email", "password", "text", "value", "username", "input", "content", "data", "message"]:
                if key in step_test_data:
                    value = step_test_data[key]
                    break

        # If no common key found, use the first string value in test_data
        # Skip keys that are structural markers (source, column_name) to avoid using them as fill values
        if not value and step_test_data:
            skip_keys = {"source", "column_name"}
            for key, val in step_test_data.items():
                if key in skip_keys:
                    continue
                if isinstance(val, str) and val:
                    value = val
                    print(f"    Using test_data['{key}'] as fill value")
                    break

        # If still no value, try to extract from instruction text
        if not value and instruction:
            extracted_value = _extract_fill_value_from_instruction(instruction)
            if extracted_value:
                value = extracted_value

        if not value and suite_test_data.get("default_credentials"):
            creds = suite_test_data["default_credentials"]
            element_name = (selector_hints.get("element_name") or "").lower()
            if "password" in element_name:
                value = creds.get("password", "")
            elif "email" in element_name:
                value = creds.get("email", "")

        # Try to get best selector
        selector = _get_best_selector_sync(page, selector_hints, step_test_data, action_type="fill", instruction=instruction)

        # Verify the selector actually finds a visible, fillable element
        fill_success = False
        if selector:
            try:
                locator = _create_locator_sync(page, selector)
                count = locator.count()
                print(f"    Trying selector: {selector} (found {count} elements)")
                if count > 0:
                    # Check if first element is visible
                    first_elem = locator.first
                    if first_elem.is_visible():
                        display_value = '*' * len(value) if 'password' in selector.lower() else (value[:50] + '...' if len(value) > 50 else value)
                        print(f"    Value: {display_value}")
                        first_elem.fill(value, timeout=timeout)
                        fill_success = True
                        selector_used = selector
                        print(f"    Fill successful!")
                    else:
                        print(f"    Element found but not visible")
                else:
                    print(f"    No elements found with this selector")
            except Exception as e:
                print(f"    Selector {selector} failed: {e}")

        # If initial selector failed, try direct textarea/input search
        if not fill_success:
            print(f"    Initial selector failed, searching for fillable elements...")
            # Try to find any visible textarea first
            try:
                textarea_locator = page.locator("textarea")
                textarea_count = textarea_locator.count()
                print(f"    Found {textarea_count} textarea(s) on page")
                if textarea_count > 0:
                    # Find the first visible textarea
                    for i in range(textarea_count):
                        ta = textarea_locator.nth(i)
                        if ta.is_visible():
                            print(f"    Filling textarea #{i}...")
                            ta.fill(value, timeout=timeout)
                            fill_success = True
                            selector_used = f"locator::textarea:nth({i})"
                            break
            except Exception as e:
                print(f"    Textarea search failed: {e}")

        # Try visible input if textarea didn't work
        if not fill_success:
            try:
                # Look for text input that's not email/password/hidden
                input_locator = page.locator("input:not([type='password']):not([type='email']):not([type='hidden']):not([type='submit']):not([type='button'])")
                input_count = input_locator.count()
                print(f"    Found {input_count} input(s) on page")
                if input_count > 0:
                    for i in range(input_count):
                        inp = input_locator.nth(i)
                        if inp.is_visible():
                            print(f"    Filling input #{i}...")
                            inp.fill(value, timeout=timeout)
                            fill_success = True
                            selector_used = f"locator::input:nth({i})"
                            break
            except Exception as e:
                print(f"    Input search failed: {e}")

        if not fill_success:
            hints_info = f"element_name={selector_hints.get('element_name')}, element_type={selector_hints.get('element_type')}"
            data_keys = list(step_test_data.keys()) if step_test_data else []
            value_info = f"value_length={len(value)}" if value else "NO VALUE FOUND"
            raise ValueError(f"Could not fill any element. Hints: {hints_info}, Data keys: {data_keys}, {value_info}")

        # Warn if we filled with empty value
        if not value:
            print(f"    WARNING: Fill executed with empty value - test_data was null/empty and no value found in instruction")

    elif action_type == "click":
        selector = _get_best_selector_sync(page, selector_hints, step_test_data, action_type="click", instruction=instruction)

        # Fast-path for login/submit buttons: if selector still not found, try
        # button[type="submit"] before running through all text-variation fallbacks.
        if not selector:
            _el_name_lc = (selector_hints.get("element_name") or "").lower().replace(" ", "")
            _instr_lc = (instruction or "").lower()
            _is_submit = _el_name_lc in {"login", "signin", "submit", "logon"} or \
                         any(kw in _instr_lc for kw in ("log in", "login", "sign in", "submit", "click login", "click submit"))
            if _is_submit:
                for _submit_sel in ('button[type="submit"]', 'input[type="submit"]'):
                    try:
                        _sub_loc = page.locator(_submit_sel)
                        if _sub_loc.count() > 0 and _sub_loc.first.is_visible():
                            selector = f'locator::{_submit_sel}'
                            print(f"    [submit-fast-path] Found via {_submit_sel}")
                            break
                    except Exception:
                        pass

        # If no selector found and hints are empty, try to extract from instruction
        if not selector and not selector_hints.get("element_name"):
            button_name = _extract_button_name_from_instruction(instruction)
            if button_name:
                print(f"    Extracted button name from instruction: '{button_name}'")
                # Try to find button with this name
                try:
                    # Try exact match first
                    btn_locator = page.get_by_role("button", name=button_name, exact=True)
                    if btn_locator.count() > 0:
                        selector = f"get_by_role::button::{button_name}"
                    else:
                        # Try non-exact match
                        btn_locator = page.get_by_role("button", name=button_name)
                        if btn_locator.count() > 0:
                            selector = f"get_by_role::button::{button_name}"
                        else:
                            # Try text match
                            text_locator = page.get_by_text(button_name)
                            if text_locator.count() > 0:
                                selector = f"get_by_text::{button_name}"
                except Exception as e:
                    print(f"    Could not find button '{button_name}': {e}")

        # SMART FALLBACK: Handle common button text variations (login/signin/submit)
        if not selector:
            instruction_lower = instruction.lower() if instruction else ""

            # Define common button text variations
            # Each key should match words that might appear in instructions
            button_variations = {
                "login": ["Log in", "Login", "LOG IN", "log in", "Sign in", "Sign In", "SIGN IN"],
                "signin": ["Sign in", "Sign In", "SIGN IN", "Log in", "Login"],
                "signup": ["Sign up", "Sign Up", "SIGN UP", "Register", "Create Account"],
                "submit": ["Submit", "SUBMIT", "Send", "SEND", "Go", "Continue"],
                "save": ["Save", "SAVE", "Save Changes", "Update"],
                "cancel": ["Cancel", "CANCEL", "Close", "Back"],
                "next": ["Next", "NEXT", "Continue", "Proceed"],
                "confirm": ["Confirm", "CONFIRM", "OK", "Yes", "Accept"],
                # ADDED: Direct keys for common button names that might appear in instructions
                "continue": ["Continue", "CONTINUE", "Proceed", "Next", "Go", "OK"],
                "back": ["Back", "BACK", "Go Back", "Return", "Previous", "Cancel"],
                "previous": ["Previous", "Back", "Go Back", "Return"],
                "ok": ["OK", "Ok", "Okay", "Yes", "Confirm", "Accept"],
                "close": ["Close", "CLOSE", "X", "Dismiss", "Cancel"],
                "add": ["Add", "ADD", "Create", "New", "+"],
                "delete": ["Delete", "DELETE", "Remove", "Trash"],
                "edit": ["Edit", "EDIT", "Modify", "Update", "Change"],
            }

            # Check if instruction mentions any of these button types
            matched_variations = []
            for key, variations in button_variations.items():
                if key in instruction_lower:
                    matched_variations = variations
                    print(f"    Smart fallback: Trying {key} button variations: {variations}")
                    break

            # Also try submit button as fallback for any "click" on a form
            if not matched_variations and ("button" in instruction_lower or "click" in instruction_lower):
                # Check if there's a submit button on the page
                try:
                    submit_btn = page.locator('button[type="submit"]')
                    if submit_btn.count() > 0 and submit_btn.first.is_visible():
                        selector = 'locator::button[type="submit"]'
                        print(f"    Smart fallback: Found submit button")
                except Exception:
                    pass

            # Try each variation
            for variation in matched_variations:
                if selector:
                    break
                try:
                    # Try getByRole with exact match
                    btn = page.get_by_role("button", name=variation, exact=True)
                    if btn.count() > 0 and btn.first.is_visible():
                        selector = f"get_by_role::button::{variation}"
                        print(f"    Smart fallback: Found button with text '{variation}'")
                        break
                except Exception:
                    pass

                try:
                    # Try getByText
                    btn = page.get_by_text(variation, exact=True)
                    if btn.count() > 0 and btn.first.is_visible():
                        selector = f"get_by_text::{variation}"
                        print(f"    Smart fallback: Found element with text '{variation}'")
                        break
                except Exception:
                    pass

        if not selector:
            hints_info = f"element_name={selector_hints.get('element_name')}, element_type={selector_hints.get('element_type')}"
            raise ValueError(f"No working selector found for click action. Hints: {hints_info}")

        print(f"    Selector: {selector}")
        locator = _create_locator_sync(page, selector)

        # Check element state
        element_exists = locator.count() > 0
        is_visible = False
        is_enabled = True

        if element_exists:
            try:
                is_visible = locator.first.is_visible()
                is_enabled = locator.first.is_enabled()
            except Exception:
                pass

        print(f"    Element state: exists={element_exists}, visible={is_visible}, enabled={is_enabled}")

        click_done = False

        # Case 1: Element exists but NOT visible - try scroll into view first, then raise
        # Do NOT use force=True here: force click bypasses visibility and clicks hidden/wrong
        # elements silently, causing false PASSes where the page never actually changes.
        if element_exists and not is_visible:
            print(f"    Element found but not visible, trying scroll into view...")
            try:
                locator.first.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                locator.first.click(timeout=10000)
                click_done = True
                selector_used = selector
                print(f"    Scroll + click successful!")
            except Exception as e2:
                print(f"    Scroll + click failed: {e2}")
                # Raise so the retry mechanism tries better selectors instead of
                # silently force-clicking an invisible/wrong element.
                raise ValueError(
                    f"Element found but not visible and could not be clicked after scroll: {e2}"
                )

        # Case 2: Element is visible but disabled - wait for it to become enabled
        if not click_done and element_exists and is_visible and not is_enabled:
            print(f"    Button is disabled, waiting for it to become enabled (max 60s)...")
            for i in range(120):  # 120 * 500ms = 60 seconds
                # Check for Next/Skip signal every iteration
                ctrl = _check_step_control(signal_file)
                if ctrl in ("next", "skip"):
                    print(f"    Step control '{ctrl}' received — skipping disabled-button wait")
                    raise _StepControlSignal(ctrl)
                try:
                    if locator.first.is_enabled():
                        print(f"    Button is now enabled after {i * 0.5}s!")
                        is_enabled = True
                        break
                except Exception:
                    pass
                page.wait_for_timeout(500)

            # If still not enabled after 60s, use force click
            if not is_enabled:
                print(f"    Button still disabled after 60s, using force click...")
                locator.click(force=True, timeout=10000)
                click_done = True
                selector_used = selector

        # Case 3: Normal click - element is visible and enabled
        # Use short-timeout polling so Next/Skip signals are checked between attempts
        if not click_done:
            CLICK_POLL_MS = 2000   # try click with 2s timeout each poll
            click_polls = max(1, timeout // CLICK_POLL_MS)
            click_error = None
            for _cp in range(click_polls):
                # Check signal before each short-timeout click attempt
                ctrl = _check_step_control(signal_file)
                if ctrl in ("next", "skip"):
                    print(f"    Step control '{ctrl}' received — skipping click wait")
                    raise _StepControlSignal(ctrl)
                try:
                    locator.click(timeout=CLICK_POLL_MS)
                    click_done = True
                    selector_used = selector
                    click_error = None
                    break
                except Exception as e:
                    click_error = e
                    err_lower = str(e).lower()
                    # Force click immediately if element is obstructed
                    if "not visible" in err_lower or "outside of the viewport" in err_lower or "intercepted" in err_lower:
                        print(f"    Normal click failed ({e}), trying force click...")
                        try:
                            locator.click(force=True, timeout=10000)
                            click_done = True
                            selector_used = selector
                            click_error = None
                        except Exception as fe:
                            click_error = fe
                        break
                    # Timeout — poll again after checking signal
                    print(f"    Click attempt {_cp + 1}/{click_polls} timed out, retrying...")
            if not click_done and click_error is not None:
                raise click_error

        # Wait for navigation/redirect after click (max 10 seconds)
        # While waiting, opportunistically check for toast/alert on the NEXT step
        # so we catch short-lived toasts before the page navigates away.
        print(f"    Waiting for page navigation (max 10s)...")
        current_url = page.url
        navigated = False
        _toast_caught_during_nav: Dict = {}  # keyed by step_number → caught text
        # Store on page so the subsequent assert step can read it
        if not hasattr(page, '_toast_cache'):
            page._toast_cache = {}


        # Peek at upcoming toast assertions so we can verify them during the nav wait
        _pending_toast_checks = []
        if 'steps' in locals() and 'step_num' in locals():
            for _peek in steps:
                if _peek.get("step_number", 0) > step_num:
                    for _a in (_peek.get("assertions") or []):
                        if _a.get("type") == "toast":
                            _pending_toast_checks.append((_peek["step_number"], _a.get("expected_value", "")))

        try:
            # Wait for URL to change or timeout
            for i in range(20):  # 20 * 500ms = 10 seconds
                # Check for Next/Skip signal from user
                ctrl = _check_step_control(signal_file)
                if ctrl in ("next", "skip"):
                    print(f"    Step control '{ctrl}' received — skipping navigation wait")
                    raise _StepControlSignal(ctrl)

                # During first 3 seconds, check for toasts from upcoming steps
                if i < 6 and _pending_toast_checks:
                    for (_t_step_num, _t_value) in list(_pending_toast_checks):
                        if _t_step_num in _toast_caught_during_nav:
                            continue
                        _toast_text = str(_t_value).strip().strip('"').strip("'").strip('"').strip()
                        _toast_selectors = ["[role='alert']", "[role='status']", ".Toastify__toast",
                                            "[class*='toast']", "[class*='Toast']", "[class*='notification']",
                                            "[class*='success']", "[class*='snack']"]
                        for _sel in _toast_selectors:
                            try:
                                _loc = page.locator(_sel).first
                                if _loc.count() > 0:
                                    _text = (_loc.inner_text() or "").strip()
                                    if _toast_text.lower() in _text.lower():
                                        print(f"    [Toast pre-check] Caught toast for step {_t_step_num}: '{_text}'")
                                        _toast_caught_during_nav[_t_step_num] = _text
                                        page._toast_cache[_t_step_num] = _text
                                        break
                            except Exception:
                                pass

                new_url = page.url
                if new_url != current_url:
                    print(f"    Page navigated to: {new_url} (after {i * 0.5:.1f}s)")
                    # Wait a bit more for page to fully load
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    navigated = True
                    break
                page.wait_for_timeout(500)
        except _StepControlSignal:
            raise
        except Exception as e:
            print(f"    Navigation wait: {e}")

        if not navigated:
            # One last check — URL may have changed right as the loop ended
            final_url = page.url
            if final_url != current_url:
                print(f"    Late navigation detected: {final_url}")
                navigated = True

        if not navigated:
            print(f"    No navigation after click — click succeeded, page stayed at {current_url}")

    elif action_type == "assert":
        _execute_assertions_sync(page, assertions, selector_hints, step_test_data, timeout, sync_expect)

    elif action_type == "wait":
        wait_timeout = step_test_data.get("timeout", WAIT_TIMEOUT)

        # Check for percentage loader on the page (e.g., "24%", "50%", "100%")
        # Only match visible progress indicator elements — not raw HTML/CSS which always contains '%'
        print(f"    Checking for percentage loader...")
        try:
            percentage_found = False
            for _ in range(5):  # Quick check
                for psel in _PROGRESS_SELECTORS:
                    try:
                        elems = page.locator(psel).all()
                        for elem in elems:
                            try:
                                if not elem.is_visible():
                                    continue
                                txt = (elem.text_content() or "").strip()
                                if re.search(r'\b\d{1,3}%', txt):
                                    percentage_found = True
                                    break
                            except Exception:
                                continue
                    except Exception:
                        continue
                    if percentage_found:
                        break
                if percentage_found:
                    break
                page.wait_for_timeout(500)

            if percentage_found:
                print(f"    Percentage loader detected, waiting for 100%...")
                # Wait for percentage to reach 100% (max 120 seconds)
                failure_detected = False
                failure_message = ""
                for i in range(240):  # 240 * 500ms = 120 seconds
                    # Check for Next/Skip signal from user
                    ctrl = _check_step_control(signal_file)
                    if ctrl in ("next", "skip"):
                        print(f"    Step control '{ctrl}' received — skipping loader wait")
                        raise _StepControlSignal(ctrl)
                    try:
                        # Check for failure/error popups first
                        failure_selectors = [
                            "[class*='error']",
                            "[class*='fail']",
                            "[role='alert']",
                            ".MuiAlert-standardError",
                            "[class*='Error']",
                            "[class*='Fail']",
                        ]
                        for fail_sel in failure_selectors:
                            try:
                                fail_elem = page.locator(fail_sel).first
                                if fail_elem.count() > 0 and fail_elem.is_visible():
                                    fail_text = fail_elem.text_content() or ""
                                    # Check if it contains failure keywords
                                    if any(kw in fail_text.lower() for kw in ['failed', 'error', 'failure', 'unsuccessful']):
                                        failure_detected = True
                                        failure_message = fail_text.strip()
                                        print(f"    FAILURE DETECTED: {failure_message}")
                                        break
                            except Exception:
                                continue

                        if failure_detected:
                            break

                        # Also check for any visible text containing "failed"
                        try:
                            failed_text = page.locator("text=/failed/i").first
                            if failed_text.count() > 0 and failed_text.is_visible():
                                failure_message = failed_text.text_content() or "Operation failed"
                                failure_detected = True
                                print(f"    FAILURE DETECTED: {failure_message}")
                                break
                        except Exception:
                            pass

                        # Find percentage value from progress indicator elements only
                        percent = None
                        for psel in _PROGRESS_SELECTORS:
                            try:
                                elems = page.locator(psel).all()
                                for elem in elems:
                                    try:
                                        if not elem.is_visible():
                                            continue
                                        txt = (elem.text_content() or "").strip()
                                        m = re.search(r'\b(\d{1,3})%', txt)
                                        if m:
                                            percent = int(m.group(1))
                                            break
                                        # Also check aria-valuenow attribute
                                        val = elem.get_attribute("aria-valuenow")
                                        if val and val.isdigit():
                                            percent = int(val)
                                            break
                                    except Exception:
                                        continue
                            except Exception:
                                continue
                            if percent is not None:
                                break
                        if percent is not None:
                            if i % 10 == 0:
                                print(f"    Progress: {percent}%")
                            if percent >= 100:
                                print(f"    Loader reached 100%!")
                                page.wait_for_timeout(2000)  # Wait a bit more after 100%
                                break
                    except Exception:
                        pass
                    page.wait_for_timeout(500)
                else:
                    if not failure_detected:
                        print(f"    Loader did not reach 100% within 120s, continuing...")

                # Raise error if failure was detected
                if failure_detected:
                    raise ValueError(f"Operation failed during loading: {failure_message}")
            else:
                # No percentage loader — check instruction for loader/spinner keywords
                instruction_lower = instruction.lower()
                _loader_keywords = ["loader", "loading", "spinner", "processing", "disappear", "wait until"]
                _wants_loader_gone = any(kw in instruction_lower for kw in _loader_keywords)

                # Selectors that cover common loader/spinner patterns (Material UI, Tailwind, custom)
                _SPINNER_SELECTORS = [
                    "[class*='loader']",
                    "[class*='loading']",
                    "[class*='spinner']",
                    "[class*='progress']",
                    "[role='progressbar']",
                    "[aria-busy='true']",
                    "[class*='circular']",
                    "[class*='Circular']",
                    "[class*='skeleton']",
                    "[class*='Skeleton']",
                    "[class*='overlay']",
                    "[class*='Loader']",
                    "[class*='Loading']",
                    "[class*='Spinner']",
                ]

                # Detect any currently-visible loader on the page
                active_loaders = []
                if _wants_loader_gone:
                    for _lsel in _SPINNER_SELECTORS:
                        try:
                            _locs = page.locator(_lsel).all()
                            for _loc in _locs:
                                try:
                                    if _loc.is_visible():
                                        active_loaders.append((_lsel, _loc))
                                        break  # one instance per selector is enough
                                except Exception:
                                    continue
                        except Exception:
                            continue

                if active_loaders:
                    # Wait up to 120 s for every detected loader to disappear
                    LOADER_MAX_WAIT_S = 120
                    print(f"    Loader/spinner detected ({len(active_loaders)} element(s)), waiting up to {LOADER_MAX_WAIT_S}s for them to disappear...")
                    for _elapsed in range(LOADER_MAX_WAIT_S * 2):  # poll every 500 ms
                        ctrl = _check_step_control(signal_file)
                        if ctrl in ("next", "skip"):
                            print(f"    Step control '{ctrl}' received — skipping loader wait")
                            raise _StepControlSignal(ctrl)
                        all_gone = True
                        for (_lsel, _) in active_loaders:
                            try:
                                if page.locator(_lsel).first.is_visible():
                                    all_gone = False
                                    break
                            except Exception:
                                pass
                        if all_gone:
                            print(f"    All loaders gone after {_elapsed * 0.5:.1f}s")
                            break
                        if _elapsed % 20 == 0:
                            print(f"    Still waiting for loader... ({_elapsed * 0.5:.0f}s elapsed)")
                        page.wait_for_timeout(500)
                    else:
                        print(f"    Loader did not disappear within {LOADER_MAX_WAIT_S}s, continuing...")

                    # Extra small buffer so the UI can finish its transition
                    page.wait_for_timeout(1000)

                    # If instruction also expects a "continue" button to become visible,
                    # wait up to 30 more seconds for it to appear
                    _wants_continue = any(w in instruction_lower for w in ["continue", "continue button"])
                    if _wants_continue:
                        print(f"    Waiting for 'Continue' button to become visible (max 30s)...")
                        _continue_selectors = [
                            "button:has-text('Continue')",
                            "[role='button']:has-text('Continue')",
                            "text=Continue",
                        ]
                        _continue_visible = False
                        for _ci in range(60):  # 60 * 500ms = 30 s
                            ctrl = _check_step_control(signal_file)
                            if ctrl in ("next", "skip"):
                                raise _StepControlSignal(ctrl)
                            for _csel in _continue_selectors:
                                try:
                                    if page.locator(_csel).first.is_visible(timeout=300):
                                        print(f"    'Continue' button is now visible after {_ci * 0.5:.1f}s")
                                        _continue_visible = True
                                        break
                                except Exception:
                                    continue
                            if _continue_visible:
                                break
                            page.wait_for_timeout(500)
                        if not _continue_visible:
                            print(f"    'Continue' button did not appear within 30s, proceeding...")
                else:
                    # No visible loader — fall back to selector-based hidden wait or fixed timeout
                    selector = _get_best_selector_sync(page, selector_hints, step_test_data)
                    if selector:
                        locator = _create_locator_sync(page, selector)
                        locator.wait_for(state="hidden", timeout=wait_timeout)
                    else:
                        print(f"    Waiting {wait_timeout}ms...")
                        page.wait_for_timeout(wait_timeout)
        except _StepControlSignal:
            raise  # Let Next/Skip propagate to retry loop
        except Exception as e:
            print(f"    Wait error: {e}, using fallback wait...")
            page.wait_for_timeout(wait_timeout)

    elif action_type == "select":
        # Get the value to select - check common keys
        value = ""
        for key in ["value", "option", "project", "item", "selection", "name"]:
            if key in step_test_data:
                value = step_test_data[key]
                break
        # If no common key found, use first string value
        if not value and step_test_data:
            for key, val in step_test_data.items():
                if isinstance(val, str) and val:
                    value = val
                    print(f"    Using test_data['{key}'] as select value")
                    break

        # If no value in test_data, try to extract from instruction
        if not value:
            # Try to extract value from instruction (e.g., "Select Project 'SAM-CLi-01-PRO-01'" or "Select Project: MyProject")
            instruction_lower = instruction.lower() if instruction else ""

            # Pattern 1: Quoted value in instruction
            quoted_match = re.search(r'["\']([^"\']+)["\']', instruction)
            if quoted_match:
                value = quoted_match.group(1)
                print(f"    Extracted select value from quoted text in instruction: '{value}'")

            # Pattern 2: Value after colon (e.g., "Select Project: MyProject")
            if not value:
                colon_match = re.search(r':\s*(.+?)(?:\s*$|\s*,)', instruction)
                if colon_match:
                    value = colon_match.group(1).strip()
                    print(f"    Extracted select value after colon: '{value}'")

        if not value:
            raise ValueError("Missing value for select action. Add test_data with the value to select, or include the value in the instruction (e.g., Select Project 'MyProject')")

        # Try native select first
        selector = _get_best_selector_sync(page, selector_hints, step_test_data, action_type="select")
        native_select_success = False

        if selector:
            try:
                locator = _create_locator_sync(page, selector)
                # Check if it's actually a native select element
                tag_name = locator.first.evaluate("el => el.tagName.toLowerCase()")
                if tag_name == "select":
                    locator.select_option(value, timeout=timeout)
                    selector_used = selector
                    native_select_success = True
                    print(f"    Native select: selected '{value}'")
            except Exception as e:
                print(f"    Native select failed: {e}")

        # Fallback: Handle custom dropdown (div/button based)
        if not native_select_success:
            print(f"    Trying custom dropdown fallback for value: '{value}'")
            element_name = selector_hints.get("element_name", "") or ""
            suggested_selectors = selector_hints.get("suggested_selectors", [])

            # Step 1: Find and click the dropdown trigger
            dropdown_clicked = False

            # Snapshot BEFORE opening — used by _wait_for_dropdown_options to detect new items
            _option_baseline = _snapshot_option_count(page)

            # PRIORITY 1: Try suggested_selectors from step definition first
            for suggested_sel in suggested_selectors:
                if not suggested_sel or dropdown_clicked:
                    continue
                try:
                    trigger = page.locator(suggested_sel).first
                    if trigger.is_visible(timeout=2000):
                        trigger.click(timeout=5000)
                        dropdown_clicked = True
                        print(f"    Clicked dropdown using suggested selector: {suggested_sel}")
                        _wait_for_dropdown_options(page, baseline=_option_baseline)
                        break
                except Exception as e:
                    print(f"    Suggested selector failed: {suggested_sel} - {str(e)[:50]}")
                    continue

            # PRIORITY 2: Try label-based detection (for dropdowns with associated labels)
            # Guard: skip if element_name looks like the value being selected (LLM mis-generation)
            # e.g. element_name="Project_Test_001" when it should be "Project"
            _element_name_is_value = (
                element_name and value and
                (element_name.lower() == value.lower() or
                 element_name.lower().replace(" ", "_") == value.lower().replace(" ", "_"))
            )
            if not dropdown_clicked and element_name and not _element_name_is_value:
                # Extract meaningful keywords from element_name (e.g., "Select Project" -> "Project")
                label_keywords = [w for w in element_name.split() if w.lower() not in _DROPDOWN_LABEL_STOPWORDS]
                label_text = ' '.join(label_keywords) if label_keywords else element_name

                print(f"    Looking for dropdown by label: '{label_text}'")

                # Try label-based patterns (label is sibling or nearby to dropdown)
                label_patterns = [
                    # Label followed by div containing button (common pattern)
                    f'label:has-text("{label_text}") + div button:has(svg)',
                    f'label:has-text("{label_text}") + div button',
                    f'label:has-text("{label_text}") ~ div button:has(svg)',
                    # Label inside container with button
                    f'div:has(> label:has-text("{label_text}")) button:has(svg)',
                    f'div:has(label:has-text("{label_text}")) div.relative button',
                    # Exact label text match
                    f'label:text-is("{element_name}") + div button',
                    f'label:text-is("{element_name}") ~ div button',
                ]

                for pattern in label_patterns:
                    if dropdown_clicked:
                        break
                    try:
                        trigger = page.locator(pattern).first
                        if trigger.is_visible(timeout=1500):
                            trigger.click(timeout=5000)
                            dropdown_clicked = True
                            print(f"    Clicked dropdown by label pattern: {pattern}")
                            _wait_for_dropdown_options(page, baseline=_option_baseline)
                            break
                    except Exception:
                        continue

            # PRIORITY 3: Generic trigger patterns — only if PRIORITY 1 & 2 both failed
            if not dropdown_clicked:
                dropdown_triggers = [
                    # By element name in button/div text
                    f'button:has-text("{element_name}")' if element_name else None,
                    f'div[class*="select"]:has-text("{element_name}")' if element_name else None,
                    # Common dropdown patterns
                    'button:has(svg[class*="rotate"])',
                    'button[class*="select"]',
                    'div[class*="select"] > button',
                    '[role="combobox"]',
                    '[role="listbox"]',
                    'button:has([class*="chevron"])',
                    'button:has([class*="arrow"])',
                    'button.rounded-full:has(svg)',
                    'button[class*="rounded"]:has(svg[viewBox])',
                    'div.relative > button:has(svg)',
                    'button[class*="justify-between"]:has(svg)',
                    'button:has(svg[class*="transition"])',
                    'button[class*="cursor-pointer"]:has(svg)',
                ]

                for trigger_selector in dropdown_triggers:
                    if not trigger_selector:
                        continue
                    try:
                        trigger = page.locator(trigger_selector).first
                        if trigger.is_visible(timeout=2000):
                            trigger.click(timeout=5000)
                            dropdown_clicked = True
                            print(f"    Clicked dropdown trigger: {trigger_selector}")
                            _wait_for_dropdown_options(page, baseline=_option_baseline)
                            break
                    except Exception:
                        continue

            # DEBUG: log what's in the popup after opening (runs after any successful trigger click)
            if dropdown_clicked:
                try:
                    visible_opts = _get_dropdown_popup_options(page)
                    print(f"    DEBUG: Found {len(visible_opts)} potential options after dropdown open")
                    for i, opt in enumerate(visible_opts[:10]):
                        try:
                            opt_text = (opt.text_content() or "").strip()[:50]
                            if opt_text:
                                print(f"      Option[{i}]: '{opt_text}'")
                        except:
                            pass
                except Exception as dbg_e:
                    print(f"    DEBUG: Could not enumerate options: {dbg_e}")

            # If no trigger found by patterns, try context-based detection
            if not dropdown_clicked:
                try:
                    # SMART DETECTION: Find dropdown by nearby label/text containing element_name keywords
                    # Extract keywords from element_name (e.g., "Project dropdown" -> "project")
                    keywords = [w.lower() for w in element_name.split() if w.lower() not in _DROPDOWN_LABEL_STOPWORDS]

                    if keywords:
                        print(f"    Searching for dropdown with context keywords: {keywords}")

                        # Try to find dropdown by label association
                        for keyword in keywords:
                            if dropdown_clicked:
                                break

                            # Method 1: Look for label + sibling/nearby dropdown
                            label_dropdown_patterns = [
                                f'label:has-text("{keyword}") + div button:has(svg)',
                                f'label:has-text("{keyword}") ~ div button:has(svg)',
                                f'div:has(label:has-text("{keyword}")) button:has(svg)',
                                f'div:has(> span:has-text("{keyword}")) button:has(svg)',
                                f'div:has-text("{keyword}") >> button:has(svg)',
                            ]

                            for pattern in label_dropdown_patterns:
                                try:
                                    trigger = page.locator(pattern).first
                                    if trigger.is_visible(timeout=1000):
                                        trigger.click(timeout=5000)
                                        dropdown_clicked = True
                                        print(f"    Clicked dropdown by label context: {pattern}")
                                        _wait_for_dropdown_options(page, baseline=_option_baseline)
                                        break
                                except Exception:
                                    continue
                except Exception as e:
                    print(f"    Context-based detection failed: {e}")

            # Final fallback: Try clicking any visible button with SVG (last resort)
            if not dropdown_clicked:
                try:
                    # Look for buttons with SVG icons (common dropdown pattern)
                    buttons_with_svg = page.locator('button:has(svg)').all()
                    for btn in buttons_with_svg:
                        try:
                            if btn.is_visible():
                                btn_text = btn.text_content() or ""
                                # Skip if it's clearly not a dropdown (like submit buttons)
                                if any(word in btn_text.lower() for word in ['submit', 'save', 'cancel', 'delete', 'close', 'add', 'create', 'remove']):
                                    continue
                                btn.click(timeout=5000)
                                dropdown_clicked = True
                                print(f"    Clicked button with SVG (fallback): '{btn_text[:30]}'")
                                _wait_for_dropdown_options(page, baseline=_option_baseline)
                                break
                        except Exception:
                            continue
                except Exception as e:
                    print(f"    Could not find dropdown trigger: {e}")

            # Step 2: Find and click the option with matching text
            # Check if dropdown options are already visible (dropdown might be pre-opened)
            if not dropdown_clicked:
                print(f"    Checking if dropdown is already open...")
                # Look for visible option elements that match our value
                pre_open_selectors = [
                    f'div.absolute div:has-text("{value}")',  # Absolute positioned dropdown
                    f'div[class*="dropdown"] div:has-text("{value}")',
                    f'div.z-50 div:has-text("{value}")',  # High z-index dropdown
                    f'div[class*="menu"] div:has-text("{value}")',
                    f'ul[class*="dropdown"] li:has-text("{value}")',
                    f'div.overflow-y-auto div:has-text("{value}")',  # Scrollable dropdown
                ]
                for pre_sel in pre_open_selectors:
                    try:
                        opt = page.locator(pre_sel).first
                        if opt.is_visible(timeout=1000):
                            print(f"    Dropdown already open! Found option with: {pre_sel}")
                            dropdown_clicked = True  # Mark as "clicked" so we proceed to select
                            break
                    except Exception:
                        continue

            if dropdown_clicked:
                option_clicked = False

                def _try_click_option(locator) -> bool:
                    """Scroll into view and click; return True on success."""
                    try:
                        if locator.is_visible(timeout=2000):
                            try:
                                locator.scroll_into_view_if_needed(timeout=1000)
                            except Exception:
                                pass
                            locator.click(timeout=5000)
                            return True
                    except Exception:
                        pass
                    return False

                # PRIORITY 1: Search inside the popup container (scoped, most reliable)
                # Covers any dropdown whose options are inside an overlay/absolute element
                popup = _get_dropdown_popup_container(page)
                if popup is not None:
                    # Exact text match inside popup
                    for tag in ("div", "li", "span", "[role='option']"):
                        try:
                            opt = popup.locator(f"{tag}:text-is('{value}')").first
                            if _try_click_option(opt):
                                option_clicked = True
                                selector_used = f"popup::{tag}:text-is('{value}')"
                                print(f"    Selected option '{value}' inside popup container")
                                break
                        except Exception:
                            continue

                    # Partial text match inside popup (if exact failed)
                    if not option_clicked:
                        try:
                            opt = popup.get_by_text(value, exact=True).first
                            if _try_click_option(opt):
                                option_clicked = True
                                selector_used = f"popup::get_by_text(exact)"
                                print(f"    Selected option '{value}' in popup by exact text")
                        except Exception:
                            pass

                # PRIORITY 2: Page-wide selectors (fallback for non-overlay dropdowns)
                if not option_clicked:
                    option_selectors = [
                        f'[role="option"]:has-text("{value}")',
                        f'div[class*="option"]:has-text("{value}")',
                        f'li:text-is("{value}")',
                        f'li:has-text("{value}")',
                        f'div:text-is("{value}")',
                        f'span:text-is("{value}")',
                        f'div.hover\\:bg-green-50:has-text("{value}")',
                        f'div.overflow-y-auto div:text-is("{value}")',
                        f'div.absolute div:text-is("{value}")',
                        f'div.fixed div:text-is("{value}")',
                        f'ul[role="listbox"] >> text="{value}"',
                    ]
                    for opt_selector in option_selectors:
                        try:
                            opt = page.locator(opt_selector).first
                            if _try_click_option(opt):
                                option_clicked = True
                                selector_used = f"custom_dropdown::{opt_selector}"
                                print(f"    Selected option: '{value}' using {opt_selector}")
                                break
                        except Exception:
                            continue

                # PRIORITY 3: get_by_text on full page
                if not option_clicked:
                    try:
                        option = page.get_by_text(value, exact=True).first
                        if _try_click_option(option):
                            option_clicked = True
                            selector_used = f"custom_dropdown::text={value}"
                            print(f"    Selected option by text: '{value}'")
                    except Exception as e:
                        print(f"    Could not find option '{value}' by exact text: {e}")

                if not option_clicked:
                    try:
                        option = page.get_by_text(value, exact=False).first
                        if _try_click_option(option):
                            option_clicked = True
                            selector_used = f"custom_dropdown::partial_text={value}"
                            print(f"    Selected option by partial text: '{value}'")
                    except Exception as e:
                        print(f"    Could not find option '{value}' by partial text: {e}")

                # Final fallback: Use JavaScript to find and click by text content
                if not option_clicked:
                    try:
                        js_value = value.replace('"', '\\"')  # Escape quotes for JS
                        clicked = page.evaluate(f'''
                            () => {{
                                const selectors = '[role="option"], div[class*="option"], li, .cursor-pointer, div.hover\\\\:bg-green-50';
                                const options = document.querySelectorAll(selectors);
                                for (const opt of options) {{
                                    const text = (opt.textContent || '').trim();
                                    if (text.includes("{js_value}")) {{
                                        opt.scrollIntoView({{ block: 'center' }});
                                        opt.click();
                                        return true;
                                    }}
                                }}
                                return false;
                            }}
                        ''')
                        if clicked:
                            option_clicked = True
                            selector_used = f"custom_dropdown::js_click({value})"
                            print(f"    Selected option via JavaScript: '{value}'")
                    except Exception as e:
                        print(f"    JavaScript click fallback failed: {e}")

                if not option_clicked:
                    raise ValueError(f"Could not find option '{value}' in dropdown")
            else:
                raise ValueError(f"Could not find dropdown trigger for '{element_name}'")

    elif action_type == "upload":
        selector = _get_best_selector_sync(page, selector_hints, step_test_data)
        file_path = step_test_data.get("file_path", "")
        if selector and file_path:
            locator = _create_locator_sync(page, selector)
            locator.set_input_files(file_path, timeout=timeout)
            selector_used = selector
        else:
            raise ValueError("Missing selector or file_path for upload action")

    elif action_type == "capture":
        source = step_test_data.get("source", "element")
        capture_key = step_test_data.get("capture_key", "captured_value")
        captured = None

        if source == "column":
            col_name = step_test_data.get("column_name", "")
            if col_name:
                captured = _read_cell_value_from_column(page, col_name)
                print(f"      Captured from column '{col_name}': {captured}")
        elif source == "url":
            captured = page.url
            print(f"      Captured URL: {captured}")
        else:
            selector = _get_best_selector_sync(page, selector_hints, step_test_data)
            if selector:
                locator = _create_locator_sync(page, selector)
                captured = locator.text_content(timeout=timeout)
                print(f"      Captured from element: {captured}")
            else:
                captured = page.url
                print(f"      No selector found — captured URL: {captured}")

        if captured and run_context is not None:
            captured = str(captured).strip()
            run_context["captured_value"] = captured
            run_context[f"captured_{capture_key}"] = captured
            run_context["last_fill_value"] = captured
            print(f"      Stored as run_context['{capture_key}'] = '{captured}'")

    elif action_type == "date_picker":
        _execute_date_picker_sync(page, selector_hints, step_test_data, timeout)

    elif action_type == "screenshot":
        filename = step_test_data.get("filename", f"screenshot_{datetime.now().strftime('%H%M%S')}.png")
        page.screenshot(path=filename)
        print(f"      Screenshot saved: {filename}")

    elif action_type == "assert_all_rows":
        _execute_assert_all_rows_sync(page, step_test_data, timeout, run_context=run_context)

    else:
        print(f"      Unknown action type: {action_type}, skipping...")

    return selector_used


def _read_cell_value_from_column(page, column_name: str) -> Optional[str]:
    """
    Read the first non-empty data cell from a named table column.
    Reuses the same table/header discovery logic as _execute_assert_all_rows_sync.
    Returns the cell text, or None if the column/table cannot be found.
    """
    TABLE_SELECTORS = [
        "table",
        "[role='grid']",
        "[role='table']",
        ".table",
        "[class*='table']",
        "[class*='Table']",
        "[class*='grid']",
    ]

    col_lower = column_name.lower()

    for tsel in TABLE_SELECTORS:
        tables = page.locator(tsel)
        if tables.count() == 0:
            continue

        for t_idx in range(tables.count()):
            tbl = tables.nth(t_idx)

            headers = tbl.locator("th")
            if headers.count() == 0:
                first_row_cells = tbl.locator("tr").first.locator("td")
                if first_row_cells.count() > 0:
                    headers = first_row_cells

            h_count = headers.count()
            if h_count == 0:
                continue

            texts = [(headers.nth(i).inner_text() or "").strip() for i in range(h_count)]

            matched_idx = None
            for i, txt in enumerate(texts):
                if txt.lower() == col_lower or col_lower in txt.lower() or txt.lower() in col_lower:
                    matched_idx = i
                    break

            if matched_idx is None:
                continue

            # Found the column — read first non-empty data cell
            tbody_rows = tbl.locator("tbody tr")
            row_count = tbody_rows.count()
            data_row_start = 0
            if row_count == 0:
                all_rows = tbl.locator("tr")
                tbody_rows = all_rows
                row_count = tbody_rows.count()
                data_row_start = 1  # skip header

            for i in range(data_row_start, tbody_rows.count()):
                row = tbody_rows.nth(i)
                cells = row.locator("td, th")
                cell_count = cells.count()
                if cell_count == 0:
                    continue
                # Skip colspan placeholder rows
                if cell_count == 1:
                    try:
                        colspan_val = cells.nth(0).get_attribute("colspan")
                        if colspan_val and int(colspan_val) > 1:
                            continue
                    except Exception:
                        pass
                if matched_idx >= cell_count:
                    continue
                cell_text = (cells.nth(matched_idx).inner_text() or "").strip()
                if cell_text:
                    print(f"    [read_cell] Column '{column_name}' → '{cell_text}' (table {tsel}, row {i})")
                    return cell_text

    print(f"    [read_cell] Could not find column '{column_name}' in any table on {page.url}")
    return None


def _execute_date_picker_sync(page, selector_hints: Dict, step_test_data: Dict, timeout: int) -> None:
    """
    Open a date picker widget, navigate to the target month/year, and click the target day.
    Falls back to direct fill() if calendar UI is not detected.
    """
    import re as _re_dp
    from datetime import datetime as _dt

    # ── Step 1: Parse target date ─────────────────────────────────────────────
    date_str = step_test_data.get("date", "")
    target_day = target_month = target_year = None

    if date_str:
        for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                parsed = _dt.strptime(date_str, fmt)
                target_day, target_month, target_year = parsed.day, parsed.month, parsed.year
                break
            except ValueError:
                pass

    if target_day is None:
        # Fallback to explicit fields
        try:
            target_day   = int(step_test_data.get("day", 0))
            target_month = int(step_test_data.get("month", 0))
            target_year  = int(step_test_data.get("year", 0))
        except (ValueError, TypeError):
            pass

    if not (target_day and target_month and target_year):
        print(f"    [date_picker] Could not parse target date from test_data: {step_test_data}")
        return

    print(f"    [date_picker] Target date: {target_year}-{target_month:02d}-{target_day:02d}")

    # ── Step 2: Open the date picker ─────────────────────────────────────────
    selector = _get_best_selector_sync(page, selector_hints, step_test_data, action_type="click")
    if selector:
        try:
            locator = _create_locator_sync(page, selector)
            locator.click(timeout=timeout)
            print(f"    [date_picker] Clicked trigger: {selector}")
        except Exception as e:
            print(f"    [date_picker] Trigger click failed: {e}")

    # Wait for calendar to appear
    calendar_selectors = [
        "[role='dialog']", "[class*='calendar']", "[class*='datepicker']",
        "[class*='date-picker']", "[class*='react-datepicker']", ".flatpickr-calendar",
        "[class*='picker']", "[class*='DayPicker']",
    ]
    calendar = None
    for csel in calendar_selectors:
        try:
            loc = page.locator(csel)
            loc.first.wait_for(state="visible", timeout=3000)
            if loc.count() > 0:
                calendar = loc.first
                print(f"    [date_picker] Calendar detected: {csel}")
                break
        except Exception:
            pass

    if calendar is None:
        print(f"    [date_picker] No calendar widget detected — falling back to fill()")
        if selector and date_str:
            try:
                locator = _create_locator_sync(page, selector)
                locator.fill(date_str, timeout=timeout)
                print(f"    [date_picker] Fallback fill: '{date_str}'")
            except Exception as e:
                print(f"    [date_picker] Fallback fill failed: {e}")
        return

    # ── Step 3: Navigate to correct month/year ────────────────────────────────
    MONTH_NAMES = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    header_selectors = [
        ".react-datepicker__current-month",
        "[class*='month-header']",
        "[class*='calendar-header']",
        "[class*='datepicker-header']",
        "[class*='CurrentMonth']",
        "[class*='month'][class*='year']",
    ]

    prev_selectors = [
        "[aria-label*='previous' i]", "[aria-label*='prev' i]",
        ".react-datepicker__navigation--previous",
        "[class*='prev-month']", "[class*='left-arrow']",
        "button[class*='prev']",
    ]
    next_selectors = [
        "[aria-label*='next' i]",
        ".react-datepicker__navigation--next",
        "[class*='next-month']", "[class*='right-arrow']",
        "button[class*='next']",
    ]

    def _get_displayed_month_year():
        for hsel in header_selectors:
            try:
                header_loc = page.locator(hsel)
                if header_loc.count() > 0:
                    text = (header_loc.first.inner_text() or "").strip()
                    if text:
                        # Try "Month YYYY" or "YYYY-MM"
                        m = _re_dp.search(r'(\w+)\s+(\d{4})', text)
                        if m:
                            mon_str = m.group(1).lower()
                            yr = int(m.group(2))
                            mon = MONTH_NAMES.get(mon_str)
                            if mon:
                                return mon, yr
                        # Try "MM/YYYY"
                        m = _re_dp.search(r'(\d{1,2})[/\-](\d{4})', text)
                        if m:
                            return int(m.group(1)), int(m.group(2))
            except Exception:
                pass
        return None, None

    max_nav = 24
    nav_count = 0
    while nav_count < max_nav:
        cur_month, cur_year = _get_displayed_month_year()
        if cur_month is None:
            print(f"    [date_picker] Could not read calendar header — skipping navigation")
            break

        if cur_year == target_year and cur_month == target_month:
            print(f"    [date_picker] Correct month/year displayed")
            break

        # Determine direction
        cur_total  = cur_year * 12 + cur_month
        tgt_total  = target_year * 12 + target_month
        go_next = tgt_total > cur_total

        nav_sels = next_selectors if go_next else prev_selectors
        clicked = False
        for nsel in nav_sels:
            try:
                nloc = page.locator(nsel)
                if nloc.count() > 0:
                    nloc.first.click(timeout=3000)
                    page.wait_for_timeout(300)
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            print(f"    [date_picker] Could not click navigation arrow — aborting")
            break
        nav_count += 1

    # ── Step 4: Click the target day ─────────────────────────────────────────
    import calendar as _cal
    month_name = _cal.month_name[target_month]  # e.g. "March"
    full_date_str = f"{month_name} {target_day}, {target_year}"
    dd = f"{target_day:02d}"

    day_selectors = [
        f"[aria-label*='{full_date_str}']",
        f".react-datepicker__day--0{dd}:not([class*='outside']):not([class*='disabled'])",
        f"td[data-day='{target_day}']",
        f"[class*='day']:not([class*='outside']):not([class*='disabled'])",
    ]

    clicked_day = False
    for dsel in day_selectors:
        try:
            dloc = page.locator(dsel)
            count = dloc.count()
            if count > 0:
                # Try to find exact day text match to avoid off-month days
                for j in range(count):
                    cell = dloc.nth(j)
                    cell_text = (cell.inner_text() or "").strip()
                    if cell_text == str(target_day):
                        cell.click(timeout=3000)
                        print(f"    [date_picker] Clicked day {target_day} via selector: {dsel}")
                        clicked_day = True
                        break
                if clicked_day:
                    break
        except Exception:
            pass

    if not clicked_day:
        # Last resort: get_by_role gridcell
        try:
            page.get_by_role("gridcell", name=str(target_day)).first.click(timeout=3000)
            print(f"    [date_picker] Clicked day {target_day} via get_by_role gridcell")
            clicked_day = True
        except Exception:
            pass

    if not clicked_day:
        print(f"    [date_picker] WARNING: Could not click day {target_day} — falling back to fill")
        if selector and date_str:
            try:
                locator = _create_locator_sync(page, selector)
                locator.fill(date_str, timeout=timeout)
            except Exception as e:
                print(f"    [date_picker] Fallback fill also failed: {e}")
    else:
        # Wait for picker to close
        page.wait_for_timeout(500)
        print(f"    [date_picker] Date {date_str or full_date_str} selected successfully")


def _execute_assert_all_rows_sync(page, step_test_data: Dict, timeout: int, run_context: Dict = None) -> None:
    """
    Assert a condition on every data row in a table.

    step_test_data keys:
      column_name  (str)  – header text of the column to inspect.
                            Accepts a positional int string ("0", "1") as fallback.
      validation   (str)  – one of: not_empty | not_null | contains | equals | matches_pattern
      expected_value (str)– required for 'contains', 'equals', 'matches_pattern'
      min_rows     (int)  – minimum visible rows required (default 1). 0 = allow empty table.
    """
    import re as _re

    column_name    = str(step_test_data.get("column_name") or "").strip()
    validation     = str(step_test_data.get("validation") or "not_empty").strip().lower()
    expected_value = str(step_test_data.get("expected_value") or "").strip()
    min_rows       = int(step_test_data.get("min_rows", 1))

    # Aliases
    if validation == "not_null":
        validation = "not_empty"
    if validation == "no_duplicates":
        validation = "unique"

    # If expected_value is not set (or equals the column name — a common parser mistake),
    # and the previous step was a fill-from-table on this same column,
    # use the actual value that was filled so the assert checks real search results.
    if run_context:
        last_fill_value = run_context.get("last_fill_value")
        if last_fill_value:
            _expected_is_empty = not expected_value
            _expected_is_col_name = (
                column_name and expected_value and expected_value.lower() == column_name.lower()
            )
            if _expected_is_empty or _expected_is_col_name:
                print(f"    [assert_all_rows] expected='{last_fill_value}' (resolved from last fill value; "
                      f"was: '{expected_value or '(empty)'}')")
                expected_value = last_fill_value
                if validation == "not_empty":
                    validation = "contains"

    # Empty column_name means this is a pure "capture rows" setup step with no
    # column to validate yet (the actual column assertion is a subsequent step).
    # Treat it as a pass — just verify the table exists with at least min_rows rows.
    if not column_name:
        print(f"    [assert_all_rows] No column_name — verifying table has ≥{min_rows} row(s)...")
        TABLE_QUICK = ["table", "[role='grid']", "[role='table']", "[class*='table']"]
        found_rows = 0
        for tsel in TABLE_QUICK:
            tbody = page.locator(f"{tsel} tbody tr")
            n = tbody.count()
            if n > 0:
                found_rows = n
                break
            alltr = page.locator(f"{tsel} tr")
            n = alltr.count()
            if n > 1:  # >1 means at least one data row beyond header
                found_rows = n - 1
                break
        if found_rows < min_rows:
            raise AssertionError(
                f"[assert_all_rows] Table has {found_rows} row(s) but min_rows={min_rows} (URL: {page.url})"
            )
        print(f"    [assert_all_rows] Table found with {found_rows} row(s). PASS (no column to validate)")
        return

    print(f"    [assert_all_rows] column='{column_name}', validation='{validation}', "
          f"expected='{expected_value}', min_rows={min_rows}")

    # ── STEP 1: Locate the table ──────────────────────────────────────────────
    # Try multiple table patterns; pick the one that contains our target column header.
    TABLE_SELECTORS = [
        "table",
        "[role='grid']",
        "[role='table']",
        ".table",
        "[class*='table']",
        "[class*='Table']",
        "[class*='grid']",
    ]

    # Find all rows including header row candidates
    found_table = None
    col_index   = None   # 0-based index of the target column
    header_texts: List[str] = []

    for tsel in TABLE_SELECTORS:
        tables = page.locator(tsel)
        count = tables.count()
        if count == 0:
            continue

        for t_idx in range(count):
            tbl = tables.nth(t_idx)

            # Try to find headers: th elements, or first tr's td elements
            headers = tbl.locator("th")
            if headers.count() == 0:
                # No <th>? Try first row's <td> as headers
                first_row_cells = tbl.locator("tr").first.locator("td")
                if first_row_cells.count() > 0:
                    headers = first_row_cells

            h_count = headers.count()
            if h_count == 0:
                continue

            # Collect header texts
            texts = []
            for i in range(h_count):
                txt = (headers.nth(i).inner_text() or "").strip()
                texts.append(txt)

            # Try to match column_name to one of the headers (case-insensitive)
            matched_idx = None
            col_lower = column_name.lower()
            for i, txt in enumerate(texts):
                if txt.lower() == col_lower or col_lower in txt.lower() or txt.lower() in col_lower:
                    matched_idx = i
                    break

            # Positional fallback: if column_name is a digit string
            if matched_idx is None and column_name.isdigit():
                pos = int(column_name)
                if 0 <= pos < h_count:
                    matched_idx = pos

            if matched_idx is not None:
                found_table  = tbl
                col_index    = matched_idx
                header_texts = texts
                print(f"    [assert_all_rows] Found column '{column_name}' at index {col_index} "
                      f"in table selector '{tsel}' (headers: {texts})")
                break

        if found_table is not None:
            break

    if found_table is None:
        # Last resort: find any table-like structure and try by position
        fallback = page.locator("table").first
        if fallback.count() > 0 and column_name.isdigit():
            found_table = fallback
            col_index   = int(column_name)
            print(f"    [assert_all_rows] Fallback: using first table, column index {col_index}")
        else:
            all_headers = header_texts or []
            raise AssertionError(
                f"[assert_all_rows] Could not find column '{column_name}' in any table on page {page.url}. "
                f"Headers found: {all_headers or 'none'}"
            )

    # ── STEP 2: Collect data rows ─────────────────────────────────────────────
    # Data rows = <tbody> rows, or all <tr>s minus the header row(s).
    tbody_rows = found_table.locator("tbody tr")
    row_count  = tbody_rows.count()

    if row_count == 0:
        # No <tbody>? Fall back to all <tr> minus the first (header)
        all_rows  = found_table.locator("tr")
        row_count = all_rows.count() - 1   # exclude header row
        tbody_rows = all_rows

        # We'll slice manually: start from row index 1
        data_row_start = 1
    else:
        data_row_start = 0

    print(f"    [assert_all_rows] Found {row_count} data row(s)")

    # ── STEP 3: Enforce min_rows ──────────────────────────────────────────────
    if row_count < min_rows:
        raise AssertionError(
            f"[assert_all_rows] Table has {row_count} row(s) but min_rows={min_rows}. "
            f"Page: {page.url}"
        )

    if row_count == 0:
        print(f"    [assert_all_rows] 0 rows — min_rows=0, nothing to validate. PASS")
        return

    # ── STEP 4: Validate each row ────────────────────────────────────────────
    failures: List[str] = []
    total_actual_rows = tbody_rows.count()
    # For "unique" validation: track seen values across all rows
    seen_values: Dict[str, int] = {}  # value → first row number it appeared

    for i in range(data_row_start, total_actual_rows):
        row = tbody_rows.nth(i)

        # Get the target cell by column index — include both <td> and <th> (row-scoped headers)
        cells = row.locator("td, th")
        cell_count = cells.count()

        if cell_count == 0:
            # Skip spacer/separator rows
            continue

        # Skip colspan placeholder rows (e.g. "No data", "Loading..." spanning all columns)
        if cell_count == 1:
            try:
                colspan_val = cells.nth(0).get_attribute("colspan")
                if colspan_val and int(colspan_val) > 1:
                    print(f"      Row {i - data_row_start + 1}: skipping colspan placeholder row")
                    continue
            except Exception:
                pass

        if col_index >= cell_count:
            failures.append(
                f"Row {i - data_row_start + 1}: only {cell_count} cell(s) but column index is {col_index}"
            )
            continue

        cell_text = (cells.nth(col_index).inner_text() or "").strip()
        row_label = f"Row {i - data_row_start + 1}"
        print(f"      {row_label}: cell text = '{cell_text}'")

        # Parse expected_value: if it looks like a list literal, treat it as a list
        import ast as _ast
        expected_list: list | None = None
        if isinstance(expected_value, list):
            expected_list = [str(v).strip() for v in expected_value]
        elif isinstance(expected_value, str) and expected_value.startswith("[") and expected_value.endswith("]"):
            try:
                parsed = _ast.literal_eval(expected_value)
                if isinstance(parsed, list):
                    expected_list = [str(v).strip() for v in parsed]
            except Exception:
                pass

        # Apply validation
        if validation == "not_empty":
            if not cell_text:
                failures.append(f"{row_label}: value is empty/null (column '{column_name}')")

        elif validation == "contains":
            # For a list: cell must contain at least one of the values
            if expected_list is not None:
                if not any(v.lower() in cell_text.lower() for v in expected_list):
                    failures.append(
                        f"{row_label}: '{cell_text}' does not contain any of {expected_list}"
                    )
            else:
                if expected_value.lower() not in cell_text.lower():
                    failures.append(
                        f"{row_label}: '{cell_text}' does not contain '{expected_value}'"
                    )

        elif validation == "equals":
            # For a list: cell must equal one of the allowed values
            if expected_list is not None:
                if cell_text not in expected_list:
                    failures.append(
                        f"{row_label}: '{cell_text}' is not one of allowed values {expected_list}"
                    )
            else:
                if cell_text != expected_value:
                    failures.append(
                        f"{row_label}: '{cell_text}' != '{expected_value}'"
                    )

        elif validation == "matches_pattern":
            # For a list: cell must match at least one pattern
            if expected_list is not None:
                if not any(_re.search(p, cell_text) for p in expected_list):
                    failures.append(
                        f"{row_label}: '{cell_text}' does not match any pattern in {expected_list}"
                    )
            else:
                if not _re.search(expected_value, cell_text):
                    failures.append(
                        f"{row_label}: '{cell_text}' does not match pattern '{expected_value}'"
                    )

        elif validation == "unique":
            if not cell_text:
                failures.append(f"{row_label}: value is empty/null — cannot check uniqueness")
            elif cell_text in seen_values:
                failures.append(
                    f"{row_label}: '{cell_text}' is a duplicate (first seen at Row {seen_values[cell_text]})"
                )
            else:
                seen_values[cell_text] = (i - data_row_start + 1)

        else:
            print(f"      Unknown validation '{validation}' — skipping row check")

    # ── STEP 5: Report ───────────────────────────────────────────────────────
    validated_rows = total_actual_rows - data_row_start
    passed_rows    = validated_rows - len(failures)
    print(f"    [assert_all_rows] Result: {passed_rows}/{validated_rows} rows passed")

    if failures:
        failure_detail = "\n  ".join(failures)
        raise AssertionError(
            f"[assert_all_rows] {len(failures)}/{validated_rows} row(s) failed validation "
            f"(column='{column_name}', validation='{validation}'):\n  {failure_detail}"
        )

    print(f"    [assert_all_rows] All {validated_rows} row(s) PASSED ({validation} on '{column_name}')")


def _extract_selector_from_assertion(playwright_assertion: str) -> Optional[str]:
    """Extract CSS selector from playwright assertion string like 'expect(page.locator('.ai-summary')).toBeVisible()'"""
    if not playwright_assertion:
        return None

    # Try to extract selector from page.locator('...')
    match = re.search(r"page\.locator\(['\"]([^'\"]+)['\"]\)", playwright_assertion)
    if match:
        return match.group(1)

    # Try to extract from getByRole, getByText, etc.
    match = re.search(r"getByRole\(['\"]([^'\"]+)['\"]", playwright_assertion)
    if match:
        return None  # Role selectors need special handling

    return None


def _execute_assertions_sync(
    page,
    assertions: List,
    selector_hints: Dict,
    step_test_data: Dict,
    timeout: int,
    sync_expect
):
    """Execute all assertions for a step (sync version)."""
    if not assertions:
        if step_test_data.get("url"):
            print(f"      URL: {page.url} [AUTO-PASS]")
        return

    for assertion in assertions:
        assertion_type = assertion.get("type", "")
        expected_value = assertion.get("expected_value", "")
        playwright_assertion = assertion.get("playwright_assertion", "")

        # Handle boolean expected_value (for visible/enabled assertions)
        if isinstance(expected_value, bool):
            expected_value_str = "true" if expected_value else "false"
        else:
            # Strip surrounding quotes that LLM sometimes wraps: '""Login successful""' → 'Login successful'
            raw = str(expected_value) if expected_value else ""
            expected_value_str = raw.strip().strip('"').strip("'").strip('"').strip()
            expected_value = expected_value_str  # keep in sync for all assertion branches

        print(f"      Asserting: {assertion_type} = '{expected_value_str}'")

        if assertion_type == "url" or assertion_type == "url_contains" or assertion_type == "verify_url":
            # URL assertions: wait briefly for navigation then check the actual URL
            import time as _t
            _t.sleep(1)  # Allow any post-action redirect to settle
            current_url = page.url

            # Replace placeholder hosts (e.g. example.com) with the real host from
            # the live page — same logic as the goto handler above.
            _PLACEHOLDER_HOSTS = {"example.com", "your-app.com", "localhost", "your-domain.com"}
            try:
                from urllib.parse import urlparse as _up
                _ep = _up(expected_value_str)
                if _ep.hostname in _PLACEHOLDER_HOSTS:
                    _cp = _up(current_url)
                    if _cp.scheme and _cp.netloc:
                        _real_base = f"{_cp.scheme}://{_cp.netloc}"
                        expected_value_str = _real_base + (_ep.path or "/")
                        print(f"      [url assert] Replaced placeholder → '{expected_value_str}'")
            except Exception:
                pass

            if expected_value_str:
                base_expected = expected_value_str.split('?')[0].rstrip('/')
                base_current = current_url.split('?')[0].rstrip('/')
                if base_expected in base_current or base_current.endswith(base_expected.split('/')[-1]):
                    print(f"      URL: {current_url} [PASS - base matches '{base_expected}']")
                else:
                    raise AssertionError(
                        f"URL mismatch: expected URL containing '{base_expected}' but got '{current_url}'"
                    )
            else:
                print(f"      URL: {current_url} [PASS - navigated successfully]")

        elif assertion_type == "text":
            # Check if expected_value looks like a dynamic ID pattern (e.g., INC169, ORD123, etc.)
            if re.match(r'^[A-Z]{2,5}\d+$', str(expected_value)):
                # Extract the prefix (e.g., "INC" from "INC169")
                prefix_match = re.match(r'^([A-Z]{2,5})\d+$', str(expected_value))
                if prefix_match:
                    prefix = prefix_match.group(1)
                    print(f"      Looking for dynamic ID with pattern '{prefix}XXX'...")
                    # Use Playwright's regex text matching
                    try:
                        pattern_locator = page.get_by_text(re.compile(rf"{prefix}\d+"))
                        if pattern_locator.count() > 0:
                            found_text = pattern_locator.first.text_content()
                            print(f"      Found dynamic ID: {found_text}")
                            sync_expect(pattern_locator.first).to_be_visible(timeout=timeout)
                        else:
                            raise AssertionError(f"Dynamic ID pattern '{prefix}XXX' not found on page (URL: {page.url})")
                    except AssertionError:
                        raise
                    except Exception as e:
                        raise AssertionError(f"Dynamic ID pattern search failed: {e} (URL: {page.url})")
            else:
                # Parse expected_value — LLMs may produce lists in various formats:
                # Python list repr, JSON array, plain CSV, semicolon- or newline-separated
                comma_items = _parse_multi_value_assertion(expected_value_str)
                if len(comma_items) >= 2:
                    print(f"      Multi-value assertion: checking {len(comma_items)} items individually")
                    for item in comma_items:
                        item_locator = page.get_by_text(item, exact=True)
                        if item_locator.count() == 0:
                            item_locator = page.get_by_text(item)
                        if item_locator.count() > 1:
                            item_locator = item_locator.first
                        sync_expect(item_locator).to_be_visible(timeout=timeout)
                        print(f"      [OK] '{item}' found")
                else:
                    # Use exact match to avoid strict mode violations
                    text_locator = page.get_by_text(expected_value_str, exact=True)
                    if text_locator.count() == 0:
                        text_locator = page.get_by_text(expected_value_str)
                    if text_locator.count() > 1:
                        print(f"      Multiple matches for text, using first")
                        text_locator = text_locator.first
                    sync_expect(text_locator).to_be_visible(timeout=timeout)

        elif assertion_type == "heading":
            heading_found = False
            selector = _get_best_selector_sync(page, selector_hints, step_test_data)
            if selector:
                try:
                    locator = _create_locator_sync(page, selector)
                    sync_expect(locator).to_contain_text(expected_value, timeout=timeout)
                    heading_found = True
                except Exception:
                    pass

            if not heading_found:
                # Try role-based heading
                try:
                    heading_locator = page.get_by_role("heading", name=expected_value)
                    if heading_locator.count() > 0:
                        sync_expect(heading_locator.first).to_be_visible(timeout=5000)
                        heading_found = True
                except Exception:
                    pass

            if not heading_found:
                # Try text search
                try:
                    text_locator = page.get_by_text(expected_value)
                    if text_locator.count() > 0:
                        sync_expect(text_locator.first).to_be_visible(timeout=5000)
                        heading_found = True
                        print(f"      Found '{expected_value}' as text (not heading role)")
                except Exception:
                    pass

            if not heading_found:
                raise AssertionError(f"Heading '{expected_value}' not found on page (URL: {page.url})")

        elif assertion_type == "toast":
            # Strip surrounding quotes that LLM sometimes wraps around the value
            # e.g. '""Login successful""' → 'Login successful'
            toast_text = str(expected_value).strip().strip('"').strip("'").strip('"').strip()

            # Check if this toast was already captured during the previous click's nav wait
            # (toasts disappear fast — we pre-catch them while polling for navigation)
            _toast_cache = getattr(page, '_toast_cache', {})
            # Find this assertion's step number from the enclosing context via the cache keys
            # Try every cached entry — if any matches the expected text, accept it
            _pre_caught = False
            for _cached_step, _cached_text in list(_toast_cache.items()):
                if toast_text.lower() in _cached_text.lower():
                    print(f"      Toast found (pre-captured during navigation): '{_cached_text}'")
                    _toast_cache.pop(_cached_step, None)
                    _pre_caught = True
                    break
            if _pre_caught:
                pass  # assertion passes — skip live DOM search, fall through to next assertion
            else:
                toast_selectors = [
                    "[role='alert']",
                    "[role='status']",
                    ".Toastify__toast",
                    "[class*='toast']",
                    "[class*='Toast']",
                    ".toast",
                    ".Toastify",
                    "[class*='snack']",
                    "[class*='Snack']",
                    "[class*='notification']",
                    "[class*='alert']",
                    "[class*='success']",
                    "[data-testid*='toast']",
                    "[id*='toast']",
                ]
                toast_found = False

                # Toasts appear briefly — poll for up to 5s across all selectors
                for toast_sel in toast_selectors:
                    try:
                        locator = page.locator(toast_sel).first
                        if locator.count() > 0:
                            text = (locator.inner_text() or "").strip()
                            if toast_text.lower() in text.lower():
                                toast_found = True
                                print(f"      Toast found with selector: {toast_sel} | text: '{text}'")
                                break
                            # Also try Playwright contains_text for partial match
                            sync_expect(locator).to_contain_text(toast_text, timeout=3000)
                            toast_found = True
                            print(f"      Toast found with selector: {toast_sel}")
                            break
                    except Exception:
                        continue

                if not toast_found:
                    # Try to find the text anywhere on the page
                    try:
                        sync_expect(page.get_by_text(toast_text, exact=False)).to_be_visible(timeout=3000)
                        toast_found = True
                        print(f"      Toast text found directly on page: '{toast_text}'")
                    except Exception:
                        pass

                if not toast_found:
                    raise AssertionError(f"Toast message '{toast_text}' not found on page (URL: {page.url})")

        elif assertion_type in ["element", "visible"]:
            selector = _get_best_selector_sync(page, selector_hints, step_test_data)
            element_found = False

            if selector:
                try:
                    locator = _create_locator_sync(page, selector)
                    sync_expect(locator).to_be_visible(timeout=timeout)
                    element_found = True
                except Exception as e:
                    print(f"      Selector failed: {e}")

            if not element_found and expected_value_str:
                # Try smart element resolution for the expected value
                # Priority: exact button > exact link > heading > generic text
                try:
                    # Try as button first (most common case)
                    button_locator = page.get_by_role("button", name=expected_value_str, exact=True)
                    if button_locator.count() == 1:
                        print(f"      Found as button: {expected_value_str}")
                        sync_expect(button_locator).to_be_visible(timeout=timeout)
                        element_found = True
                except Exception:
                    pass

                if not element_found:
                    try:
                        # Try as link
                        link_locator = page.get_by_role("link", name=expected_value_str, exact=True)
                        if link_locator.count() == 1:
                            print(f"      Found as link: {expected_value_str}")
                            sync_expect(link_locator).to_be_visible(timeout=timeout)
                            element_found = True
                    except Exception:
                        pass

                if not element_found:
                    try:
                        # Try as heading
                        heading_locator = page.get_by_role("heading", name=expected_value_str)
                        if heading_locator.count() > 0:
                            print(f"      Found as heading: {expected_value_str}")
                            sync_expect(heading_locator.first).to_be_visible(timeout=timeout)
                            element_found = True
                    except Exception:
                        pass

                if not element_found:
                    try:
                        # Try exact text match
                        text_locator = page.get_by_text(expected_value_str, exact=True)
                        if text_locator.count() == 1:
                            print(f"      Found as exact text: {expected_value_str}")
                            sync_expect(text_locator).to_be_visible(timeout=timeout)
                            element_found = True
                        elif text_locator.count() > 1:
                            print(f"      Multiple matches for '{expected_value_str}', using first")
                            sync_expect(text_locator.first).to_be_visible(timeout=timeout)
                            element_found = True
                    except Exception:
                        pass

            if not element_found:
                # Try to extract selector from playwright_assertion
                css_selector = _extract_selector_from_assertion(playwright_assertion)
                if css_selector:
                    print(f"      Using extracted selector: {css_selector}")
                    locator = page.locator(css_selector)
                    if locator.count() > 0:
                        sync_expect(locator.first).to_be_visible(timeout=timeout)
                        element_found = True
                    else:
                        raise AssertionError(
                            f"Element not found: selector '{css_selector}' matched 0 elements on {page.url}"
                        )
                else:
                    raise AssertionError(
                        f"Element not found: no selector could be resolved for visibility check on {page.url}"
                    )

        elif assertion_type == "enabled":
            selector = _get_best_selector_sync(page, selector_hints, step_test_data)
            if selector:
                locator = _create_locator_sync(page, selector)
                sync_expect(locator).to_be_enabled(timeout=timeout)
            else:
                # Try to extract selector from playwright_assertion
                css_selector = _extract_selector_from_assertion(playwright_assertion)
                if css_selector:
                    print(f"      Using extracted selector: {css_selector}")
                    locator = page.locator(css_selector)
                    if locator.count() > 0:
                        sync_expect(locator.first).to_be_enabled(timeout=timeout)
                    else:
                        raise AssertionError(
                            f"Element not found: selector '{css_selector}' matched 0 elements on {page.url}"
                        )
                else:
                    raise AssertionError(
                        f"Element not found: no selector could be resolved for enabled check on {page.url}"
                    )

        elif assertion_type == "status":
            # Use exact match to avoid strict mode violations
            status_locator = page.get_by_text(expected_value_str, exact=True)
            if status_locator.count() == 0:
                # Try non-exact if exact match fails
                status_locator = page.get_by_text(expected_value_str)
            if status_locator.count() > 1:
                status_locator = status_locator.first
            sync_expect(status_locator).to_be_visible(timeout=timeout)

        else:
            print(f"      Unknown assertion type: {assertion_type}")
            # Only try text match if expected_value is a non-boolean string
            if expected_value_str and not isinstance(expected_value, bool):
                print(f"      Trying text match for '{expected_value_str}'...")
                # Use exact match first, then try with .first if multiple matches
                text_locator = page.get_by_text(expected_value_str, exact=True)
                if text_locator.count() == 0:
                    text_locator = page.get_by_text(expected_value_str)
                if text_locator.count() > 1:
                    print(f"      Multiple matches, using first")
                    text_locator = text_locator.first
                sync_expect(text_locator).to_be_visible(timeout=timeout)
            else:
                print(f"      Auto-passing assertion")


async def execute_enhanced(test_suite: Dict, headless: bool = False, timeout: int = None, update_queue=None, stop_event=None, signal_file=None, initial_storage_state=None, keep_browser_open: bool = True) -> Dict[str, Any]:
    """
    Execute enhanced test suite with dynamic runtime selector mapping.
    Uses multiprocessing to run Playwright in a separate process (Windows compatible).

    Args:
        test_suite: Enhanced test suite with test_cases, common_selectors, test_data
        headless: Run browser in headless mode
        timeout: Default timeout for actions in milliseconds (uses DEFAULT_ACTION_TIMEOUT from .env if not provided)
        update_queue: Optional multiprocessing.Queue for real-time step updates (SSE)

    Returns:
        Execution results with passed/failed counts and step details
    """
    # Use environment variable if timeout not explicitly provided
    if timeout is None:
        timeout = DEFAULT_ACTION_TIMEOUT
    # Use multiprocessing to run Playwright in a separate process
    # This avoids Windows asyncio subprocess limitations
    result_queue = multiprocessing.Queue()

    process = multiprocessing.Process(
        target=_run_in_process,
        args=(test_suite, headless, timeout, result_queue, update_queue, signal_file, initial_storage_state, keep_browser_open)
    )

    process.start()

    # Wait for the process to complete (with a generous timeout)
    # Calculate based on number of steps, not just test cases
    total_steps = sum(len(tc.get("steps", [])) for tc in test_suite.get("test_cases", []))
    # Allow 60 seconds per step (for disabled buttons, navigation, loaders) + 5 minutes buffer
    max_wait = total_steps * 60 + 300
    print(f"Process timeout: {max_wait} seconds for {total_steps} steps")

    # Poll every second using asyncio.sleep so the event loop stays free to
    # forward screenshots from update_queue while the subprocess is running.
    elapsed = 0
    poll_interval = 1  # seconds
    stopped_by_user = False
    while elapsed < max_wait:
        if not process.is_alive():
            break
        if stop_event and stop_event.is_set():
            print(f"[execute_enhanced] Stop event received — terminating Playwright process")
            process.terminate()
            await asyncio.to_thread(process.join, 5)
            stopped_by_user = True
            break
        await asyncio.sleep(poll_interval)   # yields to event loop — screenshots can flow
        elapsed += poll_interval

    if stopped_by_user:
        return {
            "project": test_suite.get("project", "Unknown"),
            "base_url": test_suite.get("base_url", ""),
            "total": len(test_suite.get("test_cases", [])),
            "passed": 0,
            "failed": 0,
            "results": [],
            "executed_at": datetime.now().isoformat(),
            "stopped": True
        }

    if process.is_alive():
        process.terminate()
        await asyncio.to_thread(process.join)
        return {
            "project": test_suite.get("project", "Unknown"),
            "base_url": test_suite.get("base_url", ""),
            "total": len(test_suite.get("test_cases", [])),
            "passed": 0,
            "failed": len(test_suite.get("test_cases", [])),
            "results": [{"error": "Execution timed out"}],
            "executed_at": datetime.now().isoformat()
        }

    # Get result from queue
    try:
        result = result_queue.get_nowait()
        return result
    except Exception:
        return {
            "project": test_suite.get("project", "Unknown"),
            "base_url": test_suite.get("base_url", ""),
            "total": len(test_suite.get("test_cases", [])),
            "passed": 0,
            "failed": len(test_suite.get("test_cases", [])),
            "results": [{"error": "Failed to get results from process"}],
            "executed_at": datetime.now().isoformat()
        }
