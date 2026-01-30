"""
Report Node - Generates final report and Playwright script

Creates the final test report and generates reusable
Playwright Python test scripts.
"""

from typing import Dict, Any
from datetime import datetime

from app.agents.deep_agent.state import TestAutomationState
from app.tools.enhanced_script_generator import generate_enhanced_pytest_script


def report_node(state: TestAutomationState) -> Dict[str, Any]:
    """
    Generate final report and Playwright script.

    Reads:
        - parsed_suite: Test suite structure
        - execution_results: Test results
        - validation_status: Final status
        - validation_errors: Any errors
        - broadcast_func: SSE broadcast function

    Writes:
        - report_data: Complete report
        - generated_script: Playwright Python script
        - current_step: Updated progress indicator
    """
    broadcast = state.get("broadcast_func")

    if broadcast:
        broadcast({
            "type": "node_started",
            "node": "report",
            "message": "Generating report and Playwright script..."
        })

    try:
        parsed_suite = state.get("parsed_suite") or {}
        execution_results = state.get("execution_results") or {}
        validation_status = state.get("validation_status", "unknown")
        validation_errors = state.get("validation_errors") or []

        print(f"[Report Node] Building report: status={validation_status}, passed={execution_results.get('passed', 0)}/{execution_results.get('total', 0)}")

        # Generate Playwright script
        generated_script = None
        if parsed_suite:
            try:
                generated_script = generate_enhanced_pytest_script(parsed_suite)
                if broadcast:
                    broadcast({
                        "type": "thoughts",
                        "message": "Playwright Python script generated successfully"
                    })
            except Exception as e:
                if broadcast:
                    broadcast({
                        "type": "thoughts",
                        "message": f"Script generation warning: {str(e)}"
                    })

        # Build report data
        report_data = _build_report(
            parsed_suite=parsed_suite,
            execution_results=execution_results,
            validation_status=validation_status,
            validation_errors=validation_errors,
            generated_script=generated_script
        )

        if broadcast:
            # Send completion with summary
            passed = execution_results.get("passed", 0)
            failed = execution_results.get("failed", 0)
            total = execution_results.get("total", 0)

            broadcast({
                "type": "node_completed",
                "node": "report",
                "message": f"Report generated: {passed}/{total} passed",
                "data": {
                    "has_script": generated_script is not None,
                    "validation_status": validation_status
                }
            })

            # Send final deep agent complete event
            broadcast({
                "type": "deep_agent_complete",
                "message": "Deep Agent workflow completed",
                "data": {
                    "status": validation_status,
                    "passed": passed,
                    "failed": failed,
                    "total": total,
                    "has_script": generated_script is not None
                }
            })

        return {
            "report_data": report_data,
            "generated_script": generated_script,
            "current_step": "complete"
        }

    except Exception as e:
        error_msg = f"Report generation error: {str(e)}"
        errors = state.get("errors", [])
        errors.append(error_msg)

        if broadcast:
            broadcast({
                "type": "node_completed",
                "node": "report",
                "status": "error",
                "message": error_msg
            })

        return {
            "report_data": None,
            "generated_script": None,
            "current_step": "report_failed",
            "errors": errors
        }


def _build_report(
    parsed_suite: Dict[str, Any],
    execution_results: Dict[str, Any],
    validation_status: str,
    validation_errors: list,
    generated_script: str = None
) -> Dict[str, Any]:
    """Build comprehensive report data."""

    # Extract test case details for report
    test_case_reports = []
    results = execution_results.get("results", [])

    for result in results:
        test_report = {
            "test_id": result.get("test_id"),
            "test_name": result.get("test_name"),
            "status": result.get("status"),
            "error": result.get("error"),
            "steps_executed": len(result.get("steps", [])),
            "steps_passed": sum(
                1 for s in result.get("steps", [])
                if s.get("status") == "PASSED"
            ),
            "screenshots": result.get("screenshots", []),
            "selector_mappings": result.get("selector_mappings", {}),
            "started_at": result.get("started_at"),
            "finished_at": result.get("finished_at"),
        }
        test_case_reports.append(test_report)

    return {
        "project": parsed_suite.get("project", "Unknown"),
        "base_url": parsed_suite.get("base_url", ""),
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "validation_status": validation_status,
            "total_tests": execution_results.get("total", 0),
            "passed": execution_results.get("passed", 0),
            "failed": execution_results.get("failed", 0),
            "pass_rate": _calculate_pass_rate(execution_results),
            "validation_errors": validation_errors,
        },
        "test_cases": test_case_reports,
        "execution_metadata": {
            "executed_at": execution_results.get("executed_at"),
        },
        "has_playwright_script": generated_script is not None,
    }


def _calculate_pass_rate(execution_results: Dict[str, Any]) -> float:
    """Calculate pass rate percentage."""
    total = execution_results.get("total", 0)
    passed = execution_results.get("passed", 0)

    if total == 0:
        return 0.0

    return round((passed / total) * 100, 1)
