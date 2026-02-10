import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

// Clear corrupted storage on load (one-time fix for quota exceeded)
try {
  const stored = localStorage.getItem('test-automation-storage');
  if (stored) {
    const parsed = JSON.parse(stored);
    // If screenshots exist in storage, they're causing the quota issue - remove them
    if (parsed.state?.screenshots?.length > 0) {
      console.log('Clearing oversized screenshots from localStorage...');
      delete parsed.state.screenshots;
      localStorage.setItem('test-automation-storage', JSON.stringify(parsed));
    }
  }
} catch (e) {
  // If parsing fails, clear the storage entirely
  console.warn('Clearing corrupted localStorage:', e);
  localStorage.removeItem('test-automation-storage');
}

export interface TestStep {
  step_number: number;
  instruction: string;
  action: {
    type: string;
    playwright_method: string;
  };
  selector_hints: {
    element_name: string | null;
    element_type: string | null;
    suggested_selectors: string[];
  };
  test_data: Record<string, unknown> | null;
  assertions: Array<{
    type: string;
    expected_value: string;
    playwright_assertion: string;
  }> | null;
}

export interface TestCase {
  id: string;
  name: string;
  steps: TestStep[];
  expected_results: string[];
}

export interface TestSuite {
  project: string;
  base_url: string;
  common_selectors: Record<string, unknown>;
  test_data: Record<string, unknown>;
  test_cases: TestCase[];
}

export interface StepResult {
  step: number;
  action: string;
  instruction: string;
  status: 'PASSED' | 'FAILED';
  selector_used: string | null;
  error: string | null;
}

export interface TestResult {
  test_id: string;
  test_name: string;
  status: 'PASSED' | 'FAILED' | 'ERROR';
  steps: StepResult[];
  selector_mappings: Record<string, string>;
  screenshots: string[];
  started_at: string;
  finished_at: string;
  error: string | null;
}

export interface ExecutionResult {
  project: string;
  base_url: string;
  total: number;
  passed: number;
  failed: number;
  results: TestResult[];
  executed_at: string;
}

type View = 'upload' | 'suite' | 'execution' | 'results' | 'download' | 'loadtest' | 'loadtest-reports';

// Execution mode: Multi-Agent (Supervisor + Sub-agents)
export type ExecutionMode = 'multi-agent';

// LLM Provider type
export type LLMProvider = 'groq' | 'openai' | 'anthropic';

// LLM Options with models
export const LLM_OPTIONS: Record<LLMProvider, { label: string; model: string }> = {
  groq: { label: 'Groq (Llama)', model: 'llama-3.1-8b-instant' },
  openai: { label: 'OpenAI (GPT-4o)', model: 'gpt-4o' },
  anthropic: { label: 'Anthropic (Claude)', model: 'claude-sonnet-4-20250514' },
};

// Raw Excel data for reports
export interface RawTestCase {
  'T.C.No': number;
  'Test Case': string;
  'Test Case Steps': string;
  'Expected Result': string;
  [key: string]: unknown;
}

// Screenshot data for reports
export interface ScreenshotData {
  id: string;
  testId: string;
  step: number;
  status: 'running' | 'passed' | 'failed';
  image: string; // base64
  url: string;
  title: string;
  timestamp: Date;
}

// Load Test Types
export interface LoadTestAPIConfig {
  name: string;
  base_url: string;
  endpoint: string;
  method: string;
  headers: Record<string, string>;
  payload?: Record<string, any> | null;
  query_params?: Record<string, any> | null;
  auth_config: {
    auth_type: 'bearer' | 'basic' | 'api_key' | 'none';
    token?: string;
    username?: string;
    password?: string;
    api_key_name?: string;
    api_key_value?: string;
  };
  description?: string;
  // Load test configuration (from Excel)
  users?: number;
  spawn_rate?: number;
  run_time?: string;
}

export interface LoadTestConfig {
  users: number;
  spawn_rate: number;
  run_time: string;
  host?: string;
}

export interface LoadTestMetrics {
  test_id: string;
  status: string;
  current_users: number;
  total_requests: number;
  total_failures: number;
  requests_per_second: number;
  failures_per_second: number;
  avg_response_time: number;
  min_response_time: number;
  max_response_time: number;
  median_response_time: number;
  percentile_95: number;
  percentile_99: number;
  failure_rate: number;
  elapsed_time: number;
  timestamp: string;
}

