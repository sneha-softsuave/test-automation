"""
Deep Agent API Routes

Provides endpoints for running the LangGraph-based Deep Agent workflow
that orchestrates Parse → Execute → Validate → Retry → Report.
"""

from fastapi import APIRouter, Query, HTTPException, Body
from fastapi.responses import StreamingResponse
from typing import Optional, Dict, Any, List
import asyncio
import json
import traceback
from datetime import datetime

from app.core.config import settings
from app.core.sse_manager import sse_manager

# Lazy import to catch errors at runtime
def get_run_deep_agent():
    """Lazy import of run_deep_agent to catch import errors."""
    try:
        from app.agents.deep_agent import run_deep_agent
        return run_deep_agent
    except Exception as e:
        print(f"[Deep Agent] IMPORT ERROR: {e}")
        print(traceback.format_exc())
        raise


router = APIRouter(prefix="/deep-agent", tags=["Deep Agent"])


def validate_llm_provider(provider_name: str) -> str:
    """Validate and return the LLM provider name."""
    valid_providers = ["anthropic", "openai", "groq"]
    if provider_name.lower() not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid LLM provider: {provider_name}. Choose from: {', '.join(valid_providers)}"
        )
    return provider_name.lower()


def validate_api_key(provider: str) -> None:
    """Validate that the API key is configured for the provider."""
    try:
        api_key_map = {
            "anthropic": (getattr(settings, 'ANTHROPIC_API_KEY', None), "your_anthropic_api_key_here"),
            "openai": (getattr(settings, 'OPENAI_API_KEY', None), "your_openai_api_key_here"),
            "groq": (getattr(settings, 'GROQ_API_KEY', None), "your_groq_api_key_here"),
        }

        if provider not in api_key_map:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown provider: {provider}"
            )

        api_key, placeholder = api_key_map[provider]
        print(f"[Deep Agent API] API key check - provider: {provider}, key exists: {bool(api_key)}, is_placeholder: {api_key == placeholder if api_key else 'N/A'}")

        if not api_key or api_key == placeholder:
            raise HTTPException(
                status_code=500,
                detail=f"{provider.upper()}_API_KEY not configured in .env file"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Deep Agent API] Error in validate_api_key: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error validating API key: {str(e)}"
        )


