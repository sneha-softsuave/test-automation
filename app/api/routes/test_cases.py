from fastapi import APIRouter, UploadFile, File, HTTPException, Query, BackgroundTasks
from typing import Optional, List
import re
import uuid
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from app.core.config import settings
from app.services.test_case_service import TestCaseService
from app.agents.json_parser_agent import LLMProvider
from app.models.test_case import RawTestCaseInput, ParsedTestCaseInput, ScriptExecutionInput, TestCaseExecutionInput
from app.tools.selector_extractor import SelectorExtractor
from app.tools.script_executor import ScriptExecutor, execute_test_cases
from app.tools.dynamic_executor import execute_dynamic
from app.agents.enhanced_json_parser import EnhancedJsonParserAgent
from app.models.enhanced_test_case import EnhancedTestSuiteInput
from app.tools.enhanced_script_generator import (
    generate_enhanced_playwright_script,
    generate_enhanced_pytest_script
)
from app.tools.enhanced_executor import execute_enhanced

router = APIRouter()


# ---------------------------------------------------------------------------
# Credential extraction helper
# ---------------------------------------------------------------------------
import re as _cred_re

_CRED_EMAIL_RE = _cred_re.compile(r'\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b')
_CRED_PWD_RE = _cred_re.compile(
    r'(?:password|pass(?:word)?|pwd)\s*(?:is|[:=])\s*([^\s,;]+)',
    _cred_re.IGNORECASE,
)


def _extract_credentials(text: str) -> dict:
    """Extract email/password from a user message."""
    creds: dict = {}
    email_m = _CRED_EMAIL_RE.search(text)
    if email_m:
        creds["email"] = email_m.group(1)
    pwd_m = _CRED_PWD_RE.search(text)
    if pwd_m:
        creds["password"] = pwd_m.group(1)
    return creds


# Per-exec-session idempotency guard for the post-execution re-scrape
_rescrape_done: set = set()


def validate_llm_provider(provider_name: str) -> str:
    """Validate and return the LLM provider name."""
    valid_providers = ["anthropic", "openai", "groq", "waymore"]
    if provider_name.lower() not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid LLM provider: {provider_name}. Choose from: {', '.join(valid_providers)}"
        )
    return provider_name.lower()


def validate_api_key(provider: str) -> None:
    """Validate that the API key is configured for the provider."""
    api_key_map = {
        "anthropic": (settings.ANTHROPIC_API_KEY, "your_anthropic_api_key_here"),
        "openai": (settings.OPENAI_API_KEY, "your_openai_api_key_here"),
        "groq": (settings.GROQ_API_KEY, "your_groq_api_key_here"),
        "waymore": (settings.WAYMORE_API_KEY, "your_waymore_api_key_here"),
    }

    api_key, placeholder = api_key_map[provider]
    if not api_key or api_key == placeholder:
        raise HTTPException(
            status_code=500,
            detail=f"{provider.upper()}_API_KEY not configured in .env file"
        )


