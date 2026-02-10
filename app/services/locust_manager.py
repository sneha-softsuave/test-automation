"""Locust process manager for executing load tests."""

import subprocess
import httpx
import asyncio
import signal
import time
import psutil
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime

from app.models.load_test_models import LoadTestConfig, LoadTestMetrics, EndpointStats


class LocustManager:
    """Manage Locust subprocess execution and metrics collection."""

    def __init__(self):
        self.active_processes: Dict[str, subprocess.Popen] = {}
        self.test_start_times: Dict[str, datetime] = {}
        self.test_ports: Dict[str, int] = {}  # Track port for each test
        self.base_locust_port = 8089  # Starting Locust web port
        self.last_metrics: Dict[str, LoadTestMetrics] = {}  # Store last known metrics for each test

    def start_test(
        self,
        test_id: str,
        locustfile_path: str,
        config: LoadTestConfig
    ) -> bool:
        """
        Start a Locust load test in headless mode.

        Args:
            test_id: Unique test identifier
            locustfile_path: Path to generated Locustfile
            config: Load test configuration

        Returns:
            True if started successfully, False otherwise
        """
        try:
            # Stop any existing test with same ID
            self.stop_test(test_id)

            # Build Locust command with dynamic port
            cmd, port = self._build_locust_command(test_id, locustfile_path, config)

            print(f"Starting Locust test {test_id} on port {port}: {' '.join(cmd)}")

            # Start Locust process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            self.active_processes[test_id] = process
            self.test_start_times[test_id] = datetime.now()

            # Wait a moment for Locust to start
            time.sleep(2)

            # Check if process is still running
            if process.poll() is not None:
                # Process died immediately
                stdout, stderr = process.communicate()
                print(f"Locust failed to start: {stderr}")
                return False

            print(f"Locust test {test_id} started successfully (PID: {process.pid})")
            return True

        except Exception as e:
            print(f"Error starting Locust test: {e}")
            return False

    def _get_available_port(self) -> int:
        """Find an available port starting from base_locust_port."""
        import socket
        port = self.base_locust_port
        while port < self.base_locust_port + 100:  # Try up to 100 ports
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', port))
                    return port
            except OSError:
                port += 1
        raise RuntimeError("No available ports found")

    def _build_locust_command(self, test_id: str, locustfile_path: str, config: LoadTestConfig) -> tuple[list, int]:
        """Build Locust command with parameters. Returns (command, port)."""
        # Get an available port for this test
        port = self._get_available_port()
        self.test_ports[test_id] = port

        cmd = [
            "locust",
            "-f", locustfile_path,
            "--autostart",  # Start test automatically WITH web interface
            "--autoquit", "10",  # Auto quit 10 seconds after test completes
            "--web-host", "127.0.0.1",
            "--web-port", str(port),
            "-u", str(config.users),
            "-r", str(config.spawn_rate),
            "-t", config.run_time,
            "--html", f"load_test_results/report_{int(time.time())}.html",
            "--csv", f"load_test_results/stats_{int(time.time())}",
        ]

        # Override host if specified
        if config.host:
            cmd.extend(["--host", config.host])

        return cmd, port

    def stop_test(self, test_id: str) -> bool:
        """
        Stop a running Locust test.

        Args:
            test_id: Test identifier

        Returns:
            True if stopped successfully, False otherwise
        """
        if test_id not in self.active_processes:
            return False

        process = self.active_processes[test_id]

        try:
            # Send SIGTERM to gracefully stop Locust
            if process.poll() is None:  # Process is still running
                process.send_signal(signal.SIGTERM)

                # Wait up to 10 seconds for graceful shutdown
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    # Force kill if still running
                    process.kill()
                    process.wait()

            # Clean up (but keep last_metrics for report generation)
            del self.active_processes[test_id]
            if test_id in self.test_start_times:
                del self.test_start_times[test_id]
            if test_id in self.test_ports:
                del self.test_ports[test_id]
            # Note: We keep self.last_metrics[test_id] for report generation

            print(f"Locust test {test_id} stopped successfully")
            return True

        except Exception as e:
            print(f"Error stopping Locust test: {e}")
            return False

    async def get_metrics(self, test_id: str) -> Optional[LoadTestMetrics]:
        """
        Get current metrics from running Locust test.

        Args:
            test_id: Test identifier

        Returns:
            LoadTestMetrics object or None if not available
        """
        # First check if we have cached metrics (for completed tests)
        if test_id in self.last_metrics:
            process_completed = test_id not in self.active_processes or self.active_processes[test_id].poll() is not None
            if process_completed:
                print(f"📊 Returning cached final metrics for completed test {test_id}", flush=True)
                return self.last_metrics[test_id]

        if test_id not in self.active_processes:
            print(f"⚠️ Test {test_id} not in active_processes, checking cache...", flush=True)
            return self.last_metrics.get(test_id)

        process = self.active_processes[test_id]

        # Check if process is still running
        if process.poll() is not None:
            # Process has ended - return last known metrics
            print(f"⚠️ Process {test_id} has ended, returning last known metrics", flush=True)
            return self.last_metrics.get(test_id)

        try:
            # Get the port for this test
            if test_id not in self.test_ports:
                print(f"No port found for test {test_id}")
                return self.last_metrics.get(test_id)

            port = self.test_ports[test_id]

            # Poll Locust stats API
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://localhost:{port}/stats/requests",
                    timeout=5.0
                )

                if response.status_code == 200:
                    stats_data = response.json()
                    metrics = self._parse_stats(test_id, stats_data)

                    # Cache the metrics
                    if metrics:
                        self.last_metrics[test_id] = metrics
                        print(f"📊 Cached metrics for {test_id}: RPS={metrics.requests_per_second:.2f}, Total Requests={metrics.total_requests}", flush=True)

                    return metrics

        except Exception as e:
            print(f"Error fetching Locust metrics: {e}", flush=True)
            return self.last_metrics.get(test_id)

    def _parse_stats(self, test_id: str, stats_data: Dict[str, Any]) -> LoadTestMetrics:
        """Parse Locust stats API response into LoadTestMetrics."""

        # Get overall stats
        stats = stats_data.get('stats', [])
        user_count = stats_data.get('user_count', 0)
        state = stats_data.get('state', 'running')

        # Calculate elapsed time
        start_time = self.test_start_times.get(test_id)
        elapsed_time = (datetime.now() - start_time).total_seconds() if start_time else 0

        # Aggregate metrics from all endpoints
        total_requests = 0
        total_failures = 0
        response_times = []
        rps = 0
        failures_ps = 0

        for stat in stats:
            # Skip "Total" aggregated row
            if stat.get('name') == 'Aggregated':
                total_requests = stat.get('num_requests', 0)
                total_failures = stat.get('num_failures', 0)
                rps = stat.get('current_rps', 0)
                failures_ps = stat.get('current_fail_per_sec', 0)

                # Response time percentiles
                avg_response_time = stat.get('avg_response_time', 0)
                min_response_time = stat.get('min_response_time', 0)
                max_response_time = stat.get('max_response_time', 0)
                median_response_time = stat.get('median_response_time', 0)
                percentile_95 = stat.get('avg_response_time', 0) * 1.5  # Approximation
                percentile_99 = stat.get('avg_response_time', 0) * 2.0  # Approximation

        # Calculate failure rate
        failure_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0

        # Determine status
        if state == 'stopped':
            status = 'completed'
        elif state == 'running':
            status = 'running'
        else:
            status = state

        return LoadTestMetrics(
            test_id=test_id,
            status=status,
            current_users=user_count,
            total_requests=total_requests,
            total_failures=total_failures,
            requests_per_second=rps,
            failures_per_second=failures_ps,
            avg_response_time=avg_response_time,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            median_response_time=median_response_time,
            percentile_95=percentile_95,
            percentile_99=percentile_99,
            failure_rate=failure_rate,
            elapsed_time=elapsed_time
        )

    def is_test_running(self, test_id: str) -> bool:
        """Check if a test is currently running."""
        if test_id not in self.active_processes:
            return False

        process = self.active_processes[test_id]
        return process.poll() is None

    def get_test_status(self, test_id: str) -> str:
        """Get status of a test."""
        if test_id not in self.active_processes:
            return "not_found"

        if self.is_test_running(test_id):
            return "running"
        else:
            return "completed"

    def cleanup_all(self):
        """Stop all running tests."""
        test_ids = list(self.active_processes.keys())
        for test_id in test_ids:
            self.stop_test(test_id)

    def get_active_test_count(self) -> int:
        """Get number of currently active tests."""
        return len([tid for tid in self.active_processes if self.is_test_running(tid)])


# Global instance
locust_manager = LocustManager()
