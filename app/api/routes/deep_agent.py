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
import threading
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

# Per-session stop events: session_id -> threading.Event
# Set the event to signal the running orchestrator to stop immediately.
_stop_events: Dict[str, threading.Event] = {}

# Per-session step control files: session_id -> temp file path
# Used to send "next" or "skip" signals into the executor subprocess via a file.
import tempfile as _tempfile
import os as _os
_step_control_files: Dict[str, str] = {}  # session_id -> temp file path

# Result cache: session_id -> final result dict
# Stored so clients can retrieve the result even if SSE was disconnected when it fired.
_result_cache: Dict[str, Dict] = {}


@router.get("/last-result/{session_id}")
async def get_last_result(session_id: str):
    """
    Return the cached final result for a session (if available).
    Used by the frontend to recover the result when SSE was disconnected
    before deep_agent_complete was received.
    """
    result = _result_cache.get(session_id)
    if result is None:
        return {"status": "not_found"}
    return result


@router.post("/stop-execution")
async def stop_execution(session_id: str = Query(...)):
    """Signal the running orchestrator to stop immediately for the given session."""
    event = _stop_events.get(session_id)
    if event:
        event.set()
    await sse_manager.broadcast(session_id, {
        "type": "execution_stopped",
        "message": "Stop requested by user"
    })
    return {"status": "stop_requested", "session_id": session_id}


