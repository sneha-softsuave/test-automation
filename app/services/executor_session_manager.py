"""
ExecutorSessionManager
Keeps one persistent Playwright browser per chat session_id so test executions
reuse a live browser without relaunching it each time.

Uses the same threading pattern as RecorderSessionManager:
- Each session owns a dedicated background thread (the "playwright thread").
- All Playwright calls happen on that thread.
- Public methods dispatch work via a job queue and block until done.
"""
import concurrent.futures as _cf
import logging
import queue
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_STOP_SENTINEL = object()


class ExecutorSession:
    """
    Persistent Playwright browser session for test execution.
    Browser and page stay alive between execute calls on the same session.
    All Playwright operations run on a dedicated background thread.
    """

    def __init__(self, session_id: str, headless: bool = False, storage_state: Optional[dict] = None):
        self.session_id = session_id
        self.headless = headless
        self._initial_storage_state = storage_state

        # Playwright objects — only accessed from _pw_thread
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

        self._job_queue: queue.Queue = queue.Queue()
        self._pw_thread = threading.Thread(
            target=self._playwright_loop,
            name=f"exec-{session_id[:8]}",
            daemon=True,
        )
        self._pw_thread.start()

    # ------------------------------------------------------------------ #
    # Playwright thread loop                                               #
    # ------------------------------------------------------------------ #

    def _playwright_loop(self) -> None:
        """Initialize playwright + browser, then process jobs indefinitely."""
        try:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self.headless,
                slow_mo=500,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx_kwargs: dict = {"viewport": {"width": 1280, "height": 800}, "ignore_https_errors": True}
            if self._initial_storage_state:
                ctx_kwargs["storage_state"] = self._initial_storage_state
            self._context = self._browser.new_context(**ctx_kwargs)
            self._page = self._context.new_page()

            def on_page(page):
                self._page = page
                logger.info(f"[ExecutorSession {self.session_id[:8]}] New page opened, switching active page")
                
            self._context.on("page", on_page)

            logger.info(
                f"[ExecutorSession {self.session_id[:8]}] Browser launched "
                f"(headless={self.headless})"
            )
        except Exception as e:
            logger.error(
                f"[ExecutorSession {self.session_id[:8]}] Browser launch failed: {e}"
            )

        while True:
            item = self._job_queue.get()
            if item is _STOP_SENTINEL:
                break
            fn, fut = item
            try:
                fut.set_result(fn())
            except Exception as exc:
                fut.set_exception(exc)

        # Cleanup on stop
        for attr, method in [
            ("_page", "close"),
            ("_context", "close"),
            ("_browser", "close"),
            ("_playwright", "stop"),
        ]:
            obj = getattr(self, attr, None)
            if obj:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    # Public: dispatch work to the playwright thread                       #
    # ------------------------------------------------------------------ #

    def run_in_pw_thread(self, fn: Callable) -> Any:
        """Submit fn() to the playwright thread and block until it returns."""
        fut: _cf.Future = _cf.Future()
        self._job_queue.put((fn, fut))
        return fut.result()

    def preview(self, url: str) -> Dict:
        """Navigate to URL and capture a screenshot without running tests."""
        import base64 as _b64

        def _nav():
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                try:
                    self._page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass
                title = ""
                try:
                    title = self._page.title()
                except Exception:
                    pass
                ss = self._page.screenshot(type="png")
                return {
                    "success": True,
                    "url": self._page.url,
                    "title": title,
                    "image_b64": _b64.b64encode(ss).decode("utf-8"),
                }
            except Exception as e:
                return {"success": False, "url": url, "error": str(e)}

        return self.run_in_pw_thread(_nav)

    # ------------------------------------------------------------------ #
    # Test suite execution                                                 #
    # ------------------------------------------------------------------ #

    def run_test_suite(
        self,
        test_suite: Dict,
        update_queue,
        timeout: int,
        signal_file=None,
        start_url: str = "",
    ) -> Dict:
        """
        Execute all test cases in the persistent browser.
        Call this via asyncio.to_thread() to avoid blocking the event loop.
        Returns the same result dict format as execute_enhanced.
        If start_url is provided, the browser navigates there before running (used by Rerun).
        """
        def _run() -> Dict:
            from playwright.sync_api import expect as _sync_expect
            from app.tools.enhanced_executor import _execute_single_test_sync

            test_cases = list(test_suite.get("test_cases", []))
            common_selectors = test_suite.get("common_selectors", {})
            test_data = test_suite.get("test_data", {})
            results = []
            passed = 0
            failed = 0
            shared_storage_state = None

            def send_update(update_type: str, data: Dict):
                if update_queue is not None:
                    try:
                        update_queue.put({"type": update_type, **data})
                    except Exception:
                        pass

            # Navigate to start_url before running (Rerun: go back to where the TC originally started)
            if start_url and self._page:
                try:
                    self._page.goto(start_url, wait_until="domcontentloaded", timeout=30_000)
                    try:
                        self._page.wait_for_load_state("networkidle", timeout=10_000)
                    except Exception:
                        pass
                    print(f"[run_test_suite] Navigated to start_url: {start_url}")
                except Exception as _nav_err:
                    print(f"[run_test_suite] Warning: could not navigate to start_url {start_url!r}: {_nav_err}")

            send_update("execution_started", {
                "message": (
                    f"Starting execution of {len(test_cases)} "
                    f"test{'s' if len(test_cases) != 1 else ''} "
                    "(reusing persistent browser)"
                ),
                "project": test_suite.get("project", "Unknown"),
                "base_url": test_suite.get("base_url", "N/A"),
                "total_tests": len(test_cases),
                "headless": self.headless,
            })
            send_update("browser_status", {
                "message": "Persistent browser ready — continuing from current page",
                "status": "ready",
                "headless": self.headless,
            })

            for idx, test_case in enumerate(test_cases):
                test_id = test_case.get("id", f"TC_{idx + 1}")
                test_name = test_case.get("name", "Test Case")

                send_update("test_started", {
                    "message": f"Starting test: {test_name}",
                    "test_id": test_id,
                    "test_name": test_name,
                    "test_index": idx + 1,
                    "total_tests": len(test_cases),
                })

                result = _execute_single_test_sync(
                    browser=self._browser,
                    test_case=test_case,
                    common_selectors=common_selectors,
                    suite_test_data=test_data,
                    timeout=timeout,
                    sync_expect=_sync_expect,
                    send_update=send_update,
                    signal_file=signal_file,
                    initial_storage_state=shared_storage_state,
                    shared_page=self._page,
                )
                results.append(result)

                if result.get("browser_closed"):
                    send_update("browser_closed_during_exec", {
                        "message": "Execution aborted because the browser was closed manually."
                    })
                    break

                if result.get("final_storage_state") is not None:
                    shared_storage_state = result["final_storage_state"]

                if result["status"] == "PASSED":
                    passed += 1
                    send_update("test_completed", {
                        "message": f"Test passed: {test_name}",
                        "test_id": test_id,
                        "test_name": test_name,
                        "status": "PASSED",
                        "passed_count": passed,
                        "failed_count": failed,
                    })
                else:
                    failed += 1
                    send_update("test_completed", {
                        "message": f"Test failed: {test_name}",
                        "test_id": test_id,
                        "test_name": test_name,
                        "status": "FAILED",
                        "error": result.get("error", "Unknown error"),
                        "passed_count": passed,
                        "failed_count": failed,
                    })

            try:
                final_url = self._page.url if self._page else test_suite.get("base_url", "")
            except Exception:
                final_url = test_suite.get("base_url", "")

            send_update("execution_completed", {
                "message": f"Execution completed: {passed}/{len(test_cases)} tests passed",
                "total": len(test_cases),
                "passed": passed,
                "failed": failed,
            })

            return {
                "project": test_suite.get("project", "Unknown"),
                "base_url": test_suite.get("base_url", ""),
                "total": len(test_cases),
                "passed": passed,
                "failed": failed,
                "results": results,
                "executed_at": datetime.now().isoformat(),
                "final_storage_state": shared_storage_state,
                "final_url": final_url,
            }

        return self.run_in_pw_thread(_run)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def capture_page_structure(self) -> dict:
        """
        Extract the current page's DOM structure using the live browser page.
        Returns the same dict shape as SelectorExtractor — no new browser launched.
        Uses extract_from_existing_page() from playwright_runner so the live,
        authenticated, fully-rendered DOM is captured instead of a fresh headless scrape.
        """
        from app.tools.playwright_runner import extract_from_existing_page

        def _extract():
            return extract_from_existing_page(self._page)

        return self.run_in_pw_thread(_extract)

    def close(self) -> None:
        """Stop the browser and playwright thread."""
        self._job_queue.put(_STOP_SENTINEL)
        self._pw_thread.join(timeout=10)


