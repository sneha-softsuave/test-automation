import React, { useState } from 'react';
import { useStore, type LLMProvider } from '../../store/useStore';
import type { LoadTestConfig } from '../../store/useStore';
import { useLoadTestSSE } from '../../hooks/useLoadTestSSE';
import { LiveCharts } from './LiveCharts';
import type { MetricsHistoryPoint } from './LiveCharts';
import styles from './LoadTestDashboard.module.css';
import { Upload, Play, Square, Zap, Users, TrendingUp, Clock, AlertCircle, BarChart3, Grid3x3, Wrench, CheckCircle, Loader, ChevronDown, ChevronRight, RefreshCw, Brain, Activity, Gauge, Server, Network, FileUp, MousePointerClick, Settings, Rocket } from 'lucide-react';

// Use relative URL to leverage Vite proxy
const API_BASE_URL = '';

export const LoadTestDashboard: React.FC = () => {
  const {
    uploadId,
    setUploadId,
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
    lastCompletedTestId,
    setLastCompletedTestId,
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
    llmProvider,
    setLlmProvider,
    aiSuggestedConfig,
    setAiSuggestedConfig,
    addTerminalLog,
  } = useStore();
  const [isUploading, setIsUploading] = useState(false);
  const [loadConfig, setLoadConfig] = useState<LoadTestConfig>({ users: 10, spawn_rate: 2, run_time: '5m' });
  const [viewMode, setViewMode] = useState<'cards' | 'charts'>('cards');
  const [metricsHistory, setMetricsHistory] = useState<MetricsHistoryPoint[]>([]);
  const [expandedApi, setExpandedApi] = useState<string | null>(null);
  const [aiMode, setAiMode] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [aiRecommendations, setAiRecommendations] = useState<any>(null);
  const [useAiTestData, setUseAiTestData] = useState(true); // Toggle for AI test data

  // Batch AI analysis states (for sequential mode)
  const [batchAiRecommendations, setBatchAiRecommendations] = useState<any>(null);
  const [isAnalyzingBatch, setIsAnalyzingBatch] = useState(false);
  const [expandedBatchApi, setExpandedBatchApi] = useState<string | null>(null);
  const [useBatchAiTestData, setUseBatchAiTestData] = useState(false); // Common toggle - default OFF
  const [batchApiTestDataOverrides, setBatchApiTestDataOverrides] = useState<Record<string, boolean>>({}); // Per-API overrides

  // Custom Suggestions states (NEW)
  const [showSuggestionsInput, setShowSuggestionsInput] = useState(false);
  const [customSuggestions, setCustomSuggestions] = useState('');
  const [showBatchSuggestionsInput, setShowBatchSuggestionsInput] = useState(false);
  const [customBatchSuggestions, setCustomBatchSuggestions] = useState('');

  // Test Data Expansion states
  const [showTestDataSingle, setShowTestDataSingle] = useState(false); // For single API mode
  const [expandedTestDataBatch, setExpandedTestDataBatch] = useState<Record<string, boolean>>({}); // For batch mode (per API)

  // Batch edit state — per-API overrides for sequential mode
  // Key: api.name, Value: partial edits merged on top of the Excel config
  const [batchExpandedEdit, setBatchExpandedEdit] = useState<Record<string, boolean>>({}); // collapsed by default
  type BatchEditFields = { users: string; spawn_rate: string; run_time: string; payload: string; headers: string };
  const [batchEditValues, setBatchEditValues] = useState<Record<string, BatchEditFields>>({}); // per-API edited values

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
        // Set the last completed test ID for reports/insights
        if (activeLoadTestId) {
          setLastCompletedTestId(activeLoadTestId);
        }
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
      case 'terminal_log':
        // Capture terminal logs as soon as they arrive
        if (latestMessage.data?.log) {
          addTerminalLog({
            timestamp: latestMessage.data.timestamp || new Date().toISOString(),
            log: latestMessage.data.log
          });
        }
        break;
      // Sequential test events
      case 'sequential_test_started':
        setSequentialTestStatus(latestMessage.data);
        addNotification('success', 'Sequential test started');
        break;
      case 'sequential_api_started':
        // sequential_status_update fires right before this with the correct full payload.
        // Don't overwrite it — this event uses different field names (api_index/api_name)
        // that don't match SequentialTestStatus shape.
        addNotification('info', `Starting: ${latestMessage.data?.api_name || latestMessage.data?.current_api || 'API'}`);
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
        // Set the last completed test ID for reports/insights
        if (sequentialTestId) {
          setLastCompletedTestId(sequentialTestId);
        }
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

  // Track if AI config was applied so pre-fill effect skips its first run
  const aiAppliedAtMount = React.useRef(false);

  // useLayoutEffect runs synchronously before paint and before useEffect.
  // Apply AI suggested config here so it wins over the pre-fill useEffect.
  React.useLayoutEffect(() => {
    if (!aiSuggestedConfig) return;
    aiAppliedAtMount.current = true;
    setLoadConfig({
      users: aiSuggestedConfig.users ?? 10,
      spawn_rate: aiSuggestedConfig.spawn_rate ?? 2,
      run_time: aiSuggestedConfig.run_time ?? '5m',
    });
    setAiSuggestedConfig(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // After AI config is applied, show notification
  React.useEffect(() => {
    if (aiAppliedAtMount.current) {
      addNotification('success', `✨ AI-suggested values applied`);
      setTimeout(() => {
        document.getElementById('load-test-config')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 300);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pre-fill form with Excel values when API is selected (manual mode).
  // Skipped on the first run if AI config was applied at mount.
  React.useEffect(() => {
    if (aiAppliedAtMount.current) {
      aiAppliedAtMount.current = false;
      return;
    }
    if (!autoExecuteMode && selectedLoadTestApi) {
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
          selected_api: selectedLoadTestApi, // Send full API object with user edits
          config: loadConfig,
          session_id: loadTestSessionId,
          llm_provider: llmProvider, // Send LLM provider for auto AI insights
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

    // Build edited API configs to send to backend
    const selectedApisConfig = uploadedApis
      ?.filter(api => selectedApis.includes(api.name))
      .map(api => {
        const edits = batchEditValues[api.name];
        if (!edits) return api;
        // Parse edited JSON fields safely
        let parsedPayload = api.payload;
        if (edits.payload.trim()) {
          try { parsedPayload = JSON.parse(edits.payload); } catch { /* keep original */ }
        }
        let parsedHeaders = api.headers;
        if (edits.headers.trim()) {
          try { parsedHeaders = JSON.parse(edits.headers); } catch { /* keep original */ }
        }
        return {
          ...api,
          users: Number(edits.users) || api.users || 10,
          spawn_rate: Number(edits.spawn_rate) || api.spawn_rate || 2,
          run_time: edits.run_time || api.run_time || '5m',
          payload: parsedPayload,
          headers: parsedHeaders,
        };
      }) ?? [];

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/load-test/start-sequential`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          upload_id: uploadId,
          selected_api_names: selectedApis,
          selected_apis_config: selectedApisConfig,
          session_id: loadTestSessionId,
          llm_provider: llmProvider,
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

  // Helper function to format data mode for display
  const formatDataMode = (mode: string) => {
    return mode
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
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

  // Seed batch edit values for an API from its Excel config (called when API is checked)
  const seedBatchEditValues = (api: typeof uploadedApis extends (infer T)[] | null ? T : never) => {
    if (!api) return;
    setBatchEditValues(prev => ({
      ...prev,
      [api.name]: {
        users: String(api.users ?? 10),
        spawn_rate: String(api.spawn_rate ?? 2),
        run_time: api.run_time ?? '5m',
        payload: api.payload ? JSON.stringify(api.payload, null, 2) : '',
        headers: api.headers && Object.keys(api.headers).length > 0
          ? JSON.stringify(api.headers, null, 2)
          : '',
      },
    }));
  };

  const handleApiSelect = (apiName: string) => {
    if (autoExecuteMode) {
      // Checkbox behavior for auto mode
      if (selectedApis.includes(apiName)) {
        setSelectedApis(selectedApis.filter((name) => name !== apiName));
        // Clean up edit state for deselected API
        setBatchEditValues(prev => { const n = { ...prev }; delete n[apiName]; return n; });
        setBatchExpandedEdit(prev => { const n = { ...prev }; delete n[apiName]; return n; });
      } else {
        setSelectedApis([...selectedApis, apiName]);
        // Seed edit values from Excel config
        const api = uploadedApis?.find(a => a.name === apiName);
        if (api) seedBatchEditValues(api);
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

  const handleAiAnalysis = async () => {
    if (!uploadId || !selectedLoadTestApi) {
      addNotification('error', 'Please select an API first');
      return;
    }

    setIsAnalyzing(true);

    // Show notification based on whether suggestions are provided
    const notificationMsg = customSuggestions.trim()
      ? '🤖 AI is analyzing with your custom suggestions...'
      : '🤖 AI is analyzing your API...';
    addNotification('info', notificationMsg);

    try {
      const url = `${API_BASE_URL}/api/v1/load-test/agentic-analyze?upload_id=${uploadId}&api_name=${encodeURIComponent(selectedLoadTestApi.name)}&llm_provider=${llmProvider}`;

      const requestOptions: RequestInit = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      };

      // Add suggestions to request body if provided
      if (customSuggestions.trim()) {
        requestOptions.body = JSON.stringify({
          custom_suggestions: customSuggestions.trim()
        });
      }

      const response = await fetch(url, requestOptions);

      if (!response.ok) {
        throw new Error('AI analysis failed');
      }

      const data = await response.json();
      setAiRecommendations(data);

      addNotification('success', `✅ AI detected ${data.api_type} API and generated recommendations!`);
    } catch (error) {
      console.error('AI analysis error:', error);
      addNotification('error', 'AI analysis failed. Please try again.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleApplyRecommendations = async () => {
    if (!uploadId || !selectedLoadTestApi || !aiRecommendations) {
      console.log('❌ Missing required data for apply recommendations');
      return;
    }

    // Prepare recommendations based on toggle
    const recommendationsToApply = {
      ...aiRecommendations.recommendations,
    };

    // If toggle is OFF, remove test_data key entirely (to preserve Excel data)
    if (!useAiTestData) {
      delete recommendationsToApply.test_data;
    }

    console.log('✨ Applying recommendations:', recommendationsToApply);
    console.log(`   Test Data Mode: ${useAiTestData ? 'AI-Generated' : 'Excel Data (preserve existing)'}`);

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/load-test/agentic-apply?upload_id=${uploadId}&api_name=${encodeURIComponent(selectedLoadTestApi.name)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ recommendations: recommendationsToApply })
        }
      );

      if (!response.ok) {
        throw new Error('Failed to apply recommendations');
      }

      const data = await response.json();
      const updatedApi = data.api;

      console.log('✅ Updated API received:', updatedApi);
      console.log('   • Users:', updatedApi.users);
      console.log('   • Spawn Rate:', updatedApi.spawn_rate);
      console.log('   • Run Time:', updatedApi.run_time);

      // Update local state
      if (uploadedApis) {
        const updatedApis = uploadedApis.map(api =>
          api.name === selectedLoadTestApi.name ? updatedApi : api
        );
        setUploadedApis(updatedApis);
        setSelectedLoadTestApi(updatedApi);
      }

      // Update load config with explicit values
      const newConfig = {
        users: updatedApi.users || aiRecommendations.recommendations.users || 10,
        spawn_rate: updatedApi.spawn_rate || aiRecommendations.recommendations.spawn_rate || 2,
        run_time: updatedApi.run_time || '5m'
      };

      console.log('📝 Setting new load config:', newConfig);
      setLoadConfig(newConfig);

      // Force a small delay to ensure state updates
      setTimeout(() => {
        console.log('🔄 Load config after update:', loadConfig);
      }, 100);

      const dataSourceMsg = useAiTestData
        ? 'Using AI-generated test data'
        : 'Using Excel test data';
      addNotification('success', `✅ AI recommendations applied! ${dataSourceMsg}.`);
    } catch (error) {
      console.error('Apply recommendations error:', error);
      addNotification('error', 'Failed to apply recommendations');
    }
  };

  const handleBatchAiAnalysis = async () => {
    if (!uploadId || selectedApis.length === 0) {
      addNotification('error', 'Please select at least one API');
      return;
    }

    setIsAnalyzingBatch(true);

    // Show notification based on whether suggestions are provided
    const notificationMsg = customBatchSuggestions.trim()
      ? `🤖 AI is analyzing ${selectedApis.length} APIs with your custom suggestions...`
      : `🤖 AI is analyzing ${selectedApis.length} APIs...`;
    addNotification('info', notificationMsg);

    try {
      const requestBody: any = {
        upload_id: uploadId,
        api_names: selectedApis,
        llm_provider: llmProvider
      };

      // Add suggestions if provided
      if (customBatchSuggestions.trim()) {
        requestBody.custom_suggestions = customBatchSuggestions.trim();
      }

      const response = await fetch(
        `${API_BASE_URL}/api/v1/load-test/agentic-analyze-batch`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody)
        }
      );

      if (!response.ok) {
        throw new Error('Batch AI analysis failed');
      }

      const data = await response.json();
      setBatchAiRecommendations(data);

      addNotification('success', `✅ AI analyzed ${data.total_apis} APIs successfully!`);
    } catch (error) {
      console.error('Batch AI analysis error:', error);
      addNotification('error', 'Batch AI analysis failed. Please try again.');
    } finally {
      setIsAnalyzingBatch(false);
    }
  };

  const handleApplyBatchRecommendations = async () => {
    if (!batchAiRecommendations || !uploadId) {
      addNotification('error', 'No recommendations to apply');
      return;
    }

    addNotification('info', 'Applying recommendations to all selected APIs...');

    try {
      // Prepare API configs with toggle states
      const apisToApply = batchAiRecommendations.results.map((result: any) => ({
        api_name: result.api_name,
        use_ai_test_data: shouldUseAiTestData(result.api_name),
        recommendations: result.recommendations
      }));

      const response = await fetch(
        `${API_BASE_URL}/api/v1/load-test/agentic-apply-batch?upload_id=${uploadId}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ apis: apisToApply })
        }
      );

      if (!response.ok) {
        throw new Error('Failed to apply batch recommendations');
      }

      const data = await response.json();

      // Update local state with updated APIs
      if (uploadedApis) {
        const updatedApisMap = new Map(data.updated_apis.map((api: any) => [api.name, api]));
        const newUploadedApis = uploadedApis.map(api =>
          updatedApisMap.has(api.name) ? updatedApisMap.get(api.name)! : api
        );
        setUploadedApis(newUploadedApis as any);
      }

      addNotification('success', `✅ Applied recommendations to ${data.total_updated} APIs!`);
    } catch (error) {
      console.error('Apply batch recommendations error:', error);
      addNotification('error', 'Failed to apply recommendations. Please try again.');
    }
  };

  const handleReanalyzeBatch = () => {
    setBatchAiRecommendations(null);
    handleBatchAiAnalysis();
  };

  const toggleBatchApiExpansion = (apiName: string) => {
    setExpandedBatchApi(expandedBatchApi === apiName ? null : apiName);
  };

  const toggleBatchApiTestData = (apiName: string, currentValue: boolean) => {
    setBatchApiTestDataOverrides(prev => ({
      ...prev,
      [apiName]: !currentValue
    }));
  };

  // Determine if a specific API should use AI test data
  const shouldUseAiTestData = (apiName: string): boolean => {
    // If API has a specific override, use that
    if (apiName in batchApiTestDataOverrides) {
      return batchApiTestDataOverrides[apiName];
    }
    // Otherwise, use the common toggle value
    return useBatchAiTestData;
  };

  const totalApis = uploadedApis?.length || 0;
  const testsRun = 0; // TODO: Track from history
  const totalRequests = loadTestMetrics?.total_requests || 0;

  // Determine current step for breadcrumb highlighting
  const getCurrentStep = () => {
    if (isLoadTesting) return 4; // Run Load Test
    if (selectedLoadTestApi || selectedApis.length > 0) return 3; // Configure
    if (uploadedApis && uploadedApis.length > 0) return 2; // Select API
    return 1; // Upload Excel
  };

  const currentStep = getCurrentStep();

  // Check if test has completed (has metrics but not currently running)
  const testCompleted = !isLoadTesting && (loadTestMetrics !== null || lastCompletedTestId !== null);

  return (
    <div className={styles.dashboard}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.titleSection}>
          <Zap size={32} className={styles.icon} />
          <div>
            <h1>Load Test Dashboard</h1>
            {/* Dynamic Breadcrumb */}
            <div className={styles.breadcrumb}>
              <div className={`${styles.breadcrumbStep} ${!testCompleted && currentStep === 1 ? styles.active : ''} ${currentStep > 1 || testCompleted ? styles.completed : ''}`}>
                <FileUp size={14} />
                <span>Upload Excel</span>
              </div>
              <span className={`${styles.breadcrumbArrow} ${testCompleted ? styles.completed : ''}`}>→</span>
              <div className={`${styles.breadcrumbStep} ${!testCompleted && currentStep === 2 ? styles.active : ''} ${currentStep > 2 || testCompleted ? styles.completed : ''}`}>
                <MousePointerClick size={14} />
                <span>Select API</span>
              </div>
              <span className={`${styles.breadcrumbArrow} ${testCompleted ? styles.completed : ''}`}>→</span>
              <div className={`${styles.breadcrumbStep} ${!testCompleted && currentStep === 3 ? styles.active : ''} ${currentStep > 3 || testCompleted ? styles.completed : ''}`}>
                <Settings size={14} />
                <span>Configure</span>
              </div>
              <span className={`${styles.breadcrumbArrow} ${testCompleted ? styles.completed : ''}`}>→</span>
              <div className={`${styles.breadcrumbStep} ${!testCompleted && currentStep === 4 ? styles.active : ''} ${testCompleted ? styles.completed : ''}`}>
                <Rocket size={14} />
                <span>Run Load Test</span>
              </div>
            </div>
          </div>
        </div>
        <div className={styles.headerActions}>
          {/* AI Provider Selector */}
          <div className={styles.llmSelector}>
            <Brain size={16} />
            <select
              value={llmProvider}
              onChange={(e) => setLlmProvider(e.target.value as LLMProvider)}
              className={styles.llmSelect}
              disabled={isLoadTesting}
              title="Select AI Provider for Analysis"
            >
              <option value="groq">Groq (Fast)</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </div>
          <button
            className={styles.refreshButton}
            onClick={handleRefresh}
            title="Refresh Load Test Page"
            disabled={isLoadTesting}
          >
            <RefreshCw size={18} />
          </button>
        </div>
      </header>

      {/* Split View Container */}
      <div className={styles.splitContainer}>
        {/* LEFT PANEL */}
        <div className={styles.leftPanel}>
          {/* Scrollable API List Card (Top) */}
          <section className={styles.apiListCard}>
            {!uploadedApis || uploadedApis.length === 0 ? (
              // Empty state with load test animation
              <div className={styles.emptyState}>
                <div className={styles.loadTestVisual}>
                  <div className={styles.loadTestOrbit}>
                    <div className={styles.orbitRing} />
                    <div className={styles.orbitRing} style={{ animationDelay: '-2s' }} />
                    <div className={styles.orbitCenter}>
                      <Zap size={32} />
                    </div>
                    <div className={styles.orbitDot} style={{ animationDelay: '0s' }}><Activity size={14} /></div>
                    <div className={styles.orbitDot} style={{ animationDelay: '-2s' }}><Gauge size={14} /></div>
                    <div className={styles.orbitDot} style={{ animationDelay: '-4s' }}><Server size={14} /></div>
                    <div className={styles.orbitDot} style={{ animationDelay: '-6s' }}><Network size={14} /></div>
                  </div>
                </div>
                <p className={styles.emptyTitle}>No APIs loaded yet</p>
                <p className={styles.emptySubtitle}>Upload an Excel file to see your APIs</p>
              </div>
            ) : (
              // API list (existing logic)
              <>
                <h2>Select API{autoExecuteMode && 's'}</h2>
                <div className={styles.apiList}>
                {uploadedApis.map((api) => {
                  const isSelected = autoExecuteMode
                    ? selectedApis.includes(api.name)
                    : selectedLoadTestApi?.name === api.name;
                  const isExpanded = expandedApi === api.name;

                  // Check if this API is currently executing
                  const isExecuting = autoExecuteMode
                    ? (
                        sequentialTestStatus?.status === 'running' && (
                          sequentialTestStatus.current_api === api.name ||
                          // If current_api is not set yet, check if this is the first API
                          (!sequentialTestStatus.current_api && sequentialTestStatus.apis?.[0] === api.name)
                        )
                      )
                    : (isLoadTesting && selectedLoadTestApi?.name === api.name);

                  return (
                    <div key={api.name} className={styles.apiListItemWrapper}>
                      <div
                        className={`${styles.apiListItem} ${isSelected ? styles.selected : ''} ${isExecuting ? styles.executingApi : ''}`}
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

                          {/* Editable Headers */}
                          <div className={styles.detailRow}>
                            <strong>Headers:</strong>
                            <textarea
                              className={styles.editableCodeBlock}
                              rows={3}
                              value={JSON.stringify(api.headers || {}, null, 2)}
                              onChange={(e) => {
                                if (!uploadedApis) return;
                                try {
                                  const parsed = JSON.parse(e.target.value);
                                  const updatedApis = uploadedApis.map(a =>
                                    a.name === api.name ? { ...a, headers: parsed } : a
                                  );
                                  setUploadedApis(updatedApis);
                                  if (selectedLoadTestApi?.name === api.name) {
                                    setSelectedLoadTestApi({ ...api, headers: parsed });
                                  }
                                } catch (err) {
                                  // Invalid JSON - ignore while typing
                                }
                              }}
                              placeholder='{"Content-Type": "application/json"}'
                            />
                          </div>

                          {/* Editable Payload */}
                          <div className={styles.detailRow}>
                            <strong>Payload:</strong>
                            <textarea
                              className={styles.editableCodeBlock}
                              rows={5}
                              value={JSON.stringify(api.payload || {}, null, 2)}
                              onChange={(e) => {
                                if (!uploadedApis) return;
                                try {
                                  const parsed = JSON.parse(e.target.value);
                                  const updatedApis = uploadedApis.map(a =>
                                    a.name === api.name ? { ...a, payload: parsed } : a
                                  );
                                  setUploadedApis(updatedApis);
                                  if (selectedLoadTestApi?.name === api.name) {
                                    setSelectedLoadTestApi({ ...api, payload: parsed });
                                  }
                                } catch (err) {
                                  // Invalid JSON - ignore while typing
                                }
                              }}
                              placeholder='{"key": "value"}'
                            />
                          </div>

                          {/* Editable Auth Type */}
                          <div className={styles.detailRow}>
                            <strong>Auth Type:</strong>
                            <select
                              className={styles.authSelect}
                              value={api.auth_config?.auth_type || 'none'}
                              onChange={(e) => {
                                if (!uploadedApis) return;
                                const authType = e.target.value as 'none' | 'bearer' | 'api_key' | 'basic';
                                const updatedApis = uploadedApis.map(a =>
                                  a.name === api.name
                                    ? {
                                        ...a,
                                        auth_config: {
                                          ...a.auth_config,
                                          auth_type: authType
                                        }
                                      }
                                    : a
                                );
                                setUploadedApis(updatedApis);
                                if (selectedLoadTestApi?.name === api.name) {
                                  setSelectedLoadTestApi({
                                    ...api,
                                    auth_config: {
                                      ...api.auth_config,
                                      auth_type: authType
                                    }
                                  });
                                }
                              }}
                            >
                              <option value="none">None</option>
                              <option value="bearer">Bearer Token</option>
                              <option value="api_key">API Key</option>
                              <option value="basic">Basic Auth</option>
                            </select>
                          </div>

                          {/* Conditional Auth Fields */}
                          {api.auth_config?.auth_type === 'bearer' && (
                            <div className={styles.detailRow}>
                              <strong>Bearer Token:</strong>
                              <input
                                type="text"
                                className={styles.authInput}
                                placeholder="your-bearer-token"
                                value={api.auth_config?.token || ''}
                                onChange={(e) => {
                                  if (!uploadedApis) return;
                                  const updatedApis = uploadedApis.map(a =>
                                    a.name === api.name
                                      ? {
                                          ...a,
                                          auth_config: {
                                            ...a.auth_config,
                                            token: e.target.value
                                          }
                                        }
                                      : a
                                  );
                                  setUploadedApis(updatedApis);
                                  if (selectedLoadTestApi?.name === api.name) {
                                    setSelectedLoadTestApi({
                                      ...api,
                                      auth_config: {
                                        ...api.auth_config,
                                        token: e.target.value
                                      }
                                    });
                                  }
                                }}
                              />
                            </div>
                          )}

                          {api.auth_config?.auth_type === 'api_key' && (
                            <>
                              <div className={styles.detailRow}>
                                <strong>API Key Name:</strong>
                                <input
                                  type="text"
                                  className={styles.authInput}
                                  placeholder="X-API-Key"
                                  value={api.auth_config?.api_key_name || ''}
                                  onChange={(e) => {
                                    if (!uploadedApis) return;
                                    const updatedApis = uploadedApis.map(a =>
                                      a.name === api.name
                                        ? {
                                            ...a,
                                            auth_config: {
                                              ...a.auth_config,
                                              api_key_name: e.target.value
                                            }
                                          }
                                        : a
                                    );
                                    setUploadedApis(updatedApis);
                                    if (selectedLoadTestApi?.name === api.name) {
                                      setSelectedLoadTestApi({
                                        ...api,
                                        auth_config: {
                                          ...api.auth_config,
                                          api_key_name: e.target.value
                                        }
                                      });
                                    }
                                  }}
                                />
                              </div>
                              <div className={styles.detailRow}>
                                <strong>API Key Value:</strong>
                                <input
                                  type="text"
                                  className={styles.authInput}
                                  placeholder="your-api-key-value"
                                  value={api.auth_config?.api_key_value || ''}
                                  onChange={(e) => {
                                    if (!uploadedApis) return;
                                    const updatedApis = uploadedApis.map(a =>
                                      a.name === api.name
                                        ? {
                                            ...a,
                                            auth_config: {
                                              ...a.auth_config,
                                              api_key_value: e.target.value
                                            }
                                          }
                                        : a
                                    );
                                    setUploadedApis(updatedApis);
                                    if (selectedLoadTestApi?.name === api.name) {
                                      setSelectedLoadTestApi({
                                        ...api,
                                        auth_config: {
                                          ...api.auth_config,
                                          api_key_value: e.target.value
                                        }
                                      });
                                    }
                                  }}
                                />
                              </div>
                            </>
                          )}

                          {api.auth_config?.auth_type === 'basic' && (
                            <>
                              <div className={styles.detailRow}>
                                <strong>Username:</strong>
                                <input
                                  type="text"
                                  className={styles.authInput}
                                  placeholder="username"
                                  value={api.auth_config?.username || ''}
                                  onChange={(e) => {
                                    if (!uploadedApis) return;
                                    const updatedApis = uploadedApis.map(a =>
                                      a.name === api.name
                                        ? {
                                            ...a,
                                            auth_config: {
                                              ...a.auth_config,
                                              username: e.target.value
                                            }
                                          }
                                        : a
                                    );
                                    setUploadedApis(updatedApis);
                                    if (selectedLoadTestApi?.name === api.name) {
                                      setSelectedLoadTestApi({
                                        ...api,
                                        auth_config: {
                                          ...api.auth_config,
                                          username: e.target.value
                                        }
                                      });
                                    }
                                  }}
                                />
                              </div>
                              <div className={styles.detailRow}>
                                <strong>Password:</strong>
                                <input
                                  type="password"
                                  className={styles.authInput}
                                  placeholder="password"
                                  value={api.auth_config?.password || ''}
                                  onChange={(e) => {
                                    if (!uploadedApis) return;
                                    const updatedApis = uploadedApis.map(a =>
                                      a.name === api.name
                                        ? {
                                            ...a,
                                            auth_config: {
                                              ...a.auth_config,
                                              password: e.target.value
                                            }
                                          }
                                        : a
                                    );
                                    setUploadedApis(updatedApis);
                                    if (selectedLoadTestApi?.name === api.name) {
                                      setSelectedLoadTestApi({
                                        ...api,
                                        auth_config: {
                                          ...api.auth_config,
                                          password: e.target.value
                                        }
                                      });
                                    }
                                  }}
                                />
                              </div>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
                </div>
              </>
            )}
          </section>

          {/* Upload Section with Toggles Inside (Bottom) */}
          <section className={styles.uploadSection}>
            {/* Toggles Row inside upload section */}
            <div className={styles.togglesRow}>
              <div className={styles.toggleItem}>
                <Wrench size={18} />
                <span>Batch Execute</span>
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
              </div>
              <div className={styles.toggleItem}>
                <span className={styles.aiIcon}>🤖</span>
                <span>AI-Powered</span>
                <label className={styles.switch}>
                  <input
                    type="checkbox"
                    checked={aiMode}
                    onChange={(e) => {
                      setAiMode(e.target.checked);
                      setAiRecommendations(null);
                    }}
                    disabled={isLoadTesting}
                  />
                  <span className={styles.slider}></span>
                </label>
              </div>
            </div>

            {/* Upload zone below toggles */}
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

          {/* Batch AI Analysis Panel - Sequential Mode with AI */}
          {autoExecuteMode && selectedApis.length > 0 && !isLoadTesting && aiMode && (
            <div className={styles.aiPanel}>
              <h2>
                <span className={styles.aiIcon}>🤖</span> AI Analysis for Sequential Test
              </h2>

              {!batchAiRecommendations ? (
                // Pre-Analysis State
                <div className={styles.aiPrompt}>
                  <p>Let AI analyze all selected APIs and optimize configuration for sequential execution!</p>

                  {/* Suggestions Button */}
                  <button
                    className={styles.suggestionsButton}
                    onClick={() => setShowBatchSuggestionsInput(!showBatchSuggestionsInput)}
                  >
                    💡 {showBatchSuggestionsInput ? 'Back to Features' : 'Add Custom Suggestions'}
                  </button>

                  {/* Conditional: Show Features or Suggestions */}
                  {!showBatchSuggestionsInput ? (
                    <div className={styles.aiFeatures}>
                      <div className={styles.aiFeature}>
                        ✅ Detect API types automatically
                      </div>
                      <div className={styles.aiFeature}>
                        ✅ Generate realistic test data
                      </div>
                      <div className={styles.aiFeature}>
                        ✅ Recommend optimal parameters
                      </div>
                      <div className={styles.aiFeature}>
                        ✅ Optimize for each API individually
                      </div>
                    </div>
                  ) : (
                    <div className={styles.suggestionsContainer}>
                      <textarea
                        className={styles.suggestionsTextarea}
                        rows={5}
                        placeholder="Enter your suggestions for all APIs (e.g., 'Generate test data with email addresses only from @gmail.com domain', 'Use maximum 500 users for all APIs', 'Set spawn rate to 50/s')"
                        value={customBatchSuggestions}
                        onChange={(e) => setCustomBatchSuggestions(e.target.value)}
                      />
                      <div className={styles.suggestionsWarning}>
                        ⚠️ Do not include sensitive data like passwords or API keys
                      </div>
                      {customBatchSuggestions.trim() && (
                        <div className={styles.suggestionsButtonGroup}>
                          <button
                            className={styles.clearSuggestionsButton}
                            onClick={() => setCustomBatchSuggestions('')}
                          >
                            Clear Suggestions
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  <button
                    className={styles.aiButton}
                    onClick={handleBatchAiAnalysis}
                    disabled={isAnalyzingBatch}
                  >
                    {isAnalyzingBatch ? (
                      <>
                        <span className={styles.spinner}></span>
                        Analyzing {selectedApis.length} API{selectedApis.length > 1 ? 's' : ''}...
                      </>
                    ) : (
                      <>
                        <span className={styles.aiIcon}>🤖</span>
                        Analyze All Selected APIs
                        {customBatchSuggestions.trim() && (
                          <span className={styles.suggestionsBadge}>✓ Custom Suggestions</span>
                        )}
                      </>
                    )}
                  </button>
                </div>
              ) : (
                // Post-Analysis State
                <div className={styles.batchAiResults}>
                  <div className={styles.aiResultsHeader}>
                    <span className={styles.successBadge}>
                      ✅ Analysis Complete for {batchAiRecommendations.total_apis} API{batchAiRecommendations.total_apis > 1 ? 's' : ''}
                    </span>
                    <button
                      className={styles.reanalyzeButton}
                      onClick={handleReanalyzeBatch}
                    >
                      🔬 Analyze Again
                    </button>
                  </div>

                  {/* Add Custom Suggestions after analysis */}
                  <div className={styles.postAnalysisSuggestions}>
                    <button
                      className={styles.suggestionsButton}
                      onClick={() => setShowBatchSuggestionsInput(!showBatchSuggestionsInput)}
                    >
                      💡 {showBatchSuggestionsInput ? 'Hide Suggestions' : 'Add Custom Suggestions'}
                    </button>

                    {showBatchSuggestionsInput && (
                      <div className={styles.suggestionsContainer}>
                        <textarea
                          className={styles.suggestionsTextarea}
                          rows={5}
                          placeholder="Enter new suggestions for re-analysis (e.g., 'Generate test data with email addresses only from @gmail.com domain', 'Use maximum 500 users for all APIs', 'Set spawn rate to 50/s')"
                          value={customBatchSuggestions}
                          onChange={(e) => setCustomBatchSuggestions(e.target.value)}
                        />
                        <div className={styles.suggestionsWarning}>
                          ⚠️ Do not include sensitive data like passwords or API keys
                        </div>
                        {customBatchSuggestions.trim() && (
                          <div className={styles.suggestionsButtonGroup}>
                            <button
                              className={styles.clearSuggestionsButton}
                              onClick={() => setCustomBatchSuggestions('')}
                            >
                              Clear Suggestions
                            </button>
                          </div>
                        )}
                        {customBatchSuggestions.trim() && (
                          <div className={styles.suggestionsHint}>
                            💡 Click "Analyze Again" to re-run analysis with these suggestions
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Common Toggle for AI Test Data */}
                  <div className={styles.batchTestDataToggle}>
                    <span className={styles.toggleLabel}>
                      Use AI-Generated Test Data for All APIs
                    </span>
                    <label className={styles.switch}>
                      <input
                        type="checkbox"
                        checked={useBatchAiTestData}
                        onChange={(e) => setUseBatchAiTestData(e.target.checked)}
                      />
                      <span className={styles.sliderWithRobot}>
                        <span className={styles.robotIcon}>🤖</span>
                      </span>
                    </label>
                  </div>

                  <div className={styles.batchApiList}>
                    {batchAiRecommendations.results.map((result: any, index: number) => {
                      const isExpanded = expandedBatchApi === result.api_name;

                      return (
                        <div key={result.api_name} className={styles.batchApiCard}>
                          <div
                            className={styles.batchApiHeader}
                            onClick={() => toggleBatchApiExpansion(result.api_name)}
                          >
                            <div className={styles.batchApiTitle}>
                              <span className={styles.batchApiIndex}>{index + 1}.</span>
                              <div className={styles.batchApiInfo}>
                                <span className={styles.batchApiName}>{result.api_name}</span>
                                <span className={styles.batchApiEndpoint}>
                                  {result.method} {result.endpoint}
                                </span>
                                {/* Inline Summary - Always visible */}
                                <div className={styles.batchApiSummary}>
                                  <div className={styles.summaryItem}>
                                    <Users size={12} className={styles.summaryIcon} />
                                    <span className={styles.summaryValue}>{result.recommendations.users}</span>
                                  </div>
                                  <div className={styles.summaryItem}>
                                    <Zap size={12} className={styles.summaryIcon} />
                                    <span className={styles.summaryValue}>{result.recommendations.spawn_rate}/s</span>
                                  </div>
                                  <div className={styles.summaryItem}>
                                    <Clock size={12} className={styles.summaryIcon} />
                                    <span className={styles.summaryValue}>
                                      {result.recommendations.think_time_min}-{result.recommendations.think_time_max}s
                                    </span>
                                  </div>
                                  <div className={styles.summaryItem}>
                                    <RefreshCw size={12} className={styles.summaryIcon} />
                                    <span className={styles.summaryValue}>{formatDataMode(result.recommendations.data_mode)}</span>
                                  </div>
                                </div>
                              </div>
                            </div>
                            <button className={styles.expandBtn}>
                              {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                            </button>
                          </div>

                          {isExpanded && (
                            <div className={styles.batchApiDetails}>
                              {/* API Summary */}
                              <div className={styles.aiSummary}>
                                <div className={styles.aiSummaryItem}>
                                  <strong>API Type:</strong> {result.api_type}
                                </div>
                                {result.required_fields.length > 0 && (
                                  <div className={styles.aiSummaryItem}>
                                    <strong>Required Fields:</strong> {result.required_fields.join(', ')}
                                  </div>
                                )}
                              </div>

                              {/* Recommendations Grid */}
                              <div className={styles.aiRecommendations}>
                                <h4>AI Recommendations:</h4>
                                <div className={styles.recommendationGrid}>
                                  <div className={styles.recommendationItem}>
                                    <span className={styles.label}>Users:</span>
                                    <span className={styles.value}>{result.recommendations.users}</span>
                                  </div>
                                  <div className={styles.recommendationItem}>
                                    <span className={styles.label}>Spawn Rate:</span>
                                    <span className={styles.value}>{result.recommendations.spawn_rate}/s</span>
                                  </div>
                                  <div className={styles.recommendationItem}>
                                    <span className={styles.label}>Think Time:</span>
                                    <span className={styles.value}>
                                      {result.recommendations.think_time_min}-{result.recommendations.think_time_max}s
                                    </span>
                                  </div>
                                  <div className={styles.recommendationItem}>
                                    <span className={styles.label}>Data Mode:</span>
                                    <span className={styles.value}>{formatDataMode(result.recommendations.data_mode)}</span>
                                  </div>
                                </div>

                                {/* Test Data Section */}
                                {result.recommendations.test_data && result.recommendations.test_data.length > 0 && (
                                  <div className={styles.testDataSection}>
                                    <div
                                      className={styles.testDataInfo}
                                      onClick={() => {
                                        setExpandedTestDataBatch(prev => ({
                                          ...prev,
                                          [result.api_name]: !prev[result.api_name]
                                        }));
                                      }}
                                      style={{ cursor: 'pointer' }}
                                    >
                                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <span className={styles.expandArrow}>
                                          {expandedTestDataBatch[result.api_name] ? '▼' : '▶'}
                                        </span>
                                        <span className={styles.label}>Generated Test Data:</span>
                                        <span className={styles.value}>
                                          {result.recommendations.test_data.length} entries
                                        </span>
                                      </div>
                                    </div>

                                    {expandedTestDataBatch[result.api_name] && (
                                      <div className={styles.testDataPreview}>
                                        <div className={styles.textareaWrapper}>
                                          <textarea
                                            className={styles.testDataTextarea}
                                            value={JSON.stringify(result.recommendations.test_data, null, 2)}
                                            readOnly
                                            rows={10}
                                          />
                                          <button
                                            className={styles.copyIcon}
                                            onClick={() => {
                                              navigator.clipboard.writeText(JSON.stringify(result.recommendations.test_data, null, 2));
                                              addNotification('success', `Test data for ${result.api_name} copied to clipboard`);
                                            }}
                                            title="Copy to clipboard"
                                          >
                                            📋
                                          </button>
                                        </div>
                                      </div>
                                    )}

                                    {/* Individual API Toggle */}
                                    <div className={styles.testDataToggle}>
                                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <span className={styles.toggleLabel}>
                                          Use AI-Generated Test Data for this API
                                        </span>
                                        {result.api_name in batchApiTestDataOverrides && (
                                          <span className={styles.overrideBadge} title="This API has a custom override">
                                            Override
                                          </span>
                                        )}
                                      </div>
                                      <label className={styles.switch}>
                                        <input
                                          type="checkbox"
                                          checked={shouldUseAiTestData(result.api_name)}
                                          onChange={() => toggleBatchApiTestData(result.api_name, shouldUseAiTestData(result.api_name))}
                                        />
                                        <span className={styles.sliderWithRobot}>
                                          <span className={styles.robotIcon}>🤖</span>
                                        </span>
                                      </label>
                                    </div>

                                    <p className={styles.testDataHint}>
                                      {shouldUseAiTestData(result.api_name)
                                        ? '✅ Will use AI-generated test data'
                                        : '📄 Will use test data from Excel file'}
                                    </p>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Apply All Button */}
                  <button
                    className={styles.applyButton}
                    onClick={handleApplyBatchRecommendations}
                  >
                    ✨ Apply All Recommendations
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Auto Mode - Selected APIs Preview */}
          {autoExecuteMode && selectedApis.length > 0 && !isLoadTesting && !loadTestMetrics && (
            <div className={styles.autoPreviewSection}>
              <h2>Ready to Start Sequential Test</h2>
              <p className={styles.configSubtitle}>
                {selectedApis.length} API{selectedApis.length > 1 ? 's' : ''} will be tested sequentially — click any row to edit its config
              </p>

              <div className={styles.selectedApisList}>
                {uploadedApis?.filter(api => selectedApis.includes(api.name)).map((api, index) => {
                  const isExecuting = sequentialTestStatus?.status === 'running' && (
                    sequentialTestStatus.current_api === api.name ||
                    (!sequentialTestStatus.current_api && index === 0)
                  );
                  const isExpanded = !!batchExpandedEdit[api.name];
                  const edits = batchEditValues[api.name] ?? {
                    users: String(api.users ?? 10),
                    spawn_rate: String(api.spawn_rate ?? 2),
                    run_time: api.run_time ?? '5m',
                    payload: api.payload ? JSON.stringify(api.payload, null, 2) : '',
                    headers: api.headers && Object.keys(api.headers).length > 0
                      ? JSON.stringify(api.headers, null, 2) : '',
                  };
                  const setField = (field: keyof typeof edits, value: string) =>
                    setBatchEditValues(prev => ({
                      ...prev,
                      [api.name]: { ...edits, [field]: value },
                    }));

                  return (
                    <div key={api.name} className={`${styles.batchEditCard} ${isExecuting ? styles.executingApi : ''}`}>
                      {/* Collapsed header — always visible */}
                      <button
                        className={styles.batchEditCardHeader}
                        onClick={() => setBatchExpandedEdit(prev => ({ ...prev, [api.name]: !prev[api.name] }))}
                      >
                        <div className={styles.apiNumber}>{index + 1}</div>
                        <div className={`${styles.methodBadge} ${styles[api.method.toLowerCase()]}`}>
                          {api.method}
                        </div>
                        <div className={styles.apiItemInfo}>
                          <div className={styles.apiItemName}>{api.name}</div>
                          <div className={styles.apiItemEndpoint}>{api.endpoint}</div>
                        </div>
                        <div className={styles.apiItemConfig}>
                          <span className={styles.configItem}><Users size={13} /> {edits.users}</span>
                          <span className={styles.configItem}><TrendingUp size={13} /> {edits.spawn_rate}/s</span>
                          <span className={styles.configItem}><Clock size={13} /> {edits.run_time}</span>
                        </div>
                        <span className={styles.batchEditChevron}>
                          {isExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                        </span>
                      </button>

                      {/* Expanded editor */}
                      {isExpanded && (
                        <div className={styles.batchEditBody}>
                          <div className={styles.batchEditRow}>
                            <label className={styles.batchEditLabel}>
                              <Users size={13} /> Number of Users
                            </label>
                            <input
                              type="number"
                              className={styles.batchEditInput}
                              value={edits.users}
                              min={1}
                              onChange={e => setField('users', e.target.value)}
                            />
                          </div>
                          <div className={styles.batchEditRow}>
                            <label className={styles.batchEditLabel}>
                              <TrendingUp size={13} /> Spawn Rate (users/sec)
                            </label>
                            <input
                              type="number"
                              className={styles.batchEditInput}
                              value={edits.spawn_rate}
                              min={0.1}
                              step={0.1}
                              onChange={e => setField('spawn_rate', e.target.value)}
                            />
                          </div>
                          <div className={styles.batchEditRow}>
                            <label className={styles.batchEditLabel}>
                              <Clock size={13} /> Run Time (e.g. 5m, 1h, 30s)
                            </label>
                            <input
                              type="text"
                              className={styles.batchEditInput}
                              value={edits.run_time}
                              onChange={e => setField('run_time', e.target.value)}
                            />
                          </div>
                          {(api.method === 'POST' || api.method === 'PUT' || api.method === 'PATCH') && (
                            <div className={styles.batchEditRow}>
                              <label className={styles.batchEditLabel}>
                                Payload (JSON)
                              </label>
                              <textarea
                                className={styles.batchEditTextarea}
                                rows={5}
                                value={edits.payload}
                                placeholder='{"key": "value"}'
                                onChange={e => setField('payload', e.target.value)}
                              />
                            </div>
                          )}
                          <div className={styles.batchEditRow}>
                            <label className={styles.batchEditLabel}>
                              Headers (JSON)
                            </label>
                            <textarea
                              className={styles.batchEditTextarea}
                              rows={3}
                              value={edits.headers}
                              placeholder='{"Authorization": "Bearer token"}'
                              onChange={e => setField('headers', e.target.value)}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              <div className={styles.testSummary}>
                <div className={styles.summaryItem}>
                  <strong>Total APIs:</strong> {selectedApis.length}
                </div>
                <div className={styles.summaryItem}>
                  <strong>Execution:</strong> Sequential (one after another)
                </div>
                <div className={styles.summaryItem}>
                  <strong>Config Source:</strong> Excel (editable above)
                </div>
              </div>

              <button className={styles.startButton} onClick={handleStartSequentialTest}>
                <Play size={16} /> Start Sequential Test
              </button>
            </div>
          )}

          {/* AI Analysis Panel - Manual Mode with AI */}
          {!autoExecuteMode && selectedLoadTestApi && !isLoadTesting && aiMode && (
            <div className={styles.aiPanel}>
              <h2>
                <span className={styles.aiIcon}>🤖</span> AI Analysis
              </h2>

              {!aiRecommendations ? (
                <div className={styles.aiPrompt}>
                  <p>Let AI analyze your API and generate optimal test data and configuration!</p>

                  {/* Suggestions Button */}
                  <button
                    className={styles.suggestionsButton}
                    onClick={() => setShowSuggestionsInput(!showSuggestionsInput)}
                  >
                    💡 {showSuggestionsInput ? 'Back to Features' : 'Add Custom Suggestions'}
                  </button>

                  {/* Conditional: Show Features or Suggestions */}
                  {!showSuggestionsInput ? (
                    <div className={styles.aiFeatures}>
                      <div className={styles.aiFeature}>✅ Detect API type automatically</div>
                      <div className={styles.aiFeature}>✅ Generate realistic test data</div>
                      <div className={styles.aiFeature}>✅ Recommend optimal parameters</div>
                      <div className={styles.aiFeature}>✅ Suggest best practices</div>
                    </div>
                  ) : (
                    <div className={styles.suggestionsContainer}>
                      <textarea
                        className={styles.suggestionsTextarea}
                        rows={5}
                        placeholder="Enter your suggestions for load testing (e.g., 'Generate test data with email addresses only from @gmail.com domain', 'Use maximum 500 users', 'Set spawn rate to 50/s')"
                        value={customSuggestions}
                        onChange={(e) => setCustomSuggestions(e.target.value)}
                      />
                      <div className={styles.suggestionsWarning}>
                        ⚠️ Do not include sensitive data like passwords or API keys
                      </div>
                      {customSuggestions.trim() && (
                        <div className={styles.suggestionsButtonGroup}>
                          <button
                            className={styles.clearSuggestionsButton}
                            onClick={() => setCustomSuggestions('')}
                          >
                            Clear Suggestions
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  <button
                    className={styles.aiButton}
                    onClick={handleAiAnalysis}
                    disabled={isAnalyzing}
                  >
                    {isAnalyzing ? (
                      <>
                        <span className={styles.spinner}></span> Analyzing...
                      </>
                    ) : (
                      <>
                        <span className={styles.aiIcon}>🤖</span> Analyze with AI
                        {customSuggestions.trim() && (
                          <span className={styles.suggestionsBadge}>✓ Custom Suggestions</span>
                        )}
                      </>
                    )}
                  </button>
                </div>
              ) : (
                <div className={styles.aiResults}>
                  <div className={styles.aiResultsHeader}>
                    <span className={styles.successBadge}>✅ Analysis Complete</span>
                    <button
                      className={styles.reanalyzeButton}
                      onClick={handleAiAnalysis}
                      disabled={isAnalyzing}
                    >
                      {isAnalyzing ? (
                        <>
                          <span className={styles.spinner}></span> Analyzing...
                        </>
                      ) : (
                        <>
                          🔬 Analyze Again
                        </>
                      )}
                    </button>
                  </div>

                  {/* Add Custom Suggestions after analysis */}
                  <div className={styles.postAnalysisSuggestions}>
                    <button
                      className={styles.suggestionsButton}
                      onClick={() => setShowSuggestionsInput(!showSuggestionsInput)}
                    >
                      💡 {showSuggestionsInput ? 'Hide Suggestions' : 'Add Custom Suggestions'}
                    </button>

                    {showSuggestionsInput && (
                      <div className={styles.suggestionsContainer}>
                        <textarea
                          className={styles.suggestionsTextarea}
                          rows={5}
                          placeholder="Enter new suggestions for re-analysis (e.g., 'Generate test data with email addresses only from @gmail.com domain', 'Use maximum 500 users', 'Set spawn rate to 50/s')"
                          value={customSuggestions}
                          onChange={(e) => setCustomSuggestions(e.target.value)}
                        />
                        <div className={styles.suggestionsWarning}>
                          ⚠️ Do not include sensitive data like passwords or API keys
                        </div>
                        {customSuggestions.trim() && (
                          <div className={styles.suggestionsButtonGroup}>
                            <button
                              className={styles.clearSuggestionsButton}
                              onClick={() => setCustomSuggestions('')}
                            >
                              Clear Suggestions
                            </button>
                          </div>
                        )}
                        {customSuggestions.trim() && (
                          <div className={styles.suggestionsHint}>
                            💡 Click "Analyze Again" to re-run analysis with these suggestions
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  <div className={styles.aiSummary}>
                    <div className={styles.aiSummaryItem}>
                      <strong>API Type:</strong> {aiRecommendations.api_type}
                    </div>
                    <div className={styles.aiSummaryItem}>
                      <strong>Required Fields:</strong> {aiRecommendations.required_fields.join(', ') || 'None'}
                    </div>
                  </div>

                  <div className={styles.aiRecommendations}>
                    <h3>AI Recommendations:</h3>
                    <div className={styles.recommendationGrid}>
                      <div className={styles.recommendationItem}>
                        <span className={styles.label}>Users:</span>
                        <span className={styles.value}>{aiRecommendations.recommendations.users}</span>
                      </div>
                      <div className={styles.recommendationItem}>
                        <span className={styles.label}>Spawn Rate:</span>
                        <span className={styles.value}>{aiRecommendations.recommendations.spawn_rate}/s</span>
                      </div>
                      <div className={styles.recommendationItem}>
                        <span className={styles.label}>Think Time:</span>
                        <span className={styles.value}>
                          {aiRecommendations.recommendations.think_time_min}s - {aiRecommendations.recommendations.think_time_max}s
                        </span>
                      </div>
                      <div className={styles.recommendationItem}>
                        <span className={styles.label}>Data Mode:</span>
                        <span className={styles.value}>{formatDataMode(aiRecommendations.recommendations.data_mode)}</span>
                      </div>
                    </div>

                    {aiRecommendations.recommendations.test_data && aiRecommendations.recommendations.test_data.length > 0 && (
                      <div className={styles.testDataSection}>
                        <div
                          className={styles.testDataInfo}
                          onClick={() => setShowTestDataSingle(!showTestDataSingle)}
                          style={{ cursor: 'pointer' }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span className={styles.expandArrow}>
                              {showTestDataSingle ? '▼' : '▶'}
                            </span>
                            <span className={styles.label}>Generated Test Data:</span>
                            <span className={styles.value}>{aiRecommendations.recommendations.test_data.length} entries</span>
                          </div>
                        </div>

                        {showTestDataSingle && (
                          <div className={styles.testDataPreview}>
                            <div className={styles.textareaWrapper}>
                              <textarea
                                className={styles.testDataTextarea}
                                value={JSON.stringify(aiRecommendations.recommendations.test_data, null, 2)}
                                readOnly
                                rows={10}
                              />
                              <button
                                className={styles.copyIcon}
                                onClick={() => {
                                  navigator.clipboard.writeText(JSON.stringify(aiRecommendations.recommendations.test_data, null, 2));
                                  addNotification('success', 'Test data copied to clipboard');
                                }}
                                title="Copy to clipboard"
                              >
                                📋
                              </button>
                            </div>
                          </div>
                        )}

                        <div className={styles.testDataToggle}>
                          <span className={styles.toggleLabel}>
                            Use AI-Generated Test Data
                          </span>
                          <label className={styles.switch}>
                            <input
                              type="checkbox"
                              checked={useAiTestData}
                              onChange={(e) => setUseAiTestData(e.target.checked)}
                            />
                            <span className={styles.slider}></span>
                          </label>
                        </div>

                        <p className={styles.testDataHint}>
                          {useAiTestData
                            ? '✅ Will use AI-generated test data'
                            : '📄 Will use test data from Excel file'}
                        </p>
                      </div>
                    )}
                  </div>

                  <button
                    className={styles.applyButton}
                    onClick={handleApplyRecommendations}
                  >
                    ✨ Apply AI Recommendations
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Config Form - Manual Mode */}
          {!autoExecuteMode && selectedLoadTestApi && !isLoadTesting && (
            <div id="load-test-config" className={styles.configSection}>
              <h2>Load Test Configuration</h2>
              <p className={styles.configSubtitle}>
                {aiMode && aiRecommendations
                  ? '✨ AI-generated configuration (editable)'
                  : selectedLoadTestApi.users
                  ? 'Pre-filled from Excel (editable)'
                  : 'Default values (editable)'}
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

              {/* Phase 1: Multi-user data support fields */}
              <div className={styles.formGroup}>
                <label>
                  Test Data (JSON Array):
                </label>
                <textarea
                  rows={4}
                  placeholder='[{"username":"user1","password":"pass1"},{"username":"user2","password":"pass2"}]'
                  value={selectedLoadTestApi.test_data ? JSON.stringify(selectedLoadTestApi.test_data, null, 2) : ''}
                  onChange={(e) => {
                    if (!uploadedApis) return;
                    try {
                      const parsed = e.target.value ? JSON.parse(e.target.value) : null;
                      const updatedApis = uploadedApis.map(api =>
                        api.name === selectedLoadTestApi.name ? { ...api, test_data: parsed } : api
                      );
                      setUploadedApis(updatedApis);
                      setSelectedLoadTestApi({ ...selectedLoadTestApi, test_data: parsed });
                    } catch (err) {
                      // Invalid JSON - ignore for now, user might still be typing
                    }
                  }}
                  className={styles.textareaInput}
                />
                <span className={styles.hint}>
                  Optional: Provide array of objects. Use {`{{variable}}`} in payload to substitute values.
                </span>
              </div>

              <div className={styles.formGroup}>
                <label>Data Cycling Mode:</label>
                <select
                  value={selectedLoadTestApi.data_mode || 'round_robin'}
                  onChange={(e) => {
                    if (!uploadedApis) return;
                    const mode = e.target.value as 'sequential' | 'random' | 'round_robin';
                    const updatedApis = uploadedApis.map(api =>
                      api.name === selectedLoadTestApi.name ? { ...api, data_mode: mode } : api
                    );
                    setUploadedApis(updatedApis);
                    setSelectedLoadTestApi({ ...selectedLoadTestApi, data_mode: mode });
                  }}
                >
                  <option value="round_robin">Round Robin (Recommended)</option>
                  <option value="sequential">Sequential</option>
                  <option value="random">Random</option>
                </select>
                <span className={styles.hint}>
                  How to cycle through test data for different virtual users.
                </span>
              </div>

              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Think Time Min (seconds):</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={selectedLoadTestApi.think_time_min ?? 1.0}
                    onChange={(e) => {
                      if (!uploadedApis) return;
                      const value = parseFloat(e.target.value) || 1.0;
                      const updatedApis = uploadedApis.map(api =>
                        api.name === selectedLoadTestApi.name ? { ...api, think_time_min: value } : api
                      );
                      setUploadedApis(updatedApis);
                      setSelectedLoadTestApi({ ...selectedLoadTestApi, think_time_min: value });
                    }}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Think Time Max (seconds):</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={selectedLoadTestApi.think_time_max ?? 3.0}
                    onChange={(e) => {
                      if (!uploadedApis) return;
                      const value = parseFloat(e.target.value) || 3.0;
                      const updatedApis = uploadedApis.map(api =>
                        api.name === selectedLoadTestApi.name ? { ...api, think_time_max: value } : api
                      );
                      setUploadedApis(updatedApis);
                      setSelectedLoadTestApi({ ...selectedLoadTestApi, think_time_max: value });
                    }}
                  />
                </div>
              </div>
              <span className={styles.hint}>
                Wait time between requests to simulate realistic user behavior.
              </span>

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
                        width: sequentialTestStatus.status === 'completed'
                          ? '100%'
                          : `${Math.min(
                              (((sequentialTestStatus.current_index || 0) + 1) / (sequentialTestStatus.total_apis || 1)) * 100,
                              100
                            )}%`
                      }}
                    />
                  </div>

                  <div className={styles.progressStats}>
                    <div>
                      <strong>Status:</strong> {
                        sequentialTestStatus.status === 'completed' ? 'Completed' :
                        sequentialTestStatus.status === 'stopped' ? 'Stopped' :
                        sequentialTestStatus.current_api ? `Running: ${sequentialTestStatus.current_api}` :
                        'Starting...'
                      }
                    </div>
                    <div>
                      <strong>Progress:</strong> {
                        sequentialTestStatus.status === 'completed'
                          ? `${sequentialTestStatus.total_apis || 0} of ${sequentialTestStatus.total_apis || 0}`
                          : `${(sequentialTestStatus.current_index || 0) + 1} of ${sequentialTestStatus.total_apis || 0}`
                      }
                    </div>
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
