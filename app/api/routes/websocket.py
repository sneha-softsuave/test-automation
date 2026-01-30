"""
Execution routes for real-time updates with live screenshots.
Uses Server-Sent Events (SSE) for real-time communication.
"""
from fastapi import APIRouter, Query, HTTPException, Body
from typing import Optional, Dict, Any
import asyncio
import multiprocessing
import json
import base64
import os
import tempfile
from datetime import datetime

from app.core.sse_manager import sse_manager


router = APIRouter()


def _run_with_updates(test_suite: dict, headless: bool, timeout: int, result_queue, update_queue):
    """
    Run Playwright tests in a separate process with real-time updates and screenshots.
    Sends progress updates and screenshots to update_queue.
    Always runs headless for embedded browser view - screenshots captured at step boundaries.
    """
    from playwright.sync_api import sync_playwright, expect as sync_expect
    import re

    # Always run headless for embedded view
    headless = True

    def send_update(msg_type: str, **kwargs):
        """Send an update to the main process."""
        try:
            update_queue.put_nowait({"type": msg_type, **kwargs})
        except Exception:
            pass

    def capture_screenshot(page, test_id: str, step_num: int, status: str = "progress"):
        """Capture screenshot and send as base64."""
        try:
            # Capture screenshot to bytes
            screenshot_bytes = page.screenshot(type="jpeg", quality=60, full_page=False)
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

            # Get current URL and title
            current_url = page.url
            current_title = page.title()

            print(f"📸 Capturing screenshot: step={step_num}, status={status}, url={current_url[:50]}..., size={len(screenshot_base64)}")

            send_update(
                "screenshot",
                test_id=test_id,
                step=step_num,
                status=status,
                image=screenshot_base64,
                url=current_url,
                title=current_title
            )
        except Exception as e:
            print(f"❌ Screenshot error: {e}")

    test_cases = test_suite.get("test_cases", [])
    common_selectors = test_suite.get("common_selectors", {})
    test_data = test_suite.get("test_data", {})

    # Calculate total steps
    total_steps = sum(len(tc.get("steps", [])) for tc in test_cases)
    send_update("execution_start", total_tests=len(test_cases), total_steps=total_steps)

    results = []
    passed = 0
    failed = 0

    try:
        send_update("log", level="info", message="Launching embedded browser (headless mode)...")
        send_update("api_call", method="BROWSER", url="chromium.launch()",
                   payload={"headless": True, "embedded": True}, response={"status": "launching"})

        with sync_playwright() as p:
            # Launch headless - screenshots stream to UI for embedded view
            browser = p.chromium.launch(headless=True, slow_mo=100)
            send_update("log", level="info", message="Browser launched in embedded mode")
            send_update("api_call", method="BROWSER", url="chromium.launch()",
                       payload={"headless": True}, response={"status": "ready"})

            for test_idx, test_case in enumerate(test_cases):
                test_id = test_case.get("id", f"TC_{test_idx + 1}")
                test_name = test_case.get("name", "Test Case")
                steps = test_case.get("steps", [])

                send_update("test_update", test_id=test_id, status="running",
                           message=f"Starting: {test_name}")

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

                context = browser.new_context(viewport={"width": 1280, "height": 720})
                page = context.new_page()

                send_update("log", level="info", message=f"Browser context ready (1280x720)")

                try:
                    for step in steps:
                        step_num = step.get("step_number", 0)
                        instruction = step.get("instruction", "")
                        action = step.get("action", {})
                        action_type = action.get("type", "")

                        # Capture screenshot before step starts
                        capture_screenshot(page, test_id, step_num, "running")

                        # Send step starting update
                        send_update("step_update", test_id=test_id, step=step_num,
                                   status="running",
                                   message=f"{instruction[:100]}",
                                   details={"action": action_type})

                        step_result = {
                            "step": step_num,
                            "action": action_type,
                            "instruction": instruction,
                            "status": "PASSED",
                            "selector_used": None,
                            "error": None
                        }

                        try:
                            # Import the actual execution logic
                            from app.tools.enhanced_executor import _execute_action_sync, _get_best_selector_sync

                            selector_hints = step.get("selector_hints", {}) or {}
                            step_test_data = step.get("test_data", {}) or {}
                            assertions = step.get("assertions", []) or []

                            # Log the action being executed
                            send_update("api_call",
                                       method="ACTION",
                                       url=action_type,
                                       payload={
                                           "selector_hints": list(selector_hints.keys()) if selector_hints else [],
                                           "test_data": step_test_data,
                                           "assertions": len(assertions)
                                       },
                                       response={"status": "executing"})

                            selector_used = _execute_action_sync(
                                page=page,
                                action_type=action_type,
                                selector_hints=selector_hints,
                                step_test_data=step_test_data,
                                assertions=assertions,
                                suite_test_data=test_data,
                                timeout=timeout,
                                sync_expect=sync_expect,
                                instruction=instruction
                            )

                            step_result["selector_used"] = selector_used
                            if selector_used:
                                result["selector_mappings"][f"step_{step_num}"] = selector_used

                            # Capture screenshot after step completes successfully
                            capture_screenshot(page, test_id, step_num, "passed")

                            send_update("step_update", test_id=test_id, step=step_num,
                                       status="passed",
                                       message=f"Step {step_num} completed",
                                       details={"action": action_type, "selector": selector_used})

                            send_update("api_call",
                                       method="ACTION",
                                       url=action_type,
                                       payload={"selector": selector_used},
                                       response={"status": "success"})

                        except Exception as e:
                            error_msg = str(e) if str(e) else f"Unknown error in step {step_num}"
                            step_result["status"] = "FAILED"
                            step_result["error"] = error_msg
                            result["status"] = "FAILED"
                            result["error"] = f"Step {step_num}: {error_msg}"

                            # Capture screenshot on failure
                            capture_screenshot(page, test_id, step_num, "failed")

                            send_update("step_update", test_id=test_id, step=step_num,
                                       status="failed",
                                       message=f"Failed: {error_msg[:100]}",
                                       details={"action": action_type, "error": error_msg})

                            send_update("api_call",
                                       method="ACTION",
                                       url=action_type,
                                       payload={},
                                       response={"status": "failed", "error": error_msg[:200]})

                            result["steps"].append(step_result)
                            break

                        result["steps"].append(step_result)

                except Exception as e:
                    result["status"] = "ERROR"
                    result["error"] = str(e) if str(e) else "Unknown test error"
                    send_update("log", level="error", message=f"Test error: {str(e)[:100]}")

                finally:
                    context.close()

                result["finished_at"] = datetime.now().isoformat()
                results.append(result)

                if result["status"] == "PASSED":
                    passed += 1
                    send_update("test_update", test_id=test_id, status="passed",
                               message=f"Test passed: {test_name}")
                else:
                    failed += 1
                    send_update("test_update", test_id=test_id, status="failed",
                               message=f"Test failed: {result.get('error', 'Unknown error')[:100]}")

            browser.close()
            send_update("log", level="info", message="Browser closed")

        # Send completion
        send_update("execution_complete", passed=passed, failed=failed, total=len(test_cases))

        final_result = {
            "project": test_suite.get("project", "Unknown"),
            "base_url": test_suite.get("base_url", ""),
            "total": len(test_cases),
            "passed": passed,
            "failed": failed,
            "results": results,
            "executed_at": datetime.now().isoformat()
        }

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        send_update("log", level="error", message=f"Execution error: {str(e)}")
        send_update("execution_complete", passed=0, failed=len(test_cases), total=len(test_cases))

        final_result = {
            "project": test_suite.get("project", "Unknown"),
            "base_url": test_suite.get("base_url", ""),
            "total": len(test_cases),
            "passed": 0,
            "failed": len(test_cases),
            "results": [{"error": f"Browser launch failed: {str(e)}", "traceback": error_details}],
            "executed_at": datetime.now().isoformat()
        }

    result_queue.put(final_result)


