from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from typing import Optional
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
