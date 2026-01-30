"""
Reporter Tool - Generates reports and Playwright scripts

This tool wraps the script generator API to:
- Generate Playwright test scripts
- Create execution reports
- Provide summary data for reports
"""

from typing import Dict, Any, Optional
from datetime import datetime
from app.tools.enhanced_script_generator import generate_enhanced_pytest_script


class ReporterTool:
    """
    Tool for generating reports and Playwright scripts.

    Wraps the script generator service to create:
    - Playwright TypeScript test scripts
    - Execution summary reports
    - Test result documentation
    """

    name = "generate_report"
    description = "Generate Playwright scripts and execution reports"

    def __init__(self):
        pass

    def execute(
        self,
        parsed_suite: Dict[str, Any],
        execution_results: Optional[Dict[str, Any]] = None,
        validation_analysis: Optional[Dict[str, Any]] = None,
        include_script: bool = True
    ) -> Dict[str, Any]:
        """
        Generate reports and scripts from test data.

        Args:
            parsed_suite: Parsed test suite with test_cases
            execution_results: Results from ExecutorTool (optional)
            validation_analysis: Analysis from ValidatorTool (optional)
            include_script: Whether to generate Playwright script

        Returns:
            {
                "success": bool,
                "report": {
                    "project": str,
                    "base_url": str,
                    "generated_at": str,
                    "stats": {...},
                    "validation": {...},
                    "test_results": [...],
                    "failures": [...]
                },
                "generated_script": str or None,
                "summary": str,
                "error": str or None
            }
        """
        try:
            print(f"[ReporterTool] Generating report...")

            # Build report data
            report = self._build_report(parsed_suite, execution_results, validation_analysis)

            # Generate Playwright script if requested
            generated_script = None
            if include_script and parsed_suite:
                generated_script = self._generate_script(parsed_suite)

            # Generate human-readable summary
            summary = self._generate_summary(report)

            print(f"[ReporterTool] Report generated with {report['stats']['total']} tests")

            return {
                "success": True,
                "report": report,
                "generated_script": generated_script,
                "summary": summary,
                "error": None
            }

        except Exception as e:
            error_msg = str(e)
            print(f"[ReporterTool] Error: {error_msg}")
            return {
                "success": False,
                "report": None,
                "generated_script": None,
                "summary": None,
                "error": error_msg
            }

    def _build_report(
        self,
        parsed_suite: Dict[str, Any],
        execution_results: Optional[Dict[str, Any]],
        validation_analysis: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build structured report data."""
        total = execution_results.get("total", 0) if execution_results else 0
        passed = execution_results.get("passed", 0) if execution_results else 0
        failed = execution_results.get("failed", 0) if execution_results else 0

        # Get failures from results
        failures = []
        if execution_results:
            for r in execution_results.get("results", []):
                if r.get("status") in ["FAILED", "ERROR"]:
                    failures.append({
                        "test_id": r.get("test_id"),
                        "test_name": r.get("test_name"),
                        "error": r.get("error"),
                        "status": r.get("status")
                    })

        return {
            "generated_at": datetime.now().isoformat(),
            "project": parsed_suite.get("project", "Test Project") if parsed_suite else "Test Project",
            "base_url": parsed_suite.get("base_url", "") if parsed_suite else "",
            "stats": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": round((passed / total * 100) if total > 0 else 0, 2)
            },
            "validation": {
                "status": validation_analysis.get("validation_status", "unknown") if validation_analysis else "unknown",
                "summary": validation_analysis.get("analysis", {}).get("summary", "") if validation_analysis else "",
                "retryable_count": len(validation_analysis.get("analysis", {}).get("retryable_failures", [])) if validation_analysis else 0,
                "non_retryable_count": len(validation_analysis.get("analysis", {}).get("non_retryable_failures", [])) if validation_analysis else 0
            },
            "test_results": execution_results.get("results", []) if execution_results else [],
            "failures": failures
        }

    def _generate_script(self, parsed_suite: Dict[str, Any]) -> Optional[str]:
        """Generate Playwright script from parsed suite."""
        try:
            script = generate_enhanced_pytest_script(parsed_suite)
            print(f"[ReporterTool] Script generated: {len(script)} characters")
            return script
        except Exception as e:
            print(f"[ReporterTool] Script generation failed: {e}")
            # Fallback to basic script
            return self._generate_basic_script(parsed_suite)

    def _generate_basic_script(self, parsed_suite: Dict[str, Any]) -> str:
        """Generate basic Playwright script as fallback."""
        project = parsed_suite.get("project", "Test Project")
        base_url = parsed_suite.get("base_url", "https://example.com")
        test_cases = parsed_suite.get("test_cases", [])

        script_parts = [
            "import { test, expect } from '@playwright/test';",
            "",
            f"// {project}",
            f"// Base URL: {base_url}",
            f"// Generated by ReporterTool",
            "",
            f"test.describe('{project}', () => {{",
        ]

        for tc in test_cases:
            tc_name = tc.get("name", "Unnamed Test")
            script_parts.append(f"  test('{tc_name}', async ({{ page }}) => {{")
            script_parts.append(f"    await page.goto('{base_url}');")

            for step in tc.get("steps", []):
                action = step.get("action", {})
                action_type = action.get("type", "").lower() if isinstance(action, dict) else ""
                selector_hints = step.get("selector_hints", {})
                selectors = selector_hints.get("suggested_selectors", []) if selector_hints else []
                selector = selectors[0] if selectors else "body"
                test_data = step.get("test_data", {}) or {}
                value = test_data.get("value", "") if test_data else ""

                if action_type == "click":
                    script_parts.append(f"    await page.locator('{selector}').click();")
                elif action_type in ["fill", "type", "input"]:
                    script_parts.append(f"    await page.locator('{selector}').fill('{value}');")
                elif action_type == "navigate":
                    script_parts.append(f"    await page.goto('{value or base_url}');")
                elif action_type == "assert":
                    script_parts.append(f"    await expect(page.locator('{selector}')).toBeVisible();")

            script_parts.append("  });")
            script_parts.append("")

        script_parts.append("});")

        return "\n".join(script_parts)

    def _generate_summary(self, report: Dict[str, Any]) -> str:
        """Generate human-readable summary."""
        stats = report.get("stats", {})
        total = stats.get("total", 0)
        passed = stats.get("passed", 0)
        failed = stats.get("failed", 0)
        pass_rate = stats.get("pass_rate", 0)

        if failed == 0:
            status = "SUCCESS"
            emoji = "✅"
        elif pass_rate >= 80:
            status = "MOSTLY PASSED"
            emoji = "⚠️"
        elif pass_rate >= 50:
            status = "PARTIAL"
            emoji = "⚠️"
        else:
            status = "NEEDS ATTENTION"
            emoji = "❌"

        summary = f"""{emoji} Test Execution Report - {status}

Project: {report.get('project', 'Unknown')}
Generated: {report.get('generated_at', 'Unknown')}

Results: {passed}/{total} tests passed ({pass_rate}%)
- Passed: {passed}
- Failed: {failed}
"""

        if failed > 0:
            failures = report.get("failures", [])
            summary += "\nFailed Tests:\n"
            for f in failures[:5]:  # Show first 5 failures
                summary += f"  - {f.get('test_id', 'Unknown')}: {f.get('error', 'Unknown error')[:50]}...\n"
            if len(failures) > 5:
                summary += f"  ... and {len(failures) - 5} more\n"

        return summary