@router.post("/execute-enhanced-stream")
async def execute_enhanced_stream(
    input_data: Dict[str, Any] = Body(...),
    session_id: str = Query(..., description="WebSocket session ID for real-time updates"),
    headless: Optional[bool] = Query(default=False, description="Run browser in headless mode"),
    timeout: Optional[int] = Query(default=30000, description="Timeout for each action in milliseconds")
):
    """
    Execute tests with real-time WebSocket updates including live screenshots.

    Connect to /ws/{session_id} before calling this endpoint to receive updates.

    Updates sent via WebSocket:
    - execution_start: When execution begins
    - test_update: When a test starts/completes
    - step_update: When each step starts/completes
    - screenshot: Live browser screenshot after each step (base64 JPEG)
    - api_call: API/action calls being made
    - log: General log messages
    - execution_complete: When all tests finish
    """
    # Extract test suite data
    if "result" in input_data:
        test_suite = input_data["result"]
    else:
        test_suite = input_data

    test_cases = test_suite.get("test_cases", [])
    if not test_cases:
        raise HTTPException(status_code=400, detail="No test cases found in input")

    # Check SSE connection
    if session_id in sse_manager.queues:
        conn_count = len(sse_manager.queues[session_id])
        print(f"📡 SSE connections for session {session_id}: {conn_count}")
    else:
        print(f"⚠️ No SSE connections for session {session_id}")

    # Log the API call
    await sse_manager.broadcast(session_id, {
        "type": "api_call",
        "method": "POST",
        "url": "/api/v1/execute-enhanced-stream",
        "payload": {"test_cases": len(test_cases), "headless": headless, "timeout": timeout},
        "response": {"status": "started"}
    })

    # Create queues for communication
    result_queue = multiprocessing.Queue()
    update_queue = multiprocessing.Queue()

    # Start the execution process
    process = multiprocessing.Process(
        target=_run_with_updates,
        args=(test_suite, headless, timeout, result_queue, update_queue)
    )
    process.start()

    # Forward updates to SSE in background
    async def forward_updates():
        update_count = 0
        while process.is_alive() or not update_queue.empty():
            try:
                # Non-blocking check for updates
                update = update_queue.get_nowait()
                update_count += 1
                msg_type = update.get("type", "unknown")
                if msg_type == "screenshot":
                    print(f"📡 Forwarding screenshot to SSE: step={update.get('step')}, status={update.get('status')}")
                await sse_manager.broadcast(session_id, update)
            except Exception as e:
                if str(e) != "":  # Ignore empty queue exceptions
                    pass
                await asyncio.sleep(0.05)  # Faster polling for screenshots
        print(f"✅ Forward complete: {update_count} messages sent")

    # Run update forwarder
    asyncio.create_task(forward_updates())

    # Wait for process completion
    total_steps = sum(len(tc.get("steps", [])) for tc in test_cases)
    max_wait = total_steps * 60 + 300

    # Use asyncio to wait without blocking
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, process.join, max_wait)

    if process.is_alive():
        process.terminate()
        process.join()
        await sse_manager.broadcast(session_id, {
            "type": "execution_complete",
            "passed": 0,
            "failed": len(test_cases),
            "total": len(test_cases)
        })
        return {
            "message": "Execution timed out",
            "project": test_suite.get("project", "Unknown"),
            "summary": {"total": len(test_cases), "passed": 0, "failed": len(test_cases)},
            "results": [{"error": "Execution timed out"}],
            "executed_at": datetime.now().isoformat()
        }

    # Get final result
    try:
        result = result_queue.get_nowait()
        return {
            "message": f"Execution completed - {result['passed']}/{result['total']} passed",
            "project": result.get("project", "Unknown"),
            "base_url": result.get("base_url", ""),
            "summary": {
                "total": result["total"],
                "passed": result["passed"],
                "failed": result["failed"]
            },
            "results": result["results"],
            "executed_at": result["executed_at"]
        }
    except Exception:
        return {
            "message": "Failed to get results",
            "project": test_suite.get("project", "Unknown"),
            "summary": {"total": len(test_cases), "passed": 0, "failed": len(test_cases)},
            "results": [{"error": "Failed to get results from process"}],
            "executed_at": datetime.now().isoformat()
        }
