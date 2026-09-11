"""AnalyzerAgent: Analyzes completed load test results and provides insights."""

import json
import logging
from typing import Dict, Any, List
from datetime import datetime
import uuid
from pathlib import Path

from app.agents.load_test.sub_agents.base_load_test_agent import BaseLoadTestAgent
from app.agents.load_test.state import AgenticLoadTestState
from app.models.load_test_models import (
    SuggestionMetrics,
    TestSuggestion,
    APISuggestion,
    AIAnalysis
)

# Configure logger
logger = logging.getLogger(__name__)


class AnalyzerAgent(BaseLoadTestAgent):
    """
    Analyzes load test results and provides intelligent insights.

    Responsibilities:
    - Identify performance bottlenecks
    - Correlate error patterns with load levels
    - Compare against SLA thresholds
    - Recommend specific optimizations
    - Generate actionable insights
    """

    def execute(self, state: AgenticLoadTestState) -> AgenticLoadTestState:
        """
        Analyze completed test results.

        Args:
            state: Current state with execution_metrics

        Returns:
            Updated state with analysis, bottlenecks, and recommendations
        """
        logger.info("\n" + "="*80)
        logger.info("🤖 AGENT 5/6: AnalyzerAgent")
        logger.info("="*80)

        self.add_thought(
            state,
            "Analyzing test results...",
            "Using AI to identify bottlenecks and generate recommendations",
            "analyzing"
        )

        metrics = state.get('execution_metrics', {})
        api_type = state.get('api_type', 'unknown')

        if not metrics:
            logger.error("❌ No metrics available for analysis")
            self.add_error(state, "No metrics available for analysis")
            logger.info("="*80 + "\n")
            return state

        logger.info("📊 Final Test Metrics:")
        logger.info(f"   • Total Requests: {metrics.get('total_requests', 0)}")
        logger.info(f"   • Total Failures: {metrics.get('total_failures', 0)}")
        logger.info(f"   • Avg Response Time: {metrics.get('avg_response_time', 0):.0f}ms")
        logger.info(f"   • P95 Response Time: {metrics.get('percentile_95', 0):.0f}ms")
        logger.info(f"   • P99 Response Time: {metrics.get('percentile_99', 0):.0f}ms")

        # Perform rule-based analysis first
        logger.info("\n🔍 Step 1: Rule-Based Analysis...")
        rule_based_analysis = self._rule_based_analysis(metrics, api_type)
        logger.info(f"   ✅ Detected {len(rule_based_analysis['bottlenecks'])} potential bottleneck(s)")

        if rule_based_analysis['bottlenecks']:
            logger.info("\n🔍 Bottlenecks Found:")
            for i, bottleneck in enumerate(rule_based_analysis['bottlenecks'], 1):
                logger.info(f"   {i}. {bottleneck}")

        self.add_thought(
            state,
            f"Detected {len(rule_based_analysis['bottlenecks'])} potential bottlenecks",
            "Running AI analysis for deeper insights",
            "analyzing"
        )

        # Use AI for deeper analysis
        logger.info("\n🤖 Step 2: AI-Powered Deep Analysis...")
        test_id = state.get('test_id', '')
        ai_analysis = self._ai_powered_analysis(metrics, api_type, rule_based_analysis, test_id)
        logger.info(f"   ✅ Generated {len(ai_analysis.get('insights', []))} AI insight(s)")

        # Merge analyses
        final_analysis = {
            **rule_based_analysis,
            'ai_insights': ai_analysis.get('insights', []),
            'root_causes': ai_analysis.get('root_causes', []),
            'priority_recommendations': ai_analysis.get('priority_recommendations', [])
        }

        logger.info("\n📋 Recommendations:")
        for i, rec in enumerate(final_analysis['recommendations'][:5], 1):
            logger.info(f"   {i}. {rec}")
        if len(final_analysis['recommendations']) > 5:
            logger.info(f"   ... and {len(final_analysis['recommendations']) - 5} more")

        logger.info("\n✅ SLA Compliance:")
        sla = final_analysis.get('sla_compliance', {})
        logger.info(f"   • P95 Target: {sla.get('p95_target', 'N/A')}ms")
        logger.info(f"   • P95 Actual: {sla.get('p95_actual', 'N/A')}ms")
        logger.info(f"   • Status: {'✅ PASS' if sla.get('p95_compliant') else '❌ FAIL'}")

        state['analysis'] = final_analysis
        state['bottlenecks'] = final_analysis['bottlenecks']
        state['recommendations'] = final_analysis['recommendations']
        state['sla_compliance'] = final_analysis['sla_compliance']

        self.add_thought(
            state,
            "Analysis complete",
            f"Generated {len(final_analysis['recommendations'])} recommendations",
            "analyzing"
        )

        logger.info("\n✅ AnalyzerAgent Complete!")
        logger.info("="*80 + "\n")

        return state

    def _rule_based_analysis(self, metrics: Dict[str, Any], api_type: str) -> Dict[str, Any]:
        """
        Perform rule-based analysis of metrics.

        Returns:
            Dict with bottlenecks, recommendations, and SLA compliance
        """
        total_requests = metrics.get('total_requests', 0)
        total_failures = metrics.get('total_failures', 0)
        avg_response_time = metrics.get('avg_response_time', 0)
        percentile_95 = metrics.get('percentile_95', 0)
        percentile_99 = metrics.get('percentile_99', 0)
        requests_per_second = metrics.get('requests_per_second', 0)

        error_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0

        bottlenecks = []
        recommendations = []

        # Define SLA thresholds based on API type
        sla_thresholds = {
            'authentication': {'p95': 1000, 'error_rate': 1},
            'search': {'p95': 500, 'error_rate': 2},
            'transaction': {'p95': 2000, 'error_rate': 0.5},
            'crud_read': {'p95': 500, 'error_rate': 1},
            'crud_create': {'p95': 1000, 'error_rate': 1}
        }
        sla = sla_thresholds.get(api_type, {'p95': 1000, 'error_rate': 2})

        # Analyze response times
        if percentile_95 > sla['p95']:
            bottlenecks.append(
                f"P95 response time ({percentile_95:.0f}ms) exceeds SLA threshold ({sla['p95']}ms)"
            )
            recommendations.append(
                "Optimize database queries or add caching to reduce response times"
            )

        if percentile_99 > percentile_95 * 2:
            bottlenecks.append(
                f"High P99 response time ({percentile_99:.0f}ms) indicates occasional severe delays"
            )
            recommendations.append(
                "Investigate long-tail latency issues, possibly related to garbage collection or external service calls"
            )

        # Analyze error rates
        if error_rate > sla['error_rate']:
            bottlenecks.append(
                f"Error rate ({error_rate:.2f}%) exceeds SLA threshold ({sla['error_rate']}%)"
            )
            recommendations.append(
                "Review error logs to identify specific failure patterns and root causes"
            )

        if error_rate > 10:
            bottlenecks.append(
                f"High error rate ({error_rate:.1f}%) indicates significant stability issues"
            )
            recommendations.append(
                "Check for connection pool exhaustion, memory leaks, or cascading failures"
            )

        # Analyze throughput
        if requests_per_second < 10 and total_requests > 100:
            bottlenecks.append(
                f"Low throughput ({requests_per_second:.1f} req/s) suggests capacity constraints"
            )
            recommendations.append(
                "Consider horizontal scaling or optimizing request handling"
            )

        # SLA Compliance
        sla_compliance = {
            'p95_target': sla['p95'],
            'p95_actual': percentile_95,
            'p95_compliant': percentile_95 <= sla['p95'],
            'p95_margin': sla['p95'] - percentile_95,
            'error_rate_target': sla['error_rate'],
            'error_rate_actual': error_rate,
            'error_rate_compliant': error_rate <= sla['error_rate'],
            'overall_status': 'pass' if (percentile_95 <= sla['p95'] and error_rate <= sla['error_rate']) else 'fail'
        }

        return {
            'bottlenecks': bottlenecks,
            'recommendations': recommendations,
            'sla_compliance': sla_compliance,
            'assessment': self._determine_assessment(bottlenecks, sla_compliance)
        }

    def _determine_assessment(self, bottlenecks: List[str], sla_compliance: Dict[str, Any]) -> str:
        """Determine overall assessment."""
        if sla_compliance['overall_status'] == 'pass' and len(bottlenecks) == 0:
            return 'excellent'
        elif sla_compliance['overall_status'] == 'pass':
            return 'good'
        elif len(bottlenecks) <= 2:
            return 'warning'
        else:
            return 'critical'

    def _load_unique_failures(self, test_id: str) -> List[Dict[str, Any]]:
        """
        Load deduplicated failure samples from the failures file.

        Args:
            test_id: Test ID to load failures for

        Returns:
            List of unique failure samples
        """
        failures_file = Path("load_test_results") / f"{test_id}_failures.json"

        if not failures_file.exists():
            logger.info(f"   ℹ️  No failures file found: {failures_file}")
            return []

        try:
            with open(failures_file, 'r') as f:
                data = json.load(f)
                unique_failures = data.get('unique_failures', [])
                logger.info(f"   ✅ Loaded {len(unique_failures)} unique failure type(s) from {failures_file.name}")
                return unique_failures
        except Exception as e:
            logger.error(f"   ❌ Failed to load failures file: {e}")
            return []

    def _ai_powered_analysis(
        self,
        metrics: Dict[str, Any],
        api_type: str,
        rule_analysis: Dict[str, Any],
        test_id: str = ""
    ) -> Dict[str, Any]:
        """
        Use AI to provide deeper analysis and insights.

        Returns:
            Dict with AI-generated insights and recommendations
        """
        # Load deduplicated failure samples if available
        unique_failures = self._load_unique_failures(test_id)

        failures_section = ""
        if unique_failures:
            failures_section = f"""
UNIQUE FAILURE SAMPLES (Deduplicated by Status Code):
{json.dumps(unique_failures, indent=2)}

Total Unique Failure Types: {len(unique_failures)}
"""

        prompt = f"""Analyze these load test results and provide expert insights.

API Type: {api_type}

Metrics:
- Total Requests: {metrics.get('total_requests', 0)}
- Total Failures: {metrics.get('total_failures', 0)}
- Success Rate: {100 - (metrics.get('total_failures', 0) / max(metrics.get('total_requests', 1), 1) * 100):.2f}%
- Avg Response Time: {metrics.get('avg_response_time', 0):.0f}ms
- P95 Response Time: {metrics.get('percentile_95', 0):.0f}ms
- P99 Response Time: {metrics.get('percentile_99', 0):.0f}ms
- Requests/sec: {metrics.get('requests_per_second', 0):.1f}

Rule-Based Bottlenecks Detected:
{chr(10).join(f"- {b}" for b in rule_analysis['bottlenecks']) if rule_analysis['bottlenecks'] else "None"}
{failures_section}

Provide:
1. **Root Cause Analysis**: What are the likely root causes of performance issues AND failures?
2. **Deeper Insights**: What patterns or correlations do you see in metrics AND actual failure responses?
3. **Priority Recommendations**: Top 3 specific, actionable recommendations (most impactful first)
4. **Capacity Assessment**: Can this system handle production load?

IMPORTANT - Categorize Failure-Related Issues:
- If failures are due to TEST CONFIGURATION (e.g., 429 rate limiting = too many users, 401 = wrong credentials in test data), categorize as "test_improvement"
- If failures are due to API ISSUES (e.g., 500 server errors, slow response times, infrastructure problems), categorize as "api_improvement"

Examples:
- 429 Too Many Requests (100 occurrences) → Test Improvement (reduce load or adjust test config)
- 401 Unauthorized (20 occurrences) → Test Improvement (fix test credentials)
- 400 Bad Request → Could be either (check if test payload is invalid OR API validation is too strict)
- 500 Internal Server Error → API Improvement (server-side bug)
- High P99 latency → API Improvement (performance optimization needed)

Return ONLY a JSON object:
{{
  "root_causes": ["cause 1", "cause 2", ...],
  "insights": ["insight 1", "insight 2", ...],
  "priority_recommendations": [
    {{"action": "...", "impact": "high|medium|low", "effort": "high|medium|low", "description": "...", "category": "test_improvement|api_improvement"}},
    ...
  ],
  "capacity_assessment": "...",
  "failure_analysis": {{
    "test_config_issues": ["issue 1 (status code)", ...],
    "api_issues": ["issue 1 (status code)", ...]
  }}
}}"""

        try:
            response = self.call_llm(prompt)

            # Extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                ai_analysis = json.loads(json_match.group(0))
                return ai_analysis

        except Exception as e:
            print(f"AI analysis failed: {e}")

        # Fallback to structured default
        return {
            'root_causes': ['Unable to perform AI analysis'],
            'insights': ['Manual review of metrics recommended'],
            'priority_recommendations': [
                {
                    'action': 'Review detailed metrics',
                    'impact': 'high',
                    'effort': 'low',
                    'description': 'Examine request logs and error patterns for specific issues'
                }
            ],
            'capacity_assessment': 'Requires manual analysis'
        }

    def generate_summary(self, state: AgenticLoadTestState) -> str:
        """
        Generate executive summary of analysis.

        Returns:
            Human-readable summary
        """
        analysis = state.get('analysis', {})
        sla = analysis.get('sla_compliance', {})
        assessment = analysis.get('assessment', 'unknown')

        assessment_emoji = {
            'excellent': '🎉',
            'good': '✅',
            'warning': '⚠️',
            'critical': '❌'
        }

        emoji = assessment_emoji.get(assessment, '❓')

        summary = f"""{emoji} Load Test Analysis Summary

Overall Assessment: {assessment.upper()}

SLA Compliance:
- P95 Response Time: {sla.get('p95_actual', 0):.0f}ms (Target: {sla.get('p95_target', 0)}ms) {'✅' if sla.get('p95_compliant') else '❌'}
- Error Rate: {sla.get('error_rate_actual', 0):.2f}% (Target: <{sla.get('error_rate_target', 0)}%) {'✅' if sla.get('error_rate_compliant') else '❌'}

Bottlenecks Identified: {len(analysis.get('bottlenecks', []))}
{chr(10).join(f"  • {b}" for b in analysis.get('bottlenecks', [])[:3])}

Top Recommendations:
{chr(10).join(f"  {i+1}. {r.get('action', r) if isinstance(r, dict) else r}" for i, r in enumerate(analysis.get('priority_recommendations', analysis.get('recommendations', []))[:3]))}
"""
        return summary

    def analyze_and_suggest(
        self,
        metrics: Dict[str, Any],
        test_config: Dict[str, Any] = None,
        api_details: Dict[str, Any] = None
    ) -> AIAnalysis:
        """
        Generate AI-powered analysis with actionable suggestions.

        Args:
            metrics: Load test metrics (response times, errors, throughput)
            test_config: Test configuration (users, spawn_rate, run_time)
            api_details: API information (endpoint, method, type)

        Returns:
            AIAnalysis with performance score and suggestions
        """
        logger.info("\n🤖 Generating AI-powered suggestions...")

        # Extract values with defaults
        total_requests = metrics.get('total_requests', 0)
        total_failures = metrics.get('total_failures', 0)
        error_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0
        avg_response_time = metrics.get('avg_response_time', 0)
        p50 = metrics.get('median_response_time', 0)
        p95 = metrics.get('percentile_95', 0)
        p99 = metrics.get('percentile_99', 0)
        min_response = metrics.get('min_response_time', 0)
        max_response = metrics.get('max_response_time', 0)
        rps = metrics.get('requests_per_second', 0)

        # Test configuration
        if test_config is None:
            test_config = {}
        users = test_config.get('users', 10)
        spawn_rate = test_config.get('spawn_rate', 2)
        run_time = test_config.get('run_time', '5m')
        think_time_min = test_config.get('think_time_min', 1.0)
        think_time_max = test_config.get('think_time_max', 3.0)

        # API details
        if api_details is None:
            api_details = {}
        endpoint = api_details.get('endpoint', '/api/endpoint')
        method = api_details.get('method', 'GET')
        api_type = api_details.get('api_type', 'unknown')

        # Load deduplicated failure samples
        test_id = metrics.get('test_id', '')
        unique_failures = self._load_unique_failures(test_id)

        # Calculate performance score
        performance_score = self._calculate_performance_score(metrics)
        performance_level = self._determine_performance_level(performance_score)

        # Generate test suggestions (with failure analysis)
        test_suggestions = self._generate_test_suggestions(
            metrics=metrics,
            test_config=test_config,
            unique_failures=unique_failures
        )

        # Generate API suggestions (with failure analysis)
        api_suggestions = self._generate_api_suggestions(
            metrics=metrics,
            api_details=api_details,
            unique_failures=unique_failures
        )

        # Create AIAnalysis response
        analysis = AIAnalysis(
            test_id=metrics.get('test_id', str(uuid.uuid4())),
            performance_score=performance_score,
            performance_level=performance_level,
            test_suggestions=test_suggestions,
            api_suggestions=api_suggestions,
            generated_at=datetime.now().isoformat()
        )

        logger.info(f"   ✅ Performance Score: {performance_score}/100 ({performance_level})")
        logger.info(f"   ✅ Generated {len(test_suggestions)} test suggestions")
        logger.info(f"   ✅ Generated {len(api_suggestions)} API suggestions")

        return analysis

    def _calculate_performance_score(self, metrics: Dict[str, Any]) -> int:
        """
        Calculate performance score (0-100) based on metrics.

        Scoring criteria:
        - Error Rate (30 points): < 0.1% = 30, < 1% = 20, < 5% = 10, >= 5% = 0
        - p95 Response (30 points): < 200ms = 30, < 500ms = 20, < 1000ms = 10, >= 1000ms = 0
        - p99 Response (20 points): < 500ms = 20, < 1000ms = 15, < 2000ms = 10, >= 2000ms = 0
        - Consistency (20 points): (max - min) / avg < 5 = 20, < 10 = 15, < 20 = 10, >= 20 = 0
        """
        score = 0

        total_requests = metrics.get('total_requests', 0)
        total_failures = metrics.get('total_failures', 0)
        error_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0

        # Error rate score (30 points)
        if error_rate < 0.1:
            score += 30
        elif error_rate < 1.0:
            score += 20
        elif error_rate < 5.0:
            score += 10

        # p95 score (30 points)
        p95 = metrics.get('percentile_95', 0)
        if p95 < 200:
            score += 30
        elif p95 < 500:
            score += 20
        elif p95 < 1000:
            score += 10

        # p99 score (20 points)
        p99 = metrics.get('percentile_99', 0)
        if p99 < 500:
            score += 20
        elif p99 < 1000:
            score += 15
        elif p99 < 2000:
            score += 10

        # Consistency score (20 points)
        avg = metrics.get('avg_response_time', 1)
        max_resp = metrics.get('max_response_time', 0)
        min_resp = metrics.get('min_response_time', 0)
        variance_ratio = (max_resp - min_resp) / avg if avg > 0 else 0

        if variance_ratio < 5:
            score += 20
        elif variance_ratio < 10:
            score += 15
        elif variance_ratio < 20:
            score += 10

        return min(score, 100)

    def _determine_performance_level(self, score: int) -> str:
        """Determine performance level from score."""
        if score >= 80:
            return 'good'
        elif score >= 60:
            return 'warning'
        else:
            return 'critical'

    def _generate_test_suggestions(
        self,
        metrics: Dict[str, Any],
        test_config: Dict[str, Any],
        unique_failures: List[Dict[str, Any]] = None
    ) -> List[TestSuggestion]:
        """
        Generate test optimization suggestions using AI.

        Returns:
            List of TestSuggestion objects
        """
        total_requests = metrics.get('total_requests', 0)
        total_failures = metrics.get('total_failures', 0)
        error_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0
        avg_response_time = metrics.get('avg_response_time', 0)
        p50 = metrics.get('median_response_time', 0)
        p95 = metrics.get('percentile_95', 0)
        p99 = metrics.get('percentile_99', 0)
        rps = metrics.get('requests_per_second', 0)

        users = test_config.get('users', 10)
        spawn_rate = test_config.get('spawn_rate', 2)
        run_time = test_config.get('run_time', '5m')
        think_time_min = test_config.get('think_time_min', 1.0)
        think_time_max = test_config.get('think_time_max', 3.0)

        # Format failures section
        failures_section = ""
        if unique_failures:
            failures_section = f"""
ACTUAL FAILURE DETAILS (Deduplicated):
{json.dumps(unique_failures, indent=2)}

IMPORTANT: Analyze these ACTUAL error responses! If you see:
- 401 Unauthorized with "Invalid credentials" → Test data has wrong/expired credentials
- 429 Rate Limit → Test is sending too many requests
- 400 Bad Request → Test payload is invalid
- 403 Forbidden → Test user lacks permissions
"""

        prompt = f"""You are a load testing expert. Analyze these load test results and provide actionable test optimization suggestions.

Test Configuration:
- Users: {users}
- Spawn Rate: {spawn_rate}/s
- Duration: {run_time}
- Think Time: {think_time_min}-{think_time_max}s

Test Results:
- Total Requests: {total_requests}
- Failed Requests: {total_failures} ({error_rate:.2f}%)
- Average Response Time: {avg_response_time:.0f}ms
- p50: {p50:.0f}ms, p95: {p95:.0f}ms, p99: {p99:.0f}ms
- Requests/sec: {rps:.1f}
{failures_section}

Provide 2-4 test optimization suggestions focusing on:
1. Should we increase load to find breaking point?
2. Should we test with different load patterns (burst, sustained, spike)?
3. Should we adjust spawn rate or duration?
4. Should we test with different think times?

For each suggestion:
- Assign severity: "critical" (must do), "warning" (should do), "good" (optional enhancement)
- Provide clear title and description
- Suggest specific numeric values (users, spawn rate, duration)
- Explain the reasoning

Return ONLY valid JSON (no markdown, no backticks):
{{
  "suggestions": [
    {{
      "severity": "warning",
      "title": "clear concise title",
      "description": "why this test is needed",
      "metrics": {{
        "current_users": {users},
        "recommended_users": 500,
        "current_spawn_rate": {spawn_rate},
        "recommended_spawn_rate": 20.0,
        "current_duration": "{run_time}",
        "recommended_duration": "10m",
        "recommended_think_time_min": 1.0,
        "recommended_think_time_max": 3.0
      }},
      "reasoning": "why these values make sense"
    }}
  ]
}}"""

        try:
            response = self.call_llm(prompt)

            # Extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                ai_response = json.loads(json_match.group(0))
                suggestions = []

                for idx, sug in enumerate(ai_response.get('suggestions', [])):
                    suggestion = TestSuggestion(
                        id=f"test_{idx+1}",
                        severity=sug.get('severity', 'warning'),
                        title=sug.get('title', 'Test optimization'),
                        description=sug.get('description', ''),
                        reasoning=sug.get('reasoning', ''),
                        metrics=SuggestionMetrics(**sug.get('metrics', {}))
                    )
                    suggestions.append(suggestion)

                return suggestions

        except Exception as e:
            logger.error(f"Failed to generate test suggestions: {e}")

        # Fallback: rule-based suggestions
        return self._fallback_test_suggestions(metrics, test_config)

    def _generate_api_suggestions(
        self,
        metrics: Dict[str, Any],
        api_details: Dict[str, Any],
        unique_failures: List[Dict[str, Any]] = None
    ) -> List[APISuggestion]:
        """
        Generate API performance suggestions using AI.

        Returns:
            List of APISuggestion objects
        """
        total_requests = metrics.get('total_requests', 0)
        total_failures = metrics.get('total_failures', 0)
        error_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0
        avg_response_time = metrics.get('avg_response_time', 0)
        p50 = metrics.get('median_response_time', 0)
        p95 = metrics.get('percentile_95', 0)
        p99 = metrics.get('percentile_99', 0)
        min_response = metrics.get('min_response_time', 0)
        max_response = metrics.get('max_response_time', 0)
        rps = metrics.get('requests_per_second', 0)

        endpoint = api_details.get('endpoint', '/api/endpoint')
        method = api_details.get('method', 'GET')
        api_type = api_details.get('api_type', 'unknown')

        # Format failures section
        failures_section = ""
        if unique_failures:
            failures_section = f"""
ACTUAL FAILURE DETAILS (Deduplicated):
{json.dumps(unique_failures, indent=2)}

CRITICAL: Analyze these ACTUAL error responses! Categorize each failure:
- 401/403 Unauthorized/Forbidden → Usually TEST issue (bad credentials), NOT API issue
- 429 Rate Limit → Could be TEST (too aggressive) OR API (limits too strict)
- 400 Bad Request → Could be TEST (invalid payload) OR API (validation too strict)
- 500/502/503 Server Errors → API issue (server-side bug or infrastructure)
- Slow responses (>1s) → API issue (performance problem)

Only create API suggestions for ACTUAL API issues, not test configuration problems!
"""

        prompt = f"""You are an API performance expert. Analyze these load test results and provide actionable API optimization suggestions.

API Details:
- Endpoint: {endpoint}
- Method: {method}
- API Type: {api_type}

Test Results:
- Total Requests: {total_requests}
- Failed Requests: {total_failures} ({error_rate:.2f}%)
- Average Response Time: {avg_response_time:.0f}ms
- p50: {p50:.0f}ms, p95: {p95:.0f}ms, p99: {p99:.0f}ms
- Requests/sec: {rps:.1f}
- Min Response: {min_response:.0f}ms, Max Response: {max_response:.0f}ms
{failures_section}

Production Standards:
- Error Rate: < 0.1%
- p95 Response Time: < 200ms
- p99 Response Time: < 500ms

Provide 3-5 API optimization suggestions covering:
1. Response time optimization (if p95 > 200ms or p99 > 500ms)
2. Error handling (if error rate > 0.1%)
3. Scalability improvements (capacity, resource optimization)
4. Infrastructure recommendations (caching, database, rate limiting)

For each suggestion:
- Assign severity: "critical" (blocks production), "warning" (should fix), "good" (optimization)
- Assign category: "response_time", "error_rate", "scalability", "infrastructure"
- Provide high-level suggestion (non-technical)
- Provide technical suggestion (code/infrastructure specific)
- Include relevant metrics

Return ONLY valid JSON (no markdown, no backticks):
{{
  "suggestions": [
    {{
      "severity": "warning",
      "category": "response_time",
      "title": "clear concise title",
      "description": "what the problem is",
      "high_level": "non-technical suggestion",
      "technical": "specific code/infrastructure suggestion",
      "metrics": {{
        "current_p95": {p95},
        "target_p95": 200,
        "improvement_needed": "reduction percentage or description"
      }}
    }}
  ]
}}"""

        try:
            response = self.call_llm(prompt)

            # Extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                ai_response = json.loads(json_match.group(0))
                suggestions = []

                for idx, sug in enumerate(ai_response.get('suggestions', [])):
                    suggestion = APISuggestion(
                        id=f"api_{idx+1}",
                        severity=sug.get('severity', 'warning'),
                        category=sug.get('category', 'infrastructure'),
                        title=sug.get('title', 'API optimization'),
                        description=sug.get('description', ''),
                        high_level=sug.get('high_level', ''),
                        technical=sug.get('technical', ''),
                        metrics=SuggestionMetrics(**sug.get('metrics', {}))
                    )
                    suggestions.append(suggestion)

                return suggestions

        except Exception as e:
            logger.error(f"Failed to generate API suggestions: {e}")

        # Fallback: rule-based suggestions
        return self._fallback_api_suggestions(metrics, api_details)

    def _fallback_test_suggestions(
        self,
        metrics: Dict[str, Any],
        test_config: Dict[str, Any]
    ) -> List[TestSuggestion]:
        """Fallback rule-based test suggestions."""
        suggestions = []
        total_requests = metrics.get('total_requests', 0)
        total_failures = metrics.get('total_failures', 0)
        error_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0
        users = test_config.get('users', 10)
        spawn_rate = test_config.get('spawn_rate', 2)
        run_time = test_config.get('run_time', '5m')

        # Low error rate = increase load
        if error_rate < 2 and users < 500:
            suggestions.append(TestSuggestion(
                id="test_1",
                severity="warning",
                title="Increase load to find capacity limits",
                description=f"Your API handled {users} users with only {error_rate:.2f}% error rate. This indicates headroom for more load.",
                reasoning="Finding the breaking point helps plan capacity and understand system limits.",
                metrics=SuggestionMetrics(
                    current_users=users,
                    recommended_users=min(users * 5, 500),
                    current_spawn_rate=spawn_rate,
                    recommended_spawn_rate=min(spawn_rate * 2, 20),
                    current_duration=run_time,
                    recommended_duration="10m"
                )
            ))

        # High error rate = reduce load
        if error_rate > 10:
            suggestions.append(TestSuggestion(
                id="test_2",
                severity="critical",
                title="Reduce load to establish baseline",
                description=f"Error rate of {error_rate:.2f}% is too high. Need to find stable baseline first.",
                reasoning="Establishing a stable baseline helps isolate performance issues.",
                metrics=SuggestionMetrics(
                    current_users=users,
                    recommended_users=max(users // 5, 10),
                    current_spawn_rate=spawn_rate,
                    recommended_spawn_rate=max(spawn_rate / 2, 1),
                    current_duration=run_time,
                    recommended_duration="5m"
                )
            ))

        return suggestions

    def _fallback_api_suggestions(
        self,
        metrics: Dict[str, Any],
        api_details: Dict[str, Any]
    ) -> List[APISuggestion]:
        """Fallback rule-based API suggestions."""
        suggestions = []
        total_requests = metrics.get('total_requests', 0)
        total_failures = metrics.get('total_failures', 0)
        error_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0
        p95 = metrics.get('percentile_95', 0)
        p99 = metrics.get('percentile_99', 0)

        # High p95
        if p95 > 200:
            improvement_pct = ((p95 - 200) / p95 * 100)
            suggestions.append(APISuggestion(
                id="api_1",
                severity="warning" if p95 < 500 else "critical",
                category="response_time",
                title="Optimize p95 response time",
                description=f"Your p95 response time is {p95:.0f}ms, which is above the 200ms production standard.",
                high_level="Implement caching for frequently accessed data",
                technical="Add Redis cache with 5-minute TTL for GET endpoints. Consider database query optimization and indexing.",
                metrics=SuggestionMetrics(
                    current_p95=p95,
                    target_p95=200,
                    improvement_needed=f"{improvement_pct:.0f}% reduction needed"
                )
            ))

        # High error rate
        if error_rate > 0.1:
            suggestions.append(APISuggestion(
                id="api_2",
                severity="critical" if error_rate > 5 else "warning",
                category="error_rate",
                title="High error rate detected",
                description=f"{error_rate:.2f}% of requests failed",
                high_level="Investigate server errors and add retry logic",
                technical="Check database connection pool size. Current error rate suggests resource exhaustion. Increase DB connections from default to 50.",
                metrics=SuggestionMetrics(
                    current_error_rate=error_rate,
                    target_error_rate=0.1,
                    failed_requests=total_failures,
                    total_requests=total_requests
                )
            ))

        return suggestions