export interface SequentialTestStatus {
  sequential_test_id: string;
  status: 'running' | 'completed' | 'stopped';
  current_index: number;
  total_apis: number;
  current_api: string | null;
  apis: string[];
}

interface AppState {
  // Navigation
  currentView: View;
  setCurrentView: (view: View) => void;

  // Execution Mode
  executionMode: ExecutionMode;
  setExecutionMode: (mode: ExecutionMode) => void;

  // LLM Provider
  llmProvider: LLMProvider;
  setLlmProvider: (provider: LLMProvider) => void;

  // Test Suite
  testSuite: TestSuite | null;
  setTestSuite: (suite: TestSuite | null) => void;

  // Raw Excel Data (for reports)
  rawTestCases: RawTestCase[] | null;
  setRawTestCases: (data: RawTestCase[] | null) => void;

  // Generated Script
  generatedScript: string | null;
  setGeneratedScript: (script: string | null) => void;

  // Screenshots for reports
  screenshots: ScreenshotData[];
  setScreenshots: (screenshots: ScreenshotData[]) => void;
  addScreenshot: (screenshot: ScreenshotData) => void;
  clearScreenshots: () => void;

  // Execution
  isExecuting: boolean;
  setIsExecuting: (executing: boolean) => void;
  executionResult: ExecutionResult | null;
  setExecutionResult: (result: ExecutionResult | null) => void;

  // UI State
  selectedTestCase: string | null;
  setSelectedTestCase: (id: string | null) => void;
  expandedSteps: Set<number>;
  toggleStepExpanded: (step: number) => void;

  // Upload State
  uploadProgress: number;
  setUploadProgress: (progress: number) => void;
  isUploading: boolean;
  setIsUploading: (uploading: boolean) => void;

  // Notifications
  notifications: Array<{
    id: string;
    type: 'success' | 'error' | 'info' | 'warning';
    message: string;
  }>;
  addNotification: (type: 'success' | 'error' | 'info' | 'warning', message: string) => void;
  removeNotification: (id: string) => void;

  // Load Test State
  uploadedApis: LoadTestAPIConfig[] | null;
  setUploadedApis: (apis: LoadTestAPIConfig[] | null) => void;
  selectedLoadTestApi: LoadTestAPIConfig | null;
  setSelectedLoadTestApi: (api: LoadTestAPIConfig | null) => void;
  loadTestMetrics: LoadTestMetrics | null;
  setLoadTestMetrics: (metrics: LoadTestMetrics | null) => void;
  isLoadTesting: boolean;
  setIsLoadTesting: (testing: boolean) => void;
  activeLoadTestId: string | null;
  setActiveLoadTestId: (id: string | null) => void;

  // Auto-Execute Mode
  autoExecuteMode: boolean;
  setAutoExecuteMode: (enabled: boolean) => void;

  // Sequential Test State
  sequentialTestId: string | null;
  setSequentialTestId: (id: string | null) => void;
  sequentialTestStatus: SequentialTestStatus | null;
  setSequentialTestStatus: (status: SequentialTestStatus | null) => void;
  selectedApis: string[];
  setSelectedApis: (apis: string[]) => void;

  // Load Test Session ID (persists across navigation)
  loadTestSessionId: string | null;
  setLoadTestSessionId: (id: string | null) => void;

  // Reset
  reset: () => void;
}

