"""
Executor Sub-Agent

Specialized agent for running Playwright tests in the browser.
Uses the ExecutorTool which wraps the enhanced_executor.
"""

from typing import Dict, Any, Optional, Callable

from .base_sub_agent import BaseSubAgent
from ..tools import ExecutorTool


class ExecutorAgent(BaseSubAgent):
    """
    Executor Agent - Specializes in browser test execution.

    Uses ExecutorTool to:
    - Launch Playwright browser
    - Execute test steps with selectors
    - Capture screenshots on failures
    - Return detailed results
    """

    def __init__(
        self,
        llm_provider: str = "groq",
        model: Optional[str] = None,
        broadcast_func: Optional[Callable] = None
    ):
        super().__init__(
            name="ExecutorAgent",
            role="Test Executor - I run tests in real browsers",
            llm_provider=llm_provider,
            model=model,
            broadcast_func=broadcast_func
        )

        # Initialize the executor tool
        self.executor_tool = ExecutorTool()

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute parsed test suite using the ExecutorTool.

        Args:
            task: {
                "parsed_suite": Structured test suite,
                "headless": bool,
                "timeout": int (ms),
                "base_url": Optional base URL override
            }

        Returns:
            {
                "success": bool,
                "execution_results": Full execution results,
                "error": Error message if failed
            }
        """
        parsed_suite = task.get("parsed_suite")
        headless = task.get("headless", True)
        timeout = task.get("timeout", 30000)
        base_url = task.get("base_url")

        test_count = len(parsed_suite.get("test_cases", [])) if parsed_suite else 0

        self.broadcast({
            "type": "sub_agent_started",
            "node": "execute",
            "message": f"ExecutorAgent running {test_count} tests (headless={headless})..."
        })

        self.log(f"Starting execution: {test_count} tests, headless={headless}, timeout={timeout}")

        # Validate input
        if not parsed_suite:
            error_msg = "No parsed suite provided"
            self.log(error_msg, level="error")
            self.broadcast({
                "type": "sub_agent_completed",
                "node": "execute",
                "status": "error",
                "message": error_msg
            })
            return {
                "success": False,
                "execution_results": None,
                "error": error_msg
            }

        # Use the executor tool with broadcast function for real-time SSE updates
        result = self.executor_tool.execute(
            test_suite=parsed_suite,
            headless=headless,
            timeout=timeout,
            base_url=base_url,
            broadcast_func=self.broadcast_func
        )

        if result["success"]:
            exec_results = result["execution_results"]
            passed = exec_results.get("passed", 0)
            failed = exec_results.get("failed", 0)
            total = exec_results.get("total", 0)

            self.log(f"Execution complete: {passed}/{total} passed, {failed} failed")
            self.broadcast({
                "type": "sub_agent_completed",
                "node": "execute",
                "message": f"Executed {total} tests: {passed} passed, {failed} failed",
                "data": {
                    "total": total,
                    "passed": passed,
                    "failed": failed
                }
            })
        else:
            self.log(f"Execution failed: {result['error']}", level="error")
            self.broadcast({
                "type": "sub_agent_completed",
                "node": "execute",
                "status": "error",
                "message": f"Execution failed: {result['error']}"
            })

        return result

    def analyze_failure(self, step_result: Dict) -> Dict[str, Any]:
        """Use LLM to analyze why a test step failed."""
        error = step_result.get('error', 'Unknown error')
        step_info = step_result.get('step', {})

        prompt = f"""Analyze this test step failure:

Step: {step_info}
Error: {error}

What likely caused this failure? Suggest fixes.
Respond briefly in 2-3 sentences."""

        try:
            analysis = self.think(prompt)
            return {
                "cause": analysis,
                "suggestions": ["Check selector", "Increase timeout", "Verify element exists"],
                "is_transient": "timeout" in error.lower() or "not found" in error.lower()
            }
        except Exception as e:
            return {
                "cause": f"Analysis failed: {e}",
                "suggestions": ["Check selector", "Increase timeout"],
                "is_transient": False
            }
