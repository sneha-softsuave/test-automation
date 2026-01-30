"""
Validate Node - Analyzes execution results

Determines if tests passed, failed, or need retry based on
the execution results and failure patterns.
"""

from typing import Dict, Any, List

from app.agents.deep_agent.state import TestAutomationState


def validate_node(state: TestAutomationState) -> Dict[str, Any]:
    """
    Validate execution results and decide next action.

    Reads:
        - execution_results: Results from execute node
        - retry_count: Current retry attempt
        - max_retries: Maximum allowed retries
        - broadcast_func: SSE broadcast function

    Writes:
        - validation_status: "passed", "failed", or "needs_retry"
        - validation_errors: List of error messages
        - failed_tests: Tests that failed (for potential retry)
        - current_step: Updated progress indicator
    """
    broadcast = state.get("broadcast_func")

    if broadcast:
        broadcast({
            "type": "node_started",
            "node": "validate",
            "message": "Validating execution results..."
        })

    # Check for errors from previous steps (like parse failures)
    errors = state.get("errors") or []
    parsed_suite = state.get("parsed_suite")

    if errors:
        print(f"[Validate Node] Found {len(errors)} error(s) from previous steps")
        return {
            "validation_status": "failed",
            "validation_errors": errors,
            "failed_tests": [],
            "current_step": "validation_complete"
        }

    if not parsed_suite:
        print("[Validate Node] No parsed suite - parse step likely failed")
        return {
            "validation_status": "failed",
            "validation_errors": ["Parse step failed - no test suite available"],
            "failed_tests": [],
            "current_step": "validation_complete"
        }

    execution_results = state.get("execution_results") or {}

    # Check if we have valid results
    if not execution_results or not isinstance(execution_results, dict):
        print("[Validate Node] No execution results to validate")
        return {
            "validation_status": "failed",
            "validation_errors": ["No execution results to validate"],
            "failed_tests": [],
            "current_step": "validation_complete"
        }

    # Check if execution had 0 tests (likely means parse failed)
    total = execution_results.get("total", 0)
    if total == 0:
        print("[Validate Node] No tests were executed - parse may have failed")
        return {
            "validation_status": "failed",
            "validation_errors": ["No tests were executed - check parse step for errors"],
            "failed_tests": [],
            "current_step": "validation_complete"
        }

    print(f"[Validate Node] Analyzing results: {execution_results.get('passed', 0)} passed, {execution_results.get('failed', 0)} failed")

    passed = execution_results.get("passed", 0)
    failed = execution_results.get("failed", 0)
    total = execution_results.get("total", 0)
    results = execution_results.get("results", [])

    validation_errors: List[str] = []
    failed_tests: List[Dict[str, Any]] = []
    retryable_failures = 0

    # Analyze each test result
    for result in results:
        if result.get("status") in ["FAILED", "ERROR"]:
            test_id = result.get("test_id", "unknown")
            error = result.get("error", "Unknown error")

            validation_errors.append(f"{test_id}: {error}")
            failed_tests.append(result)

            # Check if failure is potentially retryable
            if _is_retryable_failure(error):
                retryable_failures += 1

    # Determine validation status
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if failed == 0:
        validation_status = "passed"
        status_message = f"All {total} tests passed!"
    elif retryable_failures > 0 and retry_count < max_retries:
        validation_status = "needs_retry"
        status_message = f"{retryable_failures} retryable failure(s) detected, will retry"
    else:
        validation_status = "failed"
        status_message = f"{failed}/{total} tests failed"

    if broadcast:
        broadcast({
            "type": "node_completed",
            "node": "validate",
            "message": status_message,
            "data": {
                "validation_status": validation_status,
                "passed": passed,
                "failed": failed,
                "retryable": retryable_failures,
                "retry_count": retry_count,
                "max_retries": max_retries
            }
        })

        # Send thoughts about validation
        if validation_errors:
            broadcast({
                "type": "thoughts",
                "message": f"Validation issues: {', '.join(validation_errors[:3])}"
            })

    return {
        "validation_status": validation_status,
        "validation_errors": validation_errors,
        "failed_tests": failed_tests,
        "current_step": "validation_complete"
    }


def _is_retryable_failure(error: str) -> bool:
    """
    Determine if a failure is potentially retryable.

    Retryable failures include:
    - Timeout errors
    - Element not found (timing issues)
    - Network errors
    - Navigation errors

    Non-retryable failures include:
    - Assertion failures (actual != expected)
    - Missing test data
    - Invalid configuration
    """
    if not error:
        return False

    error_lower = error.lower()

    # Retryable patterns
    retryable_patterns = [
        "timeout",
        "timed out",
        "not found",
        "no element",
        "waiting for selector",
        "waiting for locator",
        "network",
        "navigation",
        "net::",
        "connection",
        "refused",
        "target closed",
        "page crashed",
        "context closed",
        "browser disconnected",
        "element is not attached",
        "element is not visible",
        "intercepted",
    ]

    # Non-retryable patterns (assertion failures)
    non_retryable_patterns = [
        "expected",
        "assertion",
        "not equal",
        "does not match",
        "missing test data",
        "no url provided",
        "invalid",
        "configuration error",
    ]

    # Check for non-retryable first
    for pattern in non_retryable_patterns:
        if pattern in error_lower:
            return False

    # Check for retryable
    for pattern in retryable_patterns:
        if pattern in error_lower:
            return True

    return False