@router.post("/run")
async def run_deep_agent_endpoint(
    input_data: Dict[str, Any] = Body(...),
    session_id: str = Query(..., description="Session ID for SSE updates"),
    llm_provider: Optional[str] = Query(
        default=None,  # Will use settings.DEFAULT_LLM_PROVIDER
        description="LLM provider to use: anthropic, openai, or groq"
    ),
    model: Optional[str] = Query(
        default=None,
        description="Model to use (e.g., claude-sonnet-4-20250514, gpt-4o)"
    ),
    project_name: Optional[str] = Query(
        default="Automation Project",
        description="Name for the test project"
    ),
    base_url: Optional[str] = Query(
        default=None,
        description="Base URL for tests (auto-detected if not provided)"
    ),
    headless: Optional[bool] = Query(
        default=True,
        description="Run browser in headless mode"
    ),
    timeout: Optional[int] = Query(
        default=30000,
        description="Timeout for each action in milliseconds"
    ),
    max_retries: Optional[int] = Query(
        default=2,
        description="Maximum number of retry attempts for failed tests"
    )
):
    """
    Run the Deep Agent workflow for test automation.

    This endpoint orchestrates the full pipeline:
    1. Parse: Convert raw test data to structured format using LLM
    2. Execute: Run Playwright tests
    3. Validate: Check results and decide if retry is needed
    4. Retry: Re-run failed tests if recoverable (up to max_retries)
    5. Report: Generate final report and Playwright script

    Connect to /api/v1/sse/{session_id} before calling to receive real-time updates.

    **Input formats:**
    - Direct raw_data: `{"raw_data": [{"Test Case": "...", "Steps": "..."}]}`
    - From Excel parse: `{"result": {"raw_data": [...]}}`

    **SSE Events:**
    - agent_phase: Workflow phase transitions
    - node_started/node_completed: Individual node lifecycle
    - thoughts: Agent reasoning/decisions
    - execution_started: Test execution beginning
    - step_update: Individual step progress
    - deep_agent_complete: Workflow finished
    """
    print(f"[Deep Agent API] Received request for session {session_id}")
    print(f"[Deep Agent API] Input data keys: {list(input_data.keys())}")

    try:
        # Extract raw_data from various input formats
        if "raw_data" in input_data:
            raw_data = input_data["raw_data"]
        elif "result" in input_data and "raw_data" in input_data["result"]:
            raw_data = input_data["result"]["raw_data"]
        elif "result" in input_data and isinstance(input_data["result"], list):
            raw_data = input_data["result"]
        else:
            raise HTTPException(
                status_code=400,
                detail="Input must contain 'raw_data' field with test case data"
            )

        print(f"[Deep Agent API] Extracted raw_data: {len(raw_data)} items")

        if not raw_data or not isinstance(raw_data, list):
            raise HTTPException(
                status_code=400,
                detail="raw_data must be a non-empty list of test cases"
            )

        # Use default LLM provider if not specified
        effective_provider = llm_provider if llm_provider else settings.DEFAULT_LLM_PROVIDER
        print(f"[Deep Agent API] LLM provider requested: {llm_provider}, using: {effective_provider}")

        # Validate LLM provider
        provider_name = validate_llm_provider(effective_provider)
        print(f"[Deep Agent API] Validating API key for: {provider_name}")
        validate_api_key(provider_name)
        print(f"[Deep Agent API] Validation passed")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Deep Agent API] ERROR in setup: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Setup error: {str(e)}")

    # Get default model based on provider
    if not model:
        model_defaults = {
            "anthropic": "claude-sonnet-4-20250514",
            "openai": "gpt-4o",
            "groq": "llama-3.1-8b-instant"
        }
        model = model_defaults.get(provider_name, "llama-3.1-8b-instant")

    # Create event queue for SSE bridging
    event_queue = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def broadcast_wrapper(event: Dict[str, Any]):
        """
        Wrapper to queue events for async SSE broadcast.
        This is called from the sync LangGraph execution in a thread pool.
        """
        try:
            # Use the main event loop captured at request time
            main_loop.call_soon_threadsafe(event_queue.put_nowait, event)
        except Exception as e:
            # Log but don't fail if broadcast fails
            print(f"SSE broadcast error: {e}")

    # Start SSE broadcaster task
    async def broadcast_events():
        """Background task to broadcast queued events via SSE."""
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                await sse_manager.broadcast(session_id, event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"SSE broadcast error: {e}")
                continue

    # Broadcast initial event
    await sse_manager.broadcast(session_id, {
        "type": "api_call",
        "method": "POST",
        "url": "/api/v1/deep-agent/run",
        "payload": {
            "test_cases": len(raw_data),
            "llm_provider": provider_name,
            "model": model,
            "headless": headless,
            "max_retries": max_retries
        },
        "response": {"status": "started"}
    })

    # Start broadcaster
    broadcaster_task = asyncio.create_task(broadcast_events())

    try:
        # Run Deep Agent in thread pool to avoid blocking
        print(f"[Deep Agent] Starting workflow for session {session_id}")
        print(f"[Deep Agent] Raw data: {len(raw_data)} test cases")
        print(f"[Deep Agent] Config: provider={provider_name}, model={model}, headless={headless}")

        # Lazy import to catch errors
        run_deep_agent = get_run_deep_agent()
        print(f"[Deep Agent] Import successful, starting execution...")

        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: run_deep_agent(
                raw_data=raw_data,
                project_name=project_name,
                session_id=session_id,
                base_url=base_url,
                llm_provider=provider_name,
                model=model,
                headless=headless,
                timeout=timeout,
                max_retries=max_retries,
                broadcast_func=broadcast_wrapper
            )
        )

        print(f"[Deep Agent] Workflow completed successfully")
        print(f"[Deep Agent] Final result keys: {list(result.keys()) if result else 'None'}")
        print(f"[Deep Agent] execution_results: {result.get('execution_results') if result else 'None'}")
        print(f"[Deep Agent] validation_status: {result.get('validation_status') if result else 'None'}")

        # Give broadcaster time to send remaining events
        await asyncio.sleep(0.5)

        # Extract response data from final state (handle None values)
        execution_results = result.get("execution_results") or {}
        report_data = result.get("report_data") or {}
        generated_script = result.get("generated_script")
        validation_status = result.get("validation_status", "unknown")

        # Safely extract stats from execution_results
        passed = execution_results.get("passed", 0) if isinstance(execution_results, dict) else 0
        failed = execution_results.get("failed", 0) if isinstance(execution_results, dict) else 0
        total = execution_results.get("total", len(raw_data)) if isinstance(execution_results, dict) else len(raw_data)

        # Check for workflow errors
        workflow_errors = result.get("errors", [])
        if workflow_errors:
            print(f"[Deep Agent] Workflow had errors: {workflow_errors}")

        # Determine overall status
        if validation_status == "failed" or workflow_errors:
            status = "error" if workflow_errors else "failed"
            message = f"Deep Agent failed: {workflow_errors[0] if workflow_errors else 'Tests failed'}"
        else:
            status = "success"
            message = f"Deep Agent completed - {passed}/{total} passed"

        return {
            "status": status,
            "message": message,
            "validation_status": validation_status,
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "retries": result.get("retry_count", 0)
            },
            "execution_results": execution_results,
            "report": report_data,
            "generated_script": generated_script,
            "errors": result.get("errors", []),
            "completed_at": datetime.now().isoformat()
        }

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Deep Agent error: {error_details}")

        await sse_manager.broadcast(session_id, {
            "type": "deep_agent_complete",
            "status": "error",
            "message": str(e)
        })

        raise HTTPException(
            status_code=500,
            detail=f"Deep Agent execution failed: {str(e)}"
        )

    finally:
        # Cancel broadcaster
        broadcaster_task.cancel()
        try:
            await broadcaster_task
        except asyncio.CancelledError:
            pass


