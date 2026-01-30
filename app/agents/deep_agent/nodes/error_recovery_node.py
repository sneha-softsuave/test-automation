"""
Error Recovery Node - Handles retries and error recovery

Prepares state for retry attempts when retryable failures
are detected by the validate node.
"""

from typing import Dict, Any

from app.agents.deep_agent.state import TestAutomationState


def error_recovery_node(state: TestAutomationState) -> Dict[str, Any]:
    """
    Prepare for retry after recoverable failures.

    This node is invoked when validate_node determines that failures
    are potentially retryable (timeouts, element not found, etc.)

    Reads:
        - retry_count: Current retry attempt
        - max_retries: Maximum allowed retries
        - failed_tests: Tests that failed
        - parsed_suite: Original test suite
        - broadcast_func: SSE broadcast function

    Writes:
        - retry_count: Incremented retry count
        - parsed_suite: Potentially modified suite (with adjusted timeouts, etc.)
        - current_step: Updated progress indicator
    """
    broadcast = state.get("broadcast_func")
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    new_retry_count = retry_count + 1

    if broadcast:
        broadcast({
            "type": "node_started",
            "node": "error_recovery",
            "message": f"Preparing retry {new_retry_count}/{max_retries}..."
        })

    # Get failed tests to analyze
    failed_tests = state.get("failed_tests", [])
    parsed_suite = state.get("parsed_suite", {})

    # Analyze failures and potentially adjust suite
    adjusted_suite = _adjust_suite_for_retry(
        parsed_suite=parsed_suite,
        failed_tests=failed_tests,
        retry_count=new_retry_count
    )

    # Broadcast thoughts about recovery strategy
    recovery_actions = []

    if new_retry_count > 1:
        recovery_actions.append("Increased timeouts")

    if len(failed_tests) > 0:
        failed_ids = [t.get("test_id", "?") for t in failed_tests[:3]]
        recovery_actions.append(f"Retrying: {', '.join(failed_ids)}")

    if broadcast:
        if recovery_actions:
            broadcast({
                "type": "thoughts",
                "message": f"Recovery strategy: {', '.join(recovery_actions)}"
            })

        broadcast({
            "type": "node_completed",
            "node": "error_recovery",
            "message": f"Ready for retry {new_retry_count}",
            "data": {
                "retry_count": new_retry_count,
                "max_retries": max_retries,
                "failed_count": len(failed_tests)
            }
        })

    return {
        "retry_count": new_retry_count,
        "parsed_suite": adjusted_suite,
        "current_step": "ready_for_retry",
        # Clear previous execution results for fresh run
        "execution_results": None,
        "validation_status": "pending",
        "validation_errors": [],
        "failed_tests": []
    }


def _adjust_suite_for_retry(
    parsed_suite: Dict[str, Any],
    failed_tests: list,
    retry_count: int
) -> Dict[str, Any]:
    """
    Adjust test suite for retry attempt.

    Possible adjustments:
    - Increase timeouts progressively
    - Add extra wait steps before problematic actions
    - Filter to only run failed tests (optional)
    """
    # Create a copy to avoid modifying original
    adjusted = dict(parsed_suite)

    # For now, we'll run all tests again (not just failed)
    # This ensures state is clean and dependencies work

    # Progressive timeout increase
    # Retry 1: 1.5x timeout, Retry 2+: 2x timeout
    timeout_multiplier = 1.5 if retry_count == 1 else 2.0

    # Add metadata about retry adjustments
    adjusted["_retry_metadata"] = {
        "retry_count": retry_count,
        "timeout_multiplier": timeout_multiplier,
        "original_failed_count": len(failed_tests)
    }

    # Note: Actual timeout adjustment happens in execute_node
    # This metadata can be used there to adjust behavior

    return adjusted
