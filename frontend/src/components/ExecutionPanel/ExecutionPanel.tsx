import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Play as PlayIcon,
  Settings,
  Monitor,
  MonitorOff,
  Clock,
  Zap,
  AlertTriangle,
  Loader2,
  Rocket,
  Terminal,
  RefreshCcw,
  Code,
  ChevronDown,
  Edit3,
  Download,
} from 'lucide-react';
import { useStore, LLM_OPTIONS } from '../../store/useStore';
import { executeMultiAgent, executeFromParsed, runSingleScript, type TestCaseRaw } from '../../services/api';
import { splitCombinedScript, type IndividualScript } from '../../utils/scriptSplitter';
import { useExecutionWebSocket } from '../../hooks/useExecutionWebSocket';
import styles from './ExecutionPanel.module.css';

export const ExecutionPanel = () => {
  const {
    testSuite,
    rawTestCases,
    isExecuting,
    setIsExecuting,
    setExecutionResult,
    setGeneratedScript,
    setCurrentView,
    addNotification,
    llmProvider,
    generatedScript,
    keepBrowserOpenAgent,
  } = useStore();

  const [headless, setHeadless] = useState(true);
  const [timeout, setTimeout] = useState(30000);
  const [maxRetries, setMaxRetries] = useState(2);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);

  // Per-test script state
  const [individualScripts, setIndividualScripts] = useState<IndividualScript[]>([]);
  const [expandedScript, setExpandedScript] = useState<string | null>(null);
  const [editedScripts, setEditedScripts] = useState<Record<string, string>>({});
  const [runningScript, setRunningScript] = useState<string | null>(null);
  const [scriptResults, setScriptResults] = useState<Record<string, 'PASSED' | 'FAILED' | 'ERROR' | 'TIMEOUT'>>({});

  // SSE connection for Multi-Agent - includes browser state for live view
  const {
    sessionId,
    connect,
    disconnect,
    clearLogs,
    browserState,
    progress,
    logs: sseLogs,
    currentTest,
    currentStep,
  } = useExecutionWebSocket();

  // Split combined script whenever it changes
  useEffect(() => {
    if (generatedScript) {
      const split = splitCombinedScript(generatedScript);
      setIndividualScripts(split);
      const initial: Record<string, string> = {};
      split.forEach((s) => { initial[s.testId] = s.script; });
      setEditedScripts(initial);
    } else {
      setIndividualScripts([]);
      setEditedScripts({});
    }
  }, [generatedScript]);

  const handleDownloadScript = (testId: string) => {
    const script = editedScripts[testId] ?? individualScripts.find((s) => s.testId === testId)?.script ?? '';
    const blob = new Blob([script], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `test_${testId.toLowerCase()}.py`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleRunScript = async (testId: string) => {
    setRunningScript(testId);
    try {
      const script =
        editedScripts[testId] ??
        individualScripts.find((s) => s.testId === testId)?.script ??
        '';
      const result = await runSingleScript(script, testId, {
        headless,
        timeout,
        sessionId,
      });
      setScriptResults((prev) => ({ ...prev, [testId]: result.status }));
    } catch {
      setScriptResults((prev) => ({ ...prev, [testId]: 'ERROR' }));
    } finally {
      setRunningScript(null);
    }
  };

  if (!testSuite) {
    return (
      <div className={styles.empty}>
        <PlayIcon size={48} />
        <h2>No Test Suite Loaded</h2>
        <p>Upload a test file first to execute tests</p>
      </div>
    );
  }

  const totalSteps = testSuite.test_cases.reduce((acc, tc) => acc + tc.steps.length, 0);
  const estimatedTime = Math.ceil((totalSteps * timeout) / 1000 / 60);

  const handleExecute = async () => {
    setIsExecuting(true);
    setLogs(['Starting Multi-Agent execution...']);

    try {
      setLogs((prev) => [...prev, `[Multi-Agent] Starting supervisor orchestration...`]);
      setLogs((prev) => [...prev, `Sub-agents: Parser → Executor → Validator → Reporter`]);
      setLogs((prev) => [...prev, `Max retries: ${maxRetries}`]);
      setLogs((prev) => [...prev, '---']);

      // Connect to SSE for real-time updates
      connect();
      clearLogs();

      let result;
      if (rawTestCases && rawTestCases.length > 0) {
        // Normal path: raw Excel data → parse → execute
        result = await executeMultiAgent(
          rawTestCases as TestCaseRaw[],
          sessionId,
          {
            projectName: testSuite!.project,
            baseUrl: testSuite!.base_url,
            llmProvider: llmProvider,
            model: LLM_OPTIONS[llmProvider].model,
            headless: headless,
            keepBrowserOpen: keepBrowserOpenAgent,
            timeout,
            maxRetries,
          }
        );
      } else {
        // Loaded from Projects: testSuite is already structured → skip parsing
        result = await executeFromParsed(
          testSuite!,
          sessionId,
          {
            headless: headless,
            keepBrowserOpen: keepBrowserOpenAgent,
            timeout,
            maxRetries,
          }
        );
      }

      setLogs((prev) => [...prev, '---']);
      setLogs((prev) => [...prev, `Multi-Agent completed!`]);
      setLogs((prev) => [...prev, `Status: ${result.validation_status}`]);
      setLogs((prev) => [...prev, `Passed: ${result.summary.passed}/${result.summary.total}`]);
      setLogs((prev) => [...prev, `Failed: ${result.summary.failed}/${result.summary.total}`]);
      if (result.summary.retries > 0) {
        setLogs((prev) => [...prev, `Retries: ${result.summary.retries}`]);
      }
      if (result.orchestration?.sub_agents_used) {
        setLogs((prev) => [...prev, `Sub-agents used: ${result.orchestration.sub_agents_used.join(', ')}`]);
      }

      // Set execution result
      if (result.execution_results && typeof result.execution_results === 'object') {
        const execResult = {
          project: result.execution_results.project || testSuite?.project || 'Test Project',
          base_url: result.execution_results.base_url || testSuite?.base_url || '',
          total: result.execution_results.total ?? result.summary.total ?? 0,
          passed: result.execution_results.passed ?? result.summary.passed ?? 0,
          failed: result.execution_results.failed ?? result.summary.failed ?? 0,
          results: result.execution_results.results || [],
          executed_at: result.execution_results.executed_at || new Date().toISOString(),
        };
        setExecutionResult(execResult);
      }

      // Set generated script if available
      if (result.generated_script) {
        setGeneratedScript(result.generated_script);
        setLogs((prev) => [...prev, `Playwright script generated!`]);
      }

      addNotification(
        result.validation_status === 'passed' ? 'success' : 'warning',
        `Multi-Agent: ${result.summary.passed}/${result.summary.total} passed`
      );
      setCurrentView('results');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Multi-Agent execution failed';
      setLogs((prev) => [...prev, `ERROR: ${message}`]);
      addNotification('error', message);
    } finally {
      setIsExecuting(false);
      disconnect();
    }
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <motion.div
        className={styles.header}
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className={styles.headerIcon}>
          <Rocket size={32} />
        </div>
        <h1 className={styles.title}>Execute Tests</h1>
        <p className={styles.subtitle}>
          Run your generated Playwright scripts per test case
        </p>
      </motion.div>

      {/* Test Summary */}
      <motion.div
        className={styles.summary}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <div className={styles.summaryHeader}>
          <h2 className={styles.summaryTitle}>{testSuite.project}</h2>
          <span className={styles.summaryUrl}>{testSuite.base_url}</span>
        </div>
        <div className={styles.summaryStats}>
          <div className={styles.summaryStat}>
            <Zap size={18} className={styles.summaryIcon} />
            <span>{testSuite.test_cases.length} Test Cases</span>
          </div>
          <div className={styles.summaryStat}>
            <Terminal size={18} className={styles.summaryIcon} />
            <span>{totalSteps} Steps</span>
          </div>
          <div className={styles.summaryStat}>
            <Clock size={18} className={styles.summaryIcon} />
            <span>~{estimatedTime} min</span>
          </div>
        </div>
      </motion.div>

      {/* Configuration */}
      <motion.div
        className={styles.config}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <div className={styles.configHeader}>
          <Settings size={20} />
          <h3>Configuration</h3>
        </div>

        <div className={styles.configOptions}>
          {/* Headless Toggle */}
          <div className={styles.configOption}>
            <div className={styles.optionInfo}>
              <div className={styles.optionIcon}>
                {headless ? <MonitorOff size={20} /> : <Monitor size={20} />}
              </div>
              <div className={styles.optionText}>
                <span className={styles.optionLabel}>Browser Mode</span>
                <span className={styles.optionDesc}>
                  {headless ? 'Headless (faster)' : 'Visible (for debugging)'}
                </span>
              </div>
            </div>
            <button
              className={`${styles.toggle} ${headless ? styles.active : ''}`}
              onClick={() => setHeadless(!headless)}
            >
              <motion.div
                className={styles.toggleKnob}
                animate={{ x: headless ? 20 : 0 }}
                transition={{ type: 'spring', stiffness: 500, damping: 30 }}
              />
            </button>
          </div>

          {/* Advanced Settings Toggle */}
          <button
            className={styles.advancedToggle}
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            <span>Advanced Settings</span>
            <motion.div
              animate={{ rotate: showAdvanced ? 180 : 0 }}
            >
              <Settings size={16} />
            </motion.div>
          </button>

          {/* Advanced Settings */}
          <AnimatePresence>
            {showAdvanced && (
              <motion.div
                className={styles.advancedSettings}
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
              >
                <div className={styles.advancedOption}>
                  <label className={styles.advancedLabel}>
                    <Clock size={16} />
                    Action Timeout (ms)
                  </label>
                  <input
                    type="number"
                    className={styles.advancedInput}
                    value={timeout}
                    onChange={(e) => setTimeout(Number(e.target.value))}
                    min={5000}
                    max={120000}
                    step={5000}
                  />
                </div>
                <div className={styles.advancedOption}>
                  <label className={styles.advancedLabel}>
                    <RefreshCcw size={16} />
                    Max Retries
                  </label>
                  <input
                    type="number"
                    className={styles.advancedInput}
                    value={maxRetries}
                    onChange={(e) => setMaxRetries(Number(e.target.value))}
                    min={0}
                    max={5}
                    step={1}
                  />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.div>

      {/* Warning */}
      {!headless && (
        <motion.div
          className={styles.warning}
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.3 }}
        >
          <AlertTriangle size={20} />
          <span>
            Browser window will open. Do not interact with it during test execution.
          </span>
        </motion.div>
      )}

      {/* Execute Button */}
      <motion.div
        className={styles.actions}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <button
          className={`${styles.executeButton} ${isExecuting ? styles.executing : ''}`}
          onClick={handleExecute}
          disabled={isExecuting}
        >
          {isExecuting ? (
            <Loader2 size={20} className={styles.spinner} />
          ) : (
            <PlayIcon size={20} />
          )}
          {isExecuting ? 'Running...' : 'Execute Tests'}
        </button>
      </motion.div>

      {/* Test Cases List (shown when no generated scripts yet) */}
      {individualScripts.length === 0 && testSuite.test_cases.length > 0 && (
        <motion.div
          className={styles.scriptsSection}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35 }}
        >
          <div className={styles.scriptsSectionHeader}>
            <Code size={18} />
            <span>Test Cases</span>
            <span className={styles.scriptsCount}>{testSuite.test_cases.length} test case(s)</span>
          </div>
          {testSuite.test_cases.map((tc) => (
            <div key={tc.id} className={styles.scriptCard}>
              <div className={styles.scriptCardHeader}>
                <div className={styles.scriptExpandBtn} style={{ cursor: 'default' }}>
                  <span className={styles.scriptTestId}>{tc.id}</span>
                  <span className={styles.scriptTestName}>{tc.name}</span>
                </div>
                <span style={{ fontSize: '0.75rem', color: '#64748b' }}>{tc.steps.length} steps</span>
              </div>
            </div>
          ))}
        </motion.div>
      )}

      {/* Generated Scripts Section */}
      {individualScripts.length > 0 && (
        <motion.div
          className={styles.scriptsSection}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.25 }}
        >
          <div className={styles.scriptsSectionHeader}>
            <Code size={18} />
            <span>Generated Scripts</span>
            <span className={styles.scriptsCount}>{individualScripts.length} test case(s)</span>
          </div>

          {individualScripts.map(({ testId, testName }) => {
            const isExpanded = expandedScript === testId;
            const isRunning = runningScript === testId;
            const result = scriptResults[testId];
            const currentScript = editedScripts[testId] ?? '';

            return (
              <div key={testId} className={styles.scriptCard}>
                {/* Collapsed header row */}
                <div className={styles.scriptCardHeader}>
                  <button
                    className={styles.scriptExpandBtn}
                    onClick={() => setExpandedScript(isExpanded ? null : testId)}
                  >
                    <ChevronDown
                      size={14}
                      className={isExpanded ? styles.chevronOpen : styles.chevronClosed}
                    />
                    <span className={styles.scriptTestId}>{testId}</span>
                    <span className={styles.scriptTestName}>{testName}</span>
                  </button>

                  {/* Status badge */}
                  {result && (
                    <span className={`${styles.scriptResultBadge} ${styles[`result${result}`]}`}>
                      {result === 'PASSED' ? '✓ Passed' : result === 'FAILED' ? '✗ Failed' : result}
                    </span>
                  )}

                  {/* Download button */}
                  <button
                    className={styles.scriptDownloadBtn}
                    onClick={() => handleDownloadScript(testId)}
                    title={`Download ${testId} script`}
                  >
                    <Download size={14} />
                  </button>

                  {/* Run button */}
                  <button
                    className={styles.scriptRunBtn}
                    onClick={() => handleRunScript(testId)}
                    disabled={isRunning || !!runningScript}
                    title={`Run ${testId}`}
                  >
                    {isRunning ? (
                      <Loader2 size={14} className={styles.spinner} />
                    ) : (
                      <PlayIcon size={14} />
                    )}
                    {isRunning ? 'Running...' : 'Run'}
                  </button>
                </div>

                {/* Expanded: editable script */}
                {isExpanded && (
                  <div className={styles.scriptCardBody}>
                    <div className={styles.scriptEditorLabel}>
                      <Edit3 size={12} /> Edit script before running
                    </div>
                    <textarea
                      className={styles.scriptEditor}
                      value={currentScript}
                      onChange={(e) =>
                        setEditedScripts((prev) => ({ ...prev, [testId]: e.target.value }))
                      }
                      spellCheck={false}
                      rows={20}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </motion.div>
      )}

    </div>
  );
};