@router.get("/status/{session_id}")
async def get_deep_agent_status(
    session_id: str
):
    """
    Get the current status of a Deep Agent execution.

    This is a lightweight endpoint to check if an execution is running
    and its current phase.
    """
    # Check if session has active SSE connections
    has_connections = session_id in sse_manager.queues
    connection_count = len(sse_manager.queues.get(session_id, []))

    return {
        "session_id": session_id,
        "has_active_connections": has_connections,
        "connection_count": connection_count
    }


@router.post("/run-from-parsed")
async def run_deep_agent_from_parsed(
    input_data: Dict[str, Any] = Body(...),
    session_id: str = Query(..., description="Session ID for SSE updates"),
    headless: Optional[bool] = Query(
        default=True,
        description="Run browser in headless mode"
    ),
    timeout: Optional[int] = Query(
        default=30000,
        description="Timeout for each action in milliseconds"
    ),
    max_retries: Optional[int] = Query(
        default=2,
        description="Maximum number of retry attempts for failed tests"
    )
):
    """
    Run Deep Agent from an already-parsed test suite.

    Use this endpoint when you already have a parsed test suite
    (from /parse-enhanced) and want to run just the execution,
    validation, and retry phases.

    This skips the parse node and starts directly with execution.
    """
    # Extract test suite from input
    if "result" in input_data:
        test_suite = input_data["result"]
    else:
        test_suite = input_data

    if not test_suite.get("test_cases"):
        raise HTTPException(
            status_code=400,
            detail="Input must contain parsed test suite with 'test_cases'"
        )

    # Create event queue for SSE bridging
    event_queue = asyncio.Queue()

    def broadcast_wrapper(event: Dict[str, Any]):
        try:
            asyncio.get_event_loop().call_soon_threadsafe(
                event_queue.put_nowait, event
            )
        except Exception:
            pass

    async def broadcast_events():
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                await sse_manager.broadcast(session_id, event)
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue

    await sse_manager.broadcast(session_id, {
        "type": "api_call",
        "method": "POST",
        "url": "/api/v1/deep-agent/run-from-parsed",
        "payload": {
            "test_cases": len(test_suite.get("test_cases", [])),
            "headless": headless,
            "max_retries": max_retries
        },
        "response": {"status": "started"}
    })

    broadcaster_task = asyncio.create_task(broadcast_events())

    try:
        # Import execute and validate nodes directly
        from app.agents.deep_agent.nodes import execute_node, validate_node, report_node, error_recovery_node
        from app.agents.deep_agent.state import TestAutomationState

        # Create initial state with pre-parsed suite
        state: TestAutomationState = {
            "raw_data": [],
            "project_name": test_suite.get("project", "Test Suite"),
            "base_url": test_suite.get("base_url"),
            "llm_provider": "groq",
            "model": "llama-3.1-8b-instant",
            "session_id": session_id,
            "headless": headless,
            "timeout": timeout,
            "parsed_suite": test_suite,  # Pre-populated
            "execution_results": None,
            "validation_status": "pending",
            "validation_errors": [],
            "failed_tests": [],
            "retry_count": 0,
            "max_retries": max_retries,
            "report_data": None,
            "generated_script": None,
            "current_step": "ready_for_execution",
            "errors": [],
            "broadcast_func": broadcast_wrapper
        }

        # Run execution → validate → (retry loop) → report manually
        loop = asyncio.get_event_loop()

        def run_workflow():
            nonlocal state
            current_state = dict(state)

            # Broadcast start
            broadcast_wrapper({
                "type": "agent_phase",
                "phase": "starting",
                "message": "Deep Agent workflow starting (from parsed)..."
            })

            retry_count = 0
            while retry_count <= max_retries:
                # Execute
                exec_result = execute_node(current_state)
                current_state.update(exec_result)

                # Validate
                val_result = validate_node(current_state)
                current_state.update(val_result)

                validation_status = current_state.get("validation_status")

                if validation_status == "passed":
                    break
                elif validation_status == "needs_retry" and retry_count < max_retries:
                    # Error recovery
                    recovery_result = error_recovery_node(current_state)
                    current_state.update(recovery_result)
                    retry_count += 1
                else:
                    # Failed, no more retries
                    break

            # Generate report
            report_result = report_node(current_state)
            current_state.update(report_result)

            broadcast_wrapper({
                "type": "agent_phase",
                "phase": "complete",
                "message": "Deep Agent workflow completed"
            })

            return current_state

        result = await loop.run_in_executor(None, run_workflow)

        await asyncio.sleep(0.5)

        execution_results = result.get("execution_results", {})
        passed = execution_results.get("passed", 0)
        failed = execution_results.get("failed", 0)
        total = execution_results.get("total", 0)

        return {
            "status": "success",
            "message": f"Deep Agent completed - {passed}/{total} passed",
            "validation_status": result.get("validation_status", "unknown"),
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "retries": result.get("retry_count", 0)
            },
            "execution_results": execution_results,
            "report": result.get("report_data"),
            "generated_script": result.get("generated_script"),
            "errors": result.get("errors", []),
            "completed_at": datetime.now().isoformat()
        }

    except Exception as e:
        import traceback
        print(f"Deep Agent error: {traceback.format_exc()}")

        await sse_manager.broadcast(session_id, {
            "type": "deep_agent_complete",
            "status": "error",
            "message": str(e)
        })

        raise HTTPException(
            status_code=500,
            detail=f"Deep Agent execution failed: {str(e)}"
        )

    finally:
        broadcaster_task.cancel()
        try:
            await broadcaster_task
        except asyncio.CancelledError:
            pass


