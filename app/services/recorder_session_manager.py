"""
RecorderSessionManager
Holds one persistent Playwright browser per session_id so commands can execute
on a live browser without reopening it each time.

IMPORTANT: Playwright's sync API requires that ALL operations on a browser/page
happen on the SAME thread that called sync_playwright().start().  To satisfy
this constraint each RecorderSession owns a single long-lived background thread
(the "playwright thread") and exposes a run_in_pw_thread() helper that submits
any callable to that thread's job queue and blocks until the result is ready.
This means the asyncio route handlers never touch Playwright objects directly —
they only call run_in_pw_thread() which marshals the work to the right thread.
"""
import base64
import logging
import queue
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_STOP_SENTINEL = object()  # special marker to stop the playwright thread


class RecorderSession:
    """
    Represents a single active recording session with a live browser.

    The browser runs on a dedicated background thread (_pw_thread).  All
    Playwright calls must be dispatched via run_in_pw_thread().
    """

    def __init__(self, session_id: str, base_url: str):
        self.session_id = session_id
        self.base_url = base_url
        self.test_cases: List[Dict] = []      # finalized cases [{name, steps}]
        self._current_steps: List[Dict] = []  # steps for the case being recorded now
        self.started_at = datetime.utcnow().isoformat()

        # Playwright objects — only accessed from _pw_thread
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

        # Job queue: items are (callable, result_future)
        self._job_queue: queue.Queue = queue.Queue()
        self._pw_thread = threading.Thread(
            target=self._playwright_loop,
            name=f"pw-{session_id}",
            daemon=True,
        )
        self._pw_thread.start()

    @property
    def steps(self) -> List[Dict]:
        """Current in-progress steps (backward-compat for existing route code)."""
        return self._current_steps

    def finalize_current_case(self, name: str = "") -> int:
        """
        Move current_steps into test_cases as a new finalized case.
        Returns the number of steps finalized.
        """
        if not self._current_steps:
            return 0
        case_name = name or f"Test Case {len(self.test_cases) + 1}"
        self.test_cases.append({
            "name": case_name,
            "steps": list(self._current_steps),
        })
        finalized_count = len(self._current_steps)
        self._current_steps = []
        return finalized_count

    def all_steps(self) -> List[Dict]:
        """All steps across every finalized case plus current in-progress steps."""
        result = []
        for tc in self.test_cases:
            result.extend(tc["steps"])
        result.extend(self._current_steps)
        return result

    def get_context_summary(self) -> str:
        """
        Return a concise text summary of all finalized test cases for LLM context.
        Includes instructions and key data values so the LLM can resolve references
        like 'the candidate I just created' in subsequent cases.
        """
        if not self.test_cases:
            return ""
        lines = []
        for i, tc in enumerate(self.test_cases):
            lines.append(f"Test Case {i + 1} — {tc['name']}:")
            for s in tc.get("steps", []):
                instruction = s.get("instruction", "")
                if not instruction:
                    continue
                td = s.get("test_data") or {}
                data_parts = [f"{k}={v}" for k, v in td.items() if v and k not in ("url",)]
                data_str = f" [{', '.join(data_parts)}]" if data_parts else ""
                lines.append(f"  • {instruction}{data_str}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Playwright thread loop                                               #
    # ------------------------------------------------------------------ #

    def _playwright_loop(self) -> None:
        """Runs forever on the playwright thread, executing submitted jobs."""
        while True:
            item = self._job_queue.get()
            if item is _STOP_SENTINEL:
                break
            fn, fut = item
            try:
                result = fn()
                fut.set_result(result)
            except Exception as exc:
                fut.set_exception(exc)

    # ------------------------------------------------------------------ #
    # Public: dispatch work to the playwright thread                      #
    # ------------------------------------------------------------------ #

    def run_in_pw_thread(self, fn: Callable) -> Any:
        """
        Submit fn() to the playwright thread and block until it returns.
        Raises the exception if fn() raises.
        """
        fut: "concurrent.futures.Future" = _make_future()
        self._job_queue.put((fn, fut))
        return fut.result()  # blocks calling thread until done

    # ------------------------------------------------------------------ #
    # High-level helpers (called from route handlers via run_in_pw_thread) #
    # ------------------------------------------------------------------ #

    def init_browser(self, url: str, headless: bool = False) -> None:
        """Launch Playwright + Chromium and navigate to url. Runs on pw thread."""
        def _init():
            from playwright.sync_api import sync_playwright  # lazy import
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                ignore_https_errors=True,
            )
            self._page = context.new_page()
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as e:
                logger.warning(f"Navigation warning for {url}: {e}")

        self.run_in_pw_thread(_init)

    @property
    def page(self) -> Any:
        """
        Direct access to the page object.
        NOTE: Only safe to use from within a run_in_pw_thread() callable.
        """
        return self._page

    def take_screenshot_b64(self) -> str:
        """Capture screenshot on the playwright thread, return base64 string."""
        def _screenshot():
            try:
                data = self._page.screenshot(full_page=False)
                return base64.b64encode(data).decode("utf-8")
            except Exception as e:
                logger.error(f"Screenshot error: {e}")
                return ""

        return self.run_in_pw_thread(_screenshot)

    def add_step(self, step: Dict) -> None:
        step["step_number"] = len(self._current_steps) + 1
        self._current_steps.append(step)

    def truncate_steps(self, keep_count: int) -> None:
        """Keep only the first `keep_count` in-progress steps, discard the rest."""
        self._current_steps = self._current_steps[:keep_count]
        for i, s in enumerate(self._current_steps):
            s["step_number"] = i + 1

    def close(self) -> None:
        """Stop the browser and playwright thread."""
        def _close():
            try:
                self._browser.close()
            except Exception:
                pass
            try:
                self._playwright.stop()
            except Exception:
                pass

        try:
            self.run_in_pw_thread(_close)
        except Exception:
            pass
        finally:
            self._job_queue.put(_STOP_SENTINEL)
            self._pw_thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Small helper: a plain Future that does NOT require concurrent.futures import
