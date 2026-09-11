import { useState, useEffect, useCallback, useRef } from 'react';
import { Play, Download, Loader2, CheckCircle2, XCircle, Clock, FileCheck } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { listProjectTests, loadTestFromProject, executeFromParsed, type SavedTestMeta } from '../../services/api';
import { useExecutionWebSocket } from '../../hooks/useExecutionWebSocket';
import type { TestSuite, ExecutionResult } from '../../store/useStore';
import styles from './ProjectsView.module.css';
import wsStyles from './ProjectWorkspace.module.css';

interface Props {
  projectName: string;
}

const formatSavedAt = (savedAt: string) => {
  const parts = savedAt.split('_');
  if (parts.length === 2) return `${parts[0]} ${parts[1].replace(/-/g, ':')}`;
  return savedAt;
};

const makeSessionId = () =>
  `proj_exec_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

export const ProjectExecute = ({ projectName }: Props) => {
  const {
    setExecutionResult,
    setProjectExecutionResult,
    setCurrentView,
    addNotification,
  } = useStore();

  // State A — picker
  const [tests, setTests] = useState<SavedTestMeta[]>([]);
  const [loadingTests, setLoadingTests] = useState(false);
  const [loadingTest, setLoadingTest] = useState<string | null>(null);

  // State B — execution
  const [activeSuite, setActiveSuite] = useState<TestSuite | null>(null);
  const [headless, setHeadless] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [execResult, setExecResult] = useState<ExecutionResult | null>(null);

  const sessionIdRef = useRef<string>(makeSessionId());

  const { logs, progress, connect, disconnect, clearLogs } = useExecutionWebSocket(sessionIdRef.current);

  const fetchTests = useCallback(async () => {
    setLoadingTests(true);
    try {
      const data = await listProjectTests(projectName);
      setTests(data);
    } catch (e) {
      addNotification('error', e instanceof Error ? e.message : 'Failed to load tests');
    } finally {
      setLoadingTests(false);
    }
  }, [projectName, addNotification]);

  useEffect(() => {
    fetchTests();
  }, [fetchTests]);

  const handleSelectTest = async (filename: string) => {
    setLoadingTest(filename);
    try {
      const suite = await loadTestFromProject(projectName, filename);
      setActiveSuite(suite as TestSuite);
    } catch (e) {
      addNotification('error', e instanceof Error ? e.message : 'Failed to load test');
    } finally {
      setLoadingTest(null);
    }
  };

  const handleExecute = async () => {
    if (!activeSuite) return;
    setExecuting(true);
    setExecResult(null);
    clearLogs();
    connect();
    try {
      const result = await executeFromParsed(activeSuite, sessionIdRef.current, { headless });
      const execRes = result as unknown as ExecutionResult;
      setExecResult(execRes);
      setExecutionResult(execRes);
      setProjectExecutionResult(projectName, execRes);
      addNotification('success', `Execution complete: ${execRes.passed}/${execRes.total} passed`);
    } catch (e) {
      addNotification('error', e instanceof Error ? e.message : 'Execution failed');
    } finally {
      setExecuting(false);
      disconnect();
    }
  };

  // State A — picker
  if (!activeSuite) {
    if (loadingTests) {
      return (
        <div style={{ padding: '32px', display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', fontSize: '0.875rem' }}>
          <Loader2 size={16} className={styles.spin} />
          Loading tests…
        </div>
      );
    }
    if (tests.length === 0) {
      return (
        <div className={styles.emptyTests} style={{ padding: '32px' }}>
          <Play size={40} className={styles.emptyTestsIcon} />
          <p>No saved tests in <strong>{projectName}</strong></p>
          <p className={styles.emptyHint}>Generate and save a test case first.</p>
        </div>
      );
    }
    return (
      <div style={{ padding: '24px 32px' }}>
        <h2 className={styles.testColTitle}>Select a test to execute</h2>
        <div className={styles.testList}>
          {tests.map(t => (
            <div key={t.filename} className={styles.testCard}>
              <div className={styles.testCardBody}>
                <div className={styles.testCardDate}>{formatSavedAt(t.saved_at)}</div>
                <div className={styles.testCardUrl}>{t.base_url || '—'}</div>
                <span className={styles.testCaseBadge}>
                  {t.test_case_count} test case{t.test_case_count !== 1 ? 's' : ''}
                </span>
              </div>
              <div className={styles.testCardActions}>
                <button
                  className={styles.loadBtn}
                  onClick={() => handleSelectTest(t.filename)}
                  disabled={loadingTest === t.filename}
                >
                  {loadingTest === t.filename
                    ? <Loader2 size={13} className={styles.spin} />
                    : <Play size={13} />}
                  Select
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // State B — execution UI
  return (
    <div style={{ padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Suite summary */}
      <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: '16px 20px' }}>
        <div style={{ fontSize: '0.8125rem', color: '#64748b', marginBottom: 4 }}>Selected suite</div>
        <div style={{ fontWeight: 600, color: '#1e293b', marginBottom: 2 }}>{activeSuite.project || projectName}</div>
        <div style={{ fontSize: '0.8125rem', color: '#94a3b8' }}>
          {activeSuite.test_cases?.length ?? 0} test case{activeSuite.test_cases?.length !== 1 ? 's' : ''} · {activeSuite.base_url}
        </div>
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: '0.8125rem', color: '#374151', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={headless}
            onChange={e => setHeadless(e.target.checked)}
            disabled={executing}
            style={{ accentColor: '#3b82f6' }}
          />
          Headless mode
        </label>
        <button
          className={wsStyles.btnPrimary}
          onClick={handleExecute}
          disabled={executing}
        >
          {executing ? <Loader2 size={14} className={wsStyles.spin} /> : <Play size={14} />}
          {executing ? 'Executing…' : 'Execute'}
        </button>
        {!executing && (
          <button
            className={wsStyles.btnSecondary}
            onClick={() => { setActiveSuite(null); setExecResult(null); clearLogs(); }}
          >
            Change suite
          </button>
        )}
      </div>

      {/* Live logs */}
      {(executing || logs.length > 0) && (
        <div style={{
          background: '#0f172a',
          borderRadius: 10,
          padding: '14px 16px',
          maxHeight: 280,
          overflowY: 'auto',
          fontFamily: 'monospace',
          fontSize: '0.75rem',
          color: '#e2e8f0',
        }}>
          {logs.map(log => (
            <div key={log.id} style={{ marginBottom: 3, color: log.level === 'error' ? '#f87171' : log.status === 'failed' ? '#fb923c' : '#e2e8f0' }}>
              <span style={{ color: '#64748b' }}>[{new Date(log.timestamp).toLocaleTimeString()}]</span>{' '}
              {log.agent && <span style={{ color: '#818cf8' }}>[{log.agent}]</span>}{' '}
              {log.message}
            </div>
          ))}
          {executing && (
            <div style={{ color: '#60a5fa', display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
              <Loader2 size={12} className={styles.spin} />
              Running…
            </div>
          )}
        </div>
      )}

      {/* Result summary */}
      {execResult && !executing && (
        <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: '16px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            {execResult.failed === 0
              ? <CheckCircle2 size={20} style={{ color: '#22c55e' }} />
              : <XCircle size={20} style={{ color: '#ef4444' }} />}
            <span style={{ fontWeight: 600, fontSize: '0.9375rem', color: '#1e293b' }}>
              {execResult.passed}/{execResult.total} passed
            </span>
            {execResult.failed > 0 && (
              <span style={{ fontSize: '0.8125rem', color: '#ef4444' }}>{execResult.failed} failed</span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className={wsStyles.btnPrimary} onClick={() => setCurrentView('results')}>
              <FileCheck size={14} />
              View Full Results
            </button>
            <button className={wsStyles.btnSecondary} onClick={() => setCurrentView('download')}>
              <Download size={14} />
              Download Report
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
