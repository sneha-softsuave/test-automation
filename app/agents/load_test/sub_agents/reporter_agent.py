"""ReporterAgent: Generates comprehensive reports with AI-powered insights."""

from typing import Dict, Any
from datetime import datetime
import json
import logging

from app.agents.load_test.sub_agents.base_load_test_agent import BaseLoadTestAgent
from app.agents.load_test.state import AgenticLoadTestState

# Configure logger
logger = logging.getLogger(__name__)


class ReporterAgent(BaseLoadTestAgent):
    """
    Generates comprehensive HTML reports with AI insights.

    Responsibilities:
    - Create executive summary
    - Highlight key findings
    - Generate actionable recommendations
    - Create visualizations
    - Compare with historical data (if available)
    """

    def execute(self, state: AgenticLoadTestState) -> AgenticLoadTestState:
        """
        Generate comprehensive report.

        Args:
            state: Current state with analysis and metrics

        Returns:
            Updated state with report_path and report_summary
        """
        logger.info("\n" + "="*80)
        logger.info("🤖 AGENT 6/6: ReporterAgent")
        logger.info("="*80)

        self.add_thought(
            state,
            "Generating comprehensive report...",
            "Creating HTML report with AI-powered insights and recommendations",
            "reporting"
        )

        analysis = state.get('analysis', {})
        metrics = state.get('execution_metrics', {})
        api_type = state.get('api_type', 'unknown')
        test_id = state.get('test_id', 'test')

        logger.info("📋 Report Configuration:")
        logger.info(f"   • Test ID: {test_id}")
        logger.info(f"   • API Type: {api_type}")
        logger.info(f"   • Total Recommendations: {len(analysis.get('recommendations', []))}")

        # Generate report sections
        logger.info("\n📝 Step 1: Generating Executive Summary...")
        executive_summary = self._generate_executive_summary(analysis, metrics, api_type)
        logger.info("   ✅ Executive summary generated")

        logger.info("\n📝 Step 2: Generating Key Findings...")
        key_findings = self._generate_key_findings(analysis, metrics)
        logger.info(f"   ✅ {len(key_findings)} key finding(s) generated")

        logger.info("\n📝 Step 3: Generating Recommendations Section...")
        recommendations = self._generate_recommendations_section(analysis)
        logger.info("   ✅ Recommendations section generated")

        logger.info("\n📝 Step 4: Generating Technical Details...")
        technical_details = self._generate_technical_details(metrics)
        logger.info("   ✅ Technical details generated")

        # Build HTML report
        logger.info("\n🔨 Step 5: Building HTML Report...")
        html_report = self._build_html_report(
            test_id=test_id,
            api_type=api_type,
            executive_summary=executive_summary,
            key_findings=key_findings,
            recommendations=recommendations,
            technical_details=technical_details,
            analysis=analysis,
            metrics=metrics
        )

        logger.info(f"   ✅ HTML report generated ({len(html_report)} characters)")

        state['report_html'] = html_report
        state['report_summary'] = executive_summary

        logger.info("\n📊 Executive Summary:")
        logger.info("─" * 80)
        for line in executive_summary.strip().split('\n')[:10]:
            logger.info(f"   {line}")
        logger.info("─" * 80)

        self.add_thought(
            state,
            "Report generation complete",
            f"Generated comprehensive HTML report with {len(analysis.get('recommendations', []))} recommendations",
            "reporting"
        )

        logger.info("\n✅ ReporterAgent Complete!")
        logger.info("="*80 + "\n")

        return state

    def _generate_executive_summary(
        self,
        analysis: Dict[str, Any],
        metrics: Dict[str, Any],
        api_type: str
    ) -> str:
        """Generate executive summary using AI."""
        sla = analysis.get('sla_compliance', {})
        assessment = analysis.get('assessment', 'unknown')

        total_requests = metrics.get('total_requests', 0)
        success_rate = 100 - (metrics.get('total_failures', 0) / max(total_requests, 1) * 100)

        summary = f"""
The load test for the {api_type} API completed with {total_requests:,} requests and a {success_rate:.1f}% success rate.

**Overall Assessment**: {assessment.upper()}

**Performance**: The 95th percentile response time was {sla.get('p95_actual', 0):.0f}ms
{'✅ meeting' if sla.get('p95_compliant') else '❌ exceeding'} the SLA target of {sla.get('p95_target', 0)}ms.

**Reliability**: The error rate was {sla.get('error_rate_actual', 0):.2f}%
{'✅ within' if sla.get('error_rate_compliant') else '❌ above'} the acceptable threshold of {sla.get('error_rate_target', 0)}%.

{f"**Critical Issues**: {len(analysis.get('bottlenecks', []))} bottlenecks identified requiring immediate attention." if analysis.get('bottlenecks') else "**Status**: System performed well under load with no critical issues."}
"""
        return summary.strip()

    def _generate_key_findings(
        self,
        analysis: Dict[str, Any],
        metrics: Dict[str, Any]
    ) -> list:
        """Generate list of key findings."""
        findings = []

        # Performance findings
        p95 = metrics.get('percentile_95', 0)
        p99 = metrics.get('percentile_99', 0)

        if p95 < 500:
            findings.append({
                'type': 'positive',
                'title': 'Excellent Response Times',
                'description': f'95% of requests completed in under {p95:.0f}ms, indicating optimal performance.'
            })
        elif p95 > 2000:
            findings.append({
                'type': 'negative',
                'title': 'Slow Response Times',
                'description': f'95% of requests took {p95:.0f}ms, suggesting performance bottlenecks.'
            })

        # Error rate findings
        error_rate = analysis.get('sla_compliance', {}).get('error_rate_actual', 0)
        if error_rate < 1:
            findings.append({
                'type': 'positive',
                'title': 'High Reliability',
                'description': f'Error rate of {error_rate:.2f}% demonstrates excellent system stability.'
            })
        elif error_rate > 10:
            findings.append({
                'type': 'critical',
                'title': 'Significant Error Rate',
                'description': f'Error rate of {error_rate:.1f}% indicates critical stability issues requiring immediate investigation.'
            })

        # Bottleneck findings
        for bottleneck in analysis.get('bottlenecks', [])[:3]:
            findings.append({
                'type': 'warning',
                'title': 'Performance Bottleneck',
                'description': bottleneck
            })

        # AI insights
        for insight in analysis.get('ai_insights', [])[:2]:
            findings.append({
                'type': 'info',
                'title': 'AI Insight',
                'description': insight
            })

        return findings

    def _generate_recommendations_section(self, analysis: Dict[str, Any]) -> list:
        """Generate prioritized recommendations."""
        priority_recs = analysis.get('priority_recommendations', [])

        if priority_recs and isinstance(priority_recs[0], dict):
            return priority_recs[:5]  # Top 5 AI recommendations

        # Fallback to regular recommendations
        recommendations = analysis.get('recommendations', [])
        return [
            {
                'action': rec,
                'impact': 'medium',
                'effort': 'medium',
                'description': rec
            }
            for rec in recommendations[:5]
        ]

    def _generate_technical_details(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Extract technical details for report."""
        return {
            'total_requests': metrics.get('total_requests', 0),
            'total_failures': metrics.get('total_failures', 0),
            'requests_per_second': metrics.get('requests_per_second', 0),
            'avg_response_time': metrics.get('avg_response_time', 0),
            'min_response_time': metrics.get('min_response_time', 0),
            'max_response_time': metrics.get('max_response_time', 0),
            'median_response_time': metrics.get('median_response_time', 0),
            'percentile_95': metrics.get('percentile_95', 0),
            'percentile_99': metrics.get('percentile_99', 0),
            'current_users': metrics.get('current_users', 0),
            'elapsed_time': metrics.get('elapsed_time', 0)
        }

    def _build_html_report(
        self,
        test_id: str,
        api_type: str,
        executive_summary: str,
        key_findings: list,
        recommendations: list,
        technical_details: Dict[str, Any],
        analysis: Dict[str, Any],
        metrics: Dict[str, Any]
    ) -> str:
        """Build complete HTML report."""

        # Determine status badge
        assessment = analysis.get('assessment', 'unknown')
        status_badges = {
            'excellent': ('🎉 Excellent', '#10b981', '#d1fae5'),
            'good': ('✅ Good', '#3b82f6', '#dbeafe'),
            'warning': ('⚠️ Warning', '#f59e0b', '#fef3c7'),
            'critical': ('❌ Critical', '#ef4444', '#fee2e2')
        }
        badge_text, badge_color, badge_bg = status_badges.get(assessment, ('❓ Unknown', '#6b7280', '#f3f4f6'))

        # Build findings HTML
        findings_html = ""
        for finding in key_findings:
            icon_map = {
                'positive': '✅',
                'negative': '❌',
                'warning': '⚠️',
                'critical': '🔴',
                'info': 'ℹ️'
            }
            color_map = {
                'positive': '#10b981',
                'negative': '#ef4444',
                'warning': '#f59e0b',
                'critical': '#dc2626',
                'info': '#3b82f6'
            }
            icon = icon_map.get(finding['type'], 'ℹ️')
            color = color_map.get(finding['type'], '#6b7280')

            findings_html += f"""
            <div style="border-left: 4px solid {color}; padding: 1rem; margin-bottom: 1rem; background: #f9fafb; border-radius: 0.375rem;">
                <div style="font-weight: 600; color: #111827; margin-bottom: 0.5rem;">
                    {icon} {finding['title']}
                </div>
                <div style="color: #6b7280; font-size: 0.875rem;">
                    {finding['description']}
                </div>
            </div>
            """

        # Build recommendations HTML
        recommendations_html = ""
        for i, rec in enumerate(recommendations, 1):
            if isinstance(rec, dict):
                impact_colors = {'high': '#ef4444', 'medium': '#f59e0b', 'low': '#10b981'}
                impact_color = impact_colors.get(rec.get('impact', 'medium'), '#f59e0b')

                recommendations_html += f"""
                <div style="background: white; border: 1px solid #e5e7eb; border-radius: 0.5rem; padding: 1.5rem; margin-bottom: 1rem;">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.75rem;">
                        <div style="font-weight: 600; color: #111827; font-size: 1.125rem;">
                            {i}. {rec.get('action', 'Recommendation')}
                        </div>
                        <div style="display: flex; gap: 0.5rem;">
                            <span style="background: {impact_color}20; color: {impact_color}; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600;">
                                Impact: {rec.get('impact', 'medium').upper()}
                            </span>
                            <span style="background: #e5e7eb; color: #6b7280; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600;">
                                Effort: {rec.get('effort', 'medium').upper()}
                            </span>
                        </div>
                    </div>
                    <div style="color: #6b7280; line-height: 1.6;">
                        {rec.get('description', '')}
                    </div>
                </div>
                """
            else:
                recommendations_html += f"""
                <div style="background: white; border: 1px solid #e5e7eb; border-radius: 0.5rem; padding: 1.5rem; margin-bottom: 1rem;">
                    <div style="font-weight: 600; color: #111827; margin-bottom: 0.5rem;">
                        {i}. {rec}
                    </div>
                </div>
                """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Load Test Report - {test_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif; background: #f9fafb; color: #111827; line-height: 1.6; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 3rem 2rem; border-radius: 1rem; margin-bottom: 2rem; }}
        .status-badge {{ display: inline-block; background: {badge_bg}; color: {badge_color}; padding: 0.5rem 1.5rem; border-radius: 9999px; font-weight: 600; font-size: 0.875rem; }}
        .section {{ background: white; border-radius: 0.75rem; padding: 2rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .section-title {{ font-size: 1.5rem; font-weight: 700; color: #111827; margin-bottom: 1rem; border-bottom: 2px solid #e5e7eb; padding-bottom: 0.75rem; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-top: 1.5rem; }}
        .metric-card {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 0.5rem; padding: 1rem; }}
        .metric-value {{ font-size: 2rem; font-weight: 700; color: #667eea; }}
        .metric-label {{ font-size: 0.875rem; color: #6b7280; margin-top: 0.25rem; }}
        .footer {{ text-align: center; color: #6b7280; margin-top: 3rem; padding-top: 2rem; border-top: 1px solid #e5e7eb; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                <h1 style="font-size: 2.5rem;">🚀 Load Test Report</h1>
                <span class="status-badge">{badge_text}</span>
            </div>
            <div style="opacity: 0.9;">
                <div style="font-size: 1.125rem; margin-bottom: 0.5rem;">API Type: <strong>{api_type.replace('_', ' ').title()}</strong></div>
                <div style="font-size: 0.875rem;">Test ID: {test_id} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
            </div>
        </div>

        <div class="section">
            <h2 class="section-title">📊 Executive Summary</h2>
            <div style="white-space: pre-line; line-height: 1.8; color: #374151;">
                {executive_summary}
            </div>
        </div>

        <div class="section">
            <h2 class="section-title">🔍 Key Findings</h2>
            {findings_html if findings_html else '<p style="color: #6b7280;">No specific findings to report.</p>'}
        </div>

        <div class="section">
            <h2 class="section-title">💡 Recommendations</h2>
            {recommendations_html if recommendations_html else '<p style="color: #6b7280;">No recommendations at this time.</p>'}
        </div>

        <div class="section">
            <h2 class="section-title">📈 Technical Metrics</h2>
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-value">{technical_details['total_requests']:,}</div>
                    <div class="metric-label">Total Requests</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value" style="color: {'#10b981' if technical_details['total_failures'] == 0 else '#ef4444'};">{technical_details['total_failures']:,}</div>
                    <div class="metric-label">Failures</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{technical_details['requests_per_second']:.1f}</div>
                    <div class="metric-label">Requests/sec</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{technical_details['avg_response_time']:.0f}ms</div>
                    <div class="metric-label">Avg Response Time</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{technical_details['percentile_95']:.0f}ms</div>
                    <div class="metric-label">P95 Response Time</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{technical_details['percentile_99']:.0f}ms</div>
                    <div class="metric-label">P99 Response Time</div>
                </div>
            </div>
        </div>

        <div class="footer">
            <p>Generated by AI-Powered Load Testing System</p>
            <p style="font-size: 0.875rem; margin-top: 0.5rem;">🤖 Powered by ConfigParser, DataGenerator, Locust, Executor, Analyzer & Reporter Agents</p>
        </div>
    </div>
</body>
</html>"""

        return html
