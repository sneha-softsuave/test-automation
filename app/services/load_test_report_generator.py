"""HTML Report Generator for Load Tests."""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.models.load_test_models import LoadTestMetrics, APIConfig, LoadTestConfig, AIAnalysis, TestSuggestion, APISuggestion


class LoadTestReportGenerator:
    """Generate HTML reports for load test results."""

    def __init__(self, results_dir: Path = Path("load_test_results")):
        self.results_dir = results_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.current_report_file = self.results_dir / "current_report.txt"

    def generate_manual_report(
        self,
        test_id: str,
        api: APIConfig,
        config: LoadTestConfig,
        metrics: LoadTestMetrics,
        duration: float,
        llm_provider: str = "groq"
    ) -> str:
        """Generate HTML report for manual (single API) test."""

        print(f"🔍 [REPORT] Starting manual report generation for test_id: {test_id}", flush=True)
        print(f"🔍 [REPORT] API: {api.name if api else 'None'}", flush=True)
        print(f"🔍 [REPORT] Config: {config}", flush=True)
        print(f"🔍 [REPORT] Metrics: {metrics}", flush=True)
        print(f"🔍 [REPORT] Duration: {duration}", flush=True)
        print(f"🔍 [REPORT] LLM Provider: {llm_provider}", flush=True)

        try:
            report_filename = f"report_{test_id}.html"
            report_path = self.results_dir / report_filename

            # Fetch AI insights from cache
            ai_insights = self._get_ai_insights(test_id, llm_provider)

            html_content = self._generate_html(
                title=f"Load Test Report - {api.name}",
                test_type="Manual Test",
                test_id=test_id,
                apis=[{
                    "name": api.name,
                    "endpoint": f"{api.base_url}{api.endpoint}",
                    "method": api.method,
                    "config": config,
                    "metrics": metrics,
                    "duration": duration
                }],
                total_duration=duration,
                ai_insights=ai_insights
            )

            # Write report
            with open(report_path, 'w') as f:
                f.write(html_content)

            # Update current report pointer
            self._update_current_report(report_filename, test_id, 'manual', api.name)

            print(f"📊 Generated manual test report: {report_filename}", flush=True)
            return report_filename

        except Exception as e:
            print(f"❌ [REPORT] Error generating manual report: {e}", flush=True)
            import traceback
            traceback.print_exc()
            raise

    def generate_sequential_report(
        self,
        sequential_test_id: str,
        api_results: List[Dict[str, Any]],
        total_duration: float,
        llm_provider: str = "groq"
    ) -> str:
        """Generate HTML report for sequential test with multiple APIs."""

        print(f"🔍 [REPORT] Starting sequential report generation for: {sequential_test_id}", flush=True)
        print(f"🔍 [REPORT] Number of API results: {len(api_results)}", flush=True)
        print(f"🔍 [REPORT] Total duration: {total_duration}", flush=True)
        print(f"🔍 [REPORT] LLM Provider: {llm_provider}", flush=True)

        try:
            report_filename = f"report_{sequential_test_id}.html"
            report_path = self.results_dir / report_filename

            # Fetch AI insights from cache
            ai_insights = self._get_ai_insights(sequential_test_id, llm_provider)

            html_content = self._generate_html(
                title=f"Sequential Load Test Report",
                test_type="Sequential Test",
                test_id=sequential_test_id,
                apis=api_results,
                total_duration=total_duration,
                ai_insights=ai_insights
            )

            # Write report
            with open(report_path, 'w') as f:
                f.write(html_content)

            # Update current report pointer
            self._update_current_report(report_filename, sequential_test_id, 'sequential')

            print(f"📊 Generated sequential test report: {report_filename}", flush=True)
            return report_filename

        except Exception as e:
            print(f"❌ [REPORT] Error generating sequential report: {e}", flush=True)
            import traceback
            traceback.print_exc()
            raise

    def _update_current_report(self, filename: str, test_id: str, test_type: str, api_name: str = None):
        """Update the current report pointer file."""
        current_report_info = {
            "filename": filename,
            "test_id": test_id,
            "type": test_type,
            "timestamp": datetime.now().isoformat(),
            "api_name": api_name
        }

        with open(self.current_report_file, 'w') as f:
            json.dump(current_report_info, f)

        print(f"📄 Updated current_report.txt: {filename}", flush=True)

    def get_current_report(self) -> Optional[Dict[str, Any]]:
        """Get information about the current/latest report."""
        if not self.current_report_file.exists():
            return None

        try:
            with open(self.current_report_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error reading current report file: {e}", flush=True)
            return None

    def _get_ai_insights(self, test_id: str, llm_provider: str = "groq") -> Optional[AIAnalysis]:
        """Fetch AI insights from cache without regenerating."""
        try:
            from app.api.routes.load_test import ai_analysis_cache
            cache_key = f"{test_id}_{llm_provider}"
            insights = ai_analysis_cache.get(cache_key)
            if insights:
                print(f"✅ [REPORT] Found AI insights in cache for {cache_key}", flush=True)
            else:
                print(f"⚠️ [REPORT] No AI insights found in cache for {cache_key}", flush=True)
            return insights
        except Exception as e:
            print(f"⚠️ [REPORT] Error fetching AI insights: {e}", flush=True)
            return None

    def _generate_ai_insights_html(self, insights: AIAnalysis, test_id: str) -> str:
        """Generate HTML for AI insights section matching AISuggestionsPanel design."""
        if not insights:
            return ""

        # Determine performance level styling
        level = insights.performance_level.lower()
        level_colors = {
            "good": {"border": "#10b981", "emoji": "✅", "text": "Good"},
            "warning": {"border": "#f59e0b", "emoji": "⚠️", "text": "Warning"},
            "critical": {"border": "#ef4444", "emoji": "❌", "text": "Critical"}
        }
        level_info = level_colors.get(level, level_colors["warning"])

        # Generate test suggestions HTML
        test_suggestions_html = ""
        if insights.test_suggestions:
            for suggestion in insights.test_suggestions:
                severity_class = f"severity-{suggestion.severity.lower()}"

                # Build metrics HTML
                metrics_html = ""
                if suggestion.metrics:
                    metrics_items = []
                    m = suggestion.metrics

                    if m.current_users is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Current Users</div><div class="metric-value">{m.current_users}</div></div>')
                    if m.recommended_users is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Recommended Users</div><div class="metric-value">{m.recommended_users}</div></div>')
                    if m.current_spawn_rate is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Current Spawn Rate</div><div class="metric-value">{m.current_spawn_rate}/s</div></div>')
                    if m.recommended_spawn_rate is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Recommended Spawn Rate</div><div class="metric-value">{m.recommended_spawn_rate}/s</div></div>')
                    if m.current_duration is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Current Duration</div><div class="metric-value">{m.current_duration}</div></div>')
                    if m.recommended_duration is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Recommended Duration</div><div class="metric-value">{m.recommended_duration}</div></div>')

                    if metrics_items:
                        metrics_html = f'<div class="metrics-grid">{"".join(metrics_items)}</div>'

                test_suggestions_html += f"""
                <div class="suggestion-card">
                    <div class="suggestion-header">
                        <h4 class="suggestion-title">{suggestion.title}</h4>
                        <span class="severity-badge {severity_class}">{suggestion.severity.upper()}</span>
                    </div>
                    <p class="suggestion-description">{suggestion.description}</p>
                    {metrics_html}
                    <div class="suggestion-reasoning">
                        <strong>💡 Reasoning:</strong> {suggestion.reasoning}
                    </div>
                </div>
                """

        # Generate API suggestions HTML
        api_suggestions_html = ""
        if insights.api_suggestions:
            for suggestion in insights.api_suggestions:
                severity_class = f"severity-{suggestion.severity.lower()}"
                category_emoji = {
                    "response_time": "⏱️",
                    "error_rate": "❌",
                    "scalability": "📈",
                    "infrastructure": "🏗️"
                }.get(suggestion.category, "🔧")

                # Build metrics HTML
                metrics_html = ""
                if suggestion.metrics:
                    metrics_items = []
                    m = suggestion.metrics

                    if m.current_value is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Current Value</div><div class="metric-value">{m.current_value:.2f}ms</div></div>')
                    if m.target_value is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Target Value</div><div class="metric-value">{m.target_value:.2f}ms</div></div>')
                    if m.current_error_rate is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Current Error Rate</div><div class="metric-value">{m.current_error_rate:.2f}%</div></div>')
                    if m.target_error_rate is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Target Error Rate</div><div class="metric-value">{m.target_error_rate:.2f}%</div></div>')
                    if m.failed_requests is not None and m.total_requests is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Failed Requests</div><div class="metric-value">{m.failed_requests}/{m.total_requests}</div></div>')
                    if m.current_p95 is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Current P95</div><div class="metric-value">{m.current_p95:.2f}ms</div></div>')
                    if m.target_p95 is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Target P95</div><div class="metric-value">{m.target_p95:.2f}ms</div></div>')
                    if m.current_p99 is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Current P99</div><div class="metric-value">{m.current_p99:.2f}ms</div></div>')
                    if m.target_p99 is not None:
                        metrics_items.append(f'<div class="metric-item"><div class="metric-label">Target P99</div><div class="metric-value">{m.target_p99:.2f}ms</div></div>')

                    if metrics_items:
                        metrics_html = f'<div class="metrics-grid">{"".join(metrics_items)}</div>'

                api_suggestions_html += f"""
                <div class="suggestion-card">
                    <div class="suggestion-header">
                        <h4 class="suggestion-title">{category_emoji} {suggestion.title}</h4>
                        <span class="severity-badge {severity_class}">{suggestion.severity.upper()}</span>
                    </div>
                    <p class="suggestion-category"><strong>Category:</strong> {suggestion.category.replace('_', ' ').title()}</p>
                    <p class="suggestion-description">{suggestion.description}</p>
                    {metrics_html}
                    <div class="suggestion-details">
                        <div class="detail-section">
                            <strong>📋 High-Level Solution:</strong>
                            <p>{suggestion.high_level}</p>
                        </div>
                        <div class="detail-section">
                            <strong>⚙️ Technical Details:</strong>
                            <p>{suggestion.technical}</p>
                        </div>
                    </div>
                </div>
                """

        # Build the full AI insights section
        test_suggestions_section = ""
        if test_suggestions_html:
            test_suggestions_count = len(insights.test_suggestions)
            test_suggestions_section = f"""
            <div class="suggestions-section">
                <div class="section-header" onclick="toggleSection('test-suggestions')">
                    <h3>🎯 Test Optimization Suggestions ({test_suggestions_count})</h3>
                    <span class="toggle-icon" id="test-suggestions-icon">▼</span>
                </div>
                <div class="section-content" id="test-suggestions-content">
                    {test_suggestions_html}
                </div>
            </div>
            """

        api_suggestions_section = ""
        if api_suggestions_html:
            api_suggestions_count = len(insights.api_suggestions)
            api_suggestions_section = f"""
            <div class="suggestions-section">
                <div class="section-header" onclick="toggleSection('api-suggestions')">
                    <h3>⚡ API Performance Suggestions ({api_suggestions_count})</h3>
                    <span class="toggle-icon" id="api-suggestions-icon">▼</span>
                </div>
                <div class="section-content" id="api-suggestions-content">
                    {api_suggestions_html}
                </div>
            </div>
            """

        # Determine message based on score
        score_message = ""
        if insights.performance_score >= 80:
            score_message = "Excellent performance! Your API is handling the load well."
        elif insights.performance_score >= 60:
            score_message = "Good performance with some areas for improvement."
        elif insights.performance_score >= 40:
            score_message = "Moderate performance. Review suggestions to optimize."
        else:
            score_message = "Performance issues detected. Please review critical suggestions."

        # Add hint text if there are suggestions
        hint_text = ""
        if test_suggestions_html or api_suggestions_html:
            hint_text = '<p class="expand-hint">💡 Click section headers below to expand and view detailed suggestions</p>'

        html = f"""
        <!-- AI Insights Section -->
        <div class="ai-insights-section">
            <h2 class="ai-insights-title">🤖 AI-Powered Insights</h2>

            <!-- Performance Score -->
            <div class="performance-score-container">
                <div class="score-circle score-{level}">
                    <div class="score-value">{insights.performance_score}</div>
                    <div class="score-label">Performance Score</div>
                </div>
                <div class="score-info">
                    <div class="score-badge score-badge-{level}">{level_info['emoji']} {level_info['text']}</div>
                    <p class="score-message">{score_message}</p>
                    <div class="test-id-display">Test ID: {test_id}</div>
                    <div class="generated-at">Generated: {insights.generated_at}</div>
                </div>
            </div>

            {hint_text}

            {test_suggestions_section}
            {api_suggestions_section}

            {'' if (test_suggestions_html or api_suggestions_html) else '<div class="no-suggestions">🎉 No critical issues found. Your API is performing well!</div>'}
        </div>
        """

        return html

    def _generate_html(
        self,
        title: str,
        test_type: str,
        test_id: str,
        apis: List[Dict[str, Any]],
        total_duration: float,
        ai_insights: Optional[AIAnalysis] = None
    ) -> str:
        """Generate HTML content for the report."""

        # Helper to get metric value (handles both dict and object)
        def get_metric(metrics, key, default=0):
            if metrics is None:
                return default
            if isinstance(metrics, dict):
                return metrics.get(key, default) or default
            return getattr(metrics, key, default) or default

        # Helper to get config value (handles both dict and object)
        def get_config(config, key, default=None):
            if config is None:
                return default
            if isinstance(config, dict):
                return config.get(key, default)
            return getattr(config, key, default)

        # Calculate summary statistics
        total_requests = sum(get_metric(api.get('metrics'), 'total_requests', 0) for api in apis)
        total_failures = sum(get_metric(api.get('metrics'), 'total_failures', 0) for api in apis)
        avg_rps = sum(get_metric(api.get('metrics'), 'requests_per_second', 0) for api in apis) / len(apis) if apis else 0
        avg_response_time = sum(get_metric(api.get('metrics'), 'avg_response_time', 0) for api in apis) / len(apis) if apis else 0

        # Generate API sections with individual charts
        api_sections_html = ""
        for idx, api in enumerate(apis, 1):
            metrics = api.get('metrics', {})
            config = api.get('config', {})

            api_sections_html += f"""
            <div class="api-section">
                <div class="api-header">
                    <h2>
                        <span class="api-number">{idx}</span>
                        {api.get('name', 'Unknown API')}
                    </h2>
                    <span class="method-badge method-{api.get('method', 'GET').lower()}">{api.get('method', 'GET')}</span>
                </div>
                <div class="api-details">
                    <div class="detail-row">
                        <span class="detail-label">Endpoint:</span>
                        <span class="detail-value"><code>{api.get('endpoint', 'N/A')}</code></span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Duration:</span>
                        <span class="detail-value">{api.get('duration', 0):.1f}s</span>
                    </div>
                </div>

                <!-- Individual API Chart -->
                <div class="api-chart-section">
                    <h3 class="chart-subtitle">📊 Response Time Breakdown</h3>
                    <div class="chart-container">
                        <canvas id="apiChart_{idx}"></canvas>
                    </div>
                </div>

                <div class="metrics-grid">
                    <div class="metric-card purple">
                        <div class="metric-value">{get_config(config, 'users', 10)}</div>
                        <div class="metric-label">Users</div>
                    </div>
                    <div class="metric-card pink">
                        <div class="metric-value">{get_metric(metrics, 'requests_per_second', 0):.2f}</div>
                        <div class="metric-label">Requests/sec</div>
                    </div>
                    <div class="metric-card cyan">
                        <div class="metric-value">{get_metric(metrics, 'avg_response_time', 0):.0f}ms</div>
                        <div class="metric-label">Avg Response</div>
                    </div>
                    <div class="metric-card green">
                        <div class="metric-value">{get_metric(metrics, 'failure_rate', 0):.1f}%</div>
                        <div class="metric-label">Failure Rate</div>
                    </div>
                </div>

                <div class="stats-table">
                    <table>
                        <tr>
                            <th>Total Requests</th>
                            <td>{get_metric(metrics, 'total_requests', 0)}</td>
                            <th>Total Failures</th>
                            <td>{get_metric(metrics, 'total_failures', 0)}</td>
                        </tr>
                        <tr>
                            <th>Min Response Time</th>
                            <td>{get_metric(metrics, 'min_response_time', 0):.0f}ms</td>
                            <th>Max Response Time</th>
                            <td>{get_metric(metrics, 'max_response_time', 0):.0f}ms</td>
                        </tr>
                        <tr>
                            <th>Median Response Time</th>
                            <td>{get_metric(metrics, 'median_response_time', 0):.0f}ms</td>
                            <th>95th Percentile</th>
                            <td>{get_metric(metrics, 'percentile_95', 0):.0f}ms</td>
                        </tr>
                        <tr>
                            <th>99th Percentile</th>
                            <td>{get_metric(metrics, 'percentile_99', 0):.0f}ms</td>
                            <th>Test Configuration</th>
                            <td>{get_config(config, 'users', 10)} users @ {get_config(config, 'spawn_rate', 2)}/s for {get_config(config, 'run_time', '5m')}</td>
                        </tr>
                    </table>
                </div>
            </div>
            """

        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 2rem;
            color: #1f2937;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }}

        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2rem;
            text-align: center;
        }}

        .header h1 {{
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }}

        .header .subtitle {{
            opacity: 0.9;
            font-size: 1rem;
        }}

        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            padding: 2rem;
            background: #f9fafb;
        }}

        .summary-card {{
            background: white;
            padding: 1.5rem;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}

        .summary-card .value {{
            font-size: 2rem;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 0.5rem;
        }}

        .summary-card .label {{
            color: #6b7280;
            font-size: 0.875rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .content {{
            padding: 2rem;
        }}

        .api-section {{
            background: #f9fafb;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border: 1px solid #e5e7eb;
        }}

        .api-header {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 1rem;
        }}

        .api-header h2 {{
            flex: 1;
            font-size: 1.5rem;
            color: #111827;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}

        .api-number {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 32px;
            height: 32px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border-radius: 50%;
            font-size: 1rem;
            font-weight: bold;
        }}

        .method-badge {{
            padding: 0.25rem 0.75rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: bold;
            text-transform: uppercase;
        }}

        .method-get {{ background: #10b981; color: white; }}
        .method-post {{ background: #3b82f6; color: white; }}
        .method-put {{ background: #f59e0b; color: white; }}
        .method-delete {{ background: #ef4444; color: white; }}
        .method-patch {{ background: #8b5cf6; color: white; }}

        .api-details {{
            margin-bottom: 1.5rem;
        }}

        .detail-row {{
            display: flex;
            gap: 1rem;
            padding: 0.5rem 0;
            border-bottom: 1px solid #e5e7eb;
        }}

        .detail-row:last-child {{
            border-bottom: none;
        }}

        .detail-label {{
            font-weight: 600;
            color: #6b7280;
            min-width: 100px;
        }}

        .detail-value {{
            flex: 1;
            color: #111827;
        }}

        .detail-value code {{
            background: #e5e7eb;
            padding: 0.125rem 0.5rem;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 0.875rem;
        }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin: 1.5rem 0;
        }}

        .metric-card {{
            padding: 1.5rem;
            border-radius: 12px;
            text-align: center;
            color: white;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}

        .metric-card.purple {{ background: linear-gradient(135deg, #667eea, #764ba2); }}
        .metric-card.pink {{ background: linear-gradient(135deg, #f093fb, #f5576c); }}
        .metric-card.cyan {{ background: linear-gradient(135deg, #4facfe, #00f2fe); }}
        .metric-card.green {{ background: linear-gradient(135deg, #43e97b, #38f9d7); }}

        .metric-value {{
            font-size: 2rem;
            font-weight: bold;
            color: white;
            margin-bottom: 0.5rem;
        }}

        .metric-label {{
            font-size: 0.875rem;
            color: white;
            opacity: 0.9;
        }}

        .stats-table {{
            margin-top: 1.5rem;
        }}

        .stats-table table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 8px;
            overflow: hidden;
        }}

        .stats-table th,
        .stats-table td {{
            padding: 0.75rem 1rem;
            text-align: left;
            border-bottom: 1px solid #e5e7eb;
        }}

        .stats-table th {{
            background: #f3f4f6;
            font-weight: 600;
            color: #374151;
            font-size: 0.875rem;
        }}

        .stats-table td {{
            color: #1f2937;
        }}

        .stats-table tr:last-child th,
        .stats-table tr:last-child td {{
            border-bottom: none;
        }}

        .footer {{
            text-align: center;
            padding: 2rem;
            background: #f9fafb;
            color: #6b7280;
            font-size: 0.875rem;
            border-top: 1px solid #e5e7eb;
        }}

        .charts-section {{
            margin: 2rem 0;
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}

        .chart-container {{
            margin: 2rem 0;
            padding: 1rem;
            background: #f9fafb;
            border-radius: 8px;
        }}

        .chart-title {{
            font-size: 1.25rem;
            font-weight: 600;
            color: #111827;
            margin-bottom: 1rem;
        }}

        .download-buttons {{
            display: flex;
            gap: 1rem;
            justify-content: center;
            margin: 2rem 0;
        }}

        .download-btn {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem 1.5rem;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            border: none;
            cursor: pointer;
            font-size: 0.95rem;
        }}

        .download-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
        }}

        .preview-btn {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem 1.5rem;
            background: linear-gradient(135deg, #10b981, #059669);
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            border: none;
            cursor: pointer;
            font-size: 0.95rem;
        }}

        .preview-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
        }}

        canvas {{
            max-width: 100%;
            height: 300px;
        }}

        .api-chart-section {{
            margin: 1.5rem 0;
            padding: 1.5rem;
            background: white;
            border-radius: 8px;
            border: 1px solid #e5e7eb;
        }}

        .chart-subtitle {{
            font-size: 1.1rem;
            font-weight: 600;
            color: #374151;
            margin-bottom: 1rem;
        }}

        .summary-chart-section {{
            margin: 2rem 0;
            padding: 2rem;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}

        .summary-chart-title {{
            font-size: 1.5rem;
            font-weight: 700;
            color: #111827;
            margin-bottom: 1.5rem;
            text-align: center;
        }}

        /* AI Insights Section */
        .ai-insights-section {{
            margin: 2rem 0;
            padding: 2rem;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}

        .ai-insights-title {{
            font-size: 1.75rem;
            font-weight: 700;
            color: #111827;
            margin-bottom: 1.5rem;
            text-align: center;
        }}

        /* Performance Score */
        .performance-score-container {{
            display: flex;
            gap: 2rem;
            align-items: center;
            padding: 2rem;
            background: #f9fafb;
            border-radius: 12px;
            margin-bottom: 2rem;
        }}

        .score-circle {{
            width: 160px;
            height: 160px;
            border-radius: 50%;
            border: 8px solid;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: white;
            flex-shrink: 0;
        }}

        .score-circle.score-good {{ border-color: #10b981; }}
        .score-circle.score-warning {{ border-color: #f59e0b; }}
        .score-circle.score-critical {{ border-color: #ef4444; }}

        .score-value {{
            font-size: 3rem;
            font-weight: bold;
            color: #111827;
        }}

        .score-label {{
            font-size: 0.875rem;
            color: #6b7280;
            text-align: center;
        }}

        .score-info {{
            flex: 1;
        }}

        .score-badge {{
            display: inline-block;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            margin-bottom: 1rem;
        }}

        .score-badge.score-badge-good {{ background: #dcfce7; color: #16a34a; }}
        .score-badge.score-badge-warning {{ background: #fef3c7; color: #d97706; }}
        .score-badge.score-badge-critical {{ background: #fee2e2; color: #dc2626; }}

        .score-message {{
            font-size: 1.125rem;
            color: #374151;
            margin-bottom: 0.75rem;
        }}

        .test-id-display {{
            font-size: 0.875rem;
            color: #6b7280;
            margin-bottom: 0.25rem;
        }}

        .generated-at {{
            font-size: 0.75rem;
            color: #9ca3af;
        }}

        .expand-hint {{
            text-align: center;
            font-size: 0.875rem;
            color: #667eea;
            font-weight: 500;
            margin: 1rem 0 1.5rem 0;
            padding: 0.75rem;
            background: #f0f4ff;
            border-radius: 8px;
            border-left: 3px solid #667eea;
        }}

        /* Suggestions Section */
        .suggestions-section {{
            margin: 1.5rem 0;
            background: #f9fafb;
            border-radius: 8px;
            overflow: hidden;
        }}

        .section-header {{
            padding: 1rem 1.5rem;
            background: white;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #e5e7eb;
            transition: background 0.2s, box-shadow 0.2s;
            user-select: none;
        }}

        .section-header:hover {{
            background: #f9fafb;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        }}

        .section-header:active {{
            background: #f3f4f6;
        }}

        .section-header h3 {{
            margin: 0;
            font-size: 1.25rem;
            color: #111827;
        }}

        .toggle-icon {{
            font-size: 1.25rem;
            transition: transform 0.2s;
            color: #667eea;
            font-weight: bold;
        }}

        .section-content {{
            display: block;
        }}

        .suggestion-card {{
            margin: 1rem;
            padding: 1.5rem;
            background: white;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }}

        .suggestion-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1rem;
        }}

        .suggestion-title {{
            flex: 1;
            font-size: 1.125rem;
            font-weight: 600;
            color: #111827;
            margin: 0 1rem 0 0;
        }}

        .severity-badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            white-space: nowrap;
        }}

        .severity-badge.severity-critical {{ background: #fee2e2; color: #dc2626; }}
        .severity-badge.severity-warning {{ background: #fef3c7; color: #d97706; }}
        .severity-badge.severity-good {{ background: #dcfce7; color: #16a34a; }}

        .suggestion-category {{
            font-size: 0.875rem;
            color: #6b7280;
            margin-bottom: 0.75rem;
        }}

        .suggestion-description {{
            font-size: 1rem;
            color: #374151;
            line-height: 1.6;
            margin-bottom: 1rem;
        }}

        .suggestion-reasoning {{
            padding: 1rem;
            background: #f9fafb;
            border-left: 3px solid #667eea;
            border-radius: 4px;
            font-size: 0.9375rem;
            color: #4b5563;
            margin-top: 1rem;
        }}

        .suggestion-details {{
            margin-top: 1rem;
        }}

        .detail-section {{
            margin-bottom: 1rem;
            padding: 1rem;
            background: #f9fafb;
            border-radius: 6px;
        }}

        .detail-section:last-child {{
            margin-bottom: 0;
        }}

        .detail-section strong {{
            color: #111827;
            display: block;
            margin-bottom: 0.5rem;
        }}

        .detail-section p {{
            color: #4b5563;
            line-height: 1.6;
            margin: 0;
        }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin: 1rem 0;
        }}

        .metric-item {{
            padding: 0.75rem;
            background: #f9fafb;
            border-radius: 6px;
        }}

        .metric-item .metric-label {{
            font-size: 0.75rem;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.25rem;
        }}

        .metric-item .metric-value {{
            font-size: 1.125rem;
            font-weight: 600;
            color: #111827;
        }}

        .no-suggestions {{
            padding: 2rem;
            text-align: center;
            font-size: 1.125rem;
            color: #10b981;
            background: #dcfce7;
            border-radius: 8px;
            margin: 1rem 0;
        }}

        /* Responsive */
        @media (max-width: 768px) {{
            .performance-score-container {{
                flex-direction: column;
                text-align: center;
            }}
            .score-circle {{
                width: 120px;
                height: 120px;
            }}
            .score-value {{
                font-size: 2.5rem;
            }}
            .metrics-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            .container {{
                box-shadow: none;
            }}
            .section-header {{
                cursor: default;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ {title}</h1>
            <p class="subtitle">{test_type} | Test ID: {test_id}</p>
            <p class="subtitle">Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>

        <div class="summary">
            <div class="summary-card">
                <div class="value">{len(apis)}</div>
                <div class="label">API{'s' if len(apis) > 1 else ''} Tested</div>
            </div>
            <div class="summary-card">
                <div class="value">{total_requests:,}</div>
                <div class="label">Total Requests</div>
            </div>
            <div class="summary-card">
                <div class="value">{avg_rps:.1f}</div>
                <div class="label">Avg Requests/sec</div>
            </div>
            <div class="summary-card">
                <div class="value">{avg_response_time:.0f}ms</div>
                <div class="label">Avg Response Time</div>
            </div>
            <div class="summary-card">
                <div class="value">{total_duration:.1f}s</div>
                <div class="label">Total Duration</div>
            </div>
            <div class="summary-card">
                <div class="value">{total_failures:,}</div>
                <div class="label">Total Failures</div>
            </div>
        </div>

        <div class="content">
            <div class="download-buttons">
                <button onclick="previewReport()" class="preview-btn">
                    👁️ Preview Report
                </button>
                <button onclick="downloadAsJSON()" class="download-btn">
                    📥 Download JSON
                </button>
                <button onclick="downloadAsHTML()" class="download-btn">
                    📄 Download HTML
                </button>
            </div>

            <h2 style="margin-bottom: 1.5rem; color: #111827;">📊 Detailed Results</h2>
            {api_sections_html}

            <!-- Summary Failure Comparison Chart -->
            <div class="summary-chart-section">
                <h2 class="summary-chart-title">🔴 Failure Rate Comparison (All APIs)</h2>
                <div class="chart-container">
                    <canvas id="summaryFailureChart"></canvas>
                </div>
            </div>

            <!-- AI Insights -->
            {self._generate_ai_insights_html(ai_insights, test_id) if ai_insights else ''}
        </div>

        <div class="footer">
            <p>🤖 Generated by DEEP AGENT Load Test System</p>
            <p>© {datetime.now().year} Test Automation Platform</p>
        </div>
    </div>

    <script>
        // Global data for charts and functions
        const apiData = {json.dumps([{
            'name': api.get('name', 'Unknown'),
            'avg_response_time': get_metric(api.get('metrics'), 'avg_response_time', 0),
            'min_response_time': get_metric(api.get('metrics'), 'min_response_time', 0),
            'max_response_time': get_metric(api.get('metrics'), 'max_response_time', 0),
            'median_response_time': get_metric(api.get('metrics'), 'median_response_time', 0),
            'percentile_95': get_metric(api.get('metrics'), 'percentile_95', 0),
            'percentile_99': get_metric(api.get('metrics'), 'percentile_99', 0),
            'total_requests': get_metric(api.get('metrics'), 'total_requests', 0),
            'total_failures': get_metric(api.get('metrics'), 'total_failures', 0),
            'requests_per_second': get_metric(api.get('metrics'), 'requests_per_second', 0),
            'failure_rate': get_metric(api.get('metrics'), 'failure_rate', 0)
        } for api in apis])};

        // Preview Report in new window
        function previewReport() {{
            const reportContent = document.documentElement.outerHTML;
            const newWindow = window.open('', '_blank');
            if (newWindow) {{
                newWindow.document.write(reportContent);
                newWindow.document.close();
            }} else {{
                alert('Please allow popups to preview the report');
            }}
        }}

        // Download as JSON
        function downloadAsJSON() {{
            const reportData = {{
                test_id: "{test_id}",
                test_type: "{test_type}",
                title: "{title}",
                generated_at: "{datetime.now().isoformat()}",
                total_duration: {total_duration},
                apis: apiData
            }};

            const dataStr = JSON.stringify(reportData, null, 2);
            const dataBlob = new Blob([dataStr], {{ type: 'application/json' }});
            const url = URL.createObjectURL(dataBlob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'load_test_report_{test_id}.json';
            link.click();
            URL.revokeObjectURL(url);
        }}

        // Download as HTML
        function downloadAsHTML() {{
            const htmlContent = document.documentElement.outerHTML;
            const blob = new Blob([htmlContent], {{ type: 'text/html;charset=utf-8' }});
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'load_test_report_{test_id}.html';
            link.click();
            URL.revokeObjectURL(url);
        }}

        // Toggle collapsible sections (for AI insights)
        function toggleSection(sectionId) {{
            const content = document.getElementById(sectionId + '-content');
            const icon = document.getElementById(sectionId + '-icon');

            if (content && icon) {{
                if (content.style.display === 'none') {{
                    content.style.display = 'block';
                    icon.textContent = '▼';
                }} else {{
                    content.style.display = 'none';
                    icon.textContent = '▶';
                }}
            }}
        }}

        // Initialize charts when DOM is ready
        window.addEventListener('DOMContentLoaded', function() {{
            console.log('📊 Initializing charts with data:', apiData);

            // Initialize AI insights sections as collapsed by default
            const aiSections = document.querySelectorAll('.section-content');
            aiSections.forEach(section => {{
                section.style.display = 'none';
            }});
            // Set all toggle icons to collapsed state
            const toggleIcons = document.querySelectorAll('.toggle-icon');
            toggleIcons.forEach(icon => {{
                icon.textContent = '▶';
            }});

            // Create individual chart for each API
            apiData.forEach((api, index) => {{
                const chartId = `apiChart_${{index + 1}}`;
                const ctx = document.getElementById(chartId);

                if (!ctx) {{
                    console.warn(`Chart canvas ${{chartId}} not found`);
                    return;
                }}

                new Chart(ctx.getContext('2d'), {{
                    type: 'bar',
                    data: {{
                        labels: ['Min', 'Avg', 'Median', '95th', '99th', 'Max'],
                        datasets: [{{
                            label: 'Response Time (ms)',
                            data: [
                                api.min_response_time,
                                api.avg_response_time,
                                api.median_response_time,
                                api.percentile_95,
                                api.percentile_99,
                                api.max_response_time
                            ],
                            backgroundColor: [
                                'rgba(34, 197, 94, 0.8)',
                                'rgba(59, 130, 246, 0.8)',
                                'rgba(249, 115, 22, 0.8)',
                                'rgba(168, 85, 247, 0.8)',
                                'rgba(236, 72, 153, 0.8)',
                                'rgba(239, 68, 68, 0.8)'
                            ],
                            borderColor: [
                                'rgb(34, 197, 94)',
                                'rgb(59, 130, 246)',
                                'rgb(249, 115, 22)',
                                'rgb(168, 85, 247)',
                                'rgb(236, 72, 153)',
                                'rgb(239, 68, 68)'
                            ],
                            borderWidth: 1
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{
                                display: false
                            }},
                            title: {{
                                display: false
                            }},
                            tooltip: {{
                                mode: 'index',
                                intersect: false,
                                backgroundColor: 'rgba(255, 255, 255, 0.95)',
                                titleColor: '#111',
                                bodyColor: '#333',
                                borderColor: '#ccc',
                                borderWidth: 1,
                                callbacks: {{
                                    label: function(context) {{
                                        return context.label + ': ' + context.parsed.y + ' ms';
                                    }}
                                }}
                            }}
                        }},
                        scales: {{
                            x: {{
                                grid: {{
                                    color: 'rgba(0, 0, 0, 0.05)',
                                    drawBorder: true,
                                    borderColor: '#e5e7eb'
                                }},
                                ticks: {{
                                    color: '#6b7280',
                                    font: {{ size: 10 }}
                                }}
                            }},
                            y: {{
                                beginAtZero: true,
                                grid: {{
                                    color: 'rgba(0, 0, 0, 0.05)',
                                    drawBorder: true,
                                    borderColor: '#e5e7eb'
                                }},
                                ticks: {{
                                    color: '#6b7280',
                                    font: {{ size: 10 }},
                                    callback: function(value) {{
                                        return value + ' ms';
                                    }}
                                }},
                                title: {{
                                    display: true,
                                    text: 'Response Time (ms)',
                                    color: '#374151',
                                    font: {{ size: 11 }}
                                }}
                            }}
                        }},
                        interaction: {{
                            mode: 'nearest',
                            axis: 'x',
                            intersect: false
                        }}
                    }}
                }});
            }});

            // Summary Failure Comparison Pie Chart
            const summaryFailureCtx = document.getElementById('summaryFailureChart');
            if (summaryFailureCtx) {{
                new Chart(summaryFailureCtx.getContext('2d'), {{
                    type: 'pie',
                    data: {{
                        labels: apiData.map(d => `${{d.name}} (${{d.total_failures}} failures)`),
                        datasets: [{{
                            label: 'Total Failures',
                            data: apiData.map(d => d.total_failures),
                            backgroundColor: [
                                'rgba(239, 68, 68, 0.7)',
                                'rgba(245, 158, 11, 0.7)',
                                'rgba(59, 130, 246, 0.7)',
                                'rgba(16, 185, 129, 0.7)',
                                'rgba(139, 92, 246, 0.7)',
                                'rgba(236, 72, 153, 0.7)',
                                'rgba(249, 115, 22, 0.7)',
                                'rgba(168, 85, 247, 0.7)'
                            ],
                            borderColor: [
                                'rgba(239, 68, 68, 1)',
                                'rgba(245, 158, 11, 1)',
                                'rgba(59, 130, 246, 1)',
                                'rgba(16, 185, 129, 1)',
                                'rgba(139, 92, 246, 1)',
                                'rgba(236, 72, 153, 1)',
                                'rgba(249, 115, 22, 1)',
                                'rgba(168, 85, 247, 1)'
                            ],
                            borderWidth: 2
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{
                                position: 'right',
                                labels: {{
                                    color: '#374151',
                                    font: {{ size: 12 }},
                                    padding: 15
                                }}
                            }},
                            tooltip: {{
                                backgroundColor: 'rgba(255, 255, 255, 0.95)',
                                titleColor: '#111',
                                bodyColor: '#333',
                                borderColor: '#ccc',
                                borderWidth: 1,
                                callbacks: {{
                                    label: function(context) {{
                                        const label = context.label || '';
                                        const value = context.parsed || 0;
                                        const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                        const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                        return `${{label}}: ${{percentage}}%`;
                                    }}
                                }}
                            }}
                        }}
                    }}
                }});
            }}

            console.log('✅ Charts initialized successfully');
        }}); // End DOMContentLoaded
    </script>
</body>
</html>
        """

        return html


# Global instance
load_test_report_generator = LoadTestReportGenerator()
