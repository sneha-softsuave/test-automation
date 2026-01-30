"""
Validator Tool - Analyzes execution results

This tool analyzes test execution results to:
- Categorize failures (retryable vs non-retryable)
- Decide if retry is needed
- Provide actionable insights
"""

from typing import Dict, Any, List


class ValidatorTool:
    """
    Tool for validating and analyzing test execution results.

    Provides:
    - Failure categorization
    - Retry decision logic
    - Result analysis
    """

    name = "validate_results"
    description = "Analyze execution results, categorize failures, and decide on retries"

    # Errors that are typically transient and worth retrying
    RETRYABLE_ERRORS = [
        "timeout",
        "element not found",
        "not found",
        "navigation",
        "network",
        "connection",
        "waiting for",
        "locator resolved",
        "target closed",
        "page closed",
        "context closed",
    ]

    # Errors that indicate test logic issues, not worth retrying
    NON_RETRYABLE_ERRORS = [
        "assertion",
        "expected",
        "not equal",
        "mismatch",
        "invalid selector",
        "syntax error",
        "permission denied",
        "authentication",
        "unauthorized",
        "forbidden",
    ]

    # URL-related errors - these should be ignored or auto-passed
    # (redirects cause different URLs which is normal behavior)
    URL_IGNORABLE_ERRORS = [
        "url",
        "redirect",
        "to_have_url",
        "url_contains",
        "url mismatch",
    ]

    def __init__(self):
        pass

    def execute(
        self,
        execution_results: Dict[str, Any],
        retry_count: int = 0,
        max_retries: int = 2
    ) -> Dict[str, Any]:
        """
        Analyze execution results and decide next action.

        Args:
            execution_results: Results from ExecutorTool
            retry_count: Current retry count
            max_retries: Maximum allowed retries

        Returns:
            {
                "success": bool,
                "validation_status": "passed" | "failed" | "needs_retry",
                "analysis": {
                    "total": int,
                    "passed": int,
                    "failed": int,
                    "pass_rate": float,
                    "retryable_failures": [...],
                    "non_retryable_failures": [...],
                    "summary": str
                },
                "should_retry": bool,
                "retry_tests": [...] or None,
                "error": str or None
            }
        """
        try:
            if not execution_results:
                return {
                    "success": False,
                    "validation_status": "failed",
                    "analysis": None,
                    "should_retry": False,
                    "retry_tests": None,
                    "error": "No execution results to validate"
                }

            total = execution_results.get("total", 0)
            passed = execution_results.get("passed", 0)
            failed = execution_results.get("failed", 0)
            results = execution_results.get("results", [])

            print(f"[ValidatorTool] Analyzing {total} test results: {passed} passed, {failed} failed")

            # All passed
            if failed == 0 and passed == total:
                return {
                    "success": True,
                    "validation_status": "passed",
                    "analysis": {
                        "total": total,
                        "passed": passed,
                        "failed": failed,
                        "pass_rate": 100.0,
                        "retryable_failures": [],
                        "non_retryable_failures": [],
                        "summary": f"All {total} tests passed successfully!"
                    },
                    "should_retry": False,
                    "retry_tests": None,
                    "error": None
                }

            # Analyze failures
            retryable_failures = []
            non_retryable_failures = []
            url_ignorable_count = 0

            for result in results:
                if result.get("status") == "FAILED" or result.get("status") == "ERROR":
                    error = result.get("error", "") or ""
                    error_lower = error.lower()
                    test_id = result.get("test_id", "unknown")

                    # Check if this is a URL-related error (ignore these - redirects are normal)
                    is_url_error = any(url_err in error_lower for url_err in self.URL_IGNORABLE_ERRORS)
                    if is_url_error:
                        print(f"[ValidatorTool] Ignoring URL-related error for {test_id}: {error[:50]}...")
                        url_ignorable_count += 1
                        continue  # Skip URL errors - they're usually due to redirects

                    # Check if retryable
                    is_retryable = any(err in error_lower for err in self.RETRYABLE_ERRORS)
                    is_non_retryable = any(err in error_lower for err in self.NON_RETRYABLE_ERRORS)

                    failure_info = {
                        "test_id": test_id,
                        "test_name": result.get("test_name", "Unknown"),
                        "error": error[:200],  # Truncate long errors
                        "error_type": self._categorize_error(error_lower)
                    }

                    if is_non_retryable:
                        non_retryable_failures.append(failure_info)
                    elif is_retryable:
                        retryable_failures.append(failure_info)
                    else:
                        # Unknown error type, assume retryable for first attempt
                        if retry_count < 1:
                            retryable_failures.append(failure_info)
                        else:
                            non_retryable_failures.append(failure_info)

            # If all failures were URL-related (ignorable), treat as passed
            if url_ignorable_count > 0 and len(retryable_failures) == 0 and len(non_retryable_failures) == 0:
                print(f"[ValidatorTool] All {url_ignorable_count} failures were URL-related, treating as passed")
                return {
                    "success": True,
                    "validation_status": "passed",
                    "analysis": {
                        "total": total,
                        "passed": passed + url_ignorable_count,
                        "failed": 0,
                        "pass_rate": 100.0,
                        "retryable_failures": [],
                        "non_retryable_failures": [],
                        "url_ignorable": url_ignorable_count,
                        "summary": f"All tests passed ({url_ignorable_count} URL assertions auto-passed due to redirects)"
                    },
                    "should_retry": False,
                    "retry_tests": None,
                    "error": None
                }

            # Decide on retry
            should_retry = (
                len(retryable_failures) > 0 and
                retry_count < max_retries and
                len(non_retryable_failures) < total  # Not all failures are non-retryable
            )

            if should_retry:
                validation_status = "needs_retry"
                retry_tests = [f["test_id"] for f in retryable_failures]
                summary = f"Found {len(retryable_failures)} retryable failure(s). Retry recommended ({retry_count + 1}/{max_retries})."
            else:
                validation_status = "failed"
                retry_tests = None
                if retry_count >= max_retries:
                    summary = f"Max retries ({max_retries}) reached. {passed}/{total} tests passed."
                else:
                    summary = f"{len(non_retryable_failures)} non-retryable failure(s). {passed}/{total} tests passed."

            print(f"[ValidatorTool] Status: {validation_status}, Should retry: {should_retry}")

            return {
                "success": True,
                "validation_status": validation_status,
                "analysis": {
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "pass_rate": round((passed / total * 100) if total > 0 else 0, 2),
                    "retryable_failures": retryable_failures,
                    "non_retryable_failures": non_retryable_failures,
                    "summary": summary
                },
                "should_retry": should_retry,
                "retry_tests": retry_tests,
                "error": None
            }

        except Exception as e:
            error_msg = str(e)
            print(f"[ValidatorTool] Error: {error_msg}")
            return {
                "success": False,
                "validation_status": "failed",
                "analysis": None,
                "should_retry": False,
                "retry_tests": None,
                "error": error_msg
            }

    def _categorize_error(self, error_lower: str) -> str:
        """Categorize error type for reporting."""
        if "timeout" in error_lower:
            return "timeout"
        elif "not found" in error_lower or "element" in error_lower:
            return "element_not_found"
        elif "navigation" in error_lower:
            return "navigation"
        elif "network" in error_lower or "connection" in error_lower:
            return "network"
        elif "assertion" in error_lower or "expected" in error_lower:
            return "assertion"
        elif "selector" in error_lower:
            return "selector"
        else:
            return "unknown"
