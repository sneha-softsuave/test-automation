import React, { useState } from 'react';
import { useStore } from '../../store/useStore';
import type { LoadTestConfig } from '../../store/useStore';
import { useLoadTestSSE } from '../../hooks/useLoadTestSSE';
import { LiveCharts } from './LiveCharts';
import type { MetricsHistoryPoint } from './LiveCharts';
import styles from './LoadTestDashboard.module.css';
import { Upload, Play, Square, Zap, Users, TrendingUp, Clock, AlertCircle, BarChart3, Grid3x3, Wrench, CheckCircle, Loader, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';

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
    autoExecuteMode,
    setAutoExecuteMode,
    sequentialTestId,
    setSequentialTestId,
    sequentialTestStatus,
    setSequentialTestStatus,
    selectedApis,
    setSelectedApis,
    loadTestSessionId,
    setLoadTestSessionId,
  } = useStore();

  const [uploadId, setUploadId] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [loadConfig, setLoadConfig] = useState<LoadTestConfig>({
    users: 10,
    spawn_rate: 2,
    run_time: '5m',
  });
  const [viewMode, setViewMode] = useState<'cards' | 'charts'>('cards');
  const [metricsHistory, setMetricsHistory] = useState<MetricsHistoryPoint[]>([]);
  const [expandedApi, setExpandedApi] = useState<string | null>(null);

  // Create or retrieve persistent session ID
  React.useEffect(() => {
    if (!loadTestSessionId) {
      const newSessionId = `loadtest_${Date.now()}`;
      console.log('Creating new persistent session ID:', newSessionId);
      setLoadTestSessionId(newSessionId);
    } else {
      console.log('Using existing session ID:', loadTestSessionId);
    }
  }, []);

  // SSE connection for real-time metrics - uses persistent session ID
  const { messages } = useLoadTestSSE(loadTestSessionId || '', !!loadTestSessionId);

  // Handle SSE messages
  React.useEffect(() => {
    try {
      const latestMessage = messages[messages.length - 1];
      if (!latestMessage) return;

      console.log('SSE Message:', latestMessage.type, latestMessage.data);

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
      // Sequential test events
      case 'sequential_test_started':
        setSequentialTestStatus(latestMessage.data);
        addNotification('success', 'Sequential test started');
        break;
      case 'sequential_api_started':
        if (latestMessage.data) {
          addNotification('info', `Starting: ${latestMessage.data.current_api || 'API'}`);
        }
        break;
      case 'sequential_api_metrics':
        setLoadTestMetrics(latestMessage.data);
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
      case 'sequential_api_completed':
        if (latestMessage.data?.current_api) {
          addNotification('success', `Completed: ${latestMessage.data.current_api}`);
        }
        break;
      case 'sequential_status_update':
        setSequentialTestStatus(latestMessage.data);
        break;
      case 'sequential_test_completed':
        setSequentialTestStatus(latestMessage.data);
        setIsLoadTesting(false);
        setSequentialTestId(null); // Clear ID on completion
        addNotification('success', 'Sequential test completed');
        break;
      case 'sequential_test_stopped':
        console.log('Sequential test stopped event received', latestMessage.data);
        setIsLoadTesting(false);
        setSequentialTestId(null); // Clear ID on stop
        // Update status to stopped but keep everything else
        if (sequentialTestStatus) {
          console.log('Updating sequential status to stopped');
          setSequentialTestStatus({
            ...sequentialTestStatus,
            status: 'stopped'
          });
        }
        // Keep metrics visible so user can see final results
        addNotification('info', 'Sequential test stopped');
        break;
      default:
        console.warn('Unknown SSE message type:', latestMessage.type);
    }
    } catch (error) {
      console.error('Error handling SSE message:', error);
      addNotification('error', 'Error processing server update');
    }
  }, [messages]);

  // Pre-fill form with Excel values when API is selected (manual mode)
  React.useEffect(() => {
    if (!autoExecuteMode && selectedLoadTestApi) {
      // Pre-fill with Excel values if they exist, otherwise use defaults
      setLoadConfig({
        users: selectedLoadTestApi.users || 10,
        spawn_rate: selectedLoadTestApi.spawn_rate || 2,
        run_time: selectedLoadTestApi.run_time || '5m'
      });
    }
  }, [selectedLoadTestApi, autoExecuteMode]);

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    console.log('Uploading file:', file.name, 'Size:', file.size);
    setIsUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      console.log('Sending request to:', `${API_BASE_URL}/api/v1/load-test/upload-excel`);

      const response = await fetch(`${API_BASE_URL}/api/v1/load-test/upload-excel`, {
        method: 'POST',
        body: formData,
      });

      console.log('Response status:', response.status, response.statusText);
      console.log('Response headers:', Object.fromEntries(response.headers.entries()));

      // Check if response has content
      const contentType = response.headers.get('content-type');
      console.log('Content-Type:', contentType);

      if (!response.ok) {
        let errorMessage = 'Failed to upload file';

        // Try to get error from response
        if (contentType && contentType.includes('application/json')) {
          try {
            const error = await response.json();
            errorMessage = error.detail || errorMessage;
          } catch (e) {
            console.error('Failed to parse error JSON:', e);
            errorMessage = `HTTP ${response.status}: ${response.statusText}`;
          }
        } else {
          const text = await response.text();
          console.error('Non-JSON error response:', text);
          errorMessage = text || `HTTP ${response.status}: ${response.statusText}`;
        }

        throw new Error(errorMessage);
      }

      // Parse successful response
      if (!contentType || !contentType.includes('application/json')) {
        console.error('Expected JSON response but got:', contentType);
        const text = await response.text();
        console.error('Response body:', text);
        throw new Error('Server returned invalid response format');
      }

      const data = await response.json();
      console.log('Upload successful:', data);

      setUploadId(data.upload_id);
      setUploadedApis(data.apis);
      addNotification('success', `Parsed ${data.total_apis} APIs successfully`);
    } catch (error) {
      console.error('Upload error:', error);
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
          session_id: loadTestSessionId,
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
    if (!activeLoadTestId) {
      console.warn('No active test ID found');
      addNotification('warning', 'No active test to stop');
      return;
    }

    console.log('Stopping test:', activeLoadTestId);

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/load-test/stop/${activeLoadTestId}`, {
        method: 'POST',
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(errorData.detail || 'Failed to stop test');
      }

      const data = await response.json();
      console.log('Stop response:', data);

      setIsLoadTesting(false);
      setActiveLoadTestId(null);
      addNotification('info', 'Load test stopped successfully');
    } catch (error) {
      console.error('Stop test error:', error);
      addNotification('error', error instanceof Error ? error.message : 'Failed to stop test');
      // Force stop on frontend even if backend fails
      setIsLoadTesting(false);
    }
  };

  const handleStartSequentialTest = async () => {
    if (!uploadId || selectedApis.length === 0) {
      addNotification('error', 'Please select at least one API');
      return;
    }

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/load-test/start-sequential`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          upload_id: uploadId,
          selected_api_names: selectedApis,
          session_id: loadTestSessionId,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to start sequential test');
      }

      const data = await response.json();
      setSequentialTestId(data.sequential_test_id);
      setIsLoadTesting(true);
      setLoadTestMetrics(null);
      setMetricsHistory([]);
      addNotification('success', 'Sequential test started');
    } catch (error) {
      addNotification('error', error instanceof Error ? error.message : 'Failed to start sequential test');
    }
  };

  const handleStopSequentialTest = async () => {
    // Try to get test ID from state or status
    const testIdToStop = sequentialTestId || sequentialTestStatus?.sequential_test_id;

    if (!testIdToStop) {
      console.warn('No sequential test ID found');
      addNotification('warning', 'No sequential test to stop');
      return;
    }

    console.log('Stopping sequential test:', testIdToStop);

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/load-test/stop-sequential/${testIdToStop}`, {
        method: 'POST',
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(errorData.detail || 'Failed to stop sequential test');
      }

      const data = await response.json();
      console.log('Stop sequential response:', data);

      setIsLoadTesting(false);
      setSequentialTestId(null);
      addNotification('info', 'Sequential test stopped');
    } catch (error) {
      console.error('Stop sequential test error:', error);
      addNotification('error', error instanceof Error ? error.message : 'Failed to stop sequential test');
      // Force stop on frontend even if backend fails
      setIsLoadTesting(false);
    }
  };

  const handleRefresh = async () => {
    try {
      // Clear backend upload session if exists
      if (uploadId) {
        console.log('Clearing upload session:', uploadId);
        const response = await fetch(`${API_BASE_URL}/api/v1/load-test/clear-upload/${uploadId}`, {
          method: 'DELETE',
        });

        if (response.ok) {
          console.log('Upload session cleared from backend');
        } else {
          console.warn('Failed to clear upload session from backend');
        }
      }
    } catch (error) {
      console.error('Error clearing upload session:', error);
      // Continue with frontend refresh even if backend clear fails
    }

    // Reset all state to initial values
    setUploadedApis([]);
    setUploadId(null);
    setSelectedLoadTestApi(null);
    setLoadTestMetrics(null);
    setIsLoadTesting(false);
    setActiveLoadTestId(null);
    setSequentialTestId(null);
    setSequentialTestStatus(null);
    setSelectedApis([]);
    setMetricsHistory([]);
    setExpandedApi(null);
    setLoadConfig({
      users: 10,
      spawn_rate: 2,
      run_time: '5m',
    });

    // Also reset the file input
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    if (fileInput) {
      fileInput.value = '';
    }

    addNotification('success', 'Load test page refreshed');
  };

  const handleApiSelect = (apiName: string) => {
    if (autoExecuteMode) {
      // Checkbox behavior for auto mode
      if (selectedApis.includes(apiName)) {
        setSelectedApis(selectedApis.filter((name) => name !== apiName));
      } else {
        setSelectedApis([...selectedApis, apiName]);
      }
    } else {
      // Radio behavior for manual mode
      const api = uploadedApis?.find((a) => a.name === apiName);
      if (api) {
        setSelectedLoadTestApi(api);
        // Pre-fill config from Excel if available
        if (api.users || api.spawn_rate || api.run_time) {
          setLoadConfig({
            users: api.users || 10,
            spawn_rate: api.spawn_rate || 2,
            run_time: api.run_time || '5m',
          });
        }
      }
    }
  };

  const totalApis = uploadedApis?.length || 0;
  const testsRun = 0; // TODO: Track from history
  const totalRequests = loadTestMetrics?.total_requests || 0;

  return (
    <div className={styles.dashboard}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.titleSection}>
          <Zap size={32} className={styles.icon} />
          <div>
            <h1>Load Test Dashboard</h1>
            <p>Upload Excel → Select API → Configure → Run Load Test</p>
          </div>
        </div>
        <button
          className={styles.refreshButton}
          onClick={handleRefresh}
          title="Refresh Load Test Page"
          disabled={isLoadTesting}
        >
          <RefreshCw size={18} />
          <span>Refresh</span>
        </button>
      </header>

      {/* Split View Container */}
      <div className={styles.splitContainer}>
        {/* LEFT PANEL */}
        <div className={styles.leftPanel}>
          {/* Auto-Execute Mode Toggle */}
          <section className={styles.section}>
            <div className={styles.toggleRow}>
              <Wrench size={18} />
              <span className={styles.toggleLabel}>Auto Execute Mode</span>
              <label className={styles.switch}>
                <input
                  type="checkbox"
                  checked={autoExecuteMode}
                  onChange={(e) => {
                    setAutoExecuteMode(e.target.checked);
                    setSelectedApis([]);
                    setSelectedLoadTestApi(null);
                  }}
                  disabled={isLoadTesting}
                />
                <span className={styles.slider}></span>
              </label>
              <span className={styles.modeHint}>
                {autoExecuteMode
                  ? 'Auto mode: Load config from Excel, run multiple APIs sequentially'
                  : 'Manual mode: Enter config manually, run single API'}
              </span>
            </div>
          </section>

          {/* Upload API Configuration */}
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

          {/* API List - Swagger Style */}
          {uploadedApis && uploadedApis.length > 0 && (
            <section className={styles.section}>
              <h2>Select API{autoExecuteMode && 's'}</h2>
              <div className={styles.apiList}>
                {uploadedApis.map((api) => {
                  const isSelected = autoExecuteMode
                    ? selectedApis.includes(api.name)
                    : selectedLoadTestApi?.name === api.name;
                  const isExpanded = expandedApi === api.name;

                  return (
                    <div key={api.name} className={styles.apiListItemWrapper}>
                      <div
                        className={`${styles.apiListItem} ${isSelected ? styles.selected : ''}`}
                        onClick={() => handleApiSelect(api.name)}
                      >
                        {/* Checkbox or Radio */}
                        <input
                          type={autoExecuteMode ? 'checkbox' : 'radio'}
                          checked={isSelected}
                          readOnly
                          className={styles.selectInput}
                        />

                        {/* Method Badge */}
                        <div className={`${styles.methodBadge} ${styles[api.method.toLowerCase()]}`}>
                          {api.method}
                        </div>

                        {/* API Info */}
                        <div className={styles.apiInfo}>
                          <div className={styles.apiName}>{api.name}</div>
                          <div className={styles.apiEndpoint}>{api.endpoint}</div>
                        </div>

                        {/* Config Badges */}
                        <div className={styles.configBadges}>
                          <span className={styles.badge}>
                            <Users size={14} /> {api.users || 10}
                          </span>
                          <span className={styles.badge}>
                            <TrendingUp size={14} /> {api.spawn_rate || 2}/s
                          </span>
                          <span className={styles.badge}>
                            <Clock size={14} /> {api.run_time || '5m'}
                          </span>
                        </div>

                        {/* Expand Button */}
                        <button
                          className={styles.expandBtn}
                          onClick={(e) => {
                            e.stopPropagation();
                            setExpandedApi(isExpanded ? null : api.name);
                          }}
                        >
                          {isExpanded ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
                        </button>
                      </div>

                      {/* Expanded Details */}
                      {isExpanded && (
                        <div className={styles.apiDetails}>
                          <div className={styles.detailRow}>
                            <strong>Base URL:</strong> <span>{api.base_url}</span>
                          </div>
                          <div className={styles.detailRow}>
                            <strong>Full Endpoint:</strong> <span>{api.base_url}{api.endpoint}</span>
                          </div>
                          <div className={styles.detailRow}>
                            <strong>Method:</strong> <span>{api.method}</span>
                          </div>
                          {api.headers && Object.keys(api.headers).length > 0 && (
                            <div className={styles.detailRow}>
                              <strong>Headers:</strong>
                              <pre className={styles.codeBlock}>
                                {JSON.stringify(api.headers, null, 2)}
                              </pre>
                            </div>
                          )}
                          {api.payload && (
                            <div className={styles.detailRow}>
                              <strong>Payload:</strong>
                              <pre className={styles.codeBlock}>
                                {JSON.stringify(api.payload, null, 2)}
                              </pre>
                            </div>
                          )}
                          <div className={styles.detailRow}>
                            <strong>Auth Type:</strong> <span>{api.auth_config.auth_type}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Sequential Test Button for Auto Mode */}
              {autoExecuteMode && selectedApis.length > 0 && (
                <div className={styles.sequentialActions}>
                  <div className={styles.selectedInfo}>
                    <CheckCircle size={18} />
                    <span>{selectedApis.length} API{selectedApis.length > 1 ? 's' : ''} selected</span>
                  </div>
                  {!isLoadTesting ? (
                    <button className={styles.startButton} onClick={handleStartSequentialTest}>
                      <Play size={16} /> Start Sequential Test
                    </button>
                  ) : (
                    <button className={styles.stopButton} onClick={handleStopSequentialTest}>
                      <Square size={16} /> Stop Sequential Test
                    </button>
                  )}
                </div>
              )}
            </section>
          )}
        </div>

        {/* RIGHT PANEL */}
        <div className={styles.rightPanel}>
          {/* Welcome / Config / Metrics */}
          {!selectedLoadTestApi && !loadTestMetrics && !isLoadTesting && selectedApis.length === 0 && (
            <div className={styles.welcomeSection}>
              <div className={styles.welcomeIcon}>
                <Zap size={64} />
              </div>
              <h2>Welcome to Load Testing</h2>
              <p>Upload your API configuration Excel file to get started with load testing</p>

              <div className={styles.statsGrid}>
                <div className={styles.statCard}>
                  <BarChart3 size={32} />
                  <div className={styles.statValue}>{totalApis}</div>
                  <div className={styles.statLabel}>APIs Loaded</div>
                </div>
                <div className={styles.statCard}>
                  <Zap size={32} />
                  <div className={styles.statValue}>{testsRun}</div>
                  <div className={styles.statLabel}>Tests Run</div>
                </div>
                <div className={styles.statCard}>
                  <CheckCircle size={32} />
                  <div className={styles.statValue}>{totalRequests}</div>
                  <div className={styles.statLabel}>Requests</div>
                </div>
              </div>

              <div className={styles.quickStart}>
                <h3>🚀 Quick Start</h3>
                <ol>
                  <li>Upload Excel with API configurations</li>
                  <li>Select API(s) to test</li>
                  <li>Configure load parameters</li>
                  <li>Run test and monitor live metrics</li>
                </ol>
                <div className={styles.proTip}>
                  <AlertCircle size={16} />
                  <span>
                    <strong>Pro Tip:</strong> Use Auto-Execute mode to run multiple APIs sequentially with configs from Excel
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Auto Mode - Selected APIs Preview */}
          {autoExecuteMode && selectedApis.length > 0 && !isLoadTesting && !loadTestMetrics && (
            <div className={styles.autoPreviewSection}>
              <h2>Ready to Start Sequential Test</h2>
              <p className={styles.configSubtitle}>
                {selectedApis.length} API{selectedApis.length > 1 ? 's' : ''} will be tested sequentially using configuration from Excel
              </p>

              <div className={styles.selectedApisList}>
                {uploadedApis?.filter(api => selectedApis.includes(api.name)).map((api, index) => (
                  <div key={api.name} className={styles.selectedApiItem}>
                    <div className={styles.apiNumber}>{index + 1}</div>
                    <div className={styles.apiItemContent}>
                      <div className={`${styles.methodBadge} ${styles[api.method.toLowerCase()]}`}>
                        {api.method}
                      </div>
                      <div className={styles.apiItemInfo}>
                        <div className={styles.apiItemName}>{api.name}</div>
                        <div className={styles.apiItemEndpoint}>{api.endpoint}</div>
                      </div>
                      <div className={styles.apiItemConfig}>
                        <span className={styles.configItem}>
                          <Users size={14} /> {api.users || 10}
                        </span>
                        <span className={styles.configItem}>
                          <TrendingUp size={14} /> {api.spawn_rate || 2}/s
                        </span>
                        <span className={styles.configItem}>
                          <Clock size={14} /> {api.run_time || '5m'}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <div className={styles.testSummary}>
                <div className={styles.summaryItem}>
                  <strong>Total APIs:</strong> {selectedApis.length}
                </div>
                <div className={styles.summaryItem}>
                  <strong>Execution:</strong> Sequential (one after another)
                </div>
                <div className={styles.summaryItem}>
                  <strong>Config Source:</strong> Excel (or defaults)
                </div>
              </div>

              <button className={styles.startButton} onClick={handleStartSequentialTest}>
                <Play size={16} /> Start Sequential Test
              </button>
            </div>
          )}

          {/* Config Form - Manual Mode */}
          {!autoExecuteMode && selectedLoadTestApi && !isLoadTesting && (
            <div className={styles.configSection}>
              <h2>Load Test Configuration</h2>
              <p className={styles.configSubtitle}>
                {selectedLoadTestApi.users ? 'Pre-filled from Excel (editable)' : 'Default values (editable)'}
              </p>

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
                />
              </div>

              <button className={styles.startButton} onClick={handleStartTest}>
                <Play size={16} /> Start Load Test
              </button>
            </div>
          )}

          {/* Live Metrics */}
          {(isLoadTesting || loadTestMetrics) && (
            <div className={styles.metricsSection}>
              <div className={styles.metricsHeader}>
                <h2>
                  Live Metrics & Results
                  {isLoadTesting && <span className={styles.statusRunning}>● Running</span>}
                  {!isLoadTesting && loadTestMetrics && (
                    <span className={styles.statusCompleted}>● Completed</span>
                  )}
                </h2>
                {isLoadTesting && (
                  <button
                    className={styles.stopButton}
                    onClick={autoExecuteMode && (sequentialTestId || sequentialTestStatus) ? handleStopSequentialTest : handleStopTest}
                  >
                    <Square size={16} /> Stop Test
                  </button>
                )}
              </div>

              {/* Sequential Progress */}
              {sequentialTestStatus && (
                <div className={styles.sequentialProgress}>
                  <div className={styles.progressHeader}>
                    <Loader size={20} className={sequentialTestStatus.status === 'running' ? styles.spinning : ''} />
                    <span>Sequential Test Progress</span>
                  </div>

                  <div className={styles.progressBar}>
                    <div
                      className={styles.progressFill}
                      style={{
                        width: `${(((sequentialTestStatus.current_index || 0) + 1) / (sequentialTestStatus.total_apis || 1)) * 100}%`
                      }}
                    />
                  </div>

                  <div className={styles.progressStats}>
                    <div>
                      <strong>Status:</strong> {sequentialTestStatus.status?.toUpperCase() || 'UNKNOWN'}
                    </div>
                    <div>
                      <strong>Progress:</strong> {(sequentialTestStatus.current_index || 0) + 1} of {sequentialTestStatus.total_apis || 0}
                    </div>
                    {sequentialTestStatus.current_api && (
                      <div>
                        <strong>Current:</strong> {sequentialTestStatus.current_api}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* View Toggle */}
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

              {/* Metrics Display */}
              {viewMode === 'cards' && loadTestMetrics && (
                <>
                  {/* Top Gradient Cards */}
                  <div className={styles.metricsGrid}>
                    <div className={`${styles.metricCard} ${styles.purpleGradient}`}>
                      <div className={styles.metricValue}>{loadTestMetrics.current_users || 0}</div>
                      <div className={styles.metricLabel}>
                        <Users size={16} /> Users
                      </div>
                    </div>

                    <div className={`${styles.metricCard} ${styles.pinkGradient}`}>
                      <div className={styles.metricValue}>
                        {(loadTestMetrics.requests_per_second || 0).toFixed(1)}
                      </div>
                      <div className={styles.metricLabel}>
                        <TrendingUp size={16} /> RPS
                      </div>
                    </div>

                    <div className={`${styles.metricCard} ${styles.cyanGradient}`}>
                      <div className={styles.metricValue}>
                        {(loadTestMetrics.avg_response_time || 0).toFixed(0)}ms
                      </div>
                      <div className={styles.metricLabel}>
                        <Clock size={16} /> Avg Response
                      </div>
                    </div>

                    <div className={`${styles.metricCard} ${styles.greenGradient}`}>
                      <div className={styles.metricValue}>
                        {(loadTestMetrics.failure_rate || 0).toFixed(1)}%
                      </div>
                      <div className={styles.metricLabel}>
                        <AlertCircle size={16} /> Errors
                      </div>
                    </div>
                  </div>

                  {/* Detailed Stats Table */}
                  <div className={styles.detailedStats}>
                    <div className={styles.statRow}>
                      <span className={styles.statLabel}>Total Requests:</span>
                      <span className={styles.statValue}>{loadTestMetrics.total_requests || 0}</span>
                    </div>
                    <div className={styles.statRow}>
                      <span className={styles.statLabel}>Total Failures:</span>
                      <span className={styles.statValue}>{loadTestMetrics.total_failures || 0}</span>
                    </div>
                    <div className={styles.statRow}>
                      <span className={styles.statLabel}>Min Response Time:</span>
                      <span className={styles.statValue}>{(loadTestMetrics.min_response_time || 0).toFixed(0)}ms</span>
                    </div>
                    <div className={styles.statRow}>
                      <span className={styles.statLabel}>Max Response Time:</span>
                      <span className={styles.statValue}>{(loadTestMetrics.max_response_time || 0).toFixed(0)}ms</span>
                    </div>
                    <div className={styles.statRow}>
                      <span className={styles.statLabel}>95th Percentile:</span>
                      <span className={styles.statValue}>{(loadTestMetrics.percentile_95 || 0).toFixed(0)}ms</span>
                    </div>
                    <div className={styles.statRow}>
                      <span className={styles.statLabel}>99th Percentile:</span>
                      <span className={styles.statValue}>{(loadTestMetrics.percentile_99 || 0).toFixed(0)}ms</span>
                    </div>
                    <div className={styles.statRow}>
                      <span className={styles.statLabel}>Elapsed Time:</span>
                      <span className={styles.statValue}>{(loadTestMetrics.elapsed_time || 0).toFixed(1)}s</span>
                    </div>
                  </div>

                  {/* Active Test ID */}
                  {(activeLoadTestId || sequentialTestId) && (
                    <div className={styles.testIdBox}>
                      <span className={styles.testIdLabel}>Active Test ID:</span>
                      <span className={styles.testIdValue}>{activeLoadTestId || sequentialTestId}</span>
                    </div>
                  )}
                </>
              )}

              {viewMode === 'charts' && metricsHistory.length > 0 && (
                <LiveCharts metricsHistory={metricsHistory} />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
