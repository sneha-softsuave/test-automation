import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Download,
  FileText,
  Code,
  Image,
  Database,
  CheckCircle,
  Loader2,
  FileJson,
  Table,
  Camera,
  FileCode,
  Eye,
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import { generateScript } from '../../services/api';
import styles from './DownloadReport.module.css';

// JSON Syntax Highlighter
const syntaxHighlightJSON = (json: string): string => {
  return json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"([^"]+)":/g, '<span class="json-key">"$1"</span>:')
    .replace(/: "([^"]*)"/g, ': <span class="json-string">"$1"</span>')
    .replace(/: (\d+)/g, ': <span class="json-number">$1</span>')
    .replace(/: (true|false)/g, ': <span class="json-boolean">$1</span>')
    .replace(/: (null)/g, ': <span class="json-null">$1</span>');
};

export const DownloadReport = () => {
  const { testSuite, rawTestCases, executionResult, generatedScript, setGeneratedScript, screenshots } = useStore();
  const [isGenerating, setIsGenerating] = useState(false);

  const hasData = testSuite || rawTestCases || executionResult;

  const handleGenerateScript = async () => {
    if (!testSuite) return;
    setIsGenerating(true);
    try {
      const result = await generateScript(testSuite);
      setGeneratedScript(result.script);
    } catch (error) {
      console.error('Failed to generate script:', error);
    } finally {
      setIsGenerating(false);
    }
  };

  // Get screenshot for a specific test and step
  const getScreenshot = (testId: string, step: number): string | null => {
    // Try exact match first
    let screenshot = screenshots.find(s => s.testId === testId && s.step === step);
    if (screenshot?.image) return screenshot.image;

    // Try matching by test ID prefix (e.g., "TC_1" matches "TC_001")
    const testNum = testId.replace(/\D/g, '');
    screenshot = screenshots.find(s => {
      const sTestNum = s.testId.replace(/\D/g, '');
      return sTestNum === testNum && s.step === step;
    });

    return screenshot?.image || null;
  };

  // Get all screenshots for a specific test
  const getTestScreenshots = (testId: string): typeof screenshots => {
    const testNum = testId.replace(/\D/g, '');
    return screenshots.filter(s => {
      const sTestNum = s.testId.replace(/\D/g, '');
      return sTestNum === testNum || s.testId === testId;
    });
  };

  const generateHTMLReport = (): string => {
    const now = new Date();
    const reportDate = now.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });

    // Prepare highlighted JSON
    const highlightedJSON = testSuite
      ? syntaxHighlightJSON(JSON.stringify(testSuite, null, 2))
      : '';

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Test Automation Report - ${testSuite?.project || 'Project'}</title>
  <style>
    :root {
      --bg-primary: #09090b;
      --bg-secondary: #0f0f12;
      --bg-tertiary: #18181b;
      --bg-card: #0f0f12;
      --accent-primary: #10b981;
      --accent-secondary: #8b5cf6;
      --accent-tertiary: #06b6d4;
      --success: #22c55e;
      --error: #ef4444;
      --warning: #f59e0b;
      --text-primary: #fafafa;
      --text-secondary: #a1a1aa;
      --text-tertiary: #71717a;
      --border-subtle: rgba(255, 255, 255, 0.06);
      --border-default: rgba(255, 255, 255, 0.1);
    }

    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: var(--bg-primary);
      color: var(--text-primary);
      line-height: 1.6;
      min-height: 100vh;
    }

    .container {
      max-width: 1200px;
      margin: 0 auto;
      padding: 40px 24px;
    }

    /* Header */
    .header {
      text-align: center;
      padding: 48px 24px;
      background: linear-gradient(180deg, var(--bg-secondary) 0%, var(--bg-primary) 100%);
      border-bottom: 1px solid var(--border-subtle);
      margin-bottom: 48px;
    }

    .header-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 16px;
      background: rgba(16, 185, 129, 0.15);
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
      color: var(--accent-primary);
      text-transform: uppercase;
      letter-spacing: 0.1em;
      margin-bottom: 16px;
    }

    .header h1 {
      font-size: 2.5rem;
      font-weight: 800;
      margin-bottom: 8px;
      background: linear-gradient(135deg, #10b981 0%, #06b6d4 50%, #8b5cf6 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }

    .header-meta {
      color: var(--text-tertiary);
      font-size: 0.9rem;
    }

    .header-meta span {
      margin: 0 12px;
    }

    /* Section */
    .section {
      margin-bottom: 48px;
    }

    .section-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 24px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border-subtle);
    }

    .section-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 40px;
      height: 40px;
      background: var(--bg-tertiary);
      border-radius: 10px;
      color: var(--accent-primary);
    }

    .section-title {
      font-size: 1.25rem;
      font-weight: 600;
      color: var(--text-primary);
    }

    .section-count {
      margin-left: auto;
      padding: 4px 12px;
      background: var(--bg-tertiary);
      border-radius: 12px;
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-secondary);
    }

    /* Cards */
    .card {
      background: var(--bg-secondary);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      overflow: hidden;
      margin-bottom: 16px;
    }

    .card-header {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 16px 20px;
      background: var(--bg-tertiary);
      border-bottom: 1px solid var(--border-subtle);
    }

    .card-badge {
      padding: 4px 10px;
      background: rgba(16, 185, 129, 0.15);
      border-radius: 6px;
      font-size: 0.7rem;
      font-family: 'Fira Code', monospace;
      font-weight: 600;
      color: var(--accent-primary);
    }

    .card-title {
      font-size: 1rem;
      font-weight: 500;
      color: var(--text-primary);
    }

    .card-body {
      padding: 20px;
    }

    /* Table */
    .table-container {
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
    }

    th {
      text-align: left;
      padding: 12px 16px;
      background: var(--bg-tertiary);
      color: var(--text-secondary);
      font-weight: 600;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border-subtle);
    }

    td {
      padding: 12px 16px;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--text-secondary);
      vertical-align: top;
    }

    tr:last-child td {
      border-bottom: none;
    }

    tr:hover td {
      background: rgba(255, 255, 255, 0.02);
    }

    .step-number {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      background: var(--bg-tertiary);
      border-radius: 6px;
      font-size: 0.75rem;
      font-family: 'Fira Code', monospace;
      font-weight: 600;
      color: var(--text-tertiary);
    }

    .action-badge {
      display: inline-block;
      padding: 3px 8px;
      background: rgba(139, 92, 246, 0.15);
      border-radius: 4px;
      font-size: 0.7rem;
      font-family: 'Fira Code', monospace;
      font-weight: 600;
      color: var(--accent-secondary);
      text-transform: uppercase;
    }

    .status-passed {
      color: var(--success);
    }

    .status-failed {
      color: var(--error);
    }

    /* Code Block */
    .code-block {
      background: var(--bg-tertiary);
      border-radius: 8px;
      overflow: hidden;
    }

    .code-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 16px;
      background: rgba(0, 0, 0, 0.2);
      border-bottom: 1px solid var(--border-subtle);
    }

    .code-lang {
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--accent-tertiary);
      text-transform: uppercase;
    }

    pre {
      padding: 16px;
      overflow-x: auto;
      font-family: 'Fira Code', 'Consolas', monospace;
      font-size: 0.8rem;
      line-height: 1.6;
      color: var(--text-secondary);
    }

    code {
      font-family: 'Fira Code', 'Consolas', monospace;
    }

    /* JSON Syntax Highlighting */
    .json-key {
      color: #7dd3fc;
    }

    .json-string {
      color: #86efac;
    }

    .json-number {
      color: #fbbf24;
    }

    .json-boolean {
      color: #c084fc;
    }

    .json-null {
      color: #f87171;
    }

    /* Stats Grid */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }

    .stat-card {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 20px;
      background: var(--bg-secondary);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
    }

    .stat-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 48px;
      height: 48px;
      border-radius: 10px;
      font-size: 24px;
    }

    .stat-icon.success {
      background: rgba(34, 197, 94, 0.15);
      color: var(--success);
    }

    .stat-icon.error {
      background: rgba(239, 68, 68, 0.15);
      color: var(--error);
    }

    .stat-icon.info {
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-primary);
    }

    .stat-value {
      font-size: 2rem;
      font-weight: 800;
      color: var(--text-primary);
    }

    .stat-label {
      font-size: 0.8rem;
      color: var(--text-tertiary);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    /* Screenshots */
    .screenshots-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }

    .screenshot-card {
      background: var(--bg-tertiary);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      overflow: hidden;
    }

    .screenshot-image {
      width: 100%;
      height: auto;
      display: block;
      border-bottom: 1px solid var(--border-subtle);
    }

    .screenshot-placeholder {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 200px;
      background: rgba(0, 0, 0, 0.2);
      color: var(--text-tertiary);
      font-size: 0.875rem;
    }

    .screenshot-label {
      padding: 12px;
      font-size: 0.8rem;
      color: var(--text-secondary);
    }

    .screenshot-label strong {
      color: var(--text-primary);
    }

    .screenshot-status {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 0.7rem;
      font-weight: 600;
      margin-left: 8px;
    }

    .screenshot-status.passed {
      background: rgba(34, 197, 94, 0.15);
      color: var(--success);
    }

    .screenshot-status.failed {
      background: rgba(239, 68, 68, 0.15);
      color: var(--error);
    }

    /* Step Screenshots Section */
    .step-screenshot {
      margin-top: 12px;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--border-subtle);
    }

    .step-screenshot img {
      width: 100%;
      max-width: 600px;
      height: auto;
      display: block;
    }

    /* Footer */
    .footer {
      text-align: center;
      padding: 32px;
      margin-top: 48px;
      border-top: 1px solid var(--border-subtle);
      color: var(--text-tertiary);
      font-size: 0.8rem;
    }

    .footer-logo {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
      font-weight: 700;
      color: var(--accent-primary);
    }

    /* Collapsible Sections */
    .section-header {
      cursor: pointer;
      user-select: none;
      transition: all 0.2s ease;
    }

    .section-header:hover {
      background: rgba(255, 255, 255, 0.02);
      border-radius: 8px;
      margin: -8px;
      padding: 8px;
    }

    .section-toggle {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      background: var(--bg-tertiary);
      border-radius: 6px;
      color: var(--text-tertiary);
      font-size: 18px;
      font-weight: bold;
      transition: all 0.3s ease;
      margin-left: auto;
    }

    .section-toggle.collapsed {
      transform: rotate(-90deg);
    }

    .section-content {
      overflow: hidden;
      transition: max-height 0.3s ease-out, opacity 0.3s ease;
      max-height: 10000px;
      opacity: 1;
    }

    .section-content.collapsed {
      max-height: 0;
      opacity: 0;
      margin-top: 0;
    }

    .card-header {
      cursor: pointer;
      transition: background 0.2s ease;
    }

    .card-header:hover {
      background: rgba(255, 255, 255, 0.05);
    }

    .card-toggle {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      background: rgba(255, 255, 255, 0.05);
      border-radius: 4px;
      color: var(--text-tertiary);
      font-size: 14px;
      transition: all 0.3s ease;
      margin-left: 8px;
    }

    .card-toggle.collapsed {
      transform: rotate(-90deg);
    }

    .card-body {
      transition: max-height 0.3s ease-out, opacity 0.3s ease, padding 0.3s ease;
      max-height: 5000px;
      opacity: 1;
    }

    .card-body.collapsed {
      max-height: 0;
      opacity: 0;
      padding: 0 20px;
      overflow: hidden;
    }

    /* Print Styles */
    @media print {
      body {
        background: white;
        color: #1a1a1a;
      }

      .card, .stat-card {
        background: #f5f5f5;
        border-color: #e5e5e5;
      }

      .code-block, .code-header, pre {
        background: #f5f5f5;
      }

      .json-key { color: #0369a1; }
      .json-string { color: #15803d; }
      .json-number { color: #b45309; }
      .json-boolean { color: #7c3aed; }
      .json-null { color: #dc2626; }

      .section-content.collapsed,
      .card-body.collapsed {
        max-height: none;
        opacity: 1;
        padding: 20px;
      }

      .section-toggle, .card-toggle {
        display: none;
      }
    }
  </style>
</head>
<body>
  <header class="header">
    <div class="header-badge">
      Test Automation Report
    </div>
    <h1>${testSuite?.project || 'Test Project'}</h1>
    <div class="header-meta">
      <span>${testSuite?.base_url || ''}</span>
      <span>|</span>
      <span>Generated: ${reportDate}</span>
    </div>
    <div style="display: flex; gap: 12px; margin-top: 20px;">
      <button onclick="expandAll()" style="padding: 8px 16px; background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 8px; color: var(--accent-primary); font-size: 0.8rem; font-weight: 600; cursor: pointer; transition: all 0.2s;">
        Expand All
      </button>
      <button onclick="collapseAll()" style="padding: 8px 16px; background: rgba(139, 92, 246, 0.15); border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 8px; color: var(--accent-secondary); font-size: 0.8rem; font-weight: 600; cursor: pointer; transition: all 0.2s;">
        Collapse All
      </button>
    </div>
  </header>

  <div class="container">
    ${executionResult ? `
    <!-- Execution Summary -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon info">T</div>
        <div>
          <div class="stat-value">${executionResult.total ?? 0}</div>
          <div class="stat-label">Total Tests</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon success">P</div>
        <div>
          <div class="stat-value">${executionResult.passed ?? 0}</div>
          <div class="stat-label">Passed</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon error">F</div>
        <div>
          <div class="stat-value">${executionResult.failed ?? 0}</div>
          <div class="stat-label">Failed</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon info">%</div>
        <div>
          <div class="stat-value">${executionResult.total ? Math.round(((executionResult.passed ?? 0) / executionResult.total) * 100) : 0}%</div>
          <div class="stat-label">Pass Rate</div>
        </div>
      </div>
    </div>
    ` : ''}

    ${rawTestCases && rawTestCases.length > 0 ? `
    <!-- Original Excel Data -->
    <section class="section">
      <div class="section-header" onclick="toggleSection('excel')">
        <div class="section-icon">T</div>
        <h2 class="section-title">Original Test Cases (Excel)</h2>
        <span class="section-count">${rawTestCases.length} items</span>
        <div class="section-toggle" id="excel-toggle">▼</div>
      </div>
      <div class="section-content" id="excel-content">
        <div class="card">
          <div class="table-container">
            <table>
              <thead>
                <tr>
                  <th>T.C.No</th>
                  <th>Test Case</th>
                  <th>Test Case Steps</th>
                  <th>Expected Result</th>
                </tr>
              </thead>
              <tbody>
                ${rawTestCases.map(tc => `
                <tr>
                  <td><span class="step-number">${tc['T.C.No']}</span></td>
                  <td>${tc['Test Case'] || '-'}</td>
                  <td>${(tc['Test Case Steps'] || '-').replace(/\n/g, '<br>')}</td>
                  <td>${(tc['Expected Result'] || '-').replace(/\n/g, '<br>')}</td>
                </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
    ` : ''}

    ${testSuite ? `
    <!-- Parsed Test Suite -->
    <section class="section">
      <div class="section-header" onclick="toggleSection('parsed')">
        <div class="section-icon">J</div>
        <h2 class="section-title">Parsed Test Suite</h2>
        <span class="section-count">${testSuite.test_cases.length} test cases</span>
        <div class="section-toggle" id="parsed-toggle">▼</div>
      </div>
      <div class="section-content" id="parsed-content">
        ${testSuite.test_cases.map((tc, idx) => `
        <div class="card">
          <div class="card-header" onclick="event.stopPropagation(); toggleCard('tc-${idx}')">
            <span class="card-badge">${tc.id}</span>
            <span class="card-title">${tc.name}</span>
            <div class="card-toggle" id="tc-${idx}-toggle">▼</div>
          </div>
          <div class="card-body" id="tc-${idx}-body">
            <div class="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Step</th>
                    <th>Action</th>
                    <th>Instruction</th>
                    <th>Playwright Method</th>
                  </tr>
                </thead>
                <tbody>
                  ${tc.steps.map(step => `
                  <tr>
                    <td><span class="step-number">${step.step_number}</span></td>
                    <td><span class="action-badge">${step.action.type}</span></td>
                    <td>${step.instruction}</td>
                    <td><code>${step.action.playwright_method}</code></td>
                  </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
            ${tc.expected_results.length > 0 ? `
            <div style="margin-top: 16px; padding: 12px; background: var(--bg-tertiary); border-radius: 8px;">
              <div style="font-size: 0.75rem; font-weight: 600; color: var(--text-tertiary); text-transform: uppercase; margin-bottom: 8px;">Expected Results</div>
              <ul style="margin-left: 16px; color: var(--text-secondary);">
                ${tc.expected_results.map(r => `<li>${r}</li>`).join('')}
              </ul>
            </div>
            ` : ''}
          </div>
        </div>
        `).join('')}
      </div>
    </section>

    <!-- Full JSON Data (Colorful) -->
    <section class="section">
      <div class="section-header" onclick="toggleSection('json')">
        <div class="section-icon">{}</div>
        <h2 class="section-title">Complete JSON Structure</h2>
        <div class="section-toggle collapsed" id="json-toggle">▼</div>
      </div>
      <div class="section-content collapsed" id="json-content">
        <div class="code-block">
          <div class="code-header">
            <span class="code-lang">JSON</span>
          </div>
          <pre>${highlightedJSON}</pre>
        </div>
      </div>
    </section>
    ` : ''}

    ${executionResult ? `
    <!-- Execution Results with Screenshots -->
    <section class="section">
      <div class="section-header" onclick="toggleSection('results')">
        <div class="section-icon">R</div>
        <h2 class="section-title">Execution Results</h2>
        <span class="section-count">${executionResult.results.length} tests</span>
        <div class="section-toggle" id="results-toggle">▼</div>
      </div>
      <div class="section-content" id="results-content">
        ${executionResult.results.map((result, rIdx) => `
        <div class="card" style="border-left: 3px solid ${result.status === 'PASSED' ? 'var(--success)' : 'var(--error)'};">
          <div class="card-header" onclick="event.stopPropagation(); toggleCard('result-${rIdx}')">
            <span class="card-badge">${result.test_id}</span>
            <span class="card-title">${result.test_name}</span>
            <span class="${result.status === 'PASSED' ? 'status-passed' : 'status-failed'}" style="margin-left: auto; font-weight: 600;">
              ${result.status}
            </span>
            <div class="card-toggle" id="result-${rIdx}-toggle">▼</div>
          </div>
          <div class="card-body" id="result-${rIdx}-body">
            ${result.steps && result.steps.length > 0 ? `
            <div class="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Step</th>
                    <th>Action</th>
                    <th>Instruction</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  ${result.steps.map(step => {
                    const screenshotData = getScreenshot(result.test_id, step.step);
                    return `
                  <tr>
                    <td><span class="step-number">${step.step}</span></td>
                    <td><span class="action-badge">${step.action}</span></td>
                    <td>${step.instruction.length > 80 ? step.instruction.slice(0, 80) + '...' : step.instruction}</td>
                    <td class="${step.status === 'PASSED' ? 'status-passed' : 'status-failed'}">${step.status}</td>
                  </tr>
                  ${step.error ? `<tr><td colspan="4" style="background: rgba(239, 68, 68, 0.1); color: var(--error); font-size: 0.8rem; padding: 12px 16px;">Error: ${step.error}</td></tr>` : ''}
                  ${screenshotData ? `
                  <tr>
                    <td colspan="4" style="padding: 12px 16px; background: rgba(0,0,0,0.2);">
                      <div class="step-screenshot">
                        <img src="data:image/png;base64,${screenshotData}" alt="Step ${step.step} Screenshot" style="max-width: 100%; border-radius: 8px; border: 1px solid var(--border-subtle);" />
                      </div>
                    </td>
                  </tr>
                  ` : ''}
                  `;
                  }).join('')}
                </tbody>
              </table>
            </div>
            ` : '<p style="color: var(--text-tertiary);">No step details available</p>'}
          </div>
        </div>
        `).join('')}
      </div>
    </section>

    ${screenshots.length > 0 ? `
    <!-- Screenshots Gallery -->
    <section class="section">
      <div class="section-header" onclick="toggleSection('gallery')">
        <div class="section-icon">📸</div>
        <h2 class="section-title">Screenshots Gallery</h2>
        <span class="section-count">${screenshots.length} screenshots</span>
        <div class="section-toggle" id="gallery-toggle">▼</div>
      </div>
      <div class="section-content" id="gallery-content">
        <div class="card">
          <div class="card-body">
            <div class="screenshots-grid">
              ${screenshots.map((s, i) => `
              <div class="screenshot-card">
                <img src="data:image/png;base64,${s.image}" alt="Screenshot ${i + 1}" class="screenshot-image" />
                <div class="screenshot-label">
                  <strong>${s.testId}</strong> - Step ${s.step}
                  <span class="screenshot-status ${s.status}">${s.status.toUpperCase()}</span>
                </div>
              </div>
              `).join('')}
            </div>
          </div>
        </div>
      </div>
    </section>
    ` : ''}
    ` : ''}

    ${generatedScript ? `
    <!-- Generated Playwright Script -->
    <section class="section">
      <div class="section-header" onclick="toggleSection('script')">
        <div class="section-icon">&lt;/&gt;</div>
        <h2 class="section-title">Generated Playwright Script</h2>
        <div class="section-toggle collapsed" id="script-toggle">▼</div>
      </div>
      <div class="section-content collapsed" id="script-content">
        <div class="code-block">
          <div class="code-header">
            <span class="code-lang">TypeScript / JavaScript</span>
          </div>
          <pre>${generatedScript.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>
        </div>
      </div>
    </section>
    ` : ''}
  </div>

  <footer class="footer">
    <div class="footer-logo">
      DEEP AGENT - Test Automation Platform
    </div>
    <div>Generated automatically | ${reportDate}</div>
  </footer>

  <script>
    // Toggle section visibility
    function toggleSection(sectionId) {
      const content = document.getElementById(sectionId + '-content');
      const toggle = document.getElementById(sectionId + '-toggle');

      if (content && toggle) {
        content.classList.toggle('collapsed');
        toggle.classList.toggle('collapsed');
      }
    }

    // Toggle card visibility
    function toggleCard(cardId) {
      const body = document.getElementById(cardId + '-body');
      const toggle = document.getElementById(cardId + '-toggle');

      if (body && toggle) {
        body.classList.toggle('collapsed');
        toggle.classList.toggle('collapsed');
      }
    }

    // Expand/Collapse all sections
    function expandAll() {
      document.querySelectorAll('.section-content, .card-body').forEach(el => {
        el.classList.remove('collapsed');
      });
      document.querySelectorAll('.section-toggle, .card-toggle').forEach(el => {
        el.classList.remove('collapsed');
      });
    }

    function collapseAll() {
      document.querySelectorAll('.section-content, .card-body').forEach(el => {
        el.classList.add('collapsed');
      });
      document.querySelectorAll('.section-toggle, .card-toggle').forEach(el => {
        el.classList.add('collapsed');
      });
    }
  </script>
</body>
</html>`;
  };

  const handleDownload = () => {
    const htmlContent = generateHTMLReport();
    const blob = new Blob([htmlContent], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `test-report-${testSuite?.project || 'project'}-${new Date().toISOString().split('T')[0]}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handlePreview = () => {
    const htmlContent = generateHTMLReport();
    const newWindow = window.open('', '_blank');
    if (newWindow) {
      newWindow.document.write(htmlContent);
      newWindow.document.close();
    }
  };

  if (!hasData) {
    return (
      <div className={styles.empty}>
        <Download size={48} />
        <h2>No Data Available</h2>
        <p>Upload a test file and run tests to generate a report</p>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Header */}
      <motion.div
        className={styles.header}
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className={styles.headerIcon}>
          <FileText size={32} />
        </div>
        <h1 className={styles.title}>Download Report</h1>
        <p className={styles.subtitle}>
          Generate and download a comprehensive HTML report
        </p>
      </motion.div>

      {/* Data Summary */}
      <motion.div
        className={styles.summary}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <h2 className={styles.summaryTitle}>Report Contents</h2>
        <div className={styles.contentGrid}>
          <div className={`${styles.contentCard} ${rawTestCases ? styles.active : ''}`}>
            <div className={styles.contentIcon}>
              <Table size={24} />
            </div>
            <div className={styles.contentInfo}>
              <span className={styles.contentLabel}>Excel Test Cases</span>
              <span className={styles.contentValue}>
                {rawTestCases ? `${rawTestCases.length} rows` : 'Not available'}
              </span>
            </div>
            {rawTestCases && <CheckCircle size={20} className={styles.checkIcon} />}
          </div>

          <div className={`${styles.contentCard} ${testSuite ? styles.active : ''}`}>
            <div className={styles.contentIcon}>
              <FileJson size={24} />
            </div>
            <div className={styles.contentInfo}>
              <span className={styles.contentLabel}>Parsed JSON</span>
              <span className={styles.contentValue}>
                {testSuite ? `${testSuite.test_cases.length} test cases` : 'Not available'}
              </span>
            </div>
            {testSuite && <CheckCircle size={20} className={styles.checkIcon} />}
          </div>

          <div className={`${styles.contentCard} ${screenshots.length > 0 ? styles.active : ''}`}>
            <div className={styles.contentIcon}>
              <Camera size={24} />
            </div>
            <div className={styles.contentInfo}>
              <span className={styles.contentLabel}>Screenshots</span>
              <span className={styles.contentValue}>
                {screenshots.length > 0
                  ? `${screenshots.length} captured`
                  : 'None captured'}
              </span>
            </div>
            {screenshots.length > 0 && <CheckCircle size={20} className={styles.checkIcon} />}
          </div>

          <div className={`${styles.contentCard} ${generatedScript ? styles.active : ''}`}>
            <div className={styles.contentIcon}>
              <FileCode size={24} />
            </div>
            <div className={styles.contentInfo}>
              <span className={styles.contentLabel}>Playwright Script</span>
              <span className={styles.contentValue}>
                {generatedScript ? 'Generated' : 'Not generated'}
              </span>
            </div>
            {generatedScript && <CheckCircle size={20} className={styles.checkIcon} />}
          </div>
        </div>
      </motion.div>

      {/* Generate Script Button */}
      {testSuite && !generatedScript && (
        <motion.div
          className={styles.generateSection}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          <div className={styles.generateInfo}>
            <Code size={20} />
            <span>Generate Playwright script to include in the report</span>
          </div>
          <motion.button
            className={styles.generateButton}
            onClick={handleGenerateScript}
            disabled={isGenerating}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
          >
            {isGenerating ? (
              <>
                <Loader2 size={18} className={styles.spinner} />
                Generating...
              </>
            ) : (
              <>
                <Code size={18} />
                Generate Script
              </>
            )}
          </motion.button>
        </motion.div>
      )}

      {/* Actions */}
      <motion.div
        className={styles.actions}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <motion.button
          className={styles.previewButton}
          onClick={handlePreview}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          <Eye size={20} />
          Preview Report
        </motion.button>
        <motion.button
          className={styles.downloadButton}
          onClick={handleDownload}
          whileHover={{ scale: 1.02, y: -2 }}
          whileTap={{ scale: 0.98 }}
        >
          <Download size={20} />
          Download HTML Report
        </motion.button>
      </motion.div>

      {/* Info */}
      <motion.div
        className={styles.info}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.4 }}
      >
        <div className={styles.infoItem}>
          <Database size={16} />
          <span>Report includes all available data in a single HTML file</span>
        </div>
        <div className={styles.infoItem}>
          <Image size={16} />
          <span>Screenshots are embedded as base64 images (no external files needed)</span>
        </div>
        <div className={styles.infoItem}>
          <FileText size={16} />
          <span>JSON is syntax-highlighted with colorful formatting</span>
        </div>
      </motion.div>
    </div>
  );
};