@router.post("/run-multi-agent")
async def run_multi_agent_endpoint(
    input_data: Dict[str, Any] = Body(...),
    session_id: str = Query(..., description="Session ID for SSE updates"),
    llm_provider: Optional[str] = Query(
        default=None,
        description="LLM provider to use: anthropic, openai, or groq"
    ),
    model: Optional[str] = Query(
        default=None,
        description="Model to use for sub-agents"
    ),
    project_name: Optional[str] = Query(
        default="Automation Project",
        description="Name for the test project"
    ),
    base_url: Optional[str] = Query(
        default=None,
        description="Base URL for tests"
    ),
    headless: Optional[bool] = Query(
        default=True,
        description="Run browser in headless mode"
    ),
    timeout: Optional[int] = Query(
        default=30000,
        description="Timeout for each action in milliseconds"
    ),
    max_retries: Optional[int] = Query(
        default=2,
        description="Maximum number of retry attempts"
    )
):
    """
    Run the Multi-Agent Deep automation system.

    This uses a supervisor agent that coordinates specialized sub-agents:
    - ParserAgent: Parses raw test cases using LLM
    - ExecutorAgent: Runs tests in Playwright browser
    - ValidatorAgent: Analyzes results, decides on retries
    - ReporterAgent: Generates reports and scripts

    The supervisor LLM decides which sub-agent to delegate to at each step,
    creating intelligent workflow coordination.

    **SSE Events:**
    - thoughts: Supervisor reasoning
    - delegation: Sub-agent being called
    - sub_agent_started/completed: Sub-agent lifecycle
    - deep_agent_complete: Workflow finished
    """
    print(f"[Multi-Agent] Received request for session {session_id}")

    try:
        # Extract raw_data
        if "raw_data" in input_data:
            raw_data = input_data["raw_data"]
        elif "result" in input_data and "raw_data" in input_data["result"]:
            raw_data = input_data["result"]["raw_data"]
        elif "result" in input_data and isinstance(input_data["result"], list):
            raw_data = input_data["result"]
        else:
            raise HTTPException(
                status_code=400,
                detail="Input must contain 'raw_data' field with test case data"
            )

        if not raw_data or not isinstance(raw_data, list):
            raise HTTPException(
                status_code=400,
                detail="raw_data must be a non-empty list of test cases"
            )

        # Use default LLM provider if not specified
        effective_provider = llm_provider if llm_provider else settings.DEFAULT_LLM_PROVIDER
        provider_name = validate_llm_provider(effective_provider)
        validate_api_key(provider_name)

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Multi-Agent] Setup error: {e}")
        raise HTTPException(status_code=500, detail=f"Setup error: {str(e)}")

    # Get default model
    if not model:
        model_defaults = {
            "anthropic": "claude-sonnet-4-20250514",
            "openai": "gpt-4o",
            "groq": "llama-3.1-8b-instant"
        }
        model = model_defaults.get(provider_name, "llama-3.1-8b-instant")

    # Create event queue for SSE
    event_queue = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def broadcast_wrapper(event: Dict[str, Any]):
        try:
            main_loop.call_soon_threadsafe(event_queue.put_nowait, event)
        except Exception as e:
            print(f"SSE broadcast error: {e}")

    async def broadcast_events():
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                await sse_manager.broadcast(session_id, event)
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue

    # Initial broadcast
    await sse_manager.broadcast(session_id, {
        "type": "api_call",
        "method": "POST",
        "url": "/api/v1/deep-agent/run-multi-agent",
        "payload": {
            "test_cases": len(raw_data),
            "llm_provider": provider_name,
            "model": model,
            "headless": headless,
            "max_retries": max_retries,
            "mode": "multi-agent"
        },
        "response": {"status": "started"}
    })

    broadcaster_task = asyncio.create_task(broadcast_events())

    try:
        # Import multi-agent orchestrator
        from app.agents.deep_agent import run_multi_agent

        print(f"[Multi-Agent] Starting with {len(raw_data)} test cases")
        print(f"[Multi-Agent] Config: provider={provider_name}, model={model}")

        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: run_multi_agent(
                raw_data=raw_data,
                project_name=project_name,
                base_url=base_url,
                llm_provider=provider_name,
                model=model,
                headless=headless,
                timeout=timeout,
                max_retries=max_retries,
                broadcast_func=broadcast_wrapper
            )
        )

        print(f"[Multi-Agent] Completed: {result.get('summary', {})}")

        await asyncio.sleep(0.5)

        execution_results = result.get("execution_results") or {}
        passed = execution_results.get("passed", 0) if isinstance(execution_results, dict) else 0
        failed = execution_results.get("failed", 0) if isinstance(execution_results, dict) else 0
        total = execution_results.get("total", len(raw_data)) if isinstance(execution_results, dict) else len(raw_data)

        return {
            "status": result.get("status", "completed"),
            "message": f"Multi-Agent completed - {passed}/{total} passed",
            "validation_status": result.get("validation_status"),
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "retries": result.get("summary", {}).get("retries", 0)
            },
            "execution_results": execution_results,
            "parsed_suite": result.get("parsed_suite"),
            "report": result.get("report"),
            "generated_script": result.get("generated_script"),
            "orchestration": result.get("orchestration", {}),
            "errors": result.get("errors", []),
            "completed_at": datetime.now().isoformat()
        }

    except Exception as e:
        error_details = traceback.format_exc()
        print(f"[Multi-Agent] Error: {error_details}")

        await sse_manager.broadcast(session_id, {
            "type": "deep_agent_complete",
            "status": "error",
            "message": str(e)
        })

        raise HTTPException(
            status_code=500,
            detail=f"Multi-Agent execution failed: {str(e)}"
        )

    finally:
        broadcaster_task.cancel()
        try:
            await broadcaster_task
        except asyncio.CancelledError:
            pass
