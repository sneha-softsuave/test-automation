"""HTML Report Generator for Load Tests."""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.models.load_test_models import LoadTestMetrics, APIConfig, LoadTestConfig


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
        duration: float
    ) -> str:
        """Generate HTML report for manual (single API) test."""

        print(f"🔍 [REPORT] Starting manual report generation for test_id: {test_id}", flush=True)
        print(f"🔍 [REPORT] API: {api.name if api else 'None'}", flush=True)
        print(f"🔍 [REPORT] Config: {config}", flush=True)
        print(f"🔍 [REPORT] Metrics: {metrics}", flush=True)
        print(f"🔍 [REPORT] Duration: {duration}", flush=True)

        try:
            report_filename = f"report_{test_id}.html"
            report_path = self.results_dir / report_filename

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
                total_duration=duration
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
        total_duration: float
    ) -> str:
        """Generate HTML report for sequential test with multiple APIs."""

        print(f"🔍 [REPORT] Starting sequential report generation for: {sequential_test_id}", flush=True)
        print(f"🔍 [REPORT] Number of API results: {len(api_results)}", flush=True)
        print(f"🔍 [REPORT] Total duration: {total_duration}", flush=True)

        try:
            report_filename = f"report_{sequential_test_id}.html"
            report_path = self.results_dir / report_filename

            html_content = self._generate_html(
                title=f"Sequential Load Test Report",
                test_type="Sequential Test",
                test_id=sequential_test_id,
                apis=api_results,
                total_duration=total_duration
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

    def _generate_html(
        self,
        title: str,
        test_type: str,
        test_id: str,
        apis: List[Dict[str, Any]],
        total_duration: float
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
            margin-bottom: 0.5rem;
        }}

        .metric-label {{
            font-size: 0.875rem;
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

        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            .container {{
                box-shadow: none;
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

        // Initialize charts when DOM is ready
        window.addEventListener('DOMContentLoaded', function() {{
            console.log('📊 Initializing charts with data:', apiData);

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
                                'rgba(67, 233, 123, 0.7)',
                                'rgba(79, 172, 254, 0.7)',
                                'rgba(102, 126, 234, 0.7)',
                                'rgba(139, 92, 246, 0.7)',
                                'rgba(245, 158, 11, 0.7)',
                                'rgba(245, 87, 108, 0.7)'
                            ],
                            borderColor: [
                                'rgba(67, 233, 123, 1)',
                                'rgba(79, 172, 254, 1)',
                                'rgba(102, 126, 234, 1)',
                                'rgba(139, 92, 246, 1)',
                                'rgba(245, 158, 11, 1)',
                                'rgba(245, 87, 108, 1)'
                            ],
                            borderWidth: 2
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
                            }}
                        }},
                        scales: {{
                            y: {{
                                beginAtZero: true,
                                title: {{
                                    display: true,
                                    text: 'Time (ms)',
                                    font: {{ size: 12 }}
                                }}
                            }}
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
                                    font: {{ size: 12 }},
                                    padding: 15
                                }}
                            }},
                            tooltip: {{
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
