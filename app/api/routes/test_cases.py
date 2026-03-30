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
    """Fast regex-based credential extraction (fallback)."""
    creds: dict = {}
    email_m = _CRED_EMAIL_RE.search(text)
    if email_m:
        creds["email"] = email_m.group(1)
    pwd_m = _CRED_PWD_RE.search(text)
    if pwd_m:
        creds["password"] = pwd_m.group(1)
    return creds


def _extract_credentials_semantic(text: str, agent) -> dict:
    """
    Semantically extract email/password using LLM.
    Handles any natural language format the user may provide.
    Falls back to regex if LLM fails or returns nothing.
    """
    import json as _j
    prompt = (
        "Extract the login credentials (email address and password) from the message below.\n"
        "Return ONLY a JSON object with keys 'email' and 'password'.\n"
        "Use null for any field not found. No explanation, no extra text.\n\n"
        f"Message: \"{text}\"\n\n"
        "JSON:"
    )
    try:
        raw = agent.call_llm(prompt).strip()
        # Strip markdown code fences if the model wraps the JSON
        raw = _cred_re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=_cred_re.MULTILINE).strip()
        result = _j.loads(raw)
        return {
            k: str(v)
            for k, v in result.items()
            if v and str(v).lower() not in ('null', 'none', '')
        }
    except Exception:
        return _extract_credentials(text)