# in every file.
# ---------------------------------------------------------------------------

import concurrent.futures as _cf


def _make_future() -> _cf.Future:
    return _cf.Future()


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

class RecorderSessionManager:
    """
    Singleton manager that holds active recording sessions.
    Each session_id maps to one live browser instance running on its own thread.
    """

    _instance: Optional["RecorderSessionManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "RecorderSessionManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._sessions: Dict[str, RecorderSession] = {}
                cls._instance._sessions_lock = threading.Lock()
        return cls._instance

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start_session(
        self,
        session_id: str,
        url: str,
        headless: bool = False,
    ) -> RecorderSession:
        """
        Create a RecorderSession, launch the browser on its dedicated thread,
        navigate to url, and return the session.
        If a session with this id already exists it is closed first.
        """
        self.close_session(session_id)

        session = RecorderSession(session_id=session_id, base_url=url)
        session.init_browser(url=url, headless=headless)

        with self._sessions_lock:
            self._sessions[session_id] = session

        logger.info(f"Recorder session started: {session_id} → {url}")
        return session

    def get_session(self, session_id: str) -> Optional[RecorderSession]:
        """Return the live session or None if not found."""
        with self._sessions_lock:
            return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> None:
        """Close and remove a session."""
        with self._sessions_lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.close()
            logger.info(f"Recorder session closed: {session_id}")

    def add_step(self, session_id: str, step: Dict) -> None:
        """Append a step to the session's recorded steps."""
        session = self.get_session(session_id)
        if session:
            session.add_step(step)

    def get_steps(self, session_id: str) -> List[Dict]:
        """Return the current list of recorded steps."""
        session = self.get_session(session_id)
        return session.steps if session else []

    def list_sessions(self) -> List[str]:
        """Return all active session IDs (for debug)."""
        with self._sessions_lock:
            return list(self._sessions.keys())


# Global singleton instance
recorder_session_manager = RecorderSessionManager()
