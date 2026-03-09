"""
Recorder API Routes
Provides endpoints for the conversational test recorder:
  POST /recorder/start    — launch browser, navigate to URL
  POST /recorder/command  — execute a natural language command on the live page
  POST /recorder/complete — close browser, build + return EnhancedTestSuite
  POST /recorder/export   — export successful steps as a downloadable JSON file
  POST /recorder/cancel   — close browser, discard session
"""
import asyncio
import concurrent.futures
import json
import logging
import threading
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.sse_manager import sse_manager
from app.services.recorder_session_manager import recorder_session_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Request / Response models
# ─────────────────────────────────────────────────────────────

class StartRecorderRequest(BaseModel):
    url: str
    session_id: str
    app_name: Optional[str] = "My App"
    test_email: Optional[str] = "test@example.com"
    test_password: Optional[str] = "password123"
    headless: Optional[bool] = False


class CommandRequest(BaseModel):
    session_id: str
    command: str
    llm_provider: Optional[str] = None


class CompleteRequest(BaseModel):
    session_id: str
    app_name: Optional[str] = None
    base_url: Optional[str] = None


class CancelRequest(BaseModel):
    session_id: str


class ExportRequest(BaseModel):
    session_id: str
    app_name: Optional[str] = None
    base_url: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _validate_provider(provider_name: str) -> str:
    valid = ["anthropic", "openai", "groq"]
    p = provider_name.lower()
    if p not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider_name}. Choose from {valid}")
    return p


def _validate_api_key(provider: str) -> None:
    key_map = {
        "anthropic": settings.ANTHROPIC_API_KEY,
        "openai": settings.OPENAI_API_KEY,
        "groq": settings.GROQ_API_KEY,
    }
    key = key_map.get(provider, "")
    placeholder_vals = {"your_anthropic_api_key_here", "your_openai_api_key_here", "your_groq_api_key_here", ""}
    if not key or key in placeholder_vals:
        raise HTTPException(status_code=500, detail=f"{provider.upper()}_API_KEY not configured in .env")


