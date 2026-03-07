"""
Execute Node - Calls the same function as /api/v1/execute-enhanced

Uses execute_enhanced() exactly like the API endpoint.
"""

import asyncio
from typing import Dict, Any

from app.agents.deep_agent.state import TestAutomationState
from app.tools.enhanced_executor import execute_enhanced


def execute_node(state: TestAutomationState) -> Dict[str, Any]:
    """
    Execute Playwright tests from parsed suite.

    This calls the EXACT same code as /api/v1/execute-enhanced endpoint.
    """
    import time
    start_time = time.time()

    broadcast = state.get("broadcast_func")
    retry_count = state.get("retry_count", 0)
    retry_msg = f" (retry {retry_count})" if retry_count > 0 else ""

    print(f"\n[Execute Node] ========== STARTING EXECUTION ==========")

    if broadcast:
        broadcast({
            "type": "node_started",
            "node": "execute",
            "message": f"Executing Playwright tests{retry_msg}..."
        })

    parsed_suite = state.get("parsed_suite")

    # Log parsed suite details
    if parsed_suite:
        test_cases = parsed_suite.get("test_cases", [])
        total_steps = sum(len(tc.get("steps", [])) for tc in test_cases)
        print(f"[Execute Node] Parsed suite: {len(test_cases)} test cases, {total_steps} total steps")
        print(f"[Execute Node] Project: {parsed_suite.get('project', 'N/A')}")
        print(f"[Execute Node] Base URL: {parsed_suite.get('base_url', 'N/A')}")
        if test_cases:
            print(f"[Execute Node] First test case: {test_cases[0].get('name', 'N/A')}")
    else:
        print(f"[Execute Node] ERROR: parsed_suite is None or empty!")

    if not parsed_suite:
        error_msg = "No parsed suite available for execution"
        errors = state.get("errors", [])
        errors.append(error_msg)

        if broadcast:
            broadcast({
                "type": "node_completed",
                "node": "execute",
                "status": "error",
                "message": error_msg
            })

        from datetime import datetime
        return {
            "execution_results": {
                "project": state.get("project_name", "Test Project"),
                "base_url": state.get("base_url", ""),
                "total": 0,
                "passed": 0,
                "failed": 0,
                "results": [],
                "executed_at": datetime.now().isoformat()
            },
            "current_step": "execute_failed",
            "errors": errors
        }

    try:
        headless = state.get("headless", True)
        keep_browser_open = state.get("keep_browser_open", True)
        timeout = state.get("timeout", 30000)

        test_cases = parsed_suite.get("test_cases", [])
        total_steps = sum(len(tc.get("steps", [])) for tc in test_cases)

        print(f"[Execute Node] Running {len(test_cases)} test cases with {total_steps} steps")
        print(f"[Execute Node] Headless: {headless}, Timeout: {timeout}ms")

        if broadcast:
            broadcast({
                "type": "thoughts",
                "message": f"Running {len(test_cases)} test case(s) with {total_steps} total steps..."
            })
            broadcast({
                "type": "execution_started",
                "total_tests": len(test_cases),
                "total_steps": total_steps,
                "headless": headless
            })

        # Pull step control and stop event from state
        signal_file = state.get("step_control_file")
        stop_event = state.get("stop_event")

        # Run the async execute_enhanced function (SAME as API endpoint)
        # We need to handle async/sync context properly
        try:
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an async context, create a new thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        execute_enhanced(
                            test_suite=parsed_suite,
                            headless=headless,
                            keep_browser_open=keep_browser_open,
                            timeout=timeout,
                            stop_event=stop_event,
                            signal_file=signal_file,
                        )
                    )
                    execution_results = future.result()
            else:
                execution_results = loop.run_until_complete(
                    execute_enhanced(
                        test_suite=parsed_suite,
                        headless=headless,
                        keep_browser_open=keep_browser_open,
                        timeout=timeout,
                        stop_event=stop_event,
                        signal_file=signal_file,
                    )
                )
        except RuntimeError:
            # No event loop, create one
            execution_results = asyncio.run(
                execute_enhanced(
                    test_suite=parsed_suite,
                    headless=headless,
                    keep_browser_open=keep_browser_open,
                    timeout=timeout,
                    stop_event=stop_event,
                    signal_file=signal_file,
                )
            )

        passed = execution_results.get("passed", 0)
        failed = execution_results.get("failed", 0)
        total = execution_results.get("total", len(test_cases))

        elapsed_time = time.time() - start_time
        print(f"[Execute Node] ========== EXECUTION FINISHED ==========")
        print(f"[Execute Node] Results: {passed}/{total} passed, {failed} failed")
        print(f"[Execute Node] Total execution time: {elapsed_time:.2f} seconds")
        print(f"[Execute Node] Average time per test: {elapsed_time/total:.2f}s" if total > 0 else "")

        if broadcast:
            broadcast({
                "type": "node_completed",
                "node": "execute",
                "message": f"Execution complete: {passed}/{total} passed in {elapsed_time:.1f}s",
                "data": {
                    "passed": passed,
                    "failed": failed,
                    "total": total,
                    "elapsed_seconds": round(elapsed_time, 2)
                }
            })

        return {
            "execution_results": execution_results,
            "current_step": "execution_complete",
            "errors": state.get("errors", [])
        }

    except Exception as e:
        import traceback
        from datetime import datetime
        error_msg = f"Execution error: {str(e)}"
        print(f"[Execute Node] ERROR: {error_msg}")
        print(traceback.format_exc())

        errors = state.get("errors", [])
        errors.append(error_msg)

        if broadcast:
            broadcast({
                "type": "node_completed",
                "node": "execute",
                "status": "error",
                "message": error_msg
            })

        test_cases = parsed_suite.get("test_cases", []) if parsed_suite else []
        return {
            "execution_results": {
                "project": state.get("project_name", "Test Project"),
                "base_url": state.get("base_url", ""),
                "total": len(test_cases),
                "passed": 0,
                "failed": len(test_cases),
                "results": [],
                "error": error_msg,
                "executed_at": datetime.now().isoformat()
            },
            "current_step": "execute_failed",
            "errors": errors
        }
