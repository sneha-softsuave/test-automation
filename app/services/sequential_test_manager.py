"""Sequential Load Test Manager for running multiple APIs one after another."""

import asyncio
from typing import Dict, List, Optional
from datetime import datetime
import uuid
import time

from app.models.load_test_models import APIConfig, LoadTestConfig
from app.services.locust_manager import locust_manager
from app.services.dynamic_locust_generator import DynamicLocustfileGenerator
from app.services.load_test_report_generator import load_test_report_generator
from app.core.sse_manager import sse_manager
from pathlib import Path


def parse_time_to_seconds(time_str: str) -> int:
    """Parse time string (e.g., '5m', '1h', '30s') to seconds."""
    time_str = time_str.lower().strip()

    if time_str.endswith('s'):
        return int(time_str[:-1])
    elif time_str.endswith('m'):
        return int(time_str[:-1]) * 60
    elif time_str.endswith('h'):
        return int(time_str[:-1]) * 3600
    else:
        # Default to seconds if no unit
        return int(time_str)


class SequentialTestManager:
    """Manages sequential execution of load tests across multiple APIs."""

    def __init__(self):
        self.active_sequential_tests: Dict[str, Dict] = {}
        self.locustfile_dir = Path("generated_locustfiles")
        self.locustfile_dir.mkdir(parents=True, exist_ok=True)

    async def start_sequential_test(
        self,
        sequential_test_id: str,
        apis: List[APIConfig],
        session_id: str,
        llm_provider: str = "groq"
    ) -> bool:
        """
        Start a sequential load test.

        Args:
            sequential_test_id: Unique ID for this sequential test
            apis: List of API configurations to test
            session_id: SSE session ID for updates

        Returns:
            True if started successfully
        """
        print(f"🔄 Starting sequential test {sequential_test_id} with {len(apis)} APIs", flush=True)

        # Store test metadata
        self.active_sequential_tests[sequential_test_id] = {
            "sequential_test_id": sequential_test_id,
            "apis": [api.name for api in apis],
            "session_id": session_id,
            "llm_provider": llm_provider,  # Store for AI insights generation
            "status": "running",
            "current_index": 0,
            "start_time": datetime.now(),
            "stop_requested": False
        }

        # Start the sequential execution in background
        asyncio.create_task(
            self._execute_sequential_tests(sequential_test_id, apis, session_id)
        )

        return True

    async def _execute_sequential_tests(
        self,
        sequential_test_id: str,
        apis: List[APIConfig],
        session_id: str
    ):
        """Execute APIs sequentially one by one."""
        generator = DynamicLocustfileGenerator()
        api_results = []  # Collect results for report
        test_start_time = time.time()

        for index, api in enumerate(apis):
            # Check if stop was requested
            if self.active_sequential_tests.get(sequential_test_id, {}).get("stop_requested"):
                print(f"⏹️ Sequential test {sequential_test_id} stopped by user", flush=True)
                await sse_manager.broadcast_to_session(
                    session_id,
                    "sequential_test_stopped",
                    {"sequential_test_id": sequential_test_id, "message": "Stopped by user"}
                )
                break

            print(f"📝 Sequential test {sequential_test_id}: API {index + 1}/{len(apis)} - {api.name}", flush=True)

            # Update status
            if sequential_test_id in self.active_sequential_tests:
                self.active_sequential_tests[sequential_test_id]["current_index"] = index
                self.active_sequential_tests[sequential_test_id]["current_api"] = api.name

            # Send status update
            await sse_manager.broadcast_to_session(
                session_id,
                "sequential_status_update",
                {
                    "sequential_test_id": sequential_test_id,
                    "status": "running",
                    "current_index": index,
                    "total_apis": len(apis),
                    "current_api": api.name,
                    "apis": [a.name for a in apis]
                }
            )

            # Notify start of this API
            await sse_manager.broadcast_to_session(
                session_id,
                "sequential_api_started",
                {
                    "sequential_test_id": sequential_test_id,
                    "api_index": index,
                    "total_apis": len(apis),
                    "api_name": api.name
                }
            )

            # Generate test ID for this individual API
            test_id = f"{sequential_test_id}_api_{index}"
            locustfile_path = self.locustfile_dir / f"{test_id}.py"

            try:
                # Generate Locustfile
                generator.generate_single_api(api, str(locustfile_path))

                # Create config from API or use defaults
                config = LoadTestConfig(
                    users=api.users if api.users is not None else 10,
                    spawn_rate=api.spawn_rate if api.spawn_rate is not None else 2,
                    run_time=api.run_time if api.run_time else '5m'
                )

                # Track start time for this API
                api_start_time = time.time()

                # Start Locust test
                success = locust_manager.start_test(test_id, str(locustfile_path), config, session_id)

                if not success:
                    raise Exception(f"Failed to start Locust for {api.name}")

                # Stream metrics while test is running
                await self._stream_api_metrics(test_id, session_id, api.name)

                # Get final metrics for this API
                final_metrics = await locust_manager.get_metrics(test_id)
                api_duration = time.time() - api_start_time

                # Collect result for report
                api_results.append({
                    "name": api.name,
                    "endpoint": f"{api.base_url}{api.endpoint}",
                    "method": api.method,
                    "config": config,
                    "metrics": final_metrics,
                    "duration": api_duration
                })

                # Notify completion
                await sse_manager.broadcast_to_session(
                    session_id,
                    "sequential_api_completed",
                    {
                        "sequential_test_id": sequential_test_id,
                        "api_index": index,
                        "api_name": api.name
                    }
                )

            except Exception as e:
                print(f"❌ Error testing {api.name}: {e}", flush=True)
                await sse_manager.broadcast_to_session(
                    session_id,
                    "sequential_api_failed",
                    {
                        "sequential_test_id": sequential_test_id,
                        "api_index": index,
                        "api_name": api.name,
                        "error": str(e)
                    }
                )

        # All APIs completed
        if sequential_test_id in self.active_sequential_tests:
            self.active_sequential_tests[sequential_test_id]["status"] = "completed"

        # Calculate total duration
        total_duration = time.time() - test_start_time

        # Generate HTML report
        print(f"📊 [SEQ] Attempting to generate sequential report...", flush=True)
        print(f"📊 [SEQ] Number of api_results: {len(api_results)}", flush=True)
        print(f"📊 [SEQ] Total duration: {total_duration}", flush=True)

        if api_results:
            try:
                # Get LLM provider from session or default to groq
                test_info = self.active_sequential_tests.get(sequential_test_id, {})
                llm_provider = test_info.get("llm_provider", "groq")

                print(f"📊 [SEQ] Calling generate_sequential_report with provider: {llm_provider}...", flush=True)
                report_filename = load_test_report_generator.generate_sequential_report(
                    sequential_test_id,
                    api_results,
                    total_duration,
                    llm_provider
                )
                print(f"📄 Report generated: {report_filename}", flush=True)

                # Auto-generate AI insights for sequential test (use last API's metrics)
                try:
                    print(f"🤖 [SEQ] Auto-generating AI insights for sequential test: {sequential_test_id}", flush=True)

                    # Use the last completed API's metrics as representative
                    last_result = api_results[-1]

                    # Import the background task function
                    from app.api.routes.load_test import generate_ai_insights_background

                    asyncio.create_task(
                        generate_ai_insights_background(
                            test_id=sequential_test_id,
                            llm_provider=llm_provider,
                            metrics=last_result.get('metrics', {}),
                            config=last_result.get('config', {}),
                            api={'endpoint': last_result.get('endpoint', '/'), 'method': last_result.get('method', 'GET')},
                            regenerate_report=True
                        )
                    )
                    print(f"✅ [SEQ] AI insights generation started in background", flush=True)
                except Exception as e:
                    print(f"⚠️ Failed to start AI insights generation: {e}", flush=True)

            except Exception as e:
                print(f"⚠️ Failed to generate report: {e}", flush=True)
                import traceback
                traceback.print_exc()
        else:
            print(f"⚠️ [SEQ] No api_results to generate report from", flush=True)

        await sse_manager.broadcast_to_session(
            session_id,
            "sequential_test_completed",
            {
                "sequential_test_id": sequential_test_id,
                "status": "completed",
                "current_index": len(apis) - 1,
                "total_apis": len(apis),
                "current_api": apis[-1].name if apis else None,
                "apis": [a.name for a in apis],
                "message": "All APIs completed"
            }
        )

        print(f"✅ Sequential test {sequential_test_id} completed", flush=True)

    async def _stream_api_metrics(self, test_id: str, session_id: str, api_name: str):
        """Stream metrics for a single API test."""
        print(f"📊 Starting metrics streaming for {test_id}", flush=True)

        while locust_manager.is_test_running(test_id):
            metrics = await locust_manager.get_metrics(test_id)

            if metrics:
                print(f"📡 Broadcasting metrics for {api_name}: RPS={metrics.requests_per_second:.2f}", flush=True)

                # Send metrics directly (not nested in "metrics" key)
                metrics_data = metrics.model_dump(mode='json')

                await sse_manager.broadcast_to_session(
                    session_id,
                    "sequential_api_metrics",
                    metrics_data
                )

            await asyncio.sleep(2)

        print(f"✅ Metrics streaming completed for {test_id}", flush=True)

    def stop_sequential_test(self, sequential_test_id: str) -> bool:
        """Stop a running sequential test."""
        if sequential_test_id not in self.active_sequential_tests:
            print(f"⚠️ Sequential test {sequential_test_id} not found in active tests", flush=True)
            return False

        print(f"🛑 Stopping sequential test: {sequential_test_id}", flush=True)
        self.active_sequential_tests[sequential_test_id]["stop_requested"] = True

        # Stop ALL API tests for this sequential test (not just current one)
        # Get total number of APIs
        total_apis = len(self.active_sequential_tests[sequential_test_id].get("apis", []))

        print(f"🔍 Stopping all {total_apis} API tests for {sequential_test_id}", flush=True)

        # Try to stop all possible API tests
        stopped_count = 0
        for i in range(total_apis):
            test_id = f"{sequential_test_id}_api_{i}"
            if locust_manager.stop_test(test_id):
                print(f"✅ Stopped {test_id}", flush=True)
                stopped_count += 1
            else:
                print(f"⏭️ Skipped {test_id} (not running)", flush=True)

        # Also try pkill as fallback for any remaining processes
        import subprocess
        try:
            result = subprocess.run(
                ["pkill", "-f", f"{sequential_test_id}"],
                capture_output=True,
                text=True
            )
            print(f"🔪 pkill fallback executed for {sequential_test_id}", flush=True)
        except Exception as e:
            print(f"⚠️ pkill fallback failed: {e}", flush=True)

        print(f"✅ Stopped {stopped_count} Locust processes for sequential test", flush=True)

        return True

    def get_sequential_test_status(self, sequential_test_id: str) -> Optional[Dict]:
        """Get status of a sequential test."""
        return self.active_sequential_tests.get(sequential_test_id)


# Global instance
sequential_test_manager = SequentialTestManager()