async def _run_in_plain_thread(fn, *args):
    """
    Run a synchronous callable in a plain OS thread that has NO asyncio event
    loop set.  This is required for Playwright's sync API, which refuses to run
    inside a thread that has an event loop (including asyncio's thread-pool
    executor threads which inherit the loop from the main thread).
    """
    future: concurrent.futures.Future = concurrent.futures.Future()

    def _worker():
        try:
            result = fn(*args)
            future.set_result(result)
        except Exception as exc:
            future.set_exception(exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    # Poll until the thread finishes, yielding control to asyncio between polls
    while not future.done():
        await asyncio.sleep(0.05)
    return future.result()


async def _broadcast_screenshot(session_id: str, image_b64: str, current_url: str, step_number: int) -> None:
    """Send screenshot event via SSE."""
    await sse_manager.broadcast(session_id, {
        "type": "recorder_screenshot",
        "image_b64": image_b64,
        "current_url": current_url,
        "step_number": step_number,
    })


def _make_ref_instruction(s: dict) -> str:
    """
    Return a step instruction that uses reference keys ({Email}, {Password}, etc.)
    instead of literal values, so real data stays in the Input data column only.

    For goto steps, always include the URL in the instruction.
    """
    action_type = s.get("action_type", "")
    instruction = s.get("instruction", "")
    td = s.get("test_data") or {}

    if action_type == "goto":
        return "Navigate to Application url"

    if action_type == "verify_url":
        url = s.get("value") or (s.get("test_data") or {}).get("url", "")
        return f"Verify the page navigated to {url}" if url else s.get("instruction", "Verify page URL")

    if action_type == "fill":
        element_name = s.get("element_name") or ""
        element_type = s.get("element_type") or "field"
        # Determine reference key from test_data keys or instruction keywords
        ref_key = None
        for k in td:
            ref_key = {"email": "Email", "password": "Password"}.get(
                k.lower(), k.replace("_", " ").title()
            )
            break  # use first key
        if not ref_key:
            if "email" in instruction.lower() or "email" in element_name.lower():
                ref_key = "Email"
            elif "password" in instruction.lower() or "password" in element_name.lower():
                ref_key = "Password"
        # Use element_name as the field label if available, else element_type
        field_label = element_name if element_name else element_type
        if ref_key:
            return f"Fill {field_label} with {ref_key}"
        return instruction

    return instruction


def _build_tc_steps(steps: list) -> list:
    """Convert raw recorded steps into EnhancedTestSuite step format."""
    tc_steps = []
    for s in steps:
        action_type = s.get("action_type", "")
        step_test_data = s.get("test_data") or {}
        if action_type == "goto":
            url = s.get("value") or s.get("selector") or step_test_data.get("url", "")
            if url:
                step_test_data = {**step_test_data, "url": url}
        tc_steps.append({
            "step_number": s.get("step_number"),
            "instruction": _make_ref_instruction(s),
            "action": {
                "type": action_type,
                "playwright_method": s.get("playwright_method", ""),
            },
            "selector_hints": {
                "element_name": s.get("element_name"),
                "element_type": s.get("element_type"),
                "suggested_selectors": [s["selector"]] if s.get("selector") else [],
            },
            "test_data": step_test_data,
            "assertions": s.get("assertions"),
        })
    return tc_steps


def _build_enhanced_test_suite(
    test_cases: list,
    app_name: str,
    base_url: str,
    test_email: str,
    test_password: str,
) -> dict:
    """
    Wrap recorded test cases into EnhancedTestSuite format.
    test_cases: list of {name, steps} dicts — one entry per finalized case.
    """
    built_cases = []
    for idx, tc in enumerate(test_cases):
        case_id = f"TC_{idx + 1:03d}"
        built_cases.append({
            "id": case_id,
            "name": tc.get("name") or f"Recorded Test {idx + 1}",
            "steps": _build_tc_steps(tc.get("steps", [])),
            "expected_results": ["All recorded steps execute successfully"],
        })

    return {
        "project": f"{app_name} Tests",
        "base_url": base_url,
        "common_selectors": {},
        "test_data": {
            "default_credentials": {
                "email": test_email,
                "password": test_password,
            }
        },
        "test_cases": built_cases,
    }


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/recorder/start")
async def recorder_start(request: StartRecorderRequest):
    """
    Launch a browser, navigate to the given URL, and return the first screenshot.
    The browser stays open for subsequent commands.
    """
    logger.info(f"[recorder/start] session={request.session_id} url={request.url}")

    def _launch():
        # start_session() internally calls run_in_pw_thread() for init_browser,
        # so all Playwright work happens on the session's dedicated pw thread.
        session = recorder_session_manager.start_session(
            session_id=request.session_id,
            url=request.url,
            headless=request.headless,
        )
        # take_screenshot_b64() also dispatches to the pw thread internally
        screenshot_b64 = session.take_screenshot_b64()
        # get current URL via pw thread
        current_url = session.run_in_pw_thread(lambda: session.page.url)
        return current_url, screenshot_b64

    try:
        current_url, screenshot_b64 = await _run_in_plain_thread(_launch)
    except Exception as e:
        logger.error(f"[recorder/start] Failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start recorder: {str(e)}")

    # Broadcast screenshot via SSE
    await _broadcast_screenshot(request.session_id, screenshot_b64, current_url, 0)

    return {
        "success": True,
        "session_id": request.session_id,
        "status": "started",
        "current_url": current_url,
        "screenshot_b64": screenshot_b64,
    }


@router.post("/recorder/command")
async def recorder_command(
    request: CommandRequest,
    llm_provider: Optional[str] = Query(default=None),
):
    """
    Execute a natural language paragraph on the live browser page.
    The paragraph is parsed by the RecorderAgent into multiple atomic actions,
    each is executed sequentially. A screenshot is taken after each step and
    broadcast via SSE. Returns all executed steps.
    """
    session = recorder_session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found. Call /recorder/start first.")

    provider_name = request.llm_provider or llm_provider or settings.DEFAULT_LLM_PROVIDER
    provider_name = _validate_provider(provider_name)
    _validate_api_key(provider_name)

    logger.info(f"[recorder/command] session={request.session_id} paragraph={request.command!r}")

    from app.agents.recorder_agent import RecorderAgent
    from app.agents.base_agent import LLMProvider as AgentLLMProvider

    # Capture the running event loop so the background thread can push SSE immediately
    loop = asyncio.get_event_loop()

    def _broadcast_now(image_b64: str, current_url: str, step_number: int) -> None:
        """Fire-and-forget SSE broadcast from the background thread."""
        asyncio.run_coroutine_threadsafe(
            _broadcast_screenshot(request.session_id, image_b64, current_url, step_number),
            loop,
        )

    def _ask_llm_about_errors(agent, action: dict, errors: list, current_url: str) -> str:
        try:
            errors_text = "\n".join(f"  - {e}" for e in errors)
            prompt = f"""A test recorder executed this action:
Action: {action.get('action_type')} | Element: {action.get('element_name') or action.get('selector')} | Value: {action.get('value')}
Instruction: {action.get('instruction')}
Page: {current_url}

Inline validation errors found on page after the action:
{errors_text}

In 1-2 sentences, explain what went wrong and what the user should change in their next command to fix it. Be specific."""
            return agent.call_llm(prompt).strip()
        except Exception:
            return f"Validation error: {'; '.join(errors)}"

    def _execute():
        agent = RecorderAgent(provider=AgentLLMProvider(provider_name))

        # ── Step 1: parse the paragraph into atomic actions (needs page context)
        context_summary = session.get_context_summary()
        actions = session.run_in_pw_thread(
            lambda: agent.parse_multi_step_command(request.command, session.page, context_summary)
        )
        logger.info(f"[recorder/command] parsed {len(actions)} atomic action(s)")

        executed_steps = []
        last_screenshot_b64 = session.take_screenshot_b64()
        last_url = session.run_in_pw_thread(lambda: session.page.url)

        # ── Step 2: execute each action on the pw thread
        for action in actions:
            error_msg = None
            url_before = last_url
            # Capture screenshot before each action for image-analysis fallback
            pre_action_screenshot = last_screenshot_b64

            def _run_action(a=action, ss=pre_action_screenshot):
                agent.execute_action(a, session.page, screenshot_b64=ss)

            action_start = datetime.utcnow()
            try:
                session.run_in_pw_thread(_run_action)
            except Exception as e:
                logger.warning(f"Action execution error: {e}")
                error_msg = str(e)
            execution_time_ms = int((datetime.utcnow() - action_start).total_seconds() * 1000)

            def _pause_and_capture(pre_url=url_before, has_error=bool(error_msg)):
                import base64 as _b64
                if not has_error:
                    session.page.wait_for_timeout(1000)
                    url_now = session.page.url
                    if url_now != pre_url:
                        session.page.wait_for_timeout(1000)
                data = session.page.screenshot(full_page=False)
                return _b64.b64encode(data).decode("utf-8"), session.page.url

            last_screenshot_b64, last_url = session.run_in_pw_thread(_pause_and_capture)

            # Post-action inline error scan
            validation_errors = []
            ai_suggestion = None
            if not error_msg:
                validation_errors = session.run_in_pw_thread(
                    lambda: agent._scan_page_errors(session.page)
                )
                if validation_errors:
                    logger.warning(f"Inline errors after step: {validation_errors}")
                    ai_suggestion = _ask_llm_about_errors(agent, action, validation_errors, last_url)

            step = {
                "action_type": action.get("action_type", ""),
                "selector": action.get("selector", ""),
                "value": action.get("value", ""),
                "instruction": action.get("instruction", request.command),
                "playwright_method": action.get("playwright_method", ""),
                "element_name": action.get("element_name"),
                "element_type": action.get("element_type"),
                "test_data": action.get("test_data"),
                "assertions": action.get("assertions"),
                "command": request.command,
                "executed_at": action_start.isoformat(),
                "execution_time_ms": execution_time_ms,
                "error": error_msg,
                "validation_errors": validation_errors,
                "ai_suggestion": ai_suggestion,
            }
            session.add_step(step)
            step_number = len(session.steps)
            executed_steps.append({
                **step,
                "screenshot_b64": last_screenshot_b64,
                "current_url": last_url,
                "step_number": step_number,
            })

            # ── Broadcast screenshot + step data immediately after each step ──
            _broadcast_now(last_screenshot_b64, last_url, step_number)
            asyncio.run_coroutine_threadsafe(
                sse_manager.broadcast(request.session_id, {
                    "type": "recorder_step",
                    "step": {k: v for k, v in {**step, "step_number": step_number}.items()
                             if k != "screenshot_b64"},
                    "current_url": last_url,
                }),
                loop,
            )

            # If URL changed, insert a verify_url step with a fresh screenshot
            if last_url != url_before and not error_msg:
                logger.info(f"[recorder/command] Navigation detected: {url_before} → {last_url}")
                nav_screenshot_b64 = session.take_screenshot_b64()
                nav_step = {
                    "action_type": "verify_url",
                    "selector": "",
                    "value": last_url,
                    "instruction": f"Verify the page navigated to {last_url}",
                    "playwright_method": "expect(page).to_have_url",
                    "element_name": None,
                    "element_type": None,
                    "test_data": {"url": last_url},
                    "assertions": [{"type": "url", "expected_value": last_url, "playwright_assertion": f"expect(page).to_have_url('{last_url}')"}],
                    "command": request.command,
                    "executed_at": datetime.utcnow().isoformat(),
                    "execution_time_ms": 0,
                    "error": None,
                }
                session.add_step(nav_step)
                nav_step_number = len(session.steps)
                executed_steps.append({
                    **nav_step,
                    "screenshot_b64": nav_screenshot_b64,
                    "current_url": last_url,
                    "step_number": nav_step_number,
                })
                _broadcast_now(nav_screenshot_b64, last_url, nav_step_number)
                asyncio.run_coroutine_threadsafe(
                    sse_manager.broadcast(request.session_id, {
                        "type": "recorder_step",
                        "step": {**nav_step, "step_number": nav_step_number},
                        "current_url": last_url,
                    }),
                    loop,
                )
                last_screenshot_b64 = nav_screenshot_b64

            if error_msg:
                logger.warning(f"[recorder/command] Step {len(session.steps)} failed — continuing with next step")

        return executed_steps, last_screenshot_b64, last_url

    try:
        executed_steps, screenshot_b64, current_url = await _run_in_plain_thread(_execute)
    except Exception as e:
        logger.error(f"[recorder/command] Failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Command failed: {str(e)}")

    # Strip the screenshot data from the step records before returning
    # (screenshot is available via SSE and in final screenshot_b64 field)
    clean_steps = [
        {k: v for k, v in s.items() if k not in ("screenshot_b64", "current_url")}
        for s in executed_steps
    ]

    return {
        "success": True,
        "steps": clean_steps,
        "screenshot_b64": screenshot_b64,
        "current_url": current_url,
        "step_number": len(session.steps),
        "error": executed_steps[-1].get("error") if executed_steps else None,
    }


@router.post("/recorder/complete")
async def recorder_complete(request: CompleteRequest):
    """
    Close the browser, finalize the recorded test suite, and return it.
    Returns the same EnhancedTestSuite format as /generate-from-url.
    """
    session = recorder_session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found.")

    # Capture metadata before closing
    base_url = request.base_url or session.base_url

    # Auto-finalize any remaining in-progress steps as the last case
    if session.steps:
        case_name = f"Test Case {len(session.test_cases) + 1}"
        session.finalize_current_case(case_name)

    all_cases = list(session.test_cases)

    # Derive app name
    app_name = request.app_name
    if not app_name:
        try:
            parsed = urlparse(base_url)
            app_name = parsed.netloc.split(".")[0].title() or "My App"
        except Exception:
            app_name = "My App"

    # Retrieve test credentials from any fill step across all cases
    test_email = "test@example.com"
    test_password = "password123"
    for tc in all_cases:
        for s in tc.get("steps", []):
            td = s.get("test_data") or {}
            if isinstance(td, dict):
                if td.get("email"):
                    test_email = td["email"]
                if td.get("password"):
                    test_password = td["password"]

    # Build export JSON (successful steps + execution_time_ms) BEFORE closing session
    export_json = _build_export_json(session, app_name, base_url)

    # Close the browser
    recorder_session_manager.close_session(request.session_id)

    if not all_cases:
        raise HTTPException(status_code=400, detail="No steps were recorded. Nothing to complete.")

    test_suite = _build_enhanced_test_suite(
        test_cases=all_cases,
        app_name=app_name,
        base_url=base_url,
        test_email=test_email,
        test_password=test_password,
    )

    total_steps = sum(len(tc.get("steps", [])) for tc in all_cases)
    tc_count = len(test_suite.get("test_cases", []))
    logger.info(f"[recorder/complete] session={request.session_id} steps={total_steps} tcs={tc_count}")

    return {
        "success": True,
        "message": f"Recorded {total_steps} step(s) into {tc_count} test case(s)",
        "session_id": request.session_id,
        "test_suite": test_suite,
        "step_count": total_steps,
        "export_json": export_json,
    }


@router.post("/recorder/new-case")
async def recorder_new_case(request: CancelRequest):
    """
    Finalize the current in-progress steps as a completed test case,
    then reset the step buffer so subsequent commands go into the next case.
    The browser stays open — recording continues uninterrupted.
    """
    session = recorder_session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found.")

    if not session.steps:
        raise HTTPException(status_code=400, detail="No steps in current case. Record at least one step before starting a new case.")

    case_name = f"Test Case {len(session.test_cases) + 1}"
    finalized_count = session.finalize_current_case(case_name)
    case_number = len(session.test_cases)

    logger.info(f"[recorder/new-case] session={request.session_id} case={case_name} steps={finalized_count}")

    await sse_manager.broadcast(request.session_id, {
        "type": "recorder_new_case",
        "case_number": case_number,
        "case_name": case_name,
        "steps_finalized": finalized_count,
    })

    return {
        "success": True,
        "case_number": case_number,
        "case_name": case_name,
        "steps_finalized": finalized_count,
        "message": f"{case_name} saved ({finalized_count} step(s)). Recording next case.",
    }


def _build_export_json(session, app_name: str, base_url: str) -> dict:
    """
    Build the export JSON from a recording session.
    Only includes successfully executed steps (no error).
    Preserves test case grouping and adds execution_time_ms to each step.
    """
    test_email = "test@example.com"
    test_password = "password123"

    # Combine finalized cases + any in-progress steps as a final case
    all_cases = list(session.test_cases)
    if session.steps:
        all_cases = all_cases + [{
            "name": f"Test Case {len(all_cases) + 1}",
            "steps": list(session.steps),
        }]

    built_cases = []
    for idx, tc in enumerate(all_cases):
        raw_steps = tc.get("steps", [])

        # Keep only steps that executed without error
        successful_steps = [s for s in raw_steps if not s.get("error")]
        if not successful_steps:
            continue

        # Harvest credentials for test_data
        for s in successful_steps:
            td = s.get("test_data") or {}
            if td.get("email"):
                test_email = td["email"]
            if td.get("password"):
                test_password = td["password"]

        tc_steps = []
        for i, s in enumerate(successful_steps):
            action_type = s.get("action_type", "")
            step_test_data = dict(s.get("test_data") or {})
            if action_type == "goto":
                url = s.get("value") or s.get("selector") or step_test_data.get("url", "")
                if url:
                    step_test_data["url"] = url

            tc_steps.append({
                "step_number": i + 1,
                "instruction": _make_ref_instruction(s),
                "action": {
                    "type": action_type,
                    "playwright_method": s.get("playwright_method", ""),
                },
                "selector_hints": {
                    "element_name": s.get("element_name"),
                    "element_type": s.get("element_type"),
                    "suggested_selectors": [s["selector"]] if s.get("selector") else [],
                },
                "test_data": step_test_data or None,
                "assertions": s.get("assertions"),
                "executed_at": s.get("executed_at", ""),
                "execution_time_ms": s.get("execution_time_ms", 0),
            })

        built_cases.append({
            "id": f"TC_{idx + 1:03d}",
            "name": tc.get("name") or f"Test Case {idx + 1}",
            "steps": tc_steps,
            "expected_results": ["All recorded steps execute successfully"],
        })

    return {
        "project": app_name,
        "base_url": base_url,
        "session_id": session.session_id,
        "exported_at": datetime.utcnow().isoformat(),
        "common_selectors": {},
        "test_data": {
            "default_credentials": {
                "email": test_email,
                "password": test_password,
            }
        },
        "test_cases": built_cases,
    }


@router.post("/recorder/export")
async def recorder_export(request: ExportRequest):
    """
    Export successfully executed steps from the current recording session as a
    downloadable JSON file. The session stays open — recording continues unaffected.

    Only steps that completed without error are included.
    Each step carries execution_time_ms (wall-clock ms the action took to run).
    """
    session = recorder_session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found.")

    base_url = request.base_url or session.base_url
    app_name = request.app_name
    if not app_name:
        try:
            parsed = urlparse(base_url)
            app_name = parsed.netloc.split(".")[0].title() or "Recording"
        except Exception:
            app_name = "Recording"

    export_data = _build_export_json(session, app_name, base_url)

    total_steps = sum(len(tc["steps"]) for tc in export_data["test_cases"])
    if total_steps == 0:
        raise HTTPException(
            status_code=400,
            detail="No successfully executed steps to export. Record at least one successful step first.",
        )

    filename = f"recording_{session.session_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    logger.info(
        f"[recorder/export] session={request.session_id} "
        f"cases={len(export_data['test_cases'])} steps={total_steps}"
    )

    return FastAPIResponse(
        content=json.dumps(export_data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/recorder/cancel")
async def recorder_cancel(request: CancelRequest):
    """
    Cancel the recording session — close the browser and discard all steps.
    """
    session = recorder_session_manager.get_session(request.session_id)
    recorder_session_manager.close_session(request.session_id)

    if not session:
        return {"success": True, "message": "Session not found (already closed or never started)"}

    logger.info(f"[recorder/cancel] session={request.session_id} discarded {len(session.steps)} step(s)")
    return {
        "success": True,
        "message": f"Recording cancelled. {len(session.steps)} step(s) discarded.",
        "session_id": request.session_id,
    }


@router.get("/recorder/session/{session_id}")
async def recorder_session_status(session_id: str):
    """Get current status and steps of a recording session."""
    session = recorder_session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    def _get_status():
        try:
            current_url = session.run_in_pw_thread(lambda: session.page.url)
            screenshot_b64 = session.take_screenshot_b64()
        except Exception:
            current_url = session.base_url
            screenshot_b64 = ""
        return current_url, screenshot_b64

    current_url, screenshot_b64 = await _run_in_plain_thread(_get_status)

    return {
        "session_id": session_id,
        "status": "active",
        "current_url": current_url,
        "step_count": len(session.steps),
        "steps": session.steps,
        "started_at": session.started_at,
        "screenshot_b64": screenshot_b64,
    }
