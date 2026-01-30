"""
Reporter Sub-Agent

Specialized agent for generating test reports and Playwright scripts.
Uses the ReporterTool which wraps the script generator service.
"""

from typing import Dict, Any, List, Optional, Callable

from .base_sub_agent import BaseSubAgent
from ..tools import ReporterTool


class ReporterAgent(BaseSubAgent):
    """
    Reporter Agent - Specializes in generating reports and scripts.

    Uses ReporterTool to:
    - Generate Playwright test scripts
    - Create execution summary reports
    - Provide test result documentation
    """

    def __init__(
        self,
        llm_provider: str = "groq",
        model: Optional[str] = None,
        broadcast_func: Optional[Callable] = None
    ):
        super().__init__(
            name="ReporterAgent",
            role="Test Reporter - I generate reports and scripts",
            llm_provider=llm_provider,
            model=model,
            broadcast_func=broadcast_func
        )

        # Initialize the reporter tool
        self.reporter_tool = ReporterTool()

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate reports and scripts using the ReporterTool.

        Args:
            task: {
                "parsed_suite": Original parsed test suite,
                "execution_results": Results from executor,
                "validation_analysis": Analysis from validator,
                "include_script": bool - Generate Playwright script
            }

        Returns:
            {
                "success": bool,
                "report": Structured report data,
                "generated_script": Playwright script (if requested),
                "summary": Human-readable summary,
                "error": Error message if failed
            }
        """
        parsed_suite = task.get("parsed_suite", {})
        execution_results = task.get("execution_results", {})
        validation_analysis = task.get("validation_analysis", {})
        include_script = task.get("include_script", True)

        total = execution_results.get("total", 0) if execution_results else 0

        self.broadcast({
            "type": "sub_agent_started",
            "node": "report",
            "message": f"ReporterAgent generating report for {total} tests..."
        })

        self.log(f"Starting report generation for {total} tests")

        # Use the reporter tool
        result = self.reporter_tool.execute(
            parsed_suite=parsed_suite,
            execution_results=execution_results,
            validation_analysis=validation_analysis,
            include_script=include_script
        )

        if result["success"]:
            report = result.get("report", {})
            stats = report.get("stats", {})

            self.log(f"Report generated: {stats.get('total', 0)} tests documented")
            self.broadcast({
                "type": "sub_agent_completed",
                "node": "report",
                "message": f"Generated report: {stats.get('passed', 0)}/{stats.get('total', 0)} passed",
                "data": {
                    "has_script": bool(result.get("generated_script")),
                    "stats": stats
                }
            })
        else:
            self.log(f"Report generation failed: {result['error']}", level="error")
            self.broadcast({
                "type": "sub_agent_completed",
                "node": "report",
                "status": "error",
                "message": f"Report generation failed: {result['error']}"
            })

        return result

    def generate_executive_summary(self, reports: List[Dict]) -> str:
        """
        Generate executive summary from multiple reports.

        Uses LLM for intelligent summarization.
        """
        if not reports:
            return "No reports available for summary."

        total_tests = sum(r.get("stats", {}).get("total", 0) for r in reports)
        total_passed = sum(r.get("stats", {}).get("passed", 0) for r in reports)
        total_failed = sum(r.get("stats", {}).get("failed", 0) for r in reports)

        prompt = f"""As a QA director, write an executive summary for stakeholders:

Test Execution Overview:
- Total test runs: {len(reports)}
- Total tests executed: {total_tests}
- Overall passed: {total_passed} ({round(total_passed/total_tests*100 if total_tests else 0, 1)}%)
- Overall failed: {total_failed}

Write 2-3 sentences suitable for non-technical stakeholders."""

        try:
            return self.think(prompt)
        except Exception as e:
            self.log(f"Executive summary generation failed: {e}", level="warning")
            return f"Test execution completed: {total_passed}/{total_tests} tests passed ({round(total_passed/total_tests*100 if total_tests else 0, 1)}%)"