@router.post("/step-control")
async def step_control(
    session_id: str = Query(...),
    action: str = Query(..., description="'next' to mark current step done, 'skip' to skip it"),
):
    """
    Send a step-level control signal to the running executor subprocess.
    action='next'  → mark current step as complete and advance immediately
    action='skip'  → skip the current step (recorded as SKIPPED in report)
    """
    if action not in ("next", "skip"):
        raise HTTPException(status_code=400, detail="action must be 'next' or 'skip'")

    fpath = _step_control_files.get(session_id)
    if fpath is None:
        return {"status": "no_active_execution", "session_id": session_id}

    try:
        with open(fpath, "w") as f:
            f.write(action)
    except Exception:
        pass  # file write error — ignore

    await sse_manager.broadcast(session_id, {
        "type": "step_control_ack",
        "action": action,
        "message": f"Step control '{action}' sent"
    })
    return {"status": "sent", "action": action, "session_id": session_id}


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
    try:
        api_key_map = {
            "anthropic": (getattr(settings, 'ANTHROPIC_API_KEY', None), "your_anthropic_api_key_here"),
            "openai": (getattr(settings, 'OPENAI_API_KEY', None), "your_openai_api_key_here"),
            "groq": (getattr(settings, 'GROQ_API_KEY', None), "your_groq_api_key_here"),
            "waymore": (getattr(settings, 'WAYMORE_API_KEY', None), "your_waymore_api_key_here"),
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

    # Get default model based on provider — all models come from settings (config.py / .env)
    if not model:
        model_defaults = {
            "anthropic": settings.ANTHROPIC_MODEL,
            "openai": settings.OPENAI_MODEL,
            "groq": settings.GROQ_MODEL,
            "waymore": settings.WAYMORE_MODEL,
        }
        model = model_defaults.get(provider_name, settings.GROQ_MODEL)

    # Create per-session step control signal file and register it
    tf = _tempfile.NamedTemporaryFile(mode='w', suffix='.signal', delete=False)
    step_control_file = tf.name
    tf.close()  # Close immediately; subprocess will read/write it
    _step_control_files[session_id] = step_control_file

    # Create per-session stop event and register it
    stop_event = threading.Event()
    _stop_events[session_id] = stop_event

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
                broadcast_func=broadcast_wrapper,
                stop_event=stop_event,
                step_control_file=step_control_file,
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
        # Clean up per-session control structures
        _step_control_files.pop(session_id, None)
        _stop_events.pop(session_id, None)
        try:
            _os.unlink(step_control_file)
        except Exception:
            pass


@router.post("/execute-with-script")
async def execute_with_script(
    input_data: Dict[str, Any] = Body(...),
    session_id: str = Query(..., description="Session ID for SSE updates"),
    headless: Optional[bool] = Query(default=True, description="Run browser in headless mode"),
    timeout: Optional[int] = Query(default=30000, description="Timeout in milliseconds"),
):
    """
    Execute a single pre-built Playwright script string directly via subprocess.

    Accepts { script: str, test_id: str } and runs it via ScriptExecutor.
    Returns { test_id, status, stdout, stderr, executed_at }.
    """
    script: str = input_data.get("script", "")
    test_id: str = input_data.get("test_id", "TC_UNKNOWN")

    if not script:
        raise HTTPException(status_code=400, detail="'script' field is required")

    # Inject __main__ block if missing so `python script.py` works
    # --browser chromium is required by pytest-playwright for the `page` fixture
    main_block = (
        '\n\nif __name__ == "__main__":\n'
        '    import pytest as _pytest, sys as _sys, os as _os\n'
        '    _args = [__file__, "-v", "--tb=short", "--browser", "chromium"]\n'
        '    if _os.environ.get("PLAYWRIGHT_HEADLESS", "1") == "0":\n'
        '        _args.append("--headed")\n'
        '    _sys.exit(_pytest.main(_args))\n'
    )
    if 'if __name__ == "__main__"' not in script:
        script += main_block

    # Broadcast start event
    await sse_manager.broadcast(session_id, {
        "type": "test_started",
        "test_id": test_id,
        "message": f"Executing script for {test_id}..."
    })

    try:
        from app.tools.script_executor import ScriptExecutor

        executor = ScriptExecutor(headless=headless, timeout=timeout)

        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: executor.execute_script(script, test_id)
        )

        # Broadcast completion event
        await sse_manager.broadcast(session_id, {
            "type": "test_completed",
            "test_id": test_id,
            "status": result.get("status"),
            "message": f"{test_id}: {result.get('status')}"
        })

        return {
            "test_id": test_id,
            "status": result.get("status", "ERROR"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "executed_at": result.get("executed_at", datetime.now().isoformat()),
        }

    except Exception as e:
        error_details = traceback.format_exc()
        print(f"[execute-with-script] Error: {error_details}")

        await sse_manager.broadcast(session_id, {
            "type": "test_completed",
            "test_id": test_id,
            "status": "ERROR",
            "message": str(e)
        })

        raise HTTPException(
            status_code=500,
            detail=f"Script execution failed: {str(e)}"
        )


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
            "llm_provider": settings.DEFAULT_LLM_PROVIDER,
            "model": settings.GROQ_MODEL,
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
    keep_browser_open: Optional[bool] = Query(
        default=True,
        description="Keep browser open across all test cases (False = close/reopen per test case)"
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
    print(f"[Multi-Agent] Config: headless={headless}, keep_browser_open={keep_browser_open}")

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

    # Get default model — all models come from settings (config.py / .env)
    if not model:
        model_defaults = {
            "anthropic": settings.ANTHROPIC_MODEL,
            "openai": settings.OPENAI_MODEL,
            "groq": settings.GROQ_MODEL,
            "waymore": settings.WAYMORE_MODEL,
        }
        model = model_defaults.get(provider_name, settings.GROQ_MODEL)

    # Create event queue for SSE
    event_queue = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def broadcast_wrapper(event: Dict[str, Any]):
        try:
            # Populate result cache immediately when deep_agent_complete fires
            # so polling fallback can find it even before the HTTP response returns.
            if event.get("type") == "deep_agent_complete":
                summary = event.get("data") or {}
                _result_cache[session_id] = {
                    "status": event.get("status", "completed"),
                    "message": event.get("message", ""),
                    "validation_status": "passed" if summary.get("failed", 1) == 0 else "failed",
                    "summary": {
                        "total": summary.get("total", 0),
                        "passed": summary.get("passed", 0),
                        "failed": summary.get("failed", 0),
                        "retries": summary.get("retries", 0),
                    },
                    "execution_results": event.get("execution_results"),
                    "parsed_suite": event.get("parsed_suite"),
                    "report": None,
                    "generated_script": None,
                    "orchestration": event.get("orchestration", {}),
                    "errors": [],
                    "completed_at": datetime.now().isoformat(),
                }
                print(f"[Multi-Agent] Result cached for session {session_id}: {summary}")
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

    # Create and register a fresh stop event for this session
    stop_event = threading.Event()
    _stop_events[session_id] = stop_event

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
                keep_browser_open=keep_browser_open,
                timeout=timeout,
                max_retries=max_retries,
                broadcast_func=broadcast_wrapper,
                stop_event=stop_event,
            )
        )

        # Check if stop was requested
        if stop_event.is_set():
            print(f"[Multi-Agent] Stopped by user for session {session_id}")
            raise HTTPException(status_code=499, detail="Test stopped by user")

        print(f"[Multi-Agent] Completed: {result.get('summary', {})}")

        await asyncio.sleep(0.5)

        execution_results = result.get("execution_results") or {}
        passed = execution_results.get("passed", 0) if isinstance(execution_results, dict) else 0
        failed = execution_results.get("failed", 0) if isinstance(execution_results, dict) else 0
        total = execution_results.get("total", len(raw_data)) if isinstance(execution_results, dict) else len(raw_data)

        final_response = {
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

        # Cache result so frontend can retrieve it even if SSE was disconnected
        _result_cache[session_id] = final_response

        return final_response

    except HTTPException:
        raise
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
        _stop_events.pop(session_id, None)
        broadcaster_task.cancel()
        try:
            await broadcaster_task
        except asyncio.CancelledError:
            pass
