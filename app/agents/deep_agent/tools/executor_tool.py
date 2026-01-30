"""
Executor Tool - Wraps the execute-enhanced API

This tool allows agents to execute tests in Playwright browser
using the existing enhanced_executor.
"""

import asyncio
import threading
import multiprocessing
from typing import Dict, Any, Optional, Callable
from app.tools.enhanced_executor import execute_enhanced


class ExecutorTool:
    """
    Tool for executing tests in Playwright browser.

    Wraps the execute_enhanced function which:
    - Launches Playwright browser
    - Executes test steps with selectors
    - Captures screenshots
    - Returns detailed results
    - Broadcasts real-time step updates via SSE
    """

    name = "execute_tests"
    description = "Execute parsed test cases in Playwright browser"

    def __init__(self, broadcast_func: Optional[Callable] = None):
        self.broadcast_func = broadcast_func

    def set_broadcast_func(self, broadcast_func: Callable):
        """Set the broadcast function for SSE updates."""
        self.broadcast_func = broadcast_func

    def execute(
        self,
        test_suite: Dict[str, Any],
        headless: bool = True,
        timeout: int = 30000,
        base_url: Optional[str] = None,
        broadcast_func: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Execute tests in Playwright browser.

        Args:
            test_suite: Parsed test suite with test_cases
            headless: Run browser in headless mode
            timeout: Timeout for each action in milliseconds
            base_url: Override base URL for tests
            broadcast_func: Optional callback for real-time SSE updates

        Returns:
            {
                "success": bool,
                "execution_results": {
                    "project": str,
                    "base_url": str,
                    "total": int,
                    "passed": int,
                    "failed": int,
                    "results": [...],
                    "executed_at": str
                },
                "error": str or None
            }
        """
        try:
            # Override base_url if provided
            if base_url:
                test_suite = {**test_suite, "base_url": base_url}

            # Use the broadcast_func from parameter or instance
            active_broadcast = broadcast_func or self.broadcast_func

            total_tests = len(test_suite.get("test_cases", []))
            print(f"[ExecutorTool] Executing {total_tests} tests (headless={headless}, timeout={timeout}ms)...")

            # Create update queue for real-time updates from subprocess
            update_queue = multiprocessing.Queue() if active_broadcast else None

            # Start update listener thread if we have a broadcast function
            stop_listener = threading.Event()
            listener_thread = None

            if active_broadcast and update_queue:
                def listen_for_updates():
                    """Background thread to forward subprocess updates to SSE."""
                    while not stop_listener.is_set():
                        try:
                            # Non-blocking get with timeout
                            update = update_queue.get(timeout=0.1)
                            if update and active_broadcast:
                                active_broadcast(update)
                        except Exception:
                            # Queue.Empty or other error, continue
                            continue

                listener_thread = threading.Thread(target=listen_for_updates, daemon=True)
                listener_thread.start()

            # Run the async execute_enhanced function
            execution_results = self._run_async(
                execute_enhanced(
                    test_suite=test_suite,
                    headless=headless,
                    timeout=timeout,
                    update_queue=update_queue
                )
            )

            # Stop the listener thread
            stop_listener.set()
            if listener_thread:
                listener_thread.join(timeout=1.0)

            passed = execution_results.get("passed", 0)
            failed = execution_results.get("failed", 0)
            print(f"[ExecutorTool] Execution complete: {passed}/{total_tests} passed, {failed} failed")

            return {
                "success": True,
                "execution_results": execution_results,
                "error": None
            }

        except Exception as e:
            error_msg = str(e)
            print(f"[ExecutorTool] Error: {error_msg}")
            return {
                "success": False,
                "execution_results": None,
                "error": error_msg
            }

    def _run_async(self, coro):
        """Run async coroutine in sync context."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, use thread pool
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result()
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            # No event loop, create new one
            return asyncio.run(coro)
