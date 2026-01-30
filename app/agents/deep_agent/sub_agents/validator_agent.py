"""
Validator Sub-Agent

Specialized agent for analyzing test results and deciding on retry strategy.
Uses the ValidatorTool for failure categorization and retry decisions.
"""

from typing import Dict, Any, Optional, Callable

from .base_sub_agent import BaseSubAgent
from ..tools import ValidatorTool


class ValidatorAgent(BaseSubAgent):
    """
    Validator Agent - Specializes in analyzing test results.

    Uses ValidatorTool to:
    - Analyze execution results
    - Categorize failures (transient vs permanent)
    - Decide if retry is beneficial
    - Provide actionable insights
    """

    def __init__(
        self,
        llm_provider: str = "groq",
        model: Optional[str] = None,
        broadcast_func: Optional[Callable] = None
    ):
        super().__init__(
            name="ValidatorAgent",
            role="Test Validator - I analyze results and decide on retries",
            llm_provider=llm_provider,
            model=model,
            broadcast_func=broadcast_func
        )

        # Initialize the validator tool
        self.validator_tool = ValidatorTool()

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate execution results using the ValidatorTool.

        Args:
            task: {
                "execution_results": Results from executor,
                "retry_count": Current retry attempt,
                "max_retries": Maximum retries allowed
            }

        Returns:
            {
                "success": bool,
                "validation_status": "passed" | "failed" | "needs_retry",
                "analysis": Detailed analysis,
                "should_retry": bool,
                "retry_tests": Tests to retry,
                "error": Error message if failed
            }
        """
        execution_results = task.get("execution_results", {})
        retry_count = task.get("retry_count", 0)
        max_retries = task.get("max_retries", 2)

        total = execution_results.get("total", 0) if execution_results else 0
        passed = execution_results.get("passed", 0) if execution_results else 0
        failed = execution_results.get("failed", 0) if execution_results else 0

        self.broadcast({
            "type": "sub_agent_started",
            "node": "validate",
            "message": f"ValidatorAgent analyzing {total} test results ({passed} passed, {failed} failed)..."
        })

        self.log(f"Validating results: {passed}/{total} passed, retry {retry_count}/{max_retries}")

        # Use the validator tool
        result = self.validator_tool.execute(
            execution_results=execution_results,
            retry_count=retry_count,
            max_retries=max_retries
        )

        if result["success"]:
            status = result["validation_status"]
            analysis = result.get("analysis", {})
            summary = analysis.get("summary", "Validation complete")

            self.log(f"Validation status: {status}")
            self.broadcast({
                "type": "sub_agent_completed",
                "node": "validate",
                "message": summary,
                "data": {
                    "status": status,
                    "should_retry": result.get("should_retry", False),
                    "pass_rate": analysis.get("pass_rate", 0)
                }
            })
        else:
            self.log(f"Validation failed: {result['error']}", level="error")
            self.broadcast({
                "type": "sub_agent_completed",
                "node": "validate",
                "status": "error",
                "message": f"Validation failed: {result['error']}"
            })

        return result

    def analyze_failure_patterns(self, execution_results: Dict) -> Dict[str, Any]:
        """
        Use LLM to analyze patterns in test failures.

        Provides insights beyond basic categorization.
        """
        results = execution_results.get("results", [])
        failures = [r for r in results if r.get("status") in ["FAILED", "ERROR"]]

        if not failures:
            return {"patterns": [], "insights": "No failures to analyze"}

        # Build failure summary for LLM
        failure_info = []
        for f in failures[:5]:  # Limit to first 5
            failure_info.append({
                "test": f.get("test_id", "Unknown"),
                "error": (f.get("error") or "Unknown")[:150]
            })

        prompt = f"""Analyze these test failures for patterns:

{failure_info}

Look for:
1. Common error types
2. Possible root causes
3. Suggestions for fixes

Respond in 3-4 sentences."""

        try:
            analysis = self.think(prompt)
            return {
                "patterns": failure_info,
                "insights": analysis,
                "failure_count": len(failures)
            }
        except Exception as e:
            self.log(f"Pattern analysis failed: {e}", level="warning")
            return {
                "patterns": [],
                "insights": f"Analysis failed: {e}",
                "failure_count": len(failures)
            }
