import { useState, useEffect, useRef, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Terminal,
  CheckCircle,
  XCircle,
  RefreshCw,
  Wifi,
  WifiOff,
} from 'lucide-react';
import type { ExecutionLog } from '../../hooks/useExecutionWebSocket';
import styles from './TerminalDisplay.module.css';

interface TerminalDisplayProps {
  logs: ExecutionLog[];
  progress: {
    totalTests: number;
    completedTests: number;
    passedTests: number;
    failedTests: number;
    totalSteps: number;
    completedSteps: number;
  };
  isConnected: boolean;
  currentTest: string | null;
  currentStep: number | null;
  retries?: number;
}

interface DisplayLog extends ExecutionLog {
  isNew?: boolean;
}

export const TerminalDisplay: React.FC<TerminalDisplayProps> = ({
  logs,
  progress,
  isConnected,
  currentTest,
  currentStep,
  retries = 0,
}) => {
  const [displayedLogs, setDisplayedLogs] = useState<DisplayLog[]>([]);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [startTime] = useState<number>(Date.now());
  const logEndRef = useRef<HTMLDivElement>(null);
  const lastLogCountRef = useRef(0);

  // Track active agents based on recent logs
  const activeAgents = useMemo(() => {
    const agents = new Set<string>();
    // Look at last 10 logs to determine active agents
    logs.slice(-10).forEach(log => {
      const agent = log.agent?.toLowerCase() || '';
      if (agent.includes('supervisor')) agents.add('supervisor');
      if (agent.includes('parser') || agent === 'parse') agents.add('parser');
      if (agent.includes('executor') || agent === 'execute') agents.add('executor');
      if (agent.includes('validator') || agent === 'validate') agents.add('validator');
      if (agent.includes('reporter') || agent === 'report') agents.add('reporter');
    });
    return agents;
  }, [logs]);

  // Count retries from logs
  const retryCount = useMemo(() => {
    return logs.filter(log => log.type === 'step_retry').length;
  }, [logs]);

  // Update elapsed time
  useEffect(() => {
    const interval = setInterval(() => {
      setElapsedTime(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  // Process new logs with animation marker
  useEffect(() => {
    if (logs.length > lastLogCountRef.current) {
      const newLogs = logs.slice(lastLogCountRef.current).map(log => ({
        ...log,
        isNew: true,
      }));

      setDisplayedLogs(prev => {
        // Remove 'isNew' from previous logs
        const updated = prev.map(log => ({ ...log, isNew: false }));
        return [...updated, ...newLogs];
      });

      lastLogCountRef.current = logs.length;
    }
  }, [logs]);

  // Auto-scroll to bottom
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [displayedLogs]);

  // Format elapsed time
  const formatTime = (seconds: number): string => {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Render ASCII progress bar
  const renderProgressBar = (current: number, total: number, width: number = 24): JSX.Element => {
    const percentage = total > 0 ? Math.round((current / total) * 100) : 0;
    const filled = Math.round((current / total) * width) || 0;
    const empty = width - filled;

    return (
      <div className={styles.progressContainer}>
        <span className={styles.progressBar}>
          <span className={styles.progressFilled}>{'█'.repeat(filled)}</span>
          <span className={styles.progressEmpty}>{'░'.repeat(empty)}</span>
        </span>
        <span className={styles.progressPercent}>{percentage}%</span>
      </div>
    );
  };

  // Get agent label from log
  const getAgentLabel = (log: ExecutionLog): string | null => {
    const agent = log.agent?.toLowerCase() || '';
    const type = log.type?.toLowerCase() || '';

    if (agent.includes('supervisor')) return 'SUPERVISOR';
    if (agent.includes('parser') || agent === 'parse') return 'PARSER';
    if (agent.includes('executor') || agent === 'execute') return 'EXECUTOR';
    if (agent.includes('validator') || agent === 'validate') return 'VALIDATOR';
    if (agent.includes('reporter') || agent === 'report') return 'REPORTER';
    if (agent === 'browser') return 'BROWSER';

    // Fallback based on event type
    if (type.includes('step')) return 'EXECUTOR';
    if (type.includes('test')) return 'EXECUTOR';
    if (type.includes('browser')) return 'BROWSER';
    if (type === 'thoughts') return 'SUPERVISOR';

    return null;
  };

  // Get agent class for styling
  const getAgentClass = (log: ExecutionLog): string => {
    const agent = log.agent?.toLowerCase() || '';

    if (agent.includes('supervisor')) return styles.supervisor;
    if (agent.includes('parser') || agent === 'parse') return styles.parser;
    if (agent.includes('executor') || agent === 'execute') return styles.executor;
    if (agent.includes('validator') || agent === 'validate') return styles.validator;
    if (agent.includes('reporter') || agent === 'report') return styles.reporter;
    if (agent === 'browser') return styles.browser;

    return styles.system;
  };

  // Get status icon
  const getStatusIcon = (log: ExecutionLog): JSX.Element | null => {
    if (log.status === 'passed' || log.type === 'step_retry_success') {
      return <span className={`${styles.statusIcon} ${styles.passed}`}>✓ PASSED</span>;
    }
    if (log.status === 'failed' || log.type === 'step_retry_exhausted') {
      return <span className={`${styles.statusIcon} ${styles.failed}`}>✗ FAILED</span>;
    }
    if (log.type === 'step_retry') {
      return <span className={`${styles.statusIcon} ${styles.retry}`}>⟳ RETRY</span>;
    }
    return null;
  };

  // Get log level class
  const getLogLevelClass = (log: ExecutionLog): string => {
    if (log.level === 'error' || log.type === 'step_retry_exhausted') return styles.error;
    if (log.level === 'warn' || log.type === 'step_retry') return styles.warn;
    if (log.status === 'passed' || log.type === 'step_retry_success') return styles.success;
    return '';
  };

  // Format log message
  const formatMessage = (log: ExecutionLog): string => {
    // Truncate long messages
    let msg = log.message || '';
    if (msg.length > 100) {
      msg = msg.substring(0, 97) + '...';
    }
    return msg;
  };

  return (
    <div className={styles.terminal}>
      {/* Scanline overlay */}
      <div className={styles.scanlines} />
      <div className={styles.crtFlicker} />

      {/* Header */}
      <div className={styles.terminalHeader}>
        <div className={styles.headerLeft}>
          <div className={styles.terminalTitle}>
            <Terminal size={16} />
            <span>TERMINAL</span>
          </div>
          <span className={styles.versionBadge}>v2.0</span>
        </div>
        <div className={styles.headerRight}>
          <div className={`${styles.connectionIndicator} ${isConnected ? styles.connected : styles.disconnected}`}>
            <span className={`${styles.statusDot} ${isConnected ? styles.connected : styles.disconnected}`} />
            {isConnected ? (
              <>
                <Wifi size={10} />
                <span>CONNECTED</span>
              </>
            ) : (
              <>
                <WifiOff size={10} />
                <span>OFFLINE</span>
              </>
            )}
          </div>
          <span className={styles.timer}>{formatTime(elapsedTime)}</span>
        </div>
      </div>

      {/* Stats Panel */}
      {progress.totalSteps > 0 && (
        <div className={styles.statsPanel}>
          <div className={styles.statsBorder}>╔{'═'.repeat(56)}╗</div>
          <div className={styles.statsContent}>
            <div className={styles.statsTitle}>EXECUTION STATS</div>
            <div className={styles.statsRow}>
              {renderProgressBar(progress.completedSteps, progress.totalSteps)}
              <span className={styles.statsText}>
                Tests: <strong>{progress.completedTests}</strong>/{progress.totalTests}
                {' '}Steps: <strong>{progress.completedSteps}</strong>/{progress.totalSteps}
              </span>
            </div>
            <div className={styles.statsRow}>
              <div className={styles.statusCounters}>
                <span className={`${styles.counter} ${styles.passed}`}>
                  <CheckCircle size={14} />
                  PASSED: {progress.passedTests}
                </span>
                <span className={`${styles.counter} ${styles.failed}`}>
                  <XCircle size={14} />
                  FAILED: {progress.failedTests}
                </span>
                {(retryCount > 0 || retries > 0) && (
                  <span className={`${styles.counter} ${styles.retries}`}>
                    <RefreshCw size={14} />
                    RETRIES: {retryCount || retries}
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className={styles.statsBorder}>╚{'═'.repeat(56)}╝</div>
        </div>
      )}

      {/* Log Area */}
      <div className={styles.logArea}>
        {displayedLogs.length === 0 ? (
          <div className={styles.emptyState}>
            <Terminal size={48} />
            <span className={styles.emptyText}>Waiting for execution...</span>
            <span className={styles.emptyHint}>Activity logs will appear here</span>
          </div>
        ) : (
          <AnimatePresence>
            {displayedLogs.map((log, index) => {
              const agentLabel = getAgentLabel(log);
              const agentClass = getAgentClass(log);
              const statusIcon = getStatusIcon(log);
              const levelClass = getLogLevelClass(log);

              return (
                <motion.div
                  key={log.id}
                  className={`${styles.logEntry} ${levelClass} ${log.isNew ? styles.new : ''}`}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.15 }}
                >
                  <span className={styles.prompt}>&gt;</span>
                  <span className={styles.timestamp}>
                    [{log.timestamp.toLocaleTimeString('en-US', {
                      hour12: false,
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit'
                    })}]
                  </span>
                  {agentLabel && (
                    <span className={`${styles.agentLabel} ${agentClass}`}>
                      {agentLabel}
                    </span>
                  )}
                  <span className={styles.arrow}>→</span>
                  <span className={styles.message}>
                    {log.step && (
                      <span className={styles.stepBadge}>Step {log.step}</span>
                    )}
                    {formatMessage(log)}
                    {log.type === 'step_retry' && log.attempt && (
                      <span className={styles.retryIndicator}>
                        <RefreshCw size={10} />
                        {log.attempt}/{log.maxRetries || 3}
                      </span>
                    )}
                  </span>
                  {statusIcon}
                  {index === displayedLogs.length - 1 && currentTest && (
                    <span className={styles.cursor} />
                  )}
                </motion.div>
              );
            })}
          </AnimatePresence>
        )}
        <div ref={logEndRef} />
      </div>

      {/* Agent Bar Footer */}
      <div className={styles.agentBar}>
        <span className={styles.agentBarLabel}>[AGENTS:</span>
        {['Supervisor', 'Parser', 'Executor', 'Validator', 'Reporter'].map((agent, index, arr) => (
          <span key={agent}>
            <span
              className={`${styles.agentName} ${
                activeAgents.has(agent.toLowerCase()) ? styles.active : styles.inactive
              }`}
            >
              {agent}
            </span>
            {index < arr.length - 1 && <span className={styles.agentSeparator}>|</span>}
          </span>
        ))}
        <span className={styles.agentBarLabel}>]</span>
      </div>
    </div>
  );
};

export default TerminalDisplay;
