import React, { useState, useRef, useEffect } from 'react';
import { useLoadTestSSE } from '../../hooks/useLoadTestSSE';
import { useStore } from '../../store/useStore';
import { Terminal, Trash2, Download } from 'lucide-react';
import styles from './LoadTestLogs.module.css';

interface LogEntry {
  timestamp: string;
  log: string;
}

const LoadTestLogs: React.FC = () => {
  const terminalRef = useRef<HTMLDivElement>(null);
  const [isAutoScrollEnabled, setIsAutoScrollEnabled] = useState(true);
  const loadTestSessionId = useStore((state) => state.loadTestSessionId);
  const terminalLogs = useStore((state) => state.terminalLogs);
  const addTerminalLog = useStore((state) => state.addTerminalLog);
  const clearTerminalLogs = useStore((state) => state.clearTerminalLogs);
  const { messages } = useLoadTestSSE(loadTestSessionId || '', !!loadTestSessionId);

  // Handle SSE messages
  useEffect(() => {
    if (messages.length === 0) return;

    const latestMessage = messages[messages.length - 1];
    console.log('[LoadTestLogs] Received SSE message:', latestMessage.type, latestMessage.data);

    switch (latestMessage.type) {
      case 'terminal_log':
        addTerminalLog({
          timestamp: latestMessage.data.timestamp,
          log: latestMessage.data.log
        });
        break;

      case 'load_test_started':
      case 'sequential_test_started':
        // Clear logs on new test
        clearTerminalLogs();
        // Re-enable auto-scroll on new test
        setIsAutoScrollEnabled(true);
        break;
    }
  }, [messages, addTerminalLog, clearTerminalLogs]);

  // Smart auto-scroll: only scroll if user is at bottom
  useEffect(() => {
    if (terminalRef.current && terminalLogs.length > 0 && isAutoScrollEnabled) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [terminalLogs, isAutoScrollEnabled]);

  // Detect if user manually scrolled away from bottom
  const handleScroll = () => {
    if (!terminalRef.current) return;

    const { scrollTop, scrollHeight, clientHeight } = terminalRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 10; // 10px threshold

    // Enable auto-scroll if user scrolled to bottom, disable if scrolled up
    setIsAutoScrollEnabled(isAtBottom);
  };

  const getLogClassName = (logText: string): string => {
    if (logText.includes('[INIT]')) return styles.logInit;
    if (logText.includes('[REQUEST]')) return styles.logRequest;
    if (logText.includes('[RESPONSE]')) return styles.logResponse;
    if (logText.includes('[SUCCESS]')) return styles.logSuccess;
    if (logText.includes('[FAILURE]')) return styles.logFailure;
    if (logText.includes('[ERROR]')) return styles.logError;
    return '';
  };

  const downloadLogs = () => {
    if (terminalLogs.length === 0) return;

    // Format timestamp for filename
    const now = new Date();
    const timestamp = now.toISOString().split('T')[0] + '_' +
                     now.toTimeString().split(' ')[0].replace(/:/g, '-');
    const filename = `load_test_logs_${timestamp}.txt`;

    // Format log content with session info header
    const header = `=== Load Test Terminal Logs ===
Session ID: ${loadTestSessionId || 'N/A'}
Date: ${now.toISOString().split('T')[0]} ${now.toTimeString().split(' ')[0]}
Total Logs: ${terminalLogs.length}
================================

`;

    const logContent = terminalLogs.map(entry => {
      const time = new Date(entry.timestamp).toLocaleTimeString();
      return `[${time}] ${entry.log}`;
    }).join('\n');

    const fullContent = header + logContent;

    // Create blob and download
    const blob = new Blob([fullContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className={styles.logsContainer}>
      <div className={styles.header}>
        <div className={styles.titleSection}>
          <Terminal size={24} className={styles.icon} />
          <h1 className={styles.title}>Terminal Logs</h1>
        </div>
        <div className={styles.actions}>
          <span className={styles.logCount}>
            {terminalLogs.length} / 1000 lines
          </span>
          <button
            className={styles.downloadButton}
            onClick={downloadLogs}
            disabled={terminalLogs.length === 0}
            title="Download logs as TXT file"
          >
            <Download size={18} />
          </button>
          <button
            className={styles.clearButton}
            onClick={clearTerminalLogs}
            disabled={terminalLogs.length === 0}
          >
            <Trash2 size={16} />
            Clear Logs
          </button>
        </div>
      </div>

      <div className={styles.terminalContainer}>
        <div ref={terminalRef} className={styles.terminal} onScroll={handleScroll}>
          {terminalLogs.length === 0 ? (
            <div className={styles.emptyState}>
              <Terminal size={48} className={styles.emptyIcon} />
              <p>No logs yet</p>
              <p className={styles.emptyHint}>
                Logs will appear here when you start a load test from the Agent page
              </p>
            </div>
          ) : (
            terminalLogs.map((entry, idx) => (
              <div key={idx} className={styles.logLine}>
                <span className={styles.timestamp}>
                  {new Date(entry.timestamp).toLocaleTimeString()}
                </span>
                <span className={`${styles.logText} ${getLogClassName(entry.log)}`}>
                  {entry.log}
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className={styles.footer}>
        <p className={styles.footerText}>
          Session ID: <code>{loadTestSessionId}</code>
        </p>
        <p className={styles.footerHint}>
          Logs are retained for the duration of your session
        </p>
      </div>
    </div>
  );
};

export default LoadTestLogs;
