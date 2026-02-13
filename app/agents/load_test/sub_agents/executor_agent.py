"""ExecutorAgent: Monitors load test execution and adapts in real-time."""

import asyncio
import time
import logging
from typing import Dict, Any
from datetime import datetime

from app.agents.load_test.sub_agents.base_load_test_agent import BaseLoadTestAgent
from app.agents.load_test.state import AgenticLoadTestState

# Configure logger
logger = logging.getLogger(__name__)


class ExecutorAgent(BaseLoadTestAgent):
    """
    Monitors load test execution and makes real-time decisions.

    Responsibilities:
    - Monitor error rates and response times
    - Detect early failures (connection issues, DNS errors)
    - Auto-adjust spawn rate if server is overwhelmed
    - Decide when to stop test early
    - Track test progress and health
    - Provide real-time insights
    """

    def execute(self, state: AgenticLoadTestState) -> AgenticLoadTestState:
        """
        Monitor test execution (called periodically during test).

        Args:
            state: Current state with execution_metrics

        Returns:
            Updated state with analysis and recommendations
        """
        logger.info("\n" + "="*80)
        logger.info("🤖 AGENT 4/6: ExecutorAgent")
        logger.info("="*80)

        self.add_thought(
            state,
            "Monitoring test execution...",
            "Analyzing real-time metrics for issues and optimization opportunities",
            "executing"
        )

        metrics = state.get('execution_metrics', {})

        if not metrics:
            logger.info("ℹ️  No metrics available yet, test is starting...")
            self.add_thought(
                state,
                "No metrics available yet",
                "Test is starting, waiting for initial metrics",
                "executing"
            )
            logger.info("✅ ExecutorAgent Complete!")
            logger.info("="*80 + "\n")
            return state

        logger.info("📊 Current Metrics:")
        logger.info(f"   • Total Requests: {metrics.get('total_requests', 0)}")
        logger.info(f"   • Total Failures: {metrics.get('total_failures', 0)}")
        logger.info(f"   • Avg Response Time: {metrics.get('avg_response_time', 0):.0f}ms")
        logger.info(f"   • Requests/Second: {metrics.get('requests_per_second', 0):.1f}")

        # Analyze current state
        logger.info("\n🔍 Analyzing Metrics...")
        analysis = self._analyze_current_metrics(metrics)

        # Check for critical issues
        if analysis['critical_issue']:
            logger.error(f"   ⚠️  CRITICAL ISSUE: {analysis['issue_description']}")
            logger.error(f"   Reason: {analysis['reasoning']}")
            self.add_thought(
                state,
                f"⚠️ Critical issue detected: {analysis['issue_description']}",
                analysis['reasoning'],
                "executing"
            )
            state['should_stop_early'] = True
            state['stop_reason'] = analysis['issue_description']

        # Check for warnings
        elif analysis['warning']:
            logger.warning(f"   ⚠️  WARNING: {analysis['warning_description']}")
            logger.warning(f"   Reason: {analysis['reasoning']}")
            logger.warning(f"   Suggested Adjustment: {analysis.get('adjustment', 'None')}")
            self.add_thought(
                state,
                f"⚠️ Warning: {analysis['warning_description']}",
                analysis['reasoning'],
                "executing"
            )
            state['should_adjust'] = True
            state['adjustment'] = analysis['adjustment']

        # Normal operation
        else:
            logger.info(f"   ✅ Test running normally")
            logger.info(f"   • Error Rate: {analysis['error_rate']:.1f}%")
            logger.info(f"   • Avg Response: {analysis['avg_response_time']:.0f}ms")
            self.add_thought(
                state,
                "✅ Test running normally",
                f"Error rate: {analysis['error_rate']:.1f}%, Avg response: {analysis['avg_response_time']:.0f}ms",
                "executing"
            )

        state['execution_analysis'] = analysis

        logger.info("\n✅ ExecutorAgent Complete!")
        logger.info("="*80 + "\n")

        return state

    def _analyze_current_metrics(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze current metrics and detect issues.

        Returns:
            Dict with analysis results
        """
        total_requests = metrics.get('total_requests', 0)
        total_failures = metrics.get('total_failures', 0)
        avg_response_time = metrics.get('avg_response_time', 0)
        percentile_95 = metrics.get('percentile_95', 0)
        elapsed_time = metrics.get('elapsed_time', 0)
        current_users = metrics.get('current_users', 0)

        # Calculate error rate
        error_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0

        analysis = {
            'error_rate': error_rate,
            'avg_response_time': avg_response_time,
            'percentile_95': percentile_95,
            'elapsed_time': elapsed_time,
            'current_users': current_users,
            'total_requests': total_requests,
            'critical_issue': False,
            'warning': False,
            'issue_description': None,
            'warning_description': None,
            'reasoning': None,
            'adjustment': None
        }

        # Check for critical issues (within first 30 seconds)
        if elapsed_time < 30:
            if error_rate > 50:
                analysis['critical_issue'] = True
                analysis['issue_description'] = 'High error rate in first 30 seconds'
                analysis['reasoning'] = f'Error rate of {error_rate:.1f}% indicates server may not be ready or endpoint is incorrect'
                return analysis

            if total_requests > 10 and avg_response_time > 10000:
                analysis['critical_issue'] = True
                analysis['issue_description'] = 'Extremely slow response times'
                analysis['reasoning'] = f'Average response time of {avg_response_time:.0f}ms indicates severe performance issues'
                return analysis

        # Check for warnings (throughout test)
        if error_rate > 20:
            analysis['warning'] = True
            analysis['warning_description'] = f'Elevated error rate: {error_rate:.1f}%'
            analysis['reasoning'] = 'Server is struggling to handle load. Consider reducing spawn rate.'
            analysis['adjustment'] = {
                'action': 'reduce_spawn_rate',
                'factor': 0.5,
                'reason': 'High error rate detected'
            }
            return analysis

        if percentile_95 > 5000:
            analysis['warning'] = True
            analysis['warning_description'] = f'High P95 response time: {percentile_95:.0f}ms'
            analysis['reasoning'] = 'Response times are degrading. Server may be reaching capacity.'
            analysis['adjustment'] = {
                'action': 'slow_down',
                'factor': 1.5,
                'reason': 'Response time degradation'
            }
            return analysis

        return analysis

    def should_stop_test(self, state: AgenticLoadTestState) -> tuple[bool, str]:
        """
        Decide if test should be stopped early.

        Returns:
            (should_stop, reason)
        """
        if state.get('should_stop_early', False):
            return True, state.get('stop_reason', 'Critical issue detected')

        # Check for catastrophic failure patterns
        metrics = state.get('execution_metrics', {})
        total_requests = metrics.get('total_requests', 0)
        total_failures = metrics.get('total_failures', 0)

        if total_requests > 100:
            error_rate = total_failures / total_requests * 100
            if error_rate > 90:
                return True, f'Catastrophic failure: {error_rate:.1f}% error rate'

        return False, None

    def get_adjustment_recommendation(self, state: AgenticLoadTestState) -> Dict[str, Any]:
        """
        Get recommended adjustments for ongoing test.

        Returns:
            Dict with adjustment details
        """
        if state.get('should_adjust', False):
            return state.get('adjustment', {})

        return {'action': 'continue', 'reason': 'Test running normally'}

    def generate_progress_report(self, state: AgenticLoadTestState) -> str:
        """
        Generate human-readable progress report.

        Returns:
            Progress summary string
        """
        metrics = state.get('execution_metrics', {})
        analysis = state.get('execution_analysis', {})

        if not metrics:
            return "Test starting..."

        total_requests = metrics.get('total_requests', 0)
        total_failures = metrics.get('total_failures', 0)
        error_rate = analysis.get('error_rate', 0)
        avg_response_time = analysis.get('avg_response_time', 0)
        current_users = metrics.get('current_users', 0)
        elapsed_time = metrics.get('elapsed_time', 0)

        status_emoji = '✅' if error_rate < 5 else '⚠️' if error_rate < 20 else '❌'

        report = f"""{status_emoji} Load Test Progress Report

Time Elapsed: {elapsed_time:.0f}s
Current Users: {current_users}
Total Requests: {total_requests}
Error Rate: {error_rate:.1f}%
Avg Response Time: {avg_response_time:.0f}ms
P95 Response Time: {analysis.get('percentile_95', 0):.0f}ms

Status: {'Normal' if not analysis.get('warning') else 'Warning - ' + analysis.get('warning_description', '')}
"""
        return report