export const useStore = create<AppState>()(
  persist(
    (set) => ({
      // Navigation
      currentView: 'upload',
      setCurrentView: (view) => set({ currentView: view }),

      // Execution Mode (Multi-Agent only)
      executionMode: 'multi-agent',
      setExecutionMode: (mode) => set({ executionMode: mode }),

      // LLM Provider (default to openai)
      llmProvider: 'openai',
      setLlmProvider: (provider) => set({ llmProvider: provider }),

      // Test Suite
      testSuite: null,
      setTestSuite: (suite) => set({ testSuite: suite }),

      // Raw Excel Data
      rawTestCases: null,
      setRawTestCases: (data) => set({ rawTestCases: data }),

      // Generated Script
      generatedScript: null,
      setGeneratedScript: (script) => set({ generatedScript: script }),

      // Screenshots
      screenshots: [],
      setScreenshots: (screenshots) => set({ screenshots }),
      addScreenshot: (screenshot) => set((state) => ({ screenshots: [...state.screenshots, screenshot] })),
      clearScreenshots: () => set({ screenshots: [] }),

      // Execution
      isExecuting: false,
      setIsExecuting: (executing) => set({ isExecuting: executing }),
      executionResult: null,
      setExecutionResult: (result) => set({ executionResult: result }),

      // UI State
      selectedTestCase: null,
      setSelectedTestCase: (id) => set({ selectedTestCase: id }),
      expandedSteps: new Set(),
      toggleStepExpanded: (step) =>
        set((state) => {
          const newSet = new Set(state.expandedSteps);
          if (newSet.has(step)) {
            newSet.delete(step);
          } else {
            newSet.add(step);
          }
          return { expandedSteps: newSet };
        }),

      // Upload State
      uploadProgress: 0,
      setUploadProgress: (progress) => set({ uploadProgress: progress }),
      isUploading: false,
      setIsUploading: (uploading) => set({ isUploading: uploading }),

      // Notifications
      notifications: [],
      addNotification: (type, message) =>
        set((state) => ({
          notifications: [
            ...state.notifications,
            { id: Date.now().toString(), type, message },
          ],
        })),
      removeNotification: (id) =>
        set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== id),
        })),

      // Load Test State
      uploadedApis: null,
      setUploadedApis: (apis) => set({ uploadedApis: apis }),
      selectedLoadTestApi: null,
      setSelectedLoadTestApi: (api) => set({ selectedLoadTestApi: api }),
      loadTestMetrics: null,
      setLoadTestMetrics: (metrics) => set({ loadTestMetrics: metrics }),
      isLoadTesting: false,
      setIsLoadTesting: (testing) => set({ isLoadTesting: testing }),
      activeLoadTestId: null,
      setActiveLoadTestId: (id) => set({ activeLoadTestId: id }),

      // Auto-Execute Mode
      autoExecuteMode: false,
      setAutoExecuteMode: (enabled) => set({ autoExecuteMode: enabled }),

      // Sequential Test State
      sequentialTestId: null,
      setSequentialTestId: (id) => set({ sequentialTestId: id }),
      sequentialTestStatus: null,
      setSequentialTestStatus: (status) => set({ sequentialTestStatus: status }),
      selectedApis: [],
      setSelectedApis: (apis) => set({ selectedApis: apis }),

      // Load Test Session ID
      loadTestSessionId: null,
      setLoadTestSessionId: (id) => set({ loadTestSessionId: id }),

      // Reset - also clears localStorage
      reset: () => {
        // Clear persisted storage
        localStorage.removeItem('test-automation-storage');
        set({
          currentView: 'upload',
          executionMode: 'multi-agent',
          llmProvider: 'openai',
          testSuite: null,
          rawTestCases: null,
          generatedScript: null,
          screenshots: [],
          isExecuting: false,
          executionResult: null,
          selectedTestCase: null,
          expandedSteps: new Set(),
          uploadProgress: 0,
          isUploading: false,
        });
      },
    }),
    {
      name: 'test-automation-storage',
      storage: createJSONStorage(() => localStorage),
      // Only persist these specific fields
      // NOTE: Screenshots are NOT persisted - they are too large for localStorage
      // Screenshots are kept in memory only during the session
      partialize: (state) => ({
        rawTestCases: state.rawTestCases,
        testSuite: state.testSuite,
        executionResult: state.executionResult,
        generatedScript: state.generatedScript,
        // Load test state persistence
        loadTestSessionId: state.loadTestSessionId,
        isLoadTesting: state.isLoadTesting,
        activeLoadTestId: state.activeLoadTestId,
        sequentialTestId: state.sequentialTestId,
        loadTestMetrics: state.loadTestMetrics,
        sequentialTestStatus: state.sequentialTestStatus,
        // screenshots excluded - base64 images exceed localStorage quota
      }),
      // Handle Date serialization on rehydration
      onRehydrateStorage: () => (state) => {
        if (state?.screenshots) {
          state.screenshots = state.screenshots.map(s => ({
            ...s,
            timestamp: new Date(s.timestamp),
          }));
        }
      },
    }
  )
);
