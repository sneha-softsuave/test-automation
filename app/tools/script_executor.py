"""
Playwright Script Executor - Runs generated test scripts and captures results.
"""
import os
import sys
import subprocess
import tempfile
import json
from typing import Dict, Any, Optional
from datetime import datetime


class ScriptExecutor:
    """Executes Playwright test scripts and captures results."""

    def __init__(self, headless: bool = False, timeout: int = 60000):
        self.headless = headless
        self.timeout = timeout
        self.screenshots_dir = tempfile.mkdtemp(prefix="playwright_screenshots_")

    def execute_script(self, script: str, test_id: str = "test") -> Dict[str, Any]:
        """
        Execute a Playwright script and capture results.

        Args:
            script: The Python script content to execute
            test_id: Test identifier for naming

        Returns:
            Execution results including status, output, errors, screenshots
        """
        print(f"\n{'='*60}")
        print(f"SCRIPT EXECUTOR - Starting execution")
        print(f"Test ID: {test_id}")
        print(f"Headless: {self.headless}")
        print(f"{'='*60}\n")

        # Modify script to add headless mode and screenshot on failure
        modified_script = self._inject_execution_settings(script, test_id)

        # Create temp file for the script
        script_file = os.path.join(tempfile.gettempdir(), f"test_{test_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")

        try:
            # Write script to temp file
            with open(script_file, 'w', encoding='utf-8') as f:
                f.write(modified_script)

            print(f"Script saved to: {script_file}")
            print(f"Executing script...\n")

            # Execute the script
            result = subprocess.run(
                [sys.executable, script_file],
                capture_output=True,
                text=True,
                timeout=self.timeout // 1000,
                cwd=tempfile.gettempdir()
            )

            # Parse results
            stdout = result.stdout
            stderr = result.stderr
            return_code = result.returncode

            print(f"\n{'='*60}")
            print(f"EXECUTION OUTPUT:")
            print(f"{'='*60}")
            print(stdout)

            if stderr:
                print(f"\nSTDERR:")
                print(stderr)

            # Determine status
            if return_code == 0:
                status = "PASSED"
            else:
                status = "FAILED"

            # Check for screenshots
            screenshots = self._collect_screenshots(test_id)

            execution_result = {
                "test_id": test_id,
                "status": status,
                "return_code": return_code,
                "stdout": stdout,
                "stderr": stderr,
                "script_file": script_file,
                "screenshots": screenshots,
                "executed_at": datetime.now().isoformat()
            }

            print(f"\n{'='*60}")
            print(f"EXECUTION COMPLETED - Status: {status}")
            print(f"{'='*60}\n")

            return execution_result

        except subprocess.TimeoutExpired:
            return {
                "test_id": test_id,
                "status": "TIMEOUT",
                "return_code": -1,
                "stdout": "",
                "stderr": f"Script execution timed out after {self.timeout}ms",
                "script_file": script_file,
                "screenshots": [],
                "executed_at": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "test_id": test_id,
                "status": "ERROR",
                "return_code": -1,
                "stdout": "",
                "stderr": str(e),
                "script_file": script_file,
                "screenshots": [],
                "executed_at": datetime.now().isoformat()
            }

    def _inject_execution_settings(self, script: str, test_id: str) -> str:
        """Inject execution settings into the script."""

        # Replace headless setting
        headless_str = "True" if self.headless else "False"

        # Add screenshot directory and error handling
        screenshot_path = os.path.join(self.screenshots_dir, f"{test_id}_error.png").replace("\\", "/")

        # Modify the script to use our headless setting
        script = script.replace(
            'browser = p.chromium.launch(headless=False)',
            f'browser = p.chromium.launch(headless={headless_str})'
        )

        # Add screenshot on error
        script = script.replace(
            'except AssertionError as e:',
            f'''except AssertionError as e:
            page.screenshot(path="{screenshot_path}")
            print(f"Screenshot saved: {screenshot_path}")'''
        )

        return script

    def _collect_screenshots(self, test_id: str) -> list:
        """Collect any screenshots generated during execution."""
        screenshots = []
        try:
            for filename in os.listdir(self.screenshots_dir):
                if test_id in filename:
                    filepath = os.path.join(self.screenshots_dir, filename)
                    screenshots.append({
                        "filename": filename,
                        "path": filepath
                    })
        except Exception:
            pass
        return screenshots


def execute_test_cases(test_cases: list, headless: bool = False) -> Dict[str, Any]:
    """
    Execute multiple test cases and collect results.

    Args:
        test_cases: List of test cases with scripts
        headless: Run in headless mode

    Returns:
        Combined execution results
    """
    from app.agents.nodes.script_generator_node import generate_playwright_script

    executor = ScriptExecutor(headless=headless)
    results = []
    passed = 0
    failed = 0
    errors = 0

    for test_case in test_cases:
        test_id = test_case.get("test_id", "unknown")

        # Generate script if not provided
        script = test_case.get("script")
        if not script:
            script = generate_playwright_script(test_case)

        # Execute
        result = executor.execute_script(script, test_id)
        results.append(result)

        # Count results
        if result["status"] == "PASSED":
            passed += 1
        elif result["status"] == "FAILED":
            failed += 1
        else:
            errors += 1

    return {
        "total": len(test_cases),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "results": results,
        "executed_at": datetime.now().isoformat()
    }