# ---------------------------------------------------------------------------
# Session manager (singleton)
# ---------------------------------------------------------------------------

class ExecutorSessionManager:
    """Singleton that holds one ExecutorSession per chat session_id."""

    _instance: Optional["ExecutorSessionManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ExecutorSessionManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._sessions: Dict[str, ExecutorSession] = {}
                cls._instance._sessions_lock = threading.Lock()
        return cls._instance

    def get_or_create_session(
        self, session_id: str, headless: bool = False, storage_state: Optional[dict] = None
    ) -> ExecutorSession:
        """Return the existing live session or create a new one."""
        with self._sessions_lock:
            session = self._sessions.get(session_id)
            if session is None or not session._pw_thread.is_alive():
                session = ExecutorSession(session_id=session_id, headless=headless, storage_state=storage_state)
                self._sessions[session_id] = session
                logger.info(
                    f"[ExecutorSessionManager] Created executor session "
                    f"{session_id[:8]}"
                )
        return session

    def close_session(self, session_id: str) -> None:
        """Close and remove a session (closes its browser)."""
        with self._sessions_lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.close()
            logger.info(
                f"[ExecutorSessionManager] Closed executor session "
                f"{session_id[:8]}"
            )

    def get_session(self, session_id: str) -> Optional[ExecutorSession]:
        with self._sessions_lock:
            return self._sessions.get(session_id)


# Global singleton
executor_session_manager = ExecutorSessionManager()