@router.post("/parse-test-cases")
async def parse_test_cases(
    file: UploadFile = File(...),
    llm_provider: Optional[str] = Query(
        default=None,
        description="LLM provider to use: anthropic, openai, or groq"
    )
):
    """
    Upload Excel file and use JSON Parser Agent to convert it to structured test cases.

    - **file**: Excel file (.xlsx or .xls) containing test case data
    - **llm_provider**: LLM provider to use (anthropic, openai, groq). Defaults to configured default.
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="File must be an Excel file (.xlsx or .xls)")

    provider_name = llm_provider or settings.DEFAULT_LLM_PROVIDER
    provider_name = validate_llm_provider(provider_name)
    validate_api_key(provider_name)

    try:
        provider = LLMProvider(provider_name)
        content = await file.read()
        test_case_service = TestCaseService()
        result = test_case_service.parse_excel_to_test_cases(
            content=content,
            filename=file.filename,
            provider=provider
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@router.post("/parse-json-test-cases")
async def parse_json_test_cases(
    input_data: RawTestCaseInput,
    llm_provider: Optional[str] = Query(
        default="groq",
        description="LLM provider to use: anthropic, openai, or groq"
    ),
    model: Optional[str] = Query(
        default=None,
        description="Model to use (overrides .env config). E.g., gpt-4o, llama-3.1-8b-instant, claude-sonnet-4-20250514"
    ),
    project_name: Optional[str] = Query(
        default="Automation Project",
        description="Project name for the test suite"
    ),
    base_url: Optional[str] = Query(
        default=None,
        description="Base URL for the application (auto-detected if not provided)"
    )
):
    """
    Parse raw test case JSON data into ENHANCED Playwright-optimized structure.

    **Output includes:**
    - `common_selectors`: Reusable selectors for login, navigation, common elements
    - `test_data`: Extracted credentials and sample data
    - `test_cases`: Rich structure with selector hints, assertions, Playwright methods

    **Each step includes:**
    - `instruction`: Original human-readable description
    - `action.type`: goto, fill, click, assert, wait, etc.
    - `action.playwright_method`: page.goto(), page.fill(), expect(), etc.
    - `selector_hints.suggested_selectors`: Multiple Playwright selector strategies
    - `assertions`: Expected assertions with Playwright methods
    """
    provider_name = validate_llm_provider(llm_provider)
    validate_api_key(provider_name)

    # Get model from settings if not provided
    model_map = {
        "openai": settings.OPENAI_MODEL,
        "anthropic": settings.ANTHROPIC_MODEL,
        "groq": settings.GROQ_MODEL
    }
    used_model = model or model_map.get(provider_name, settings.GROQ_MODEL)

    try:
        print("\n" + "="*60)
        print("ENHANCED JSON PARSER - Starting")
        print(f"Provider: {provider_name}, Model: {used_model}")
        print(f"Project: {project_name}")
        print(f"Input data items: {len(input_data.data)}")
        print("="*60 + "\n")

        # Use Enhanced Parser
        provider = LLMProvider(provider_name)
        parser = EnhancedJsonParserAgent(provider=provider, model=used_model)

        # Parse to enhanced structure
        result = parser.parse_to_enhanced_structure(
            raw_data=input_data.data,
            project_name=project_name,
            base_url=base_url
        )

        # Get statistics
        stats = parser.get_statistics(result)

        print("\n" + "="*60)
        print("ENHANCED PARSING COMPLETED")
        print(f"Test cases: {stats['total_test_cases']}")
        print(f"Total steps: {stats['total_steps']}")
        print(f"Total assertions: {stats['total_assertions']}")
        print("="*60 + "\n")

        return {
            "message": "Test cases parsed successfully (Enhanced Format)",
            "llm_provider": provider_name,
            "model": used_model,
            "statistics": stats,
            **result  # Spread the result (project, base_url, common_selectors, test_data, test_cases)
        }

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error processing data: {str(e)}")


# Note: /run-deep-agent, /map-selectors, /generate-script endpoints removed
# LangGraph orchestration was not used - frontend uses direct API calls

# --- Removed endpoints (used deleted graph infrastructure) ---
# /map-selectors - used extract_placeholders, selector_mapper_node, AgentState
# /generate-script - used generate_playwright_script, generate_pytest_script


# REMOVED: /map-selectors endpoint
# This endpoint used deleted graph infrastructure:
# - extract_placeholders (from deleted nodes)
# - selector_mapper_node (deleted)
# - AgentState, TestStatus (deleted state module)
#
# The working alternative is /execute-enhanced which uses
# enhanced_executor.py with dynamic selector resolution.


# REMOVED: /generate-script endpoint
# Used deleted generate_playwright_script, generate_pytest_script functions
# Use /generate-enhanced-script instead (uses app/tools/enhanced_script_generator.py)



@router.post("/execute-script")
async def execute_script(
    input_data: ScriptExecutionInput,
    headless: Optional[bool] = Query(
        default=False,
        description="Run browser in headless mode (False = you can see the browser)"
    ),
    timeout: Optional[int] = Query(
        default=60000,
        description="Execution timeout in milliseconds"
    )
):
    """
    Execute a Playwright script and see the browser in action.

    Pass the generated script from `/generate-script` endpoint.

    **Input format:**
    ```json
    {
        "script": "import pytest\\nfrom playwright.sync_api import Page...",
        "test_id": "TC_01"
    }
    ```

    **Parameters:**
    - `headless=false`: See the browser window (default)
    - `headless=true`: Run in background
    - `timeout`: Max execution time in ms

    **Returns:**
    - Execution status (PASSED/FAILED/ERROR/TIMEOUT)
    - Console output
    - Error messages
    - Screenshots (on failure)
    """
    try:
        print("\n" + "="*60)
        print("SCRIPT EXECUTOR - Starting")
        print(f"Test ID: {input_data.test_id}")
        print(f"Headless: {headless}")
        print(f"Timeout: {timeout}ms")
        print("="*60 + "\n")

        executor = ScriptExecutor(headless=headless, timeout=timeout)
        result = executor.execute_script(input_data.script, input_data.test_id)

        return {
            "message": f"Script execution completed - {result['status']}",
            "execution_result": result
        }

    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error executing script: {str(e)}")


@router.post("/execute-test-cases")
async def execute_test_cases_endpoint(
    input_data: TestCaseExecutionInput,
    headless: Optional[bool] = Query(
        default=False,
        description="Run browser in headless mode"
    )
):
    """
    Execute test cases directly - generates scripts and runs them.

    Pass test cases with mapped selectors (output from `/map-selectors`).

    **Input format:**
    ```json
    {
        "test_cases": [
            {
                "test_id": "TC_01",
                "test_name": "Login Test",
                "base_url": "https://...",
                "actions": [...]
            }
        ]
    }
    ```

    This endpoint will:
    1. Generate Playwright scripts for each test case
    2. Execute each script
    3. Return combined results

    **Parameters:**
    - `headless=false`: See the browser (default)
    - `headless=true`: Run in background
    """
    try:
        test_cases = input_data.test_cases

        if not test_cases:
            raise HTTPException(status_code=400, detail="No test cases provided")

        print("\n" + "="*60)
        print("TEST CASE EXECUTOR - Starting")
        print(f"Total test cases: {len(test_cases)}")
        print(f"Headless: {headless}")
        print("="*60 + "\n")

        # Execute all test cases
        results = execute_test_cases(test_cases, headless=headless)

        return {
            "message": f"Execution completed - {results['passed']}/{results['total']} passed",
            "summary": {
                "total": results["total"],
                "passed": results["passed"],
                "failed": results["failed"],
                "errors": results["errors"]
            },
            "results": results["results"],
            "executed_at": results["executed_at"]
        }

    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error executing test cases: {str(e)}")


@router.post("/execute-dynamic")
async def execute_dynamic_endpoint(
    input_data: TestCaseExecutionInput,
    headless: Optional[bool] = Query(
        default=False,
        description="Run browser in headless mode"
    ),
    timeout: Optional[int] = Query(
        default=30000,
        description="Timeout for each action in milliseconds"
    )
):
    """
    Execute test cases with DYNAMIC runtime selector mapping.

    **Why use this endpoint?**

    Unlike `/execute-test-cases` which requires pre-mapped selectors, this endpoint:
    - Maps selectors AT RUNTIME while navigating through pages
    - Can access protected pages (dashboard, profile, etc.) AFTER logging in
    - Works for ANY website without hardcoded selectors

    **How it works:**
    1. Test starts with placeholder selectors like `{{email_field}}`, `{{login_button}}`
    2. When executing each step, the executor extracts elements from the CURRENT page
    3. Placeholders are mapped to real selectors dynamically
    4. If login is required, selectors for dashboard are mapped AFTER login succeeds

    **Input format:**
    ```json
    {
        "test_cases": [
            {
                "test_id": "TC_01",
                "test_name": "Login Test",
                "base_url": "https://example.com",
                "actions": [
                    {"step": 1, "action": "navigate", "value": "https://example.com/login"},
                    {"step": 2, "action": "type", "selector": "{{email_field}}", "value": "user@test.com"},
                    {"step": 3, "action": "type", "selector": "{{password_field}}", "value": "password123"},
                    {"step": 4, "action": "click", "selector": "{{login_button}}"},
                    {"step": 5, "action": "verify_text", "value": "Dashboard"},
                    {"step": 6, "action": "verify_element", "selector": "{{user_profile}}"}
                ]
            }
        ]
    }
    ```

    **Placeholder naming conventions:**
    - `{{email_field}}` - Email input field
    - `{{password_field}}` - Password input field
    - `{{username_field}}` - Username input field
    - `{{login_button}}` / `{{submit_button}}` - Submit/login button
    - `{{dashboard_heading}}` - Heading text on dashboard
    - `{{toast_message}}` - Toast/alert notifications

    **Parameters:**
    - `headless=false`: See the browser window (default)
    - `headless=true`: Run in background
    - `timeout`: Timeout per action in ms (default: 30000)

    **Returns:**
    - Execution status per test case
    - Step-by-step results
    - Selector mappings discovered during execution
    - Screenshots on failure
    """
    try:
        test_cases = input_data.test_cases

        if not test_cases:
            raise HTTPException(status_code=400, detail="No test cases provided")

        print("\n" + "="*60)
        print("DYNAMIC EXECUTOR - Runtime Selector Mapping")
        print(f"Total test cases: {len(test_cases)}")
        print(f"Headless: {headless}")
        print(f"Timeout: {timeout}ms")
        print("="*60 + "\n")

        # Execute with dynamic selector mapping (runs in thread pool)
        results = await execute_dynamic(test_cases, headless=headless, timeout=timeout)

        # Collect all selector mappings from all test cases
        all_mappings = {}
        for result in results.get("results", []):
            if result.get("selector_mappings"):
                all_mappings.update(result["selector_mappings"])

        return {
            "message": f"Dynamic execution completed - {results['passed']}/{results['total']} passed",
            "mode": "dynamic_runtime_mapping",
            "summary": {
                "total": results["total"],
                "passed": results["passed"],
                "failed": results["failed"]
            },
            "selector_mappings_discovered": all_mappings,
            "results": results["results"],
            "executed_at": results["executed_at"]
        }

    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error in dynamic execution: {str(e)}")


@router.post("/parse-enhanced")
async def parse_enhanced_test_cases(
    input_data: EnhancedTestSuiteInput,
    llm_provider: Optional[str] = Query(
        default="groq",
        description="LLM provider to use: anthropic, openai, or groq"
    ),
    model: Optional[str] = Query(
        default=None,
        description="Model to use (overrides .env config)"
    )
):
    """
    Parse raw test case data into ENHANCED Playwright-optimized structure.

    This is the NEW parser that generates a comprehensive test suite with:
    - **Common selectors**: Reusable selector patterns for login, navigation, etc.
    - **Test data**: Extracted credentials, sample data organized by type
    - **Playwright hints**: Multiple selector strategies per element
    - **Assertion mapping**: Proper Playwright assertion methods
    - **Action types**: Mapped to Playwright methods

    **Input format:**
    ```json
    {
        "data": [
            {
                "T.C.No": "TC_001",
                "Test Case": "Login Test",
                "Test Case Steps": "Step 1: Navigate to URL...",
                "Expected Result": "User should login successfully"
            }
        ],
        "project_name": "My Project",
        "base_url": "https://example.com"
    }
    ```

    **Output includes:**
    - `project`: Project name
    - `base_url`: Base URL for the application
    - `common_selectors`: Reusable selectors organized by category
    - `test_data`: Extracted test data (credentials, sample data)
    - `test_cases`: Array of test cases with rich step structure
    - `statistics`: Breakdown of steps, assertions, action types

    **Each step includes:**
    - `instruction`: Original human-readable description
    - `action`: Type and Playwright method
    - `selector_hints`: Element info with multiple selector suggestions
    - `test_data`: Data values for this step
    - `assertions`: Expected assertions with Playwright methods
    """
    provider_name = validate_llm_provider(llm_provider)
    validate_api_key(provider_name)

    # Get model from settings if not provided
    model_map = {
        "openai": settings.OPENAI_MODEL,
        "anthropic": settings.ANTHROPIC_MODEL,
        "groq": settings.GROQ_MODEL
    }
    used_model = model or model_map.get(provider_name, settings.GROQ_MODEL)

    # Define retry-decorated parsing function
    attempt_counter = {"count": 0}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(ValueError),
        before_sleep=lambda retry_state: print(f"\n[Parse Enhanced] Attempt {retry_state.attempt_number} failed, retrying in 1s...")
    )
    def parse_with_retry():
        attempt_counter["count"] += 1
        attempt = attempt_counter["count"]

        print("\n" + "="*60)
        print(f"ENHANCED JSON PARSER - Attempt {attempt}/3")
        print(f"Provider: {provider_name}, Model: {used_model}")
        print(f"Project: {input_data.project_name}")
        print(f"Input data items: {len(input_data.data)}")
        print("="*60 + "\n")

        # Initialize enhanced parser
        provider = LLMProvider(provider_name)
        parser = EnhancedJsonParserAgent(provider=provider, model=used_model)

        # Parse to enhanced structure
        result = parser.parse_to_enhanced_structure(
            raw_data=input_data.data,
            project_name=input_data.project_name or "Automation Project",
            base_url=input_data.base_url
        )

        return result, parser, attempt

    try:
        result, parser, attempts = parse_with_retry()

        # Get statistics
        stats = parser.get_statistics(result)

        print("\n" + "="*60)
        print("ENHANCED PARSING COMPLETED")
        print(f"Test cases: {stats['total_test_cases']}")
        print(f"Total steps: {stats['total_steps']}")
        print(f"Total assertions: {stats['total_assertions']}")
        if attempts > 1:
            print(f"(Succeeded on attempt {attempts})")
        print("="*60 + "\n")

        return {
            "success": True,
            "message": "Enhanced parsing completed successfully",
            "llm_provider": provider_name,
            "model": used_model,
            "statistics": stats,
            "result": result,
            "attempts": attempts
        }

    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Failed after 3 attempts: {str(e)}")
    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error in enhanced parsing: {str(e)}")


@router.post("/generate-enhanced-script")
async def generate_enhanced_script(
    input_data: dict,
    output_format: Optional[str] = Query(
        default="both",
        description="Output format: 'individual', 'pytest', or 'both'"
    )
):
    """
    Generate Playwright scripts from ENHANCED test suite format.

    Pass the output from `/parse-enhanced` or `/parse-json-test-cases` endpoint.

    **Input format (Enhanced Test Suite):**
    ```json
    {
        "project": "My Project",
        "base_url": "https://example.com",
        "common_selectors": {...},
        "test_data": {...},
        "test_cases": [
            {
                "id": "TC_001",
                "name": "Login Test",
                "steps": [
                    {
                        "step_number": 1,
                        "instruction": "Navigate to login page",
                        "action": {"type": "goto", "playwright_method": "page.goto()"},
                        "selector_hints": {...},
                        "test_data": {"url": "https://..."},
                        "assertions": null
                    }
                ]
            }
        ]
    }
    ```

    **Output formats:**
    - `individual`: Separate script per test case
    - `pytest`: Combined pytest file with all test cases
    - `both`: Both formats

    **Generated code uses Playwright Python syntax:**
    - `page.get_by_label()`, `page.get_by_role()`, `page.locator()`
    - `expect(page).to_have_url()`, `expect(locator).to_be_visible()`
    """
    try:
        # Extract test suite data
        project = input_data.get("project") or input_data.get("result", {}).get("project", "Test Suite")
        common_selectors = input_data.get("common_selectors") or input_data.get("result", {}).get("common_selectors", {})
        test_data = input_data.get("test_data") or input_data.get("result", {}).get("test_data", {})
        test_cases = input_data.get("test_cases") or input_data.get("result", {}).get("test_cases", [])
        base_url = input_data.get("base_url") or input_data.get("result", {}).get("base_url", "")

        if not test_cases:
            raise HTTPException(status_code=400, detail="No test cases found in input")

        print("\n" + "="*60)
        print("ENHANCED SCRIPT GENERATOR")
        print(f"Project: {project}")
        print(f"Test cases: {len(test_cases)}")
        print(f"Output format: {output_format}")
        print("="*60 + "\n")

        response = {
            "message": "Enhanced scripts generated successfully",
            "project": project,
            "total_test_cases": len(test_cases)
        }

        # Generate individual scripts
        if output_format in ["individual", "both"]:
            individual_scripts = []
            for test_case in test_cases:
                test_id = test_case.get("id", "TC_001")
                test_name = test_case.get("name", "Test Case")

                print(f"Generating script for: {test_id} - {test_name}")

                script = generate_enhanced_playwright_script(
                    test_case=test_case,
                    common_selectors=common_selectors,
                    test_data=test_data
                )

                individual_scripts.append({
                    "test_id": test_id,
                    "test_name": test_name,
                    "filename": f"test_{test_id.lower().replace('-', '_').replace(' ', '_')}.py",
                    "script": script
                })

            response["individual_scripts"] = individual_scripts

        # Generate combined pytest script
        if output_format in ["pytest", "both"]:
            print("Generating combined pytest script...")

            test_suite = {
                "project": project,
                "base_url": base_url,
                "common_selectors": common_selectors,
                "test_data": test_data,
                "test_cases": test_cases
            }

            combined_script = generate_enhanced_pytest_script(test_suite)
            response["pytest_script"] = {
                "filename": "test_suite.py",
                "script": combined_script
            }

        print("\n" + "="*60)
        print("Script generation completed!")
        print("="*60 + "\n")

        return response

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error generating enhanced scripts: {str(e)}")


@router.post("/execute-enhanced")
async def execute_enhanced_endpoint(
    input_data: dict,
    headless: Optional[bool] = Query(
        default=False,
        description="Run browser in headless mode"
    ),
    timeout: Optional[int] = Query(
        default=30000,
        description="Timeout for each action in milliseconds"
    )
):
    """
    Execute tests from ENHANCED test suite format with intelligent selector resolution.

    Pass the output from `/parse-enhanced` or `/parse-json-test-cases` endpoint.

    **How it works:**
    1. Takes enhanced test suite with selector_hints for each step
    2. For each action, tries suggested_selectors in order until one works
    3. Falls back to generating selectors from element_name and element_type
    4. Executes assertions using Playwright's expect() API

    **Input format (Enhanced Test Suite):**
    ```json
    {
        "project": "My Project",
        "base_url": "https://example.com",
        "common_selectors": {...},
        "test_data": {
            "default_credentials": {"email": "...", "password": "..."}
        },
        "test_cases": [
            {
                "id": "TC_001",
                "name": "Login Test",
                "steps": [
                    {
                        "step_number": 1,
                        "instruction": "Navigate to login page",
                        "action": {"type": "goto"},
                        "selector_hints": {
                            "element_name": null,
                            "element_type": null,
                            "suggested_selectors": []
                        },
                        "test_data": {"url": "https://example.com/login"},
                        "assertions": null
                    },
                    {
                        "step_number": 2,
                        "instruction": "Enter email",
                        "action": {"type": "fill"},
                        "selector_hints": {
                            "element_name": "Email",
                            "element_type": "input",
                            "suggested_selectors": [
                                "page.getByLabel('Email')",
                                "page.getByPlaceholder('Email')",
                                "page.locator('input[name=\"email\"]')"
                            ]
                        },
                        "test_data": {"email": "user@example.com"},
                        "assertions": null
                    }
                ]
            }
        ]
    }
    ```

    **Supported action types:**
    - `goto`: Navigate to URL
    - `fill`: Fill input field
    - `click`: Click element
    - `assert`: Run assertions (url, text, heading, toast, visible, etc.)
    - `wait`: Wait for element or timeout
    - `select`: Select dropdown option
    - `upload`: Upload file
    - `capture`: Capture text content or URL
    - `screenshot`: Take screenshot

    **Parameters:**
    - `headless=false`: See the browser window (default)
    - `headless=true`: Run in background
    - `timeout`: Timeout per action in ms (default: 30000)

    **Returns:**
    - Execution summary (passed/failed counts)
    - Per-test results with step-by-step status
    - Selectors that were actually used
    - Screenshots on failure
    """
    try:
        # Extract test suite data - handle both direct and nested "result" formats
        if "result" in input_data:
            test_suite = input_data["result"]
        else:
            test_suite = input_data

        # Validate required fields
        test_cases = test_suite.get("test_cases", [])
        if not test_cases:
            raise HTTPException(status_code=400, detail="No test cases found in input")

        print("\n" + "="*60)
        print("ENHANCED EXECUTOR - Starting")
        print(f"Project: {test_suite.get('project', 'Unknown')}")
        print(f"Base URL: {test_suite.get('base_url', 'N/A')}")
        print(f"Test cases: {len(test_cases)}")
        print(f"Headless: {headless}")
        print(f"Timeout: {timeout}ms")
        print("="*60 + "\n")

        # Execute with enhanced executor (runs in thread pool)
        results = await execute_enhanced(test_suite, headless=headless, timeout=timeout)

        return {
            "message": f"Enhanced execution completed - {results['passed']}/{results['total']} passed",
            "project": results.get("project", "Unknown"),
            "base_url": results.get("base_url", ""),
            "summary": {
                "total": results["total"],
                "passed": results["passed"],
                "failed": results["failed"]
            },
            "results": results["results"],
            "executed_at": results["executed_at"]
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error in enhanced execution: {str(e)}")


# ---------------------------------------------------------------------------
# Generate test cases from URL + natural language intent
# ---------------------------------------------------------------------------

from pydantic import BaseModel as PydanticBaseModel

class GenerateFromUrlRequest(PydanticBaseModel):
    url: str
    intent: str
    app_name: Optional[str] = "My App"
    test_email: Optional[str] = "test@example.com"
    test_password: Optional[str] = "password123"


@router.post("/generate-from-url")
async def generate_from_url(
    request: GenerateFromUrlRequest,
    llm_provider: Optional[str] = Query(
        default=None,
        description="LLM provider: groq, openai, or anthropic"
    ),
    model: Optional[str] = Query(
        default=None,
        description="Override model name"
    ),
    headless: Optional[bool] = Query(
        default=True,
        description="Run Playwright in headless mode for crawling"
    ),
):
    """
    Generate a complete EnhancedTestSuite from a URL + natural language intent.

    1. Playwright crawls the URL and extracts all real page elements + selectors
    2. LLM receives the page structure + user intent
    3. LLM generates a complete test suite using real selectors (no guessing)

    **Input:**
    ```json
    {
      "url": "https://myapp.com/login",
      "intent": "Test the login page with valid and invalid credentials",
      "app_name": "MyApp",
      "test_email": "user@test.com",
      "test_password": "secret123"
    }
    ```

    **Returns:** EnhancedTestSuite JSON ready for execution via /execute-enhanced
    """
    from app.agents.test_case_generator import TestCaseGeneratorAgent
    from app.agents.base_agent import LLMProvider as AgentLLMProvider
    from app.tools.selector_extractor import SelectorExtractor

    provider_name = llm_provider or settings.DEFAULT_LLM_PROVIDER
    provider_name = validate_llm_provider(provider_name)
    validate_api_key(provider_name)

    print("\n" + "=" * 60)
    print("GENERATE FROM URL - Starting")
    print(f"URL: {request.url}")
    print(f"Intent: {request.intent[:80]}")
    print(f"Provider: {provider_name}")
    print("=" * 60)

    try:
        # Step 1: Crawl the page
        print("[1/2] Crawling page with Playwright...")
        extractor = SelectorExtractor(headless=headless)
        page_structure = await extractor.extract_selectors(request.url)

        summary = page_structure.get("summary", {})
        print(f"  Found: {summary.get('inputs', 0)} inputs, "
              f"{summary.get('buttons', 0)} buttons, "
              f"{summary.get('headings', 0)} headings, "
              f"{summary.get('links', 0)} links")

        # Step 2: Generate test cases with LLM
        print("[2/2] Generating test cases with AI...")
        provider_enum = AgentLLMProvider(provider_name)
        agent = TestCaseGeneratorAgent(provider=provider_enum, model=model)

        test_suite = agent.generate(
            page_structure=page_structure,
            intent=request.intent,
            app_name=request.app_name or "My App",
            base_url=None,  # auto-derived from URL
            test_email=request.test_email or "test@example.com",
            test_password=request.test_password or "password123",
        )

        tc_count = len(test_suite.get("test_cases", []))
        print(f"  Generated {tc_count} test case(s)")
        print("=" * 60 + "\n")

        return {
            "success": True,
            "message": f"Generated {tc_count} test case(s) from {request.url}",
            "llm_provider": provider_name,
            "model": model or getattr(settings, f"{provider_name.upper()}_MODEL", ""),
            "page_summary": summary,
            "test_suite": test_suite,
        }

    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error generating test cases: {str(e)}")


# ---------------------------------------------------------------------------
# Chatbot Generate from URL — /analyze-url + /chat-generate
# ---------------------------------------------------------------------------

class AnalyzeUrlRequest(PydanticBaseModel):
    url: str
    llm_provider: Optional[str] = None


class ChatGenerateRequest(PydanticBaseModel):
    session_id: str
    user_message: str
    llm_provider: Optional[str] = None
    app_name: Optional[str] = None
    test_email: Optional[str] = None
    test_password: Optional[str] = None


@router.post("/analyze-url")
async def analyze_url(
    request: AnalyzeUrlRequest,
    background_tasks: BackgroundTasks,
    headless: Optional[bool] = Query(default=True),
):
    """
    Step 1 of the chatbot Generate flow.

    Returns a session_id immediately so the frontend can open an SSE connection.
    The scraping + LLM intro run in a background task and are delivered via SSE
    as a 'chat_page_ready' event.
    """
    from app.core.chat_sessions import create_pending_session, finalize_session, append_message
    from app.core.sse_manager import sse_manager

    provider_name = validate_llm_provider(request.llm_provider or settings.DEFAULT_LLM_PROVIDER)
    validate_api_key(provider_name)

    session_id = create_pending_session()
    print(f"\n[analyze-url] session={session_id} | url={request.url} | provider={provider_name}")

    async def _analyze():
        import asyncio as _asyncio
        from app.agents.test_case_generator import TestCaseGeneratorAgent, compact_page_elements
        from app.agents.base_agent import LLMProvider as AgentLLMProvider
        from app.tools.selector_extractor import SelectorExtractor
        try:
            await sse_manager.broadcast(session_id, {
                "type": "chat_thinking",
                "message": "Analyzing page…",
            })
            extractor = SelectorExtractor(headless=headless)
            page_structure = await extractor.extract_selectors(request.url)
            compact = compact_page_elements(page_structure)

            provider_enum = AgentLLMProvider(provider_name)
            agent = TestCaseGeneratorAgent(provider=provider_enum)
            message = await _asyncio.to_thread(agent.generate_intro, compact)

            finalize_session(session_id, page_structure, compact)
            append_message(session_id, "assistant", message)

            print(f"[analyze-url] Session ready: {session_id}")
            await sse_manager.broadcast(session_id, {
                "type": "chat_page_ready",
                "message": message,
                "compact_summary": compact,
                "session_id": session_id,
            })
        except Exception as e:
            import traceback
            print(f"[analyze-url] Error: {traceback.format_exc()}")
            await sse_manager.broadcast(session_id, {
                "type": "chat_error",
                "message": f"Failed to analyse page: {str(e)}",
            })

    background_tasks.add_task(_analyze)
    return {"session_id": session_id, "status": "thinking"}


@router.post("/chat-generate")
async def chat_generate(request: ChatGenerateRequest, background_tasks: BackgroundTasks):
    """
    Step 2+ of the chatbot Generate flow.

    Returns immediately with {status:"thinking"} then streams the result via SSE
    on the session_id channel using chat_thinking → chat_test_suite events.
    """
    import asyncio as _asyncio
    from app.agents.test_case_generator import TestCaseGeneratorAgent
    from app.agents.base_agent import LLMProvider as AgentLLMProvider
    from app.core.chat_sessions import (
        get_session, append_message, set_last_test_suite, get_last_test_suite,
        get_messages, get_credentials, set_credentials,
    )
    from app.core.sse_manager import sse_manager

    provider_name = validate_llm_provider(request.llm_provider or settings.DEFAULT_LLM_PROVIDER)
    validate_api_key(provider_name)

    session = get_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    page_structure = session["page_structure"]
    compact = session["compact"]

    history = get_messages(request.session_id)
    append_message(request.session_id, "user", request.user_message)

    new_creds = _extract_credentials(request.user_message)
    session_creds = get_credentials(request.session_id)
    if new_creds:
        session_creds = {**session_creds, **new_creds}
        set_credentials(request.session_id, session_creds)

    last_suite = get_last_test_suite(request.session_id)
    if last_suite:
        prior_tc_names = ", ".join(
            f"{tc.get('id', '')}: {tc.get('name', '')}"
            for tc in last_suite.get("test_cases", [])
        )
        effective_intent = (
            f"Previously generated test cases: {prior_tc_names}\n\n"
            f"User's follow-up instruction: {request.user_message}\n\n"
            "Apply the follow-up instruction to refine or replace the test cases as requested."
        )
    else:
        effective_intent = request.user_message

    recent_user_lines = [m["content"][:300] for m in history if m["role"] == "user"][-3:]
    if recent_user_lines:
        effective_intent = (
            "Recent conversation context:\n"
            + "\n".join(f"- {l}" for l in recent_user_lines)
            + "\n\n" + effective_intent
        )

    # Snapshot values needed inside the background task
    _session_id = request.session_id
    _app_name = request.app_name or "My App"
    _test_email = session_creds.get("email") or request.test_email or "test@example.com"
    _test_password = session_creds.get("password") or request.test_password or "password123"
    _new_creds = new_creds
    _provider_name = provider_name

    async def _generate():
        try:
            await sse_manager.broadcast(_session_id, {
                "type": "chat_thinking",
                "message": "Generating test cases…",
            })

            from app.services.executor_session_manager import executor_session_manager as _esm_gen
            _browser_alive = _esm_gen.get_session(_session_id) is not None

            provider_enum = AgentLLMProvider(_provider_name)
            agent = TestCaseGeneratorAgent(provider=provider_enum)

            test_suite = await _asyncio.to_thread(
                agent.generate,
                page_structure=page_structure,
                intent=effective_intent,
                app_name=_app_name,
                base_url=None,
                test_email=_test_email,
                test_password=_test_password,
                browser_already_on_page=_browser_alive,
            )

            # Re-sequence TC IDs to continue from the highest existing ID in this session
            import re as _re
            _prior = last_suite or {}
            _max_num = max(
                (int(m.group(0)) for tc in _prior.get("test_cases", [])
                 if (m := _re.search(r'\d+', str(tc.get("id", ""))))),
                default=0,
            )
            for _i, _tc in enumerate(test_suite.get("test_cases", [])):
                _tc["id"] = f"TC_{_max_num + _i + 1:03d}"

            confirm_msg = await _asyncio.to_thread(agent.generate_confirm, test_suite, compact)
            if _new_creds:
                parts = []
                if _new_creds.get("email"):
                    parts.append(f"email: {_new_creds['email']}")
                if _new_creds.get("password"):
                    parts.append(f"password: {_new_creds['password']}")
                ack = f"Got it — I'll use {' and '.join(parts)} for tests requiring login. " if parts else ""
                confirm_msg = ack + confirm_msg

            append_message(_session_id, "assistant", confirm_msg)
            set_last_test_suite(_session_id, test_suite)

            tc_count = len(test_suite.get("test_cases", []))
            print(f"[chat-generate] Generated {tc_count} test case(s) for session {_session_id[:8]}")

            await sse_manager.broadcast(_session_id, {
                "type": "chat_test_suite",
                "message": confirm_msg,
                "test_suite": test_suite,
            })
        except Exception as e:
            import traceback
            print(f"[chat-generate] Error: {traceback.format_exc()}")
            await sse_manager.broadcast(_session_id, {
                "type": "chat_error",
                "message": f"Error generating test cases: {str(e)}",
            })

    background_tasks.add_task(_generate)
    return {"session_id": request.session_id, "status": "thinking"}


# ---------------------------------------------------------------------------
# POST /re-analyze-url — re-scrape page after navigation and update session
# ---------------------------------------------------------------------------

class ReAnalyzeRequest(PydanticBaseModel):
    session_id: str
    url: str
    llm_provider: Optional[str] = None


@router.post("/re-analyze-url")
async def re_analyze_url(
    request: ReAnalyzeRequest,
    headless: Optional[bool] = Query(default=True),
):
    """
    Re-scrape a new page URL after browser navigation.
    Updates the session's page_structure + compact so subsequent
    /chat-generate calls generate tests for the NEW page.
    """
    from app.agents.test_case_generator import TestCaseGeneratorAgent, compact_page_elements
    from app.agents.base_agent import LLMProvider as AgentLLMProvider
    from app.tools.selector_extractor import SelectorExtractor
    from app.core.chat_sessions import get_session, append_message

    session = get_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    provider_name = validate_llm_provider(request.llm_provider or settings.DEFAULT_LLM_PROVIDER)
    validate_api_key(provider_name)

    print(f"\n[re-analyze-url] Scraping {request.url} | session={request.session_id}")

    try:
        # Re-use stored cookies so authenticated pages are scraped correctly
        from app.core.chat_sessions import get_execution_result
        exec_result = get_execution_result(request.session_id) or {}
        auth_state = exec_result.get("final_storage_state")

        extractor = SelectorExtractor(headless=headless)
        page_structure = await extractor.extract_selectors(request.url, storage_state=auth_state)
        compact = compact_page_elements(page_structure)

        # Update session with new page data; clear stale test suite
        session["page_structure"] = page_structure
        session["compact"] = compact
        session["last_test_suite"] = None

        provider_enum = AgentLLMProvider(provider_name)
        agent = TestCaseGeneratorAgent(provider=provider_enum)
        intro = agent.generate_intro(compact)
        message = f"The browser navigated to a new page. Here's what I found:\n\n{intro}"
        append_message(request.session_id, "assistant", message)

        print(f"[re-analyze-url] Done — session updated")
        return {
            "session_id": request.session_id,
            "message": message,
            "compact_summary": compact,
        }

    except Exception as e:
        import traceback
        print(f"[re-analyze-url] Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error re-analyzing URL: {str(e)}")


# ---------------------------------------------------------------------------
# Export EnhancedTestSuite back to Excel format
# ---------------------------------------------------------------------------

@router.post("/export-to-excel")
async def export_to_excel(input_data: dict):
    """
    Convert an EnhancedTestSuite JSON back to Excel format (.xlsx).

    The exported Excel uses the same column format as the input Excel:
    T.C.No | Test Case | Test Case Steps | Expected Result | Input data

    Pass the test_suite from /generate-from-url or /parse-enhanced output.
    """
    from app.services.excel_export_service import export_test_suite_to_excel
    from fastapi.responses import Response

    try:
        # Accept either {test_suite: {...}} wrapper or raw suite
        if "test_suite" in input_data:
            suite = input_data["test_suite"]
        elif "result" in input_data:
            suite = input_data["result"]
        else:
            suite = input_data

        test_cases = suite.get("test_cases", [])
        if not test_cases:
            raise HTTPException(status_code=400, detail="No test cases found in input")

        excel_bytes = export_test_suite_to_excel(suite)
        project_name = suite.get("project", "test_cases").replace(" ", "_")

        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{project_name}.xlsx"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error exporting to Excel: {str(e)}")


# ---------------------------------------------------------------------------
# Intent classification + chatbot helpers
# ---------------------------------------------------------------------------

_EXECUTE_RE = re.compile(
    r"\b(execute|run)\s+\d+"
    r"|\b(execute|run|play|start)\b.*\b(all|test|tests|them|it)\b"
    r"|\b(execute|run)\s+test\s*\d+"
    r"|\bexecute all\b|\brun all\b",
    re.IGNORECASE,
)

_EDIT_RE = re.compile(
    r"\b(edit|change|update|modify|replace|remove|delete)\b.*(step|test case|expected|selector|instruction)"
    r"|\bstep\s+\d+\b"
    r"|\btest case\s+\d+\b",
    re.IGNORECASE,
)

_INFORMATIONAL_RE = re.compile(
    r"^(what|which|how|why|where|when|is|are|does|do|can|could|should|would|tell me|show me|list|explain)\b",
    re.IGNORECASE,
)

_MISSING_INFO_KEYWORDS = re.compile(
    r"\b(test|check|verify|validate)\b.*\b(login|sign.?in|auth|register|signup|form|page|feature)\b",
    re.IGNORECASE,
)


def _classify_intent(message: str) -> str:
    """Classify user message intent: execute | edit | informational | generate"""
    if _EXECUTE_RE.search(message):
        return "execute"
    if _EDIT_RE.search(message):
        return "edit"
    if _INFORMATIONAL_RE.match(message.strip()):
        return "informational"
    return "generate"


# ---------------------------------------------------------------------------
# POST /chat-message — unified LLM-classified intent entry point
# ---------------------------------------------------------------------------

class ChatMessageRequest(PydanticBaseModel):
    session_id: str
    user_message: str
    llm_provider: Optional[str] = None
    headless: bool = True
    timeout: int = 30000


@router.post("/chat-message")
async def chat_message(request: ChatMessageRequest, background_tasks: BackgroundTasks):
    """
    Unified entry point for all chat intents.
    1. Classifies intent via LLM (fast synchronous call with full context).
    2. Routes internally to the same handler logic as the existing endpoints.
    3. Returns immediately; SSE delivers results on the session channel.
    """
    import asyncio as _asyncio
    from app.agents.test_case_generator import TestCaseGeneratorAgent
    from app.agents.base_agent import LLMProvider as AgentLLMProvider
    from app.core.chat_sessions import (
        get_session, append_message, get_last_test_suite, set_last_test_suite,
        get_messages, get_credentials, set_credentials,
    )
    from app.core.sse_manager import sse_manager

    provider_name = validate_llm_provider(request.llm_provider or settings.DEFAULT_LLM_PROVIDER)
    validate_api_key(provider_name)

    session = get_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    last_suite = get_last_test_suite(request.session_id)
    test_cases = last_suite.get("test_cases", []) if last_suite else []
    page_url = session.get("compact", {}).get("url", "")
    history = get_messages(request.session_id)

    # Extract credentials first — always useful regardless of intent
    new_creds = _extract_credentials(request.user_message)
    if new_creds:
        existing = get_credentials(request.session_id)
        set_credentials(request.session_id, {**existing, **new_creds})

    provider_enum = AgentLLMProvider(provider_name)
    agent = TestCaseGeneratorAgent(provider=provider_enum)

    # ── Fast pre-classification — bypass LLM for unambiguous patterns ─────────
    import re as _intent_re
    from app.core.chat_sessions import get_pending_approval as _get_pending
    _msg = request.user_message.strip()
    _pending_results = _get_pending(request.session_id)

    _YES_RE = _intent_re.compile(
        r'^(yes|yeah|yep|yup|sure|ok|okay|confirm|add it|go ahead|do it|proceed)\b',
        _intent_re.IGNORECASE,
    )
    _NO_RE = _intent_re.compile(
        r'^(no|nope|nah|cancel|skip|don\'t|dont|stop)\b',
        _intent_re.IGNORECASE,
    )

    if _pending_results is not None and _YES_RE.match(_msg):
        classification: dict = {
            "intent": "approve",
            "confidence": 1.0,
            "reasoning": "pre-classified: confirming pending approval",
            "metadata": {"approve_targets": "__pending_confirm__"},
        }
    elif _pending_results is not None and _NO_RE.match(_msg):
        classification = {
            "intent": "approve",
            "confidence": 1.0,
            "reasoning": "pre-classified: cancelling pending approval",
            "metadata": {"approve_targets": "__pending_cancel__"},
        }
    else:
        _EXEC_RE = _intent_re.compile(
            r'^(execute|run|play|start|launch)\s*(?:test\s*case\s*|test\s*|tc\s*)?(\d+(?:\s*[,\s]\s*\d+)*|all)\b',
            _intent_re.IGNORECASE,
        )
        _exec_m = _EXEC_RE.match(_msg)
        if _exec_m:
            _raw_targets = _exec_m.group(2).strip().lower()
            _exec_targets: object = "all" if _raw_targets == "all" else [
                int(n) for n in _intent_re.findall(r'\d+', _raw_targets)
            ]
            classification = {
                "intent": "execute",
                "confidence": 1.0,
                "reasoning": "pre-classified: execute keyword + test reference",
                "metadata": {"execute_targets": _exec_targets},
            }
        else:
            # ── Classify intent via LLM (non-blocking) ───────────────────────
            classification = await _asyncio.to_thread(
                agent.classify_intent,
                request.user_message,
                test_cases,
                page_url,
                history[-6:],
            )

    intent = classification.get("intent", "generate")
    metadata = classification.get("metadata", {})
    print(f"[chat-message] intent={intent} confidence={classification.get('confidence')} reason={classification.get('reasoning', '')[:80]}")
    # ────────────────────────────────────────────────────────────────────────

    _session_id = request.session_id

    # ── Execute ──────────────────────────────────────────────────────────────
    if intent == "execute":
        # Delegate to /chat-execute logic by building an equivalent request
        execute_req = ChatExecuteRequest(
            session_id=request.session_id,
            user_message=request.user_message,
            llm_provider=request.llm_provider,
            headless=request.headless,
            timeout=request.timeout,
        )
        return await chat_execute(execute_req, background_tasks)

    # ── Approve ──────────────────────────────────────────────────────────────
    elif intent == "approve":
        from app.core.chat_sessions import (
            get_execution_result, get_pending_approval,
            set_pending_approval, clear_pending_approval,
        )
        targets = metadata.get("approve_targets")
        append_message(_session_id, "user", request.user_message)

        def _result_lines(results: list) -> list[str]:
            lines = []
            for r in results:
                icon = "✅" if r.get("status") == "passed" else "❌"
                desc = (r.get("expected_results") or [None])[0] or f"{len(r.get('steps', []))} steps"
                lines.append(f"- **{r['name']}** {icon} {r.get('status', '').capitalize()} — {desc}")
            return lines

        # ── User confirmed a pending approval ────────────────────────────────
        if targets == "__pending_confirm__":
            confirmed = get_pending_approval(request.session_id) or []
            clear_pending_approval(request.session_id)
            if confirmed:
                success_msg = "✅ Added to Excel successfully!\n" + "\n".join(_result_lines(confirmed))
            else:
                success_msg = "Nothing to add — please run the tests first and then approve."

            async def _do_confirm():
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_approve",
                    "results": confirmed,
                    "message": success_msg,
                })

            background_tasks.add_task(_do_confirm)
            return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

        # ── User cancelled a pending approval ────────────────────────────────
        if targets == "__pending_cancel__":
            clear_pending_approval(request.session_id)
            cancel_msg = "Okay, I won't add anything to Excel. Let me know if you change your mind."
            append_message(_session_id, "assistant", cancel_msg)

            async def _do_cancel():
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": cancel_msg,
                    "intent": "approve",
                })

            background_tasks.add_task(_do_cancel)
            return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

        # ── New approval request — match results and ask for confirmation ─────
        _raw_results = get_execution_result(request.session_id)
        exec_results = _raw_results if isinstance(_raw_results, list) else []

        if not exec_results:
            matched: list = []
        elif targets is None or targets == "all":
            matched = exec_results
        elif isinstance(targets, list) and targets and isinstance(targets[0], int):
            # Look up by TC ID (e.g. 1 → "TC_001") so "approve test case 1" always
            # means TC_001 regardless of execution order
            _target_ids = {f"TC_{n:03d}" for n in targets}
            matched = [r for r in exec_results if r.get("id", "").upper() in _target_ids]
            if not matched:
                # fallback: position-based (1-indexed) for sessions where IDs differ
                matched = [exec_results[n - 1] for n in targets if 0 < n <= len(exec_results)]
        else:
            matched = [
                r for r in exec_results
                if any(str(t).lower() in r.get("name", "").lower() for t in (targets or []))
            ]

        if not matched:
            response_msg = (
                "I don't have any execution results to add. "
                "Please run the tests first, then ask me to approve them."
            )

            async def _approve_none():
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": response_msg,
                    "intent": "approve",
                })

            background_tasks.add_task(_approve_none)
        else:
            # Store pending and ask user to confirm
            set_pending_approval(_session_id, matched)
            confirm_ask = (
                "I'd like to add the following to Excel:\n"
                + "\n".join(_result_lines(matched))
                + "\n\nShall I go ahead? *(yes / no)*"
            )
            append_message(_session_id, "assistant", confirm_ask)

            async def _approve_ask():
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": confirm_ask,
                    "intent": "approve",
                })

            background_tasks.add_task(_approve_ask)

        return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

    # ── Informational ─────────────────────────────────────────────────────────
    elif intent == "informational":
        compact = session["compact"]
        append_message(_session_id, "user", request.user_message)
        _user_message = request.user_message

        async def _info():
            try:
                await sse_manager.broadcast(_session_id, {"type": "chat_thinking", "message": "Thinking…"})
                answer = await _asyncio.to_thread(agent.answer_question, compact, _user_message, history)
                append_message(_session_id, "assistant", answer)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": answer,
                    "intent": "informational",
                })
            except Exception as e:
                import traceback
                print(f"[chat-message/informational] Error: {traceback.format_exc()}")
                await sse_manager.broadcast(_session_id, {"type": "chat_error", "message": f"Error: {str(e)}"})

        background_tasks.add_task(_info)
        return {"session_id": _session_id, "status": "thinking", "intent": "informational"}

    # ── Edit ──────────────────────────────────────────────────────────────────
    elif intent == "edit":
        if not last_suite:
            raise HTTPException(status_code=400, detail="No test cases to edit. Please generate test cases first.")
        compact = session["compact"]
        append_message(_session_id, "user", request.user_message)
        _user_message = request.user_message

        async def _edit():
            try:
                await sse_manager.broadcast(_session_id, {"type": "chat_thinking", "message": "Applying edits…"})
                updated = await _asyncio.to_thread(agent.generate_edit, last_suite, _user_message, history)
                set_last_test_suite(_session_id, updated)
                edit_msg = await _asyncio.to_thread(agent.generate_confirm, updated, compact)
                append_message(_session_id, "assistant", edit_msg)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_test_suite",
                    "message": edit_msg,
                    "test_suite": updated,
                    "intent": "edit",
                })
            except Exception as e:
                import traceback
                print(f"[chat-message/edit] Error: {traceback.format_exc()}")
                await sse_manager.broadcast(_session_id, {"type": "chat_error", "message": f"Error: {str(e)}"})

        background_tasks.add_task(_edit)
        return {"session_id": _session_id, "status": "thinking", "intent": "edit"}

    # ── Clarify ───────────────────────────────────────────────────────────────
    elif intent == "clarify":
        # Use the LLM's context-aware clarify_message; build a dynamic fallback if absent
        clarify_msg = classification.get("clarify_message") or ""
        if not clarify_msg.strip():
            _tc_names = [tc.get("name", f"Test {i+1}") for i, tc in enumerate(test_cases)]
            _tc_hint = (
                f" I can see you have {len(_tc_names)} test case(s): "
                + ", ".join(f"**{n}**" for n in _tc_names[:5])
                + ("..." if len(_tc_names) > 5 else "") + "."
            ) if _tc_names else ""
            clarify_msg = (
                f"I'm not sure what you'd like to do with \"{request.user_message}\"."
                f"{_tc_hint} Did you mean to:\n"
                "- **Run tests** — say *\"execute all\"* or *\"run test 1\"*\n"
                "- **Generate new test cases** — say *\"generate tests for checkout\"*\n"
                "- **Edit a test** — say *\"change step 2 to click submit\"*\n"
                "- **Save results to Excel** — say *\"approve test case 1\"*\n\n"
                "What would you like to do?"
            )
        append_message(_session_id, "user", request.user_message)
        append_message(_session_id, "assistant", clarify_msg)

        async def _clarify():
            await sse_manager.broadcast(_session_id, {
                "type": "chat_response",
                "message": clarify_msg,
                "intent": "clarify",
            })

        background_tasks.add_task(_clarify)
        return {"session_id": _session_id, "status": "thinking", "intent": "clarify"}

    # ── Generate (default) ────────────────────────────────────────────────────
    else:
        page_structure = session["page_structure"]
        compact = session["compact"]
        session_creds = get_credentials(_session_id)

        if last_suite:
            prior_tc_names = ", ".join(
                f"{tc.get('id', '')}: {tc.get('name', '')}"
                for tc in last_suite.get("test_cases", [])
            )
            effective_intent = (
                f"Previously generated test cases: {prior_tc_names}\n\n"
                f"User's follow-up instruction: {request.user_message}\n\n"
                "Apply the follow-up instruction to refine or replace the test cases as requested."
            )
        else:
            effective_intent = request.user_message

        recent_user_lines = [m["content"][:300] for m in history if m["role"] == "user"][-3:]
        if recent_user_lines:
            effective_intent = (
                "Recent conversation context:\n"
                + "\n".join(f"- {l}" for l in recent_user_lines)
                + "\n\n" + effective_intent
            )

        append_message(_session_id, "user", request.user_message)
        _test_email = session_creds.get("email") or "test@example.com"
        _test_password = session_creds.get("password") or "password123"
        _new_creds = new_creds

        async def _generate():
            try:
                await sse_manager.broadcast(_session_id, {"type": "chat_thinking", "message": "Generating test cases…"})

                from app.services.executor_session_manager import executor_session_manager as _esm_gen
                _browser_alive = _esm_gen.get_session(_session_id) is not None

                test_suite = await _asyncio.to_thread(
                    agent.generate,
                    page_structure=page_structure,
                    intent=effective_intent,
                    app_name="My App",
                    base_url=None,
                    test_email=_test_email,
                    test_password=_test_password,
                    browser_already_on_page=_browser_alive,
                )

                # Re-sequence TC IDs to continue from the highest existing ID in this session
                import re as _re
                _prior = last_suite or {}
                _max_num = max(
                    (int(m.group(0)) for tc in _prior.get("test_cases", [])
                     if (m := _re.search(r'\d+', str(tc.get("id", ""))))),
                    default=0,
                )
                for _i, _tc in enumerate(test_suite.get("test_cases", [])):
                    _tc["id"] = f"TC_{_max_num + _i + 1:03d}"

                confirm_msg = await _asyncio.to_thread(agent.generate_confirm, test_suite, compact)
                if _new_creds:
                    parts = []
                    if _new_creds.get("email"):
                        parts.append(f"email: {_new_creds['email']}")
                    if _new_creds.get("password"):
                        parts.append(f"password: {_new_creds['password']}")
                    ack = f"Got it — I'll use {' and '.join(parts)} for tests requiring login. " if parts else ""
                    confirm_msg = ack + confirm_msg

                append_message(_session_id, "assistant", confirm_msg)
                set_last_test_suite(_session_id, test_suite)

                tc_count = len(test_suite.get("test_cases", []))
                print(f"[chat-message/generate] Generated {tc_count} test case(s) for session {_session_id[:8]}")

                await sse_manager.broadcast(_session_id, {
                    "type": "chat_test_suite",
                    "message": confirm_msg,
                    "test_suite": test_suite,
                })
            except Exception as e:
                import traceback
                print(f"[chat-message/generate] Error: {traceback.format_exc()}")
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_error",
                    "message": f"Error generating test cases: {str(e)}",
                })

        background_tasks.add_task(_generate)
        return {"session_id": _session_id, "status": "thinking", "intent": "generate"}


def _parse_tc_selection(message: str, test_cases: list) -> list:
    """
    Parse which test cases the user wants to run.
    "execute all" / "run all" → all test cases
    "run test 1" → test_cases[0]
    "execute test 1, 3" → test_cases[0], test_cases[2]
    "run tests 1 to 3" → test_cases[0:3]
    """
    if re.search(r'\ball\b', message, re.IGNORECASE) or not re.search(r'\d+', message):
        return test_cases
    # Range: "1 to 3" or "1-3"
    range_match = re.search(r'(\d+)\s+to\s+(\d+)', message, re.IGNORECASE)
    if not range_match:
        range_match = re.search(r'(\d+)\s*-\s*(\d+)', message)
    if range_match:
        start = int(range_match.group(1)) - 1
        end = int(range_match.group(2))
        return test_cases[max(0, start):min(end, len(test_cases))]
    # Individual numbers
    numbers = re.findall(r'\d+', message)
    indices = [int(n) - 1 for n in numbers]
    selected = [test_cases[i] for i in indices if 0 <= i < len(test_cases)]
    return selected if selected else test_cases


# ---------------------------------------------------------------------------
# POST /chat-informational — answer a question without generating test cases
# ---------------------------------------------------------------------------

class ChatInfoRequest(PydanticBaseModel):
    session_id: str
    user_message: str
    llm_provider: Optional[str] = None


@router.post("/chat-informational")
async def chat_informational(request: ChatInfoRequest, background_tasks: BackgroundTasks):
    """
    Answer an informational question about the analysed page without generating test cases.

    Returns immediately with {status:"thinking"} then streams the answer via SSE
    on the session_id channel using chat_thinking → chat_response events.
    """
    import asyncio as _asyncio
    from app.agents.test_case_generator import TestCaseGeneratorAgent
    from app.agents.base_agent import LLMProvider as AgentLLMProvider
    from app.core.chat_sessions import get_session, append_message, get_messages
    from app.core.sse_manager import sse_manager

    provider_name = validate_llm_provider(request.llm_provider or settings.DEFAULT_LLM_PROVIDER)
    validate_api_key(provider_name)

    session = get_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    compact = session["compact"]
    history = get_messages(request.session_id)
    append_message(request.session_id, "user", request.user_message)

    _session_id = request.session_id
    _user_message = request.user_message
    _provider_name = provider_name

    async def _answer():
        try:
            await sse_manager.broadcast(_session_id, {
                "type": "chat_thinking",
                "message": "Thinking…",
            })

            provider_enum = AgentLLMProvider(_provider_name)
            agent = TestCaseGeneratorAgent(provider=provider_enum)
            answer = await _asyncio.to_thread(
                agent.answer_question, compact, _user_message, history
            )
            append_message(_session_id, "assistant", answer)

            await sse_manager.broadcast(_session_id, {
                "type": "chat_response",
                "message": answer,
                "intent": "informational",
            })
        except Exception as e:
            import traceback
            print(f"[chat-informational] Error: {traceback.format_exc()}")
            await sse_manager.broadcast(_session_id, {
                "type": "chat_error",
                "message": f"Error: {str(e)}",
            })

    background_tasks.add_task(_answer)
    return {"session_id": request.session_id, "status": "thinking"}


# ---------------------------------------------------------------------------
# POST /chat-execute — execute selected test cases via deep agent + SSE
# ---------------------------------------------------------------------------

# Keys that identify non-credential fill values (LLM-generated values are fine)
_NON_CRED_FILL_KEYS = {"text", "value", "input", "content", "data", "message", "search", "query"}

# Substring patterns that identify a field as needing real user credentials
_EMAIL_FIELD_HINTS = ("email", "e-mail", "e mail", "user name", "username", "login name")
_PASSWORD_FIELD_HINTS = ("password", "passwd", "pass ")


def _field_needs_credential(element_name: str, step_td: dict) -> tuple:
    """
    Returns (True, "email"|"password"|"username") if this fill step needs a
    real user credential, otherwise (False, None).

    Credential fields must come from the user (session credentials), NOT from
    LLM-generated placeholder values such as test@example.com / password123.
    """
    name = (element_name or "").lower()
    # Detect by step test_data key
    if "email" in step_td:
        return True, "email"
    if "password" in step_td:
        return True, "password"
    if "username" in step_td:
        return True, "username"
    # Detect by element name
    if any(h in name for h in _EMAIL_FIELD_HINTS):
        return True, "email"
    if any(h in name for h in _PASSWORD_FIELD_HINTS):
        return True, "password"
    if "username" in name:
        return True, "username"
    return False, None


def validate_test_suite_data(suite: dict, credentials: dict) -> dict:
    """
    Scan the test suite for fill steps that require real credentials but none
    have been provided by the user yet.

    KEY RULE: For email / password / username fields the LLM always inserts
    placeholder values (test@example.com, password123, …).  Those must NOT be
    treated as "the user provided this" — only values present in `credentials`
    (extracted from the user's chat messages) count as real.

    Non-credential fill steps (search text, comment body, etc.) pass through
    unconditionally — their LLM-generated test_data values are real test data.

    Returns {"valid": bool, "missing_fields": [{"step_id", "step_number",
    "field_name", "action", "instruction"}]}.
    """
    missing = []
    # Deduplicate: once we know "email" is missing don't report it again from TC_002
    already_reported: set = set()

    for tc in suite.get("test_cases", []):
        tc_id = tc.get("id", "")
        for step in tc.get("steps", []):
            action_type = (step.get("action") or {}).get("type", "")
            if action_type not in ("fill", "select"):
                continue

            step_td = step.get("test_data") or {}

            # Context/table-driven steps resolve their value at runtime
            if step_td.get("source") in ("table", "context"):
                continue

            element_name = (step.get("selector_hints") or {}).get("element_name") or ""
            is_cred, cred_key = _field_needs_credential(element_name, step_td)

            if is_cred:
                # For credential fields, only real session credentials count.
                # Reject LLM-generated placeholders entirely.
                if credentials.get(cred_key):
                    continue  # user already supplied this credential → OK
                # Also accept "username" in credentials for an email field
                if cred_key == "email" and credentials.get("username"):
                    continue
                if cred_key in already_reported:
                    continue  # already asking for this — don't duplicate
                already_reported.add(cred_key)
                field_label = element_name or cred_key.capitalize()
                missing.append({
                    "step_id": tc_id,
                    "step_number": step.get("step_number", "?"),
                    "field_name": field_label,
                    "action": action_type,
                    "instruction": step.get("instruction", ""),
                })
            else:
                # Non-credential field: any non-empty string value in step_td is fine.
                has_value = any(
                    isinstance(step_td.get(k), str) and step_td.get(k)
                    for k in step_td
                    if k not in {"source", "column_name"}
                )
                if not has_value:
                    field_label = element_name or f"field at step {step.get('step_number', '?')}"
                    missing.append({
                        "step_id": tc_id,
                        "step_number": step.get("step_number", "?"),
                        "field_name": field_label,
                        "action": action_type,
                        "instruction": step.get("instruction", ""),
                    })

    return {"valid": len(missing) == 0, "missing_fields": missing}


class ChatExecuteRequest(PydanticBaseModel):
    session_id: str
    user_message: str
    llm_provider: Optional[str] = None
    headless: bool = True
    timeout: int = 30000
    max_retries: int = 1
    input_data: Optional[dict] = None  # user-supplied values after a needs_input prompt


class ChatExecuteResponse(PydanticBaseModel):
    session_id: str
    exec_session_id: str
    message: str
    selected_tests: List[str]


@router.post("/chat-execute")
async def chat_execute(request: ChatExecuteRequest, background_tasks: BackgroundTasks):
    """
    Execute selected test cases from the chatbot session via the deep agent engine.
    Returns immediately with exec_session_id; frontend subscribes to SSE for live updates.
    """
    from app.core.chat_sessions import (
        get_session, append_message, get_last_test_suite,
        set_execution_session, set_execution_result, get_execution_result,
    )
    from app.core.sse_manager import sse_manager

    provider_name = validate_llm_provider(request.llm_provider or settings.DEFAULT_LLM_PROVIDER)
    validate_api_key(provider_name)

    session = get_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    last_suite = get_last_test_suite(request.session_id)
    if not last_suite:
        raise HTTPException(status_code=400, detail="No test cases available. Please generate test cases first.")

    all_tcs = last_suite.get("test_cases", [])
    if not all_tcs:
        raise HTTPException(status_code=400, detail="The test suite has no test cases to execute.")

    selected = _parse_tc_selection(request.user_message, all_tcs)
    if not selected:
        selected = all_tcs

    exec_session_id = str(uuid.uuid4())
    set_execution_session(request.session_id, exec_session_id)
    append_message(request.session_id, "user", request.user_message)

    count = len(selected)
    start_msg = f"Running {count} test case{'s' if count != 1 else ''}... Watch the browser view on the right."

    # Build a partial suite with only the selected test cases
    partial_suite = {**last_suite, "test_cases": selected}

    # Inject session credentials into test_data so executor uses them
    from app.core.chat_sessions import get_credentials, set_credentials
    session_creds = get_credentials(request.session_id)

    # If the user just provided input_data (after a needs_input prompt), persist and merge it
    if request.input_data:
        session_creds = {**session_creds, **request.input_data}
        set_credentials(request.session_id, session_creds)

    if session_creds:
        merged_data = {**partial_suite.get("test_data", {}), **session_creds}
        partial_suite = {**partial_suite, "test_data": merged_data}

    # Pre-flight check: ask user for missing test data before starting execution.
    # Skip when input_data was already supplied (user just answered the prompt).
    if not request.input_data:
        validation = validate_test_suite_data(partial_suite, session_creds)
        if not validation["valid"]:
            fields_text = "\n".join(
                f"- **{f['field_name']}** *(step {f['step_number']})*"
                for f in validation["missing_fields"]
            )
            example_text = "  ".join(
                f"{f['field_name'].lower()}: your_{f['field_name'].lower()}"
                for f in validation["missing_fields"]
            )
            needs_msg = (
                "Before I run these tests, I need the following values:\n\n"
                f"{fields_text}\n\n"
                f"Reply with the values, for example:\n"
                f"> {example_text}"
            )
            append_message(request.session_id, "assistant", needs_msg)
            return {
                "status": "needs_input",
                "session_id": request.session_id,
                "message": needs_msg,
                "missing_fields": validation["missing_fields"],
            }

    chat_session_id = request.session_id

    async def _run_and_notify():
        import queue as _queue
        import asyncio as _asyncio
        from app.services.executor_session_manager import executor_session_manager as _esm
        from app.tools.enhanced_executor import DEFAULT_ACTION_TIMEOUT as _DEFAULT_TIMEOUT
        from urllib.parse import urlparse as _urlparse

        _base_url = partial_suite.get("base_url", "")

        def _meaningful_navigation(url_a: str, url_b: str) -> bool:
            """True when the URLs differ in host or path (ignores query/fragment)."""
            try:
                a, b = _urlparse(url_a), _urlparse(url_b)
                return a.netloc != b.netloc or a.path.rstrip("/") != b.path.rstrip("/")
            except Exception:
                return url_a != url_b

        # The first URL the browser visits is the test's setup navigation (e.g. /login).
        # We must never re-scrape it — only scrape pages the test navigates TO afterwards.
        # Using a dict so the nested _forward_updates closure can mutate it.
        _nav_state: dict = {"initial_path": None}

        def _nav_path(url: str) -> str:
            """Normalised netloc+path for same-page detection (ignores query/fragment)."""
            try:
                p = _urlparse(url)
                return (p.netloc + p.path).rstrip("/")
            except Exception:
                return url

        # Track URLs already being/been scraped so we never double-scrape
        _scraped_nav_urls: set = set()
        # Scrapes detected during execution — deferred so they run AFTER chat_execution_done
        _pending_scrapes: list = []   # [(nav_url, storage_state), ...]
        _scrape_tasks: list = []      # asyncio Tasks (started after execution completes)

        async def _do_page_scrape(nav_url: str, storage_state):
            """Re-scrape a navigated page and push the AI summary to the chatbot."""
            try:
                from app.tools.selector_extractor import SelectorExtractor as _SE
                from app.agents.test_case_generator import (
                    TestCaseGeneratorAgent as _TGA,
                    compact_page_elements as _cpe,
                )
                from app.agents.base_agent import LLMProvider as _LP
                from app.core.chat_sessions import get_session as _gs, append_message as _am

                await sse_manager.broadcast(exec_session_id, {
                    "type": "page_analysis_start",
                    "url": nav_url,
                    "message": "Browser navigated to a new page — analyzing it for you…",
                })
                extractor = _SE(headless=True)
                new_page_structure = await extractor.extract_selectors(nav_url, storage_state=storage_state)
                new_compact = _cpe(new_page_structure)

                _session = _gs(chat_session_id)
                if _session:
                    _session["page_structure"] = new_page_structure
                    _session["compact"] = new_compact
                    _session["last_test_suite"] = None

                _provider = _LP(provider_name)
                _agent = _TGA(provider=_provider)
                nav_intro = await _asyncio.to_thread(_agent.generate_intro, new_compact)
                nav_msg = (
                    "The browser navigated to a new page after execution. "
                    f"Here's what I found:\n\n{nav_intro}"
                )
                _am(chat_session_id, "assistant", nav_msg)
                await sse_manager.broadcast(exec_session_id, {
                    "type": "page_analysis_done",
                    "url": nav_url,
                    "message": nav_msg,
                })
                print(f"[chat-execute] Re-analysis complete for {nav_url}")
            except Exception as _nav_err:
                print(f"[chat-execute] Re-analysis failed for {nav_url}: {_nav_err}")

        # Queue for live screenshot/navigation/step events from the executor thread
        update_queue = _queue.Queue()
        _fwd_state = {"running": True}

        async def _forward_updates():
            """Drain update_queue and relay events to SSE."""
            while _fwd_state["running"] or not update_queue.empty():
                try:
                    msg = update_queue.get_nowait()
                    msg_type = msg.get("type")
                    if msg_type == "screenshot":
                        await sse_manager.broadcast(exec_session_id, {
                            "type": "exec_screenshot",
                            "image_b64": msg.get("image", ""),
                            "url": msg.get("url", ""),
                        })
                    elif msg_type == "page_navigated":
                        nav_url = msg.get("url", "")
                        await sse_manager.broadcast(exec_session_id, {
                            "type": "page_navigated",
                            "url": nav_url,
                            "elements_summary": msg.get("elements_summary", ""),
                            "image_b64": msg.get("image", ""),
                        })
                        # Collect genuinely new post-login navigations for deferred
                        # re-scraping.  We intentionally do NOT start the scrape here
                        # because _do_page_scrape broadcasts page_analysis_start, which
                        # would appear in the chat before chat_execution_done.
                        # The scrape tasks are created after execution completes.
                        nav_ss = msg.get("storage_state")
                        if nav_url and nav_ss and _meaningful_navigation(nav_url, _base_url):
                            cur_path = _nav_path(nav_url)
                            if _nav_state["initial_path"] is None:
                                # First navigation — test setup page, skip
                                _nav_state["initial_path"] = cur_path
                            elif (cur_path != _nav_state["initial_path"]
                                    and nav_url not in _scraped_nav_urls):
                                # Defer: start scraping after chat_execution_done
                                _scraped_nav_urls.add(nav_url)
                                _pending_scrapes.append((nav_url, nav_ss))
                    elif msg_type == "test_started":
                        await sse_manager.broadcast(exec_session_id, {
                            "type": "step_update",
                            "test_id": msg.get("test_id", ""),
                            "test_name": msg.get("test_name", ""),
                            "step_number": 0,
                            "instruction": msg.get("message", "Starting…"),
                            "status": "running",
                        })
                    elif msg_type == "test_completed":
                        await sse_manager.broadcast(exec_session_id, {
                            "type": "test_update",
                            "test_id": msg.get("test_id", ""),
                            "test_name": msg.get("test_name", ""),
                            "status": "passed" if msg.get("status") == "PASSED" else "failed",
                        })
                except Exception:
                    await _asyncio.sleep(0.05)

        fwd_task = _asyncio.create_task(_forward_updates())

        try:
            await sse_manager.broadcast(exec_session_id, {
                "type": "agent_phase",
                "phase": "executing",
                "message": f"Starting execution of {count} test case(s)...",
            })

            # Get or create a persistent executor session for this chat session.
            # The browser stays open between "Execute" clicks — no relaunch overhead.
            _exec_session = _esm.get_or_create_session(
                chat_session_id, headless=bool(request.headless)
            )
            _timeout = request.timeout or _DEFAULT_TIMEOUT

            # Run ALL selected test cases on the persistent browser thread.
            # asyncio.to_thread keeps the event loop free so SSE screenshots
            # can flow while the executor is running.
            full_result = await _asyncio.to_thread(
                _exec_session.run_test_suite,
                partial_suite,
                update_queue,
                _timeout,
                None,  # signal_file — not used in chat-execute
            )

            all_results = full_result.get("results", [])
            total_passed = full_result.get("passed", 0)
            total_failed = full_result.get("failed", 0)

            summary_msg = f"Execution complete! {total_passed}/{count} test{'s' if count != 1 else ''} passed."
            if total_failed > 0:
                summary_msg += f" {total_failed} failed."

            # Build formatted tc_results once — reused for SSE payload and session storage
            tc_results_data = [
                {
                    "id": tc.get("id"),
                    "name": tc.get("name"),
                    "status": "passed" if r.get("status") == "PASSED" else "failed",
                    "steps": tc.get("steps", []),
                    "expected_results": tc.get("expected_results", []),
                    "test_data": partial_suite.get("test_data", {}),
                    "error": r.get("error"),
                }
                for tc, r in zip(selected, all_results)
            ]
            # Merge into accumulated results keyed by TC ID so previous runs aren't lost
            _existing_raw = get_execution_result(chat_session_id)
            _existing = _existing_raw if isinstance(_existing_raw, list) else []
            _by_id = {r["id"]: r for r in _existing if r.get("id")}
            for _r in tc_results_data:
                _by_id[_r["id"]] = _r  # upsert: latest run wins for same ID
            set_execution_result(chat_session_id, list(_by_id.values()))

            await sse_manager.broadcast(exec_session_id, {
                "type": "chat_execution_done",
                "chat_session_id": chat_session_id,
                "message": summary_msg,
                "summary": {"total": count, "passed": total_passed, "failed": total_failed},
                "final_url": full_result.get("final_url", ""),
                "tc_results": tc_results_data,
            })

            # ── Start deferred navigation scrapes (collected during execution) ──
            # These are started HERE so page_analysis_start only appears in the
            # chat AFTER the execution summary (chat_execution_done) is visible.
            for _nav_url, _nav_ss in _pending_scrapes:
                _rescrape_done.add(exec_session_id)
                print(f"[chat-execute] Deferred re-scrape → {_nav_url}")
                _scrape_tasks.append(
                    _asyncio.create_task(_do_page_scrape(_nav_url, _nav_ss))
                )

            # ── Post-execution fallback re-scrape ─────────────────────────────
            # Runs only when the final_url was NOT captured during execution
            # (e.g. navigation happened after the last measured step).
            final_url = full_result.get("final_url", "")
            if (
                final_url
                and total_passed > 0
                and _meaningful_navigation(final_url, _base_url)
                and not final_url.startswith("about:")
                and final_url not in _scraped_nav_urls
                and exec_session_id not in _rescrape_done
            ):
                _rescrape_done.add(exec_session_id)
                _scraped_nav_urls.add(final_url)
                auth_state = full_result.get("final_storage_state")
                print(f"[chat-execute] Post-execution fallback re-scrape → {final_url}")
                t = _asyncio.create_task(_do_page_scrape(final_url, auth_state))
                _scrape_tasks.append(t)

        except Exception as e:
            import traceback
            print(f"[chat-execute] Background error: {traceback.format_exc()}")
            await sse_manager.broadcast(exec_session_id, {
                "type": "error",
                "message": f"Execution error: {str(e)}",
            })
        finally:
            _fwd_state["running"] = False
            await _asyncio.sleep(0.3)  # drain remaining queue events
            fwd_task.cancel()
            # Wait for any concurrent re-scrape tasks so the summary reaches the
            # frontend before exec_session_complete closes the SSE connection.
            for _t in _scrape_tasks:
                if not _t.done():
                    try:
                        await _asyncio.wait_for(_t, timeout=120.0)
                    except Exception:
                        pass
            _rescrape_done.discard(exec_session_id)
            await sse_manager.broadcast(exec_session_id, {"type": "exec_session_complete"})

    background_tasks.add_task(_run_and_notify)

    selected_ids = [tc.get("id", f"TC_{i+1}") for i, tc in enumerate(selected)]

    print(f"[chat-execute] session={request.session_id} exec_session={exec_session_id} tests={selected_ids}")

    return {
        "status": "started",
        "session_id": request.session_id,
        "exec_session_id": exec_session_id,
        "message": start_msg,
        "selected_tests": selected_ids,
    }


# ---------------------------------------------------------------------------
# POST /chat-edit — surgical LLM edit of test cases
# ---------------------------------------------------------------------------

class ChatEditRequest(PydanticBaseModel):
    session_id: str
    user_message: str
    llm_provider: Optional[str] = None


@router.post("/chat-edit")
async def chat_edit(request: ChatEditRequest, background_tasks: BackgroundTasks):
    """
    Apply a surgical edit to the stored test suite based on user instruction.

    Returns immediately with {status:"thinking"} then streams the result via SSE
    on the session_id channel using chat_thinking → chat_test_suite events.
    """
    import asyncio as _asyncio
    from app.agents.test_case_generator import TestCaseGeneratorAgent
    from app.agents.base_agent import LLMProvider as AgentLLMProvider
    from app.core.chat_sessions import (
        get_session, append_message, get_last_test_suite, set_last_test_suite, get_messages,
    )
    from app.core.sse_manager import sse_manager

    provider_name = validate_llm_provider(request.llm_provider or settings.DEFAULT_LLM_PROVIDER)
    validate_api_key(provider_name)

    session = get_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    last_suite = get_last_test_suite(request.session_id)
    if not last_suite:
        raise HTTPException(status_code=400, detail="No test cases to edit. Please generate test cases first.")

    compact = session["compact"]
    history = get_messages(request.session_id)
    append_message(request.session_id, "user", request.user_message)

    _session_id = request.session_id
    _user_message = request.user_message
    _provider_name = provider_name

    async def _edit():
        try:
            await sse_manager.broadcast(_session_id, {
                "type": "chat_thinking",
                "message": "Applying edits…",
            })

            provider_enum = AgentLLMProvider(_provider_name)
            agent = TestCaseGeneratorAgent(provider=provider_enum)
            updated_suite = await _asyncio.to_thread(
                agent.generate_edit, last_suite, _user_message, history
            )
            set_last_test_suite(_session_id, updated_suite)

            tc_count = len(updated_suite.get("test_cases", []))
            confirm_msg = await _asyncio.to_thread(agent.generate_confirm, updated_suite, compact)
            edit_msg = f"Done! I've updated the test suite. {confirm_msg}"
            append_message(_session_id, "assistant", edit_msg)

            print(f"[chat-edit] session={_session_id[:8]} updated {tc_count} test case(s)")

            await sse_manager.broadcast(_session_id, {
                "type": "chat_test_suite",
                "message": edit_msg,
                "test_suite": updated_suite,
                "intent": "edit",
            })
        except Exception as e:
            import traceback
            print(f"[chat-edit] Error: {traceback.format_exc()}")
            # Broadcast the original suite unchanged on LLM failure
            err_msg = "I couldn't apply that edit. Please try rephrasing your instruction."
            await sse_manager.broadcast(_session_id, {
                "type": "chat_test_suite",
                "message": err_msg,
                "test_suite": last_suite,
                "intent": "edit",
            })

    background_tasks.add_task(_edit)
    return {"session_id": request.session_id, "status": "thinking"}
