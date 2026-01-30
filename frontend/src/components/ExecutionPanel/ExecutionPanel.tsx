import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Play,
  Settings,
  Monitor,
  MonitorOff,
  Clock,
  Zap,
  AlertTriangle,
  Loader2,
  Rocket,
  Terminal,
  Bot,
  RefreshCcw,
  Chrome,
  CheckCircle,
  XCircle,
  ExternalLink,
  FileText,
  Cpu,
  Shield,
  FileCheck,
  Brain,
  ArrowRight,
  Globe,
  Sparkles,
} from 'lucide-react';
import { useStore, LLM_OPTIONS } from '../../store/useStore';
import { executeMultiAgent, type TestCaseRaw } from '../../services/api';
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
  } = useStore();

  const [headless, setHeadless] = useState(true);
  const [timeout, setTimeout] = useState(30000);
  const [maxRetries, setMaxRetries] = useState(2);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);

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

  if (!testSuite) {
    return (
      <div className={styles.empty}>
        <Play size={48} />
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
      // Need raw test cases for Multi-Agent
      if (!rawTestCases || rawTestCases.length === 0) {
        throw new Error('Raw test cases not available. Please re-upload your Excel file.');
      }

      setLogs((prev) => [...prev, `[Multi-Agent] Starting supervisor orchestration...`]);
      setLogs((prev) => [...prev, `Sub-agents: Parser → Executor → Validator → Reporter`]);
      setLogs((prev) => [...prev, `Max retries: ${maxRetries}`]);
      setLogs((prev) => [...prev, '---']);

      // Connect to SSE for real-time updates
      connect();
      clearLogs();

      const result = await executeMultiAgent(
        rawTestCases as TestCaseRaw[],
        sessionId,
        {
          projectName: testSuite!.project,
          baseUrl: testSuite!.base_url,
          llmProvider: llmProvider,
          model: LLM_OPTIONS[llmProvider].model,
          headless,
          timeout,
          maxRetries,
        }
      );

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
          AI-powered test automation with Multi-Agent orchestration
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

      {/* Multi-Agent Info */}
      <motion.div
        className={styles.modeSelector}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
      >
        <div className={styles.modeSelectorHeader}>
          <Bot size={20} />
          <h3>Multi-Agent Orchestration</h3>
        </div>
        <div className={styles.modeInfo}>
          <RefreshCcw size={14} />
          <span>AI supervisor coordinates specialized sub-agents (max {maxRetries} retries)</span>
        </div>
        <div className={styles.subAgentFlow}>
          <span className={`${styles.subAgentBadge} ${styles.badgeParser}`}>
            <FileText size={14} />
            <span>Parser</span>
          </span>
          <span className={styles.flowArrow}>→</span>
          <span className={`${styles.subAgentBadge} ${styles.badgeExecutor}`}>
            <Cpu size={14} />
            <span>Executor</span>
          </span>
          <span className={styles.flowArrow}>→</span>
          <span className={`${styles.subAgentBadge} ${styles.badgeValidator}`}>
            <Shield size={14} />
            <span>Validator</span>
          </span>
          <span className={styles.flowArrow}>→</span>
          <span className={`${styles.subAgentBadge} ${styles.badgeReporter}`}>
            <FileCheck size={14} />
            <span>Reporter</span>
          </span>
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
        <motion.button
          className={`${styles.executeButton} ${isExecuting ? styles.executing : ''}`}
          onClick={handleExecute}
          disabled={isExecuting}
          whileHover={!isExecuting ? { scale: 1.02, y: -2 } : {}}
          whileTap={!isExecuting ? { scale: 0.98 } : {}}
        >
          {isExecuting ? (
            <>
              <Loader2 size={22} className={styles.spinner} />
              Executing...
            </>
          ) : (
            <>
              <Bot size={22} />
              Start Multi-Agent Execution
            </>
          )}
        </motion.button>
      </motion.div>

      {/* Live Browser View - Shows during execution */}
      <AnimatePresence>
        {isExecuting && (
          <motion.div
            className={styles.browserView}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
          >
            <div className={styles.browserHeader}>
              <div className={styles.browserControls}>
                <span className={styles.browserDot} style={{ background: '#ff5f56' }} />
                <span className={styles.browserDot} style={{ background: '#ffbd2e' }} />
                <span className={styles.browserDot} style={{ background: '#27ca40' }} />
              </div>
              <div className={styles.browserUrlBar}>
                <Chrome size={14} />
                <span>{browserState.url || 'Waiting for browser...'}</span>
                {browserState.url && (
                  <a
                    href={browserState.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.browserExternalLink}
                  >
                    <ExternalLink size={12} />
                  </a>
                )}
              </div>
              <div className={styles.browserStatus}>
                {browserState.status === 'running' && (
                  <motion.div
                    animate={{ opacity: [1, 0.5, 1] }}
                    transition={{ repeat: Infinity, duration: 1 }}
                    className={styles.browserStatusLive}
                  >
                    <span className={styles.browserStatusDot} />
                    LIVE
                  </motion.div>
                )}
                {browserState.status === 'passed' && (
                  <span className={styles.browserStatusPassed}>
                    <CheckCircle size={14} /> Passed
                  </span>
                )}
                {browserState.status === 'failed' && (
                  <span className={styles.browserStatusFailed}>
                    <XCircle size={14} /> Failed
                  </span>
                )}
              </div>
            </div>

            <div className={styles.browserContent}>
              {browserState.screenshot ? (
                <img
                  src={`data:image/png;base64,${browserState.screenshot}`}
                  alt="Live Browser View"
                  className={styles.browserScreenshot}
                />
              ) : (
                <div className={styles.browserPlaceholder}>
                  <Loader2 size={40} className={styles.spinner} />
                  <p>Waiting for browser screenshot...</p>
                </div>
              )}
            </div>

            {/* Progress Info */}
            <div className={styles.browserProgress}>
              <div className={styles.progressInfo}>
                <span>
                  Test: {currentTest || '-'} | Step: {currentStep || '-'}
                </span>
                <span>
                  Progress: {progress.completedTests}/{progress.totalTests} tests,{' '}
                  {progress.completedSteps}/{progress.totalSteps} steps
                </span>
              </div>
              <div className={styles.progressBar}>
                <motion.div
                  className={styles.progressFill}
                  initial={{ width: 0 }}
                  animate={{
                    width: progress.totalSteps > 0
                      ? `${(progress.completedSteps / progress.totalSteps) * 100}%`
                      : '0%',
                  }}
                  transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                />
              </div>
              <div className={styles.progressStats}>
                <span className={styles.progressPassed}>
                  <CheckCircle size={12} /> {progress.passedTests} passed
                </span>
                <span className={styles.progressFailed}>
                  <XCircle size={12} /> {progress.failedTests} failed
                </span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Execution Logs */}
      <AnimatePresence>
        {(logs.length > 0 || sseLogs.length > 0) && (
          <motion.div
            className={styles.logs}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
          >
            <div className={styles.logsHeader}>
              <Terminal size={16} />
              <span>Execution Log ({sseLogs.length + logs.length} entries)</span>
            </div>
            <div className={styles.logsContent}>
              {/* Show SSE logs first (real-time from browser) */}
              {sseLogs.map((log, index) => {
                const type = log.type?.toLowerCase() || '';
                const agent = log.agent?.toLowerCase() || '';
                const subAgent = log.subAgent?.toLowerCase() || '';

                // Determine agent type for styling - check both agent and subAgent fields
                const getAgentType = () => {
                  // For delegation events, use subAgent to determine color
                  if (type === 'delegation' && subAgent) {
                    if (subAgent.includes('parser')) return 'parser';
                    if (subAgent.includes('executor')) return 'executor';
                    if (subAgent.includes('validator')) return 'validator';
                    if (subAgent.includes('reporter')) return 'reporter';
                    if (subAgent.includes('recovery') || subAgent.includes('error')) return 'supervisor';
                    return 'delegation';
                  }
                  // Check agent field for agent name
                  if (agent.includes('parser') || agent === 'parse') return 'parser';
                  if (agent.includes('executor') || agent === 'execute') return 'executor';
                  if (agent.includes('validator') || agent === 'validate') return 'validator';
                  if (agent.includes('reporter') || agent === 'report') return 'reporter';
                  if (agent.includes('recovery') || agent === 'error_recovery') return 'supervisor';
                  if (agent.includes('supervisor')) return 'supervisor';
                  if (agent === 'browser') return 'browser';
                  // Check type for event-based coloring
                  if (type.includes('step') || type.includes('test_started') || type.includes('test_completed') || type.includes('execution')) return 'executor';
                  if (type === 'thoughts') return 'thoughts';
                  if (type === 'agent_phase') return 'phase';
                  if (type.includes('browser')) return 'browser';
                  return 'default';
                };

                const agentType = getAgentType();

                // Get the appropriate CSS class
                const getLogTypeClass = () => {
                  const classMap: Record<string, string> = {
                    parser: styles.logTypeParser,
                    executor: styles.logTypeExecutor,
                    validator: styles.logTypeValidator,
                    reporter: styles.logTypeReporter,
                    supervisor: styles.logTypeSupervisor,
                    browser: styles.logTypeBrowser,
                    thoughts: styles.logTypeThoughts,
                    delegation: styles.logTypeDelegation,
                    phase: styles.logTypePhase,
                    default: styles.logTypeDefault,
                  };
                  return classMap[agentType] || styles.logTypeDefault;
                };

                // Get the appropriate icon
                const getIcon = () => {
                  switch (agentType) {
                    case 'parser': return <FileText size={14} />;
                    case 'executor': return <Cpu size={14} />;
                    case 'validator': return <Shield size={14} />;
                    case 'reporter': return <FileCheck size={14} />;
                    case 'supervisor': return <Bot size={14} />;
                    case 'browser': return <Globe size={14} />;
                    case 'thoughts': return <Brain size={14} />;
                    case 'delegation': return <ArrowRight size={14} />;
                    case 'phase': return <Sparkles size={14} />;
                    default: return <Terminal size={14} />;
                  }
                };

                // Get display label
                const getDisplayLabel = () => {
                  // For delegation, show the sub-agent name
                  if (type === 'delegation' && log.subAgent) return log.subAgent;
                  // For sub_agent events, format the node name nicely
                  if ((type === 'sub_agent_started' || type === 'sub_agent_completed') && log.agent) {
                    const agentMap: Record<string, string> = {
                      'parse': 'ParserAgent',
                      'execute': 'ExecutorAgent',
                      'validate': 'ValidatorAgent',
                      'report': 'ReporterAgent',
                    };
                    return agentMap[log.agent.toLowerCase()] || log.agent;
                  }
                  // For node events, format nicely
                  if ((type === 'node_started' || type === 'node_completed') && log.agent) {
                    const nodeMap: Record<string, string> = {
                      'parse': 'ParserAgent',
                      'execute': 'ExecutorAgent',
                      'validate': 'ValidatorAgent',
                      'report': 'ReporterAgent',
                      'error_recovery': 'ErrorRecovery',
                    };
                    return nodeMap[log.agent.toLowerCase()] || log.agent;
                  }
                  if (log.agent) return log.agent;
                  if (type === 'thoughts') return 'Thoughts';
                  if (type === 'agent_phase') return 'Phase';
                  if (type === 'browser_status') return 'Browser';
                  return log.type;
                };

                const getLogLineClass = () => {
                  if (log.level === 'error') return styles.logError;
                  if (log.status === 'passed' || log.message?.includes('PASSED')) return styles.logSuccess;
                  return '';
                };

                return (
                  <motion.div
                    key={log.id || `sse-${index}`}
                    className={`${styles.logLine} ${getLogLineClass()}`}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                  >
                    <span className={styles.logTime}>
                      {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : ''}
                    </span>
                    <span className={`${styles.logType} ${getLogTypeClass()}`}>
                      <span className={styles.logIcon}>{getIcon()}</span>
                      <span>{getDisplayLabel()}</span>
                    </span>
                    <span className={styles.logText}>{log.message}</span>
                  </motion.div>
                );
              })}
              {/* Show local logs */}
              {logs.map((log, index) => (
                <motion.div
                  key={`local-${index}`}
                  className={styles.logLine}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.02 }}
                >
                  <span className={styles.logTime}>
                    {new Date().toLocaleTimeString()}
                  </span>
                  <span className={styles.logText}>{log}</span>
                </motion.div>
              ))}
              {isExecuting && (
                <motion.div
                  className={styles.logLine}
                  animate={{ opacity: [0.5, 1, 0.5] }}
                  transition={{ repeat: Infinity, duration: 1.5 }}
                >
                  <span className={styles.logTime}>
                    {new Date().toLocaleTimeString()}
                  </span>
                  <span className={styles.logText}>Processing...</span>
                </motion.div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
