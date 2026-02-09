import React, { useState } from 'react';
import { useStore } from '../../store/useStore';
import type { LoadTestConfig } from '../../store/useStore';
import { useLoadTestSSE } from '../../hooks/useLoadTestSSE';
import { LiveCharts } from './LiveCharts';
import type { MetricsHistoryPoint } from './LiveCharts';
import styles from './LoadTestDashboard.module.css';
import { Upload, Play, Square, Zap, Users, TrendingUp, Clock, AlertCircle, BarChart3, Grid3x3 } from 'lucide-react';

// Use relative URL to leverage Vite proxy
const API_BASE_URL = '';

export const LoadTestDashboard: React.FC = () => {
  const {
    uploadedApis,
    setUploadedApis,
    selectedLoadTestApi,
    setSelectedLoadTestApi,
    loadTestMetrics,
    setLoadTestMetrics,
    isLoadTesting,
    setIsLoadTesting,
    activeLoadTestId,
    setActiveLoadTestId,
    addNotification,
  } = useStore();

  const [uploadId, setUploadId] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [loadConfig, setLoadConfig] = useState<LoadTestConfig>({
    users: 10,
    spawn_rate: 1,
    run_time: '5m',
  });
  const [viewMode, setViewMode] = useState<'cards' | 'charts'>('cards');
  const [metricsHistory, setMetricsHistory] = useState<MetricsHistoryPoint[]>([]);

  // SSE connection for real-time metrics
  const sessionId = React.useMemo(() => `loadtest_${Date.now()}`, []);
  const { messages } = useLoadTestSSE(sessionId, isLoadTesting);

  // Handle SSE messages
  React.useEffect(() => {
    const latestMessage = messages[messages.length - 1];
    if (!latestMessage) return;

    switch (latestMessage.type) {
      case 'load_test_started':
        setMetricsHistory([]); // Clear history on new test
        addNotification('success', 'Load test started successfully');
        break;
      case 'load_test_metrics':
        setLoadTestMetrics(latestMessage.data);
        // Add to history for charts
        setMetricsHistory((prev) => [
          ...prev,
          {
            timestamp: latestMessage.data.timestamp || new Date().toISOString(),
            requests_per_second: latestMessage.data.requests_per_second || 0,
            failures_per_second: latestMessage.data.failures_per_second || 0,
            median_response_time: latestMessage.data.median_response_time || 0,
            percentile_95: latestMessage.data.percentile_95 || 0,
            current_users: latestMessage.data.current_users || 0,
          },
        ]);
        break;
      case 'load_test_completed':
        setLoadTestMetrics(latestMessage.data);
        setIsLoadTesting(false);
        addNotification('success', 'Load test completed');
        break;
      case 'load_test_stopped':
        setIsLoadTesting(false);
        addNotification('info', 'Load test stopped');
        break;
      case 'load_test_error':
        setIsLoadTesting(false);
        addNotification('error', latestMessage.data.error || 'Load test error');
        break;
    }
  }, [messages]);

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${API_BASE_URL}/api/v1/load-test/upload-excel`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to upload file');
      }

      const data = await response.json();
      setUploadId(data.upload_id);
      setUploadedApis(data.apis);
      addNotification('success', `Parsed ${data.total_apis} APIs successfully`);
    } catch (error) {
      addNotification('error', error instanceof Error ? error.message : 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  };

  const handleStartTest = async () => {
    if (!uploadId || !selectedLoadTestApi) {
      addNotification('error', 'Please select an API first');
      return;
    }

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/load-test/start-from-excel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          upload_id: uploadId,
          selected_api_name: selectedLoadTestApi.name,
          config: loadConfig,
          session_id: sessionId,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to start test');
      }

      const data = await response.json();
      setActiveLoadTestId(data.test_id);
      setIsLoadTesting(true);
      setLoadTestMetrics(null); // Clear previous metrics
      setMetricsHistory([]); // Clear metrics history
    } catch (error) {
      addNotification('error', error instanceof Error ? error.message : 'Failed to start test');
    }
  };

  const handleStopTest = async () => {
    if (!activeLoadTestId) return;

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/load-test/stop/${activeLoadTestId}`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('Failed to stop test');
      }

      setIsLoadTesting(false);
    } catch (error) {
      addNotification('error', error instanceof Error ? error.message : 'Failed to stop test');
    }
  };

  return (
    <div className={styles.dashboard}>
      <header className={styles.header}>
        <div className={styles.titleSection}>
          <Zap size={32} className={styles.icon} />
          <div>
            <h1>Load Test Dashboard</h1>
            <p>Upload Excel → Select API → Configure → Run Load Test</p>
          </div>
        </div>
      </header>

      {/* Section 1: Upload Excel */}
      <section className={styles.section}>
        <h2>
          <Upload size={20} /> Upload API Configuration
        </h2>
        <div className={styles.uploadZone}>
          <input
            type="file"
            accept=".xlsx,.xls"
            onChange={handleFileUpload}
            disabled={isUploading || isLoadTesting}
            id="excel-upload"
            className={styles.fileInput}
          />
          <label htmlFor="excel-upload" className={styles.uploadLabel}>
            {isUploading ? (
              'Uploading...'
            ) : uploadedApis ? (
              `✓ Parsed ${uploadedApis.length} APIs`
            ) : (
              'Click to browse or drag & drop Excel file'
            )}
          </label>
          <p className={styles.hint}>
            Sample columns: API Name, Base URL, Endpoint, Method, Headers, Payload, Auth Token
          </p>
        </div>
      </section>

      {/* Section 2: Select API & Configure */}
      {uploadedApis && uploadedApis.length > 0 && (
        <section className={styles.section}>
          <h2>Select API & Configure Load Test</h2>

          <div className={styles.apiGrid}>
            {uploadedApis.map((api) => (
              <div
                key={api.name}
                className={`${styles.apiCard} ${
                  selectedLoadTestApi?.name === api.name ? styles.selected : ''
                }`}
                onClick={() => setSelectedLoadTestApi(api)}
              >
                <div className={styles.methodBadge}>{api.method}</div>
                <h3>{api.name}</h3>
                <p className={styles.endpoint}>{api.endpoint}</p>
              </div>
            ))}
          </div>

          {selectedLoadTestApi && (
            <div className={styles.configSection}>
              <div className={styles.apiDetails}>
                <h3>API Details</h3>
                <div className={styles.detailRow}>
                  <strong>Base URL:</strong> {selectedLoadTestApi.base_url}
                </div>
                <div className={styles.detailRow}>
                  <strong>Endpoint:</strong> {selectedLoadTestApi.endpoint}
                </div>
                <div className={styles.detailRow}>
                  <strong>Method:</strong> {selectedLoadTestApi.method}
                </div>
              </div>

              <div className={styles.configForm}>
                <h3>Load Test Configuration</h3>
                <div className={styles.formGroup}>
                  <label>
                    <Users size={16} /> Number of Users:
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="10000"
                    value={loadConfig.users}
                    onChange={(e) =>
                      setLoadConfig({ ...loadConfig, users: parseInt(e.target.value) || 1 })
                    }
                    disabled={isLoadTesting}
                  />
                </div>

                <div className={styles.formGroup}>
                  <label>
                    <TrendingUp size={16} /> Spawn Rate (users/sec):
                  </label>
                  <input
                    type="number"
                    min="0.1"
                    step="0.1"
                    value={loadConfig.spawn_rate}
                    onChange={(e) =>
                      setLoadConfig({ ...loadConfig, spawn_rate: parseFloat(e.target.value) || 1 })
                    }
                    disabled={isLoadTesting}
                  />
                </div>

                <div className={styles.formGroup}>
                  <label>
                    <Clock size={16} /> Run Time:
                  </label>
                  <input
                    type="text"
                    placeholder="5m, 1h, 30s"
                    value={loadConfig.run_time}
                    onChange={(e) => setLoadConfig({ ...loadConfig, run_time: e.target.value })}
                    disabled={isLoadTesting}
                  />
                </div>

                <button
                  className={styles.startButton}
                  onClick={handleStartTest}
                  disabled={isLoadTesting}
                >
                  <Play size={16} /> Start Load Test
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {/* Section 3: Live Metrics */}
      {loadTestMetrics && (
        <section className={styles.section}>
          <div className={styles.metricsHeader}>
            <h2>
              Live Metrics & Results
              {isLoadTesting && <span className={styles.statusRunning}>● Running</span>}
              {!isLoadTesting && loadTestMetrics.status === 'completed' && (
                <span className={styles.statusCompleted}>● Completed</span>
              )}
            </h2>
            <div className={styles.viewToggle}>
              <button
                className={`${styles.viewButton} ${viewMode === 'cards' ? styles.active : ''}`}
                onClick={() => setViewMode('cards')}
                title="Card View"
              >
                <Grid3x3 size={18} />
              </button>
              <button
                className={`${styles.viewButton} ${viewMode === 'charts' ? styles.active : ''}`}
                onClick={() => setViewMode('charts')}
                title="Chart View"
              >
                <BarChart3 size={18} />
              </button>
            </div>
          </div>

          {viewMode === 'cards' ? (
            <>
              <div className={styles.metricsGrid}>
                <div className={styles.metricCard}>
                  <div className={styles.metricValue}>{loadTestMetrics.current_users}</div>
                  <div className={styles.metricLabel}>
                    <Users size={16} /> Users
                  </div>
                </div>

                <div className={styles.metricCard}>
                  <div className={styles.metricValue}>{loadTestMetrics.requests_per_second.toFixed(1)}</div>
                  <div className={styles.metricLabel}>
                    <TrendingUp size={16} /> RPS
                  </div>
                </div>

                <div className={styles.metricCard}>
                  <div className={styles.metricValue}>{loadTestMetrics.avg_response_time.toFixed(0)}ms</div>
                  <div className={styles.metricLabel}>
                    <Clock size={16} /> Avg Response
                  </div>
                </div>

                <div className={styles.metricCard}>
                  <div className={styles.metricValue}>{loadTestMetrics.failure_rate.toFixed(1)}%</div>
                  <div className={styles.metricLabel}>
                    <AlertCircle size={16} /> Errors
                  </div>
                </div>
              </div>

              <div className={styles.detailMetrics}>
                <div className={styles.statRow}>
                  <span>Total Requests:</span>
                  <strong>{loadTestMetrics.total_requests}</strong>
                </div>
                <div className={styles.statRow}>
                  <span>Total Failures:</span>
                  <strong>{loadTestMetrics.total_failures}</strong>
                </div>
                <div className={styles.statRow}>
                  <span>Min Response Time:</span>
                  <strong>{loadTestMetrics.min_response_time.toFixed(0)}ms</strong>
                </div>
                <div className={styles.statRow}>
                  <span>Max Response Time:</span>
                  <strong>{loadTestMetrics.max_response_time.toFixed(0)}ms</strong>
                </div>
                <div className={styles.statRow}>
                  <span>95th Percentile:</span>
                  <strong>{loadTestMetrics.percentile_95.toFixed(0)}ms</strong>
                </div>
                <div className={styles.statRow}>
                  <span>99th Percentile:</span>
                  <strong>{loadTestMetrics.percentile_99.toFixed(0)}ms</strong>
                </div>
                <div className={styles.statRow}>
                  <span>Elapsed Time:</span>
                  <strong>{loadTestMetrics.elapsed_time.toFixed(1)}s</strong>
                </div>
              </div>
            </>
          ) : (
            <LiveCharts metricsHistory={metricsHistory} />
          )}

          {isLoadTesting && (
            <button className={styles.stopButton} onClick={handleStopTest}>
              <Square size={16} /> Stop Test
            </button>
          )}
        </section>
      )}
    </div>
  );
};