def _extract_form_data_semantic(text: str, agent) -> dict:
    """
    Extract general form field values (dates, names, descriptions, locations, etc.)
    from the user's message using LLM. Returns {field_name: value} dict.
    Only called when message is longer than 60 chars (likely contains real data).
    """
    import json as _j
    if len(text.strip()) < 60:
        return {}
    prompt = (
        "Extract any specific data values a user wants to enter into a form from the message below.\n"
        "Return ONLY a JSON object where keys are field names and values are the data to enter.\n"
        "Include: dates, times, names, descriptions, locations, IDs, amounts, statuses.\n"
        "Use null for any ambiguous field. No explanation, no extra text.\n\n"
        f"Message: \"{text[:800]}\"\n\n"
        "JSON:"
    )
    try:
        raw = agent.call_llm(prompt, markdown=False).strip()
        raw = _cred_re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=_cred_re.MULTILINE).strip()
        result = _j.loads(raw)
        return {
            k: str(v)
            for k, v in result.items()
            if v and str(v).lower() not in ('null', 'none', '')
        }
    except Exception:
        return {}


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

            # Launch persistent browser and send preview screenshot (non-fatal)
            try:
                from app.services.executor_session_manager import executor_session_manager as _esm
                import asyncio as _asyncio

                _exec_session = _esm.get_or_create_session(session_id, headless=True)
                _preview = await _asyncio.to_thread(_exec_session.preview, request.url)
                if _preview.get("success"):
                    await sse_manager.broadcast(session_id, {
                        "type": "browser_preview",
                        "url": _preview["url"],
                        "title": _preview.get("title", ""),
                        "image_b64": _preview["image_b64"],
                    })
            except Exception as _pe:
                print(f"[analyze-url] Browser preview failed (non-fatal): {_pe}")

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
        get_max_tc_id, set_max_tc_id, add_session_tokens, get_session_tokens,
    )
    from app.core.sse_manager import sse_manager
    from app.utils.logger import get_stats as _get_stats

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

    # Clean intent — just the raw user message.
    # History is passed directly to agent.generate() as real messages.
    effective_intent = request.user_message

    # Extract form data via LLM for fill steps (dates, names, descriptions, etc.)
    _classifier_form_data: dict = {}
    try:
        _classifier_form_data = _extract_form_data_semantic(request.user_message, agent)
    except Exception:
        pass

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

            _tok_before = _get_stats()
            test_suite = await _asyncio.to_thread(
                agent.generate,
                page_structure=page_structure,
                intent=effective_intent,
                app_name=_app_name,
                base_url=None,
                test_email=_test_email,
                test_password=_test_password,
                browser_already_on_page=_browser_alive,
                history=history,
                form_data=_classifier_form_data,
            )

            # Re-sequence TC IDs using the session-level global counter so IDs
            # are continuous across page navigations and multiple generations.
            _max_num = get_max_tc_id(_session_id)
            for _i, _tc in enumerate(test_suite.get("test_cases", [])):
                _tc["id"] = f"TS_{_max_num + _i + 1:03d}"
            set_max_tc_id(_session_id, _max_num + len(test_suite.get("test_cases", [])))

            confirm_msg = await _asyncio.to_thread(agent.generate_confirm, test_suite, compact)
            _tok_after = _get_stats()
            _msg_tokens = _tok_after["total_tokens"] - _tok_before["total_tokens"]
            _msg_cost = round(_tok_after["total_cost_usd"] - _tok_before["total_cost_usd"], 8)
            add_session_tokens(_session_id, _msg_tokens, _msg_cost)
            _sess_tok = get_session_tokens(_session_id)

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
            print(f"[chat-generate] Generated {tc_count} test case(s) for session {_session_id[:8]} | tokens={_msg_tokens} cost=${_msg_cost:.5f}")

            await sse_manager.broadcast(_session_id, {
                "type": "chat_test_suite",
                "message": confirm_msg,
                "test_suite": test_suite,
                "tokens_used": _msg_tokens,
                "cost_usd": _msg_cost,
                "session_total_tokens": _sess_tok["total_tokens"],
                "session_total_cost": _sess_tok["cost_usd"],
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
# POST /chat-freeform — lightweight pre-session conversational LLM call
# ---------------------------------------------------------------------------

class ChatFreeformRequest(PydanticBaseModel):
    user_message: str
    llm_provider: Optional[str] = None
    context: Optional[str] = None  # optional caller hint (e.g. "url_input")


@router.post("/chat-freeform")
async def chat_freeform(request: ChatFreeformRequest):
    """
    Stateless conversational LLM call — no session required.
    Used by the frontend before a test session exists (e.g. url_input phase)
    to give dynamic, contextual responses instead of hardcoded strings.
    """
    from app.agents.test_case_generator import TestCaseGeneratorAgent
    from app.agents.base_agent import LLMProvider as AgentLLMProvider

    provider_name = validate_llm_provider(request.llm_provider or settings.DEFAULT_LLM_PROVIDER)
    validate_api_key(provider_name)

    model_map = {
        "openai": settings.OPENAI_MODEL,
        "anthropic": settings.ANTHROPIC_MODEL,
        "groq": settings.GROQ_MODEL,
        "waymore": settings.WAYMORE_MODEL,
    }
    model = model_map.get(provider_name, settings.GROQ_MODEL)

    agent = TestCaseGeneratorAgent(
        provider=AgentLLMProvider(provider_name),
        model=model,
    )

    ctx = request.context or "url_input"

    if ctx == "url_input":
        system_prompt = (
            "You are a friendly test automation assistant helping someone set up automated browser tests.\n"
            "The user needs to share the URL of the web page they want to test — but they haven't yet.\n\n"
            "Based on what they said, respond in 1-2 short, conversational sentences.\n"
            "Your only goal is to naturally guide them to share the URL.\n\n"
            "Rules:\n"
            "- If they describe a feature or page (e.g. 'login page', 'dashboard') → ask for its URL warmly.\n"
            "- If they seem confused about what to provide → briefly explain you need the page URL (e.g. https://app.example.com/login).\n"
            "- If they typed something that looks like a partial URL (missing https, has spaces) → gently ask them to share the full URL.\n"
            "- Never give long explanations. Be warm, concise, and human.\n"
            "- Do NOT repeat or echo what they said back to them verbatim.\n"
        )
    else:
        system_prompt = (
            "You are a friendly test automation assistant. Respond helpfully and concisely (1-3 sentences)."
        )

    prompt = f"{system_prompt}\n\nUser message: \"{request.user_message}\"\n\nYour response:"

    try:
        response_text = agent.call_llm(prompt).strip()
    except Exception as e:
        print(f"[chat-freeform] LLM call failed: {e}")
        response_text = "Could you share the URL of the page you'd like to test? (e.g. https://yourapp.com/login)"

    return {"message": response_text}


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
        get_max_tc_id, set_max_tc_id, add_session_tokens, get_session_tokens,
    )
    from app.core.sse_manager import sse_manager
    from app.utils.logger import get_stats as _get_stats

    provider_name = validate_llm_provider(request.llm_provider or settings.DEFAULT_LLM_PROVIDER)
    validate_api_key(provider_name)

    session = get_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    last_suite = get_last_test_suite(request.session_id)
    test_cases = last_suite.get("test_cases", []) if last_suite else []
    page_url = session.get("compact", {}).get("url", "")
    history = get_messages(request.session_id)

    provider_enum = AgentLLMProvider(provider_name)
    agent = TestCaseGeneratorAgent(provider=provider_enum)

    # Semantically extract credentials — handles any natural language format
    new_creds = await _asyncio.to_thread(_extract_credentials_semantic, request.user_message, agent)
    if new_creds:
        existing = get_credentials(request.session_id)
        set_credentials(request.session_id, {**existing, **new_creds})

    # ── Fast pre-classification — bypass LLM for unambiguous patterns ─────────
    import re as _intent_re
    from app.core.chat_sessions import (
        get_pending_approval as _get_pending,
        get_pending_row_choice as _get_row_choice,
    )
    _msg = request.user_message.strip()
    _pending_results = _get_pending(request.session_id)
    _pending_row_choice = _get_row_choice(request.session_id)

    _YES_RE = _intent_re.compile(
        r'^(yes|yeah|yep|yup|sure|ok|okay|confirm|add it|go ahead|do it|proceed|'
        r'fine|sounds good|let\'s go|perfect|great|absolutely|of course|please|'
        r'approved?|that\'s right|correct|affirmative|roger|done|submit)\b',
        _intent_re.IGNORECASE,
    )
    _NO_RE = _intent_re.compile(
        r'^(no|nope|nah|cancel|skip|don\'t|dont|stop|never mind|nevermind|'
        r'forget it|discard|reject|not now|leave it|ignore)\b',
        _intent_re.IGNORECASE,
    )
    # Row-choice responses: "split/individual/separate" vs "combined/one row/same row"
    _ROW_SPLIT_RE = _intent_re.compile(
        r'\b(split|individual|separate|each|one\s+per|per\s+row)\b',
        _intent_re.IGNORECASE,
    )
    _ROW_COMBINED_RE = _intent_re.compile(
        r'\b(combined?|one\s+row|same\s+row|single\s+row|together|merge|all\s+in\s+one)\b',
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
    elif _pending_row_choice is not None and _ROW_SPLIT_RE.search(_msg):
        classification = {
            "intent": "approve",
            "confidence": 1.0,
            "reasoning": "pre-classified: row-choice → individual",
            "metadata": {"approve_targets": "__row_choice_individual__"},
        }
    elif _pending_row_choice is not None and _ROW_COMBINED_RE.search(_msg):
        classification = {
            "intent": "approve",
            "confidence": 1.0,
            "reasoning": "pre-classified: row-choice → combined",
            "metadata": {"approve_targets": "__row_choice_combined__"},
        }
    elif _pending_row_choice is not None and _NO_RE.match(_msg):
        classification = {
            "intent": "approve",
            "confidence": 1.0,
            "reasoning": "pre-classified: row-choice → cancelled",
            "metadata": {"approve_targets": "__row_choice_cancel__"},
        }
    else:
        _EXEC_RE = _intent_re.compile(
            r'^(execute|run|play|start|launch)\s*(?:test\s*case\s*|test\s*|tc\s*)?(\d+(?:\s*[,\s]\s*\d+)*|all)\b',
            _intent_re.IGNORECASE,
        )
        _exec_m = _EXEC_RE.match(_msg)

        # Multi-range grouping: "add 1 to 5 in one row and 6 to 10 in another"
        # Requires 2+ "X to Y" pairs and an approve-like keyword anywhere in message
        _ANY_RANGE_RE = _intent_re.compile(r'(\d+)\s+to\s+(\d+)', _intent_re.IGNORECASE)
        _all_ranges = _ANY_RANGE_RE.findall(_msg)
        _has_approve_kw = bool(_intent_re.search(
            r'\b(add|append|save|approve|export|put|place)\b', _msg, _intent_re.IGNORECASE
        ))
        _is_multi_range = len(_all_ranges) >= 2 and _has_approve_kw

        # Single-range grouping: "add test steps from 1 to 10"
        _RANGE_RE = _intent_re.compile(
            r'(?:add|append|export|save|approve)\s+(?:test\s*)?steps?\s+(?:from\s+)?(\d+)\s+to\s+(\d+)',
            _intent_re.IGNORECASE,
        )
        _range_m = _RANGE_RE.search(_msg)

        # List unadded / export all: "export to excel", "export all", "list unadded steps"
        _EXPORT_RE = _intent_re.compile(
            r'\b(export\s+(?:to\s+)?excel|export\s+all|list\s+unadded\s+(?:steps?|tests?)|'
            r'what\s+steps?\s+haven\'?t\s+been\s+added)\b',
            _intent_re.IGNORECASE,
        )

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
        elif _is_multi_range:
            classification = {
                "intent": "approve",
                "confidence": 1.0,
                "reasoning": "pre-classified: multi-range group pattern",
                "metadata": {
                    "approve_targets": None,
                    "approve_mode": "multi_group",
                    "approve_ranges": [{"from": int(f), "to": int(t)} for f, t in _all_ranges],
                },
            }
        elif _range_m:
            _r_from, _r_to = int(_range_m.group(1)), int(_range_m.group(2))
            classification = {
                "intent": "approve",
                "confidence": 1.0,
                "reasoning": "pre-classified: range group pattern",
                "metadata": {
                    "approve_targets": list(range(_r_from, _r_to + 1)),
                    "approve_mode": "group",
                    "approve_range": {"from": _r_from, "to": _r_to},
                },
            }
        elif _EXPORT_RE.search(_msg):
            classification = {
                "intent": "approve",
                "confidence": 1.0,
                "reasoning": "pre-classified: export/list-unadded pattern",
                "metadata": {"approve_targets": "all", "approve_mode": "list_unadded"},
            }
        elif _has_approve_kw and _intent_re.search(r'\b\d+\b', _msg):
            # Generic specific-list: "add TC001 and TC006", "add only 6 7 10",
            # "add test case 1 and 6", "approve TS003, TS007" — extract all numbers
            _approve_list_nums = list(dict.fromkeys(
                int(n) for n in _intent_re.findall(r'\b(\d+)\b', _msg)
            ))
            classification = {
                "intent": "approve",
                "confidence": 1.0,
                "reasoning": "pre-classified: approve keyword + specific number list",
                "metadata": {"approve_targets": _approve_list_nums},
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

    # Safety override: cannot edit without existing test cases → redirect to generate
    if intent == "edit" and not last_suite:
        print(f"[chat-message] edit intent with no test suite — redirecting to generate")
        intent = "generate"

    # ────────────────────────────────────────────────────────────────────────

    _session_id = request.session_id

    # ── Execute ──────────────────────────────────────────────────────────────
    if intent == "execute":
        if not last_suite:
            _exec_user_msg = request.user_message
            append_message(_session_id, "user", request.user_message)

            async def _exec_no_tc():
                no_tc_msg = await _asyncio.to_thread(
                    agent.narrate, "no_test_cases_execute", _exec_user_msg, page_url, {}
                )
                append_message(_session_id, "assistant", no_tc_msg)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": no_tc_msg,
                    "intent": "clarify",
                })

            background_tasks.add_task(_exec_no_tc)
            return {"session_id": _session_id, "status": "thinking", "intent": "clarify"}

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
            add_confirmed_ids, get_confirmed_ids,
            get_pending_row_choice, set_pending_row_choice, clear_pending_row_choice,
        )
        targets = metadata.get("approve_targets")
        approve_mode = metadata.get("approve_mode", "individual")
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
                # Mark all TS IDs (including grouped sub-IDs) as confirmed
                _all_confirmed_ids = []
                for _r in confirmed:
                    _all_confirmed_ids.append(_r.get("id", ""))
                    _all_confirmed_ids.extend(_r.get("grouped_ids", []))
                add_confirmed_ids(request.session_id, [i for i in _all_confirmed_ids if i])
            _confirm_user_msg = request.user_message
            _confirm_results = confirmed

            async def _do_confirm():
                if _confirm_results:
                    _ctx = {"confirmed": [{"id": r.get("id"), "name": r.get("name"), "status": r.get("status")} for r in _confirm_results]}
                    success_msg = await _asyncio.to_thread(
                        agent.narrate, "approve_success", _confirm_user_msg, page_url, _ctx
                    )
                else:
                    success_msg = await _asyncio.to_thread(
                        agent.narrate, "approve_nothing_to_add", _confirm_user_msg, page_url, {}
                    )
                append_message(_session_id, "assistant", success_msg)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_approve",
                    "results": _confirm_results,
                    "message": success_msg,
                })

            background_tasks.add_task(_do_confirm)
            return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

        # ── User cancelled a pending approval ────────────────────────────────
        if targets == "__pending_cancel__":
            clear_pending_approval(request.session_id)
            _cancel_user_msg = request.user_message

            async def _do_cancel():
                cancel_msg = await _asyncio.to_thread(
                    agent.narrate, "approve_cancel", _cancel_user_msg, page_url, {}
                )
                append_message(_session_id, "assistant", cancel_msg)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": cancel_msg,
                    "intent": "approve",
                })

            background_tasks.add_task(_do_cancel)
            return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

        # ── Row-choice: user answered individual vs combined question ─────────
        if targets in ("__row_choice_individual__", "__row_choice_combined__", "__row_choice_cancel__"):
            _choice_data = get_pending_row_choice(request.session_id) or {}
            clear_pending_row_choice(request.session_id)
            _choice_matched = _choice_data.get("results", [])

            if targets == "__row_choice_cancel__" or not _choice_matched:
                _rc_user_msg = request.user_message

                async def _row_cancel():
                    _cancel_row_msg = await _asyncio.to_thread(
                        agent.narrate, "approve_row_cancel", _rc_user_msg, page_url, {}
                    )
                    append_message(_session_id, "assistant", _cancel_row_msg)
                    await sse_manager.broadcast(_session_id, {
                        "type": "chat_response",
                        "message": _cancel_row_msg,
                        "intent": "approve",
                    })

                background_tasks.add_task(_row_cancel)
                return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

            if targets == "__row_choice_individual__":
                # Add each as a separate row
                set_pending_approval(_session_id, _choice_matched)
                _ri_matched = _choice_matched
                _ri_user_msg = request.user_message

                async def _row_individual():
                    _choice_confirm = await _asyncio.to_thread(
                        agent.narrate, "approve_confirm_individual", _ri_user_msg, page_url,
                        {"matched": [{"id": r.get("id"), "name": r.get("name"), "status": r.get("status")} for r in _ri_matched]}
                    )
                    append_message(_session_id, "assistant", _choice_confirm)
                    await sse_manager.broadcast(_session_id, {
                        "type": "chat_response",
                        "message": _choice_confirm,
                        "intent": "approve",
                    })

                background_tasks.add_task(_row_individual)
                return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

            if targets == "__row_choice_combined__":
                # Merge all into one row with LLM summary
                _all_steps = [s for _r in _choice_matched for s in _r.get("steps", [])]
                _all_expected = [e for _r in _choice_matched for e in _r.get("expected_results", [])]
                _merged_data: dict = {}
                for _r in _choice_matched:
                    _merged_data.update(_r.get("test_data", {}))
                _failed = next((_r for _r in _choice_matched if _r.get("status") == "failed"), None)
                _ids = [_r["id"] for _r in _choice_matched]
                _summary_prompt = (
                    f"Summarize what these {len(_choice_matched)} test steps collectively verify "
                    f"in one short phrase (max 10 words, no quotes, no punctuation at end):\n"
                    + "\n".join(f"- {_r['name']}" for _r in _choice_matched)
                )
                _group_name = await _asyncio.to_thread(agent.call_llm, _summary_prompt)
                _group_name = re.sub(r'\*+', '', _group_name).strip().lstrip('-').strip().strip('"').strip("'").rstrip(".")
                _grouped = {
                    "id": f"GROUP_{_ids[0]}_{_ids[-1]}",
                    "name": _group_name,
                    "status": "failed" if _failed else "passed",
                    "steps": _all_steps,
                    "expected_results": _all_expected,
                    "test_data": _merged_data,
                    "error": _failed.get("error") if _failed else None,
                    "grouped_ids": _ids,
                }
                set_pending_approval(_session_id, [_grouped])
                _rcomb_group_name = _group_name
                _rcomb_ids = _ids
                _rcomb_count = len(_choice_matched)
                _rcomb_user_msg = request.user_message

                async def _row_combined():
                    _combined_confirm = await _asyncio.to_thread(
                        agent.narrate, "approve_confirm_group", _rcomb_user_msg, page_url,
                        {"name": _rcomb_group_name, "id_range": f"{_rcomb_ids[0]}–{_rcomb_ids[-1]}", "count": _rcomb_count}
                    )
                    append_message(_session_id, "assistant", _combined_confirm)
                    await sse_manager.broadcast(_session_id, {
                        "type": "chat_response",
                        "message": _combined_confirm,
                        "intent": "approve",
                    })

                background_tasks.add_task(_row_combined)
                return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

        # ── New approval request ──────────────────────────────────────────────
        _raw_results = get_execution_result(request.session_id)
        exec_results = _raw_results if isinstance(_raw_results, list) else []

        # ── Mode: list_unadded — list all executed steps not yet in Excel ─────
        if approve_mode == "list_unadded":
            _confirmed_ids = get_confirmed_ids(request.session_id)
            _unconfirmed = [r for r in exec_results if r.get("id") not in _confirmed_ids]

            _lu_user_msg = request.user_message
            if not _unconfirmed:
                _lu_situation = "approve_no_results" if not exec_results else "approve_all_added"
                _lu_ctx: dict = {}
            else:
                _lu_situation = "approve_list_unadded"
                _lu_ctx = {"unadded": [{"id": r.get("id"), "name": r.get("name"), "status": r.get("status")} for r in _unconfirmed]}
                set_pending_approval(_session_id, _unconfirmed)

            async def _list_unadded_respond():
                response_msg = await _asyncio.to_thread(
                    agent.narrate, _lu_situation, _lu_user_msg, page_url, _lu_ctx
                )
                append_message(_session_id, "assistant", response_msg)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": response_msg,
                    "intent": "approve",
                })

            background_tasks.add_task(_list_unadded_respond)
            return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

        # ── Mode: multi_group — each specified range becomes its own Excel row ─
        if approve_mode == "multi_group":
            _approve_ranges = metadata.get("approve_ranges") or []
            _confirmed_ids = get_confirmed_ids(request.session_id)

            def _resolve_range_results(range_from: int, range_to: int) -> list:
                """Return exec_results whose numeric ID falls within [range_from, range_to]."""
                import re as _rr
                result = []
                for _r in exec_results:
                    _m = _rr.search(r'\d+', str(_r.get("id", "")))
                    if _m and range_from <= int(_m.group(0)) <= range_to:
                        result.append(_r)
                if not result:
                    # Fallback: positional (1-indexed)
                    result = [exec_results[i - 1] for i in range(range_from, range_to + 1) if 0 < i <= len(exec_results)]
                return result

            _grouped_rows = []
            _preview_lines = []
            for _rng in _approve_ranges:
                # LLM may return ranges as dicts {"from":1,"to":2} or as lists [1,2]
                if isinstance(_rng, (list, tuple)):
                    _rng_from = int(_rng[0]) if len(_rng) > 0 else 1
                    _rng_to = int(_rng[1]) if len(_rng) > 1 else _rng_from
                else:
                    _rng_from = _rng.get("from", 1)
                    _rng_to = _rng.get("to", 1)
                _rng_results = _resolve_range_results(_rng_from, _rng_to)
                if not _rng_results:
                    continue
                _rng_steps = [s for _r in _rng_results for s in _r.get("steps", [])]
                _rng_expected = [e for _r in _rng_results for e in _r.get("expected_results", [])]
                _rng_data: dict = {}
                for _r in _rng_results:
                    _rng_data.update(_r.get("test_data", {}))
                _rng_failed = next((_r for _r in _rng_results if _r.get("status") == "failed"), None)
                _rng_ids = [_r["id"] for _r in _rng_results]
                _rng_summary_prompt = (
                    f"Summarize what these {len(_rng_results)} test steps collectively verify "
                    f"in one short phrase (max 10 words, no quotes, no punctuation at end):\n"
                    + "\n".join(f"- {_r['name']}" for _r in _rng_results)
                )
                _rng_name = await _asyncio.to_thread(agent.call_llm, _rng_summary_prompt)
                _rng_name = re.sub(r'\*+', '', _rng_name).strip().lstrip('-').strip().strip('"').strip("'").rstrip(".")
                _grouped_rows.append({
                    "id": f"GROUP_{_rng_ids[0]}_{_rng_ids[-1]}",
                    "name": _rng_name,
                    "status": "failed" if _rng_failed else "passed",
                    "steps": _rng_steps,
                    "expected_results": _rng_expected,
                    "test_data": _rng_data,
                    "error": _rng_failed.get("error") if _rng_failed else None,
                    "grouped_ids": _rng_ids,
                })
                _icon = "❌" if _rng_failed else "✅"
                _preview_lines.append(
                    f"- **Row {len(_preview_lines) + 1}**: {_rng_name} {_icon} "
                    f"({_rng_ids[0]}–{_rng_ids[-1]}, {len(_rng_results)} steps)"
                )

            _mg_user_msg = request.user_message
            if not _grouped_rows:
                async def _mg_none():
                    _no_mg_msg = await _asyncio.to_thread(
                        agent.narrate, "approve_multi_group_no_results", _mg_user_msg, page_url, {}
                    )
                    append_message(_session_id, "assistant", _no_mg_msg)
                    await sse_manager.broadcast(_session_id, {
                        "type": "chat_response",
                        "message": _no_mg_msg,
                        "intent": "approve",
                    })

                background_tasks.add_task(_mg_none)
                return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

            set_pending_approval(_session_id, _grouped_rows)
            _mg_rows_ctx = [
                {"name": r.get("name"), "id_range": f"{r['grouped_ids'][0]}–{r['grouped_ids'][-1]}" if r.get("grouped_ids") else r.get("id", ""), "status": r.get("status")}
                for r in _grouped_rows
            ]

            async def _multi_group_ask():
                _mg_confirm = await _asyncio.to_thread(
                    agent.narrate, "approve_confirm_multi_group", _mg_user_msg, page_url,
                    {"rows": _mg_rows_ctx}
                )
                append_message(_session_id, "assistant", _mg_confirm)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": _mg_confirm,
                    "intent": "approve",
                })

            background_tasks.add_task(_multi_group_ask)
            return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

        # ── Resolve target IDs → matched results ──────────────────────────────
        _confirmed_ids = get_confirmed_ids(request.session_id)

        if not exec_results:
            matched: list = []
        elif targets is None or targets == "all":
            # Filter out already-confirmed results
            matched = [
                r for r in exec_results
                if r.get("id") not in _confirmed_ids
                and all(gid not in _confirmed_ids for gid in (r.get("grouped_ids") or []))
            ]
        elif isinstance(targets, list) and targets and isinstance(targets[0], int):
            # Look up by TS ID (e.g. 1 → "TS_001") so "approve test step 1" always
            # means TS_001 regardless of execution order
            _target_ids = {f"TS_{n:03d}" for n in targets}
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
            _an_user_msg = request.user_message
            _an_situation = "approve_all_added" if (exec_results and (targets is None or targets == "all")) else "approve_no_results"

            async def _approve_none():
                response_msg = await _asyncio.to_thread(
                    agent.narrate, _an_situation, _an_user_msg, page_url, {}
                )
                append_message(_session_id, "assistant", response_msg)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": response_msg,
                    "intent": "approve",
                })

            background_tasks.add_task(_approve_none)
            return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

        # ── Mode: group — merge matched steps into a single Excel row ─────────
        if approve_mode == "group":
            _all_steps = [s for _r in matched for s in _r.get("steps", [])]
            _all_expected = [e for _r in matched for e in _r.get("expected_results", [])]
            _merged_data = {}
            for _r in matched:
                _merged_data.update(_r.get("test_data", {}))
            _failed = next((_r for _r in matched if _r.get("status") == "failed"), None)
            _ids = [_r["id"] for _r in matched]

            # LLM-generated summary for the "Test Case" column
            _summary_prompt = (
                f"Summarize what these {len(matched)} test steps collectively verify "
                f"in one short phrase (max 10 words, no quotes, no punctuation at end):\n"
                + "\n".join(f"- {_r['name']}" for _r in matched)
            )
            _group_name = await _asyncio.to_thread(agent.call_llm, _summary_prompt)
            _group_name = re.sub(r'\*+', '', _group_name).strip().lstrip('-').strip().strip('"').strip("'").rstrip(".")

            _grouped = {
                "id": f"GROUP_{_ids[0]}_{_ids[-1]}",
                "name": _group_name,
                "status": "failed" if _failed else "passed",
                "steps": _all_steps,
                "expected_results": _all_expected,
                "test_data": _merged_data,
                "error": _failed.get("error") if _failed else None,
                "grouped_ids": _ids,
            }
            set_pending_approval(_session_id, [_grouped])
            _ga_group_name = _group_name
            _ga_ids = _ids
            _ga_count = len(matched)
            _ga_user_msg = request.user_message

            async def _group_ask():
                _confirm_ask = await _asyncio.to_thread(
                    agent.narrate, "approve_confirm_group", _ga_user_msg, page_url,
                    {"name": _ga_group_name, "id_range": f"{_ga_ids[0]}–{_ga_ids[-1]}", "count": _ga_count}
                )
                append_message(_session_id, "assistant", _confirm_ask)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": _confirm_ask,
                    "intent": "approve",
                })

            background_tasks.add_task(_group_ask)
            return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

        # ── Mode: individual (default) — one row per matched result ───────────
        # When "approve all" targets 2+ results without specifying row structure,
        # ask the user first whether they want separate rows or a combined row.
        if (targets is None or targets == "all") and len(matched) >= 2:
            set_pending_row_choice(_session_id, {"results": matched})
            _rs_matched = matched
            _rs_user_msg = request.user_message

            async def _row_structure_ask():
                _row_q = await _asyncio.to_thread(
                    agent.narrate, "approve_row_structure", _rs_user_msg, page_url,
                    {"results": [{"id": r.get("id"), "name": r.get("name"), "status": r.get("status")} for r in _rs_matched]}
                )
                append_message(_session_id, "assistant", _row_q)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": _row_q,
                    "intent": "approve",
                })

            background_tasks.add_task(_row_structure_ask)
            return {"session_id": _session_id, "status": "thinking", "intent": "approve"}

        # Single result or specific target — add directly without row-structure question
        set_pending_approval(_session_id, matched)
        _ai_matched = matched
        _ai_user_msg = request.user_message

        async def _approve_ask():
            confirm_ask = await _asyncio.to_thread(
                agent.narrate, "approve_confirm_individual", _ai_user_msg, page_url,
                {"matched": [{"id": r.get("id"), "name": r.get("name"), "status": r.get("status")} for r in _ai_matched]}
            )
            append_message(_session_id, "assistant", confirm_ask)
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
                _tok_before = _get_stats()
                answer = await _asyncio.to_thread(agent.answer_question, compact, _user_message, history)
                _tok_after = _get_stats()
                _msg_tokens = _tok_after["total_tokens"] - _tok_before["total_tokens"]
                _msg_cost = round(_tok_after["total_cost_usd"] - _tok_before["total_cost_usd"], 8)
                add_session_tokens(_session_id, _msg_tokens, _msg_cost)
                _sess_tok = get_session_tokens(_session_id)
                append_message(_session_id, "assistant", answer)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": answer,
                    "intent": "informational",
                    "tokens_used": _msg_tokens,
                    "cost_usd": _msg_cost,
                    "session_total_tokens": _sess_tok["total_tokens"],
                    "session_total_cost": _sess_tok["cost_usd"],
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
            _edit_user_msg = request.user_message
            append_message(_session_id, "user", request.user_message)

            async def _edit_no_tc():
                no_tc_msg = await _asyncio.to_thread(
                    agent.narrate, "no_test_cases_edit", _edit_user_msg, page_url, {}
                )
                append_message(_session_id, "assistant", no_tc_msg)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_response",
                    "message": no_tc_msg,
                    "intent": "clarify",
                })

            background_tasks.add_task(_edit_no_tc)
            return {"session_id": _session_id, "status": "thinking", "intent": "clarify"}
        compact = session["compact"]
        append_message(_session_id, "user", request.user_message)
        _user_message = request.user_message

        async def _edit():
            try:
                await sse_manager.broadcast(_session_id, {"type": "chat_thinking", "message": "Applying edits…"})
                _tok_before = _get_stats()
                updated = await _asyncio.to_thread(agent.generate_edit, last_suite, _user_message, history)
                set_last_test_suite(_session_id, updated)
                edit_msg = await _asyncio.to_thread(agent.generate_confirm, updated, compact)
                _tok_after = _get_stats()
                _msg_tokens = _tok_after["total_tokens"] - _tok_before["total_tokens"]
                _msg_cost = round(_tok_after["total_cost_usd"] - _tok_before["total_cost_usd"], 8)
                add_session_tokens(_session_id, _msg_tokens, _msg_cost)
                _sess_tok = get_session_tokens(_session_id)
                append_message(_session_id, "assistant", edit_msg)
                await sse_manager.broadcast(_session_id, {
                    "type": "chat_test_suite",
                    "message": edit_msg,
                    "test_suite": updated,
                    "intent": "edit",
                    "tokens_used": _msg_tokens,
                    "cost_usd": _msg_cost,
                    "session_total_tokens": _sess_tok["total_tokens"],
                    "session_total_cost": _sess_tok["cost_usd"],
                })
            except Exception as e:
                import traceback
                print(f"[chat-message/edit] Error: {traceback.format_exc()}")
                await sse_manager.broadcast(_session_id, {"type": "chat_error", "message": f"Error: {str(e)}"})

        background_tasks.add_task(_edit)
        return {"session_id": _session_id, "status": "thinking", "intent": "edit"}

    # ── Clarify ───────────────────────────────────────────────────────────────
    elif intent == "clarify":
        clarify_msg = classification.get("clarify_message") or ""
        _clarify_user_msg = request.user_message
        _clarify_tc_names = [tc.get("name", "") for tc in test_cases]
        append_message(_session_id, "user", request.user_message)

        async def _clarify():
            nonlocal clarify_msg
            if not clarify_msg.strip():
                clarify_msg = await _asyncio.to_thread(
                    agent.narrate, "clarify_fallback", _clarify_user_msg, page_url,
                    {"test_cases": _clarify_tc_names}
                )
            append_message(_session_id, "assistant", clarify_msg)
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

        # ── Fuzzy element-name correction (silent auto-correct) ───────────────
        # Compare element names the user typed against actual DOM element names.
        # Auto-correct close-but-not-exact matches and proceed immediately —
        # no confirmation prompt, just inform the user in the generation message.
        from app.agents.test_case_generator import fuzzy_correct_intent as _fce
        _corrected_msg, _corrections = _fce(request.user_message, page_structure)

        # Use corrected intent if any corrections were made
        effective_intent = _corrected_msg if _corrections else request.user_message

        append_message(_session_id, "user", request.user_message)
        _test_email = session_creds.get("email") or "test@example.com"
        _test_password = session_creds.get("password") or "password123"
        _new_creds = new_creds

        async def _generate():
            try:
                await sse_manager.broadcast(_session_id, {"type": "chat_thinking", "message": "Generating test cases…"})

                from app.services.executor_session_manager import executor_session_manager as _esm_gen
                _browser_alive = _esm_gen.get_session(_session_id) is not None

                _tok_before = _get_stats()
                test_suite = await _asyncio.to_thread(
                    agent.generate,
                    page_structure=page_structure,
                    intent=effective_intent,
                    app_name="My App",
                    base_url=None,
                    test_email=_test_email,
                    test_password=_test_password,
                    browser_already_on_page=_browser_alive,
                    history=history,
                    form_data=metadata.get("form_data") or {},
                )

                # Re-sequence TC IDs using the session-level global counter so IDs
                # are continuous across page navigations and multiple generations.
                _max_num = get_max_tc_id(_session_id)
                for _i, _tc in enumerate(test_suite.get("test_cases", [])):
                    _tc["id"] = f"TS_{_max_num + _i + 1:03d}"
                set_max_tc_id(_session_id, _max_num + len(test_suite.get("test_cases", [])))

                confirm_msg = await _asyncio.to_thread(
                    agent.generate_confirm, test_suite, compact,
                    corrections=_corrections if _corrections else None,
                    new_creds=_new_creds if _new_creds else None,
                )
                _tok_after = _get_stats()
                _msg_tokens = _tok_after["total_tokens"] - _tok_before["total_tokens"]
                _msg_cost = round(_tok_after["total_cost_usd"] - _tok_before["total_cost_usd"], 8)
                add_session_tokens(_session_id, _msg_tokens, _msg_cost)
                _sess_tok = get_session_tokens(_session_id)

                append_message(_session_id, "assistant", confirm_msg)
                set_last_test_suite(_session_id, test_suite)

                tc_count = len(test_suite.get("test_cases", []))
                print(f"[chat-message/generate] Generated {tc_count} test case(s) for session {_session_id[:8]} | tokens={_msg_tokens} cost=${_msg_cost:.5f}")

                await sse_manager.broadcast(_session_id, {
                    "type": "chat_test_suite",
                    "message": confirm_msg,
                    "test_suite": test_suite,
                    "tokens_used": _msg_tokens,
                    "cost_usd": _msg_cost,
                    "session_total_tokens": _sess_tok["total_tokens"],
                    "session_total_cost": _sess_tok["cost_usd"],
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
    from app.core.chat_sessions import (
        get_session, append_message, get_messages,
        add_session_tokens, get_session_tokens,
    )
    from app.core.sse_manager import sse_manager
    from app.utils.logger import get_stats as _get_stats

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
            _tok_before = _get_stats()
            answer = await _asyncio.to_thread(
                agent.answer_question, compact, _user_message, history
            )
            _tok_after = _get_stats()
            _msg_tokens = _tok_after["total_tokens"] - _tok_before["total_tokens"]
            _msg_cost = round(_tok_after["total_cost_usd"] - _tok_before["total_cost_usd"], 8)
            add_session_tokens(_session_id, _msg_tokens, _msg_cost)
            _sess_tok = get_session_tokens(_session_id)
            append_message(_session_id, "assistant", answer)

            await sse_manager.broadcast(_session_id, {
                "type": "chat_response",
                "message": answer,
                "intent": "informational",
                "tokens_used": _msg_tokens,
                "cost_usd": _msg_cost,
                "session_total_tokens": _sess_tok["total_tokens"],
                "session_total_cost": _sess_tok["cost_usd"],
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
                    elif msg_type == "step_started":
                        await sse_manager.broadcast(exec_session_id, {
                            "type": "chat_step_executing",
                            "test_id": msg.get("test_id", ""),
                            "test_name": msg.get("test_name", ""),
                            "step_number": msg.get("step_number", 0),
                            "total_steps": msg.get("total_steps", 0),
                            "instruction": msg.get("instruction", ""),
                        })
                        await sse_manager.broadcast(exec_session_id, {
                            "type": "step_update",
                            "test_id": msg.get("test_id", ""),
                            "test_name": msg.get("test_name", ""),
                            "step_number": msg.get("step_number", 0),
                            "instruction": msg.get("instruction", ""),
                            "status": "running",
                        })
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
                    # Failure diagnostics — only meaningful when status is failed
                    "failed_steps": [
                        s for s in r.get("steps", []) if s.get("status") == "FAILED"
                    ] if r.get("status") != "PASSED" else [],
                    "console_errors": [
                        m for m in r.get("console_log", [])
                        if any(kw in m.lower() for kw in ("error", "warning", "failed", "uncaught", "401", "403", "404", "500"))
                    ] if r.get("status") != "PASSED" else [],
                    "network_errors": r.get("network_errors", []) if r.get("status") != "PASSED" else [],
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
        add_session_tokens, get_session_tokens,
    )
    from app.core.sse_manager import sse_manager
    from app.utils.logger import get_stats as _get_stats

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
            _tok_before = _get_stats()
            updated_suite = await _asyncio.to_thread(
                agent.generate_edit, last_suite, _user_message, history
            )
            set_last_test_suite(_session_id, updated_suite)

            tc_count = len(updated_suite.get("test_cases", []))
            confirm_msg = await _asyncio.to_thread(agent.generate_confirm, updated_suite, compact)
            edit_msg = f"Done! I've updated the test suite. {confirm_msg}"
            _tok_after = _get_stats()
            _msg_tokens = _tok_after["total_tokens"] - _tok_before["total_tokens"]
            _msg_cost = round(_tok_after["total_cost_usd"] - _tok_before["total_cost_usd"], 8)
            add_session_tokens(_session_id, _msg_tokens, _msg_cost)
            _sess_tok = get_session_tokens(_session_id)
            append_message(_session_id, "assistant", edit_msg)

            print(f"[chat-edit] session={_session_id[:8]} updated {tc_count} test case(s) | tokens={_msg_tokens} cost=${_msg_cost:.5f}")

            await sse_manager.broadcast(_session_id, {
                "type": "chat_test_suite",
                "message": edit_msg,
                "test_suite": updated_suite,
                "intent": "edit",
                "tokens_used": _msg_tokens,
                "cost_usd": _msg_cost,
                "session_total_tokens": _sess_tok["total_tokens"],
                "session_total_cost": _sess_tok["cost_usd"],
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
