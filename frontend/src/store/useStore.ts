import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

const API_BASE_URL = '';

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

type View = 'generate' | 'upload' | 'suite' | 'execution' | 'results' | 'download' | 'loadtest' | 'loadtest-logs' | 'loadtest-reports' | 'loadtest-insights' | 'settings' | 'projects';

export interface ProjectSummary { name: string; test_count: number; }

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
  // Phase 1: Multi-user data support
  test_data?: Array<Record<string, any>>;
  data_mode?: 'sequential' | 'random' | 'round_robin';
  think_time_min?: number;
  think_time_max?: number;
  user_journey?: string;
  variable_mapping?: Record<string, string>;
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
  initializeLlmProvider: () => Promise<void>;

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
  uploadId: string | null;
  setUploadId: (id: string | null) => void;
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

  // Last completed test (for reports/insights display)
  lastCompletedTestId: string | null;
  setLastCompletedTestId: (id: string | null) => void;

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

  // Terminal Logs (persists across navigation)
  terminalLogs: Array<{ timestamp: string; log: string }>;
  addTerminalLog: (log: { timestamp: string; log: string }) => void;
  clearTerminalLogs: () => void;

  // AI Suggested Load Test Config
  aiSuggestedConfig: {
    users?: number;
    spawn_rate?: number;
    run_time?: string;
    think_time_min?: number;
    think_time_max?: number;
  } | null;
  setAiSuggestedConfig: (config: {
    users?: number;
    spawn_rate?: number;
    run_time?: string;
    think_time_min?: number;
    think_time_max?: number;
  } | null) => void;

  // Settings State
  healthCheckEnabled: boolean;
  setHealthCheckEnabled: (enabled: boolean) => void;
  healthCheckInterval: number;  // in minutes (default: 120 = 2 hours)
  setHealthCheckInterval: (interval: number) => void;
  lastHealthCheck: Date | null;
  setLastHealthCheck: (date: Date | null) => void;

  // Application Settings
  useDefaultLandingPage: boolean;
  setUseDefaultLandingPage: (enabled: boolean) => void;
  defaultLandingPage: 'upload' | 'loadtest';  // 'upload' = Functional Test
  setDefaultLandingPage: (page: 'upload' | 'loadtest') => void;

  // Browser Behaviour Settings
  keepBrowserOpenAgent: boolean;  // Functional Test Agent: default false (close between test cases)
  setKeepBrowserOpenAgent: (enabled: boolean) => void;
  liveBrowserEnabled: boolean;    // Show real browser window on server (headless=false)
  setLiveBrowserEnabled: (enabled: boolean) => void;

  // Image Analysis (Vision) Settings
  imageAnalysisEnabled: boolean;
  setImageAnalysisEnabled: (enabled: boolean) => void;

  // Projects
  selectedProjectName: string | null;
  setSelectedProjectName: (name: string | null) => void;

  // Per-project workspace
  activeProjectSection: 'generate' | 'history' | 'suite' | 'execute';
  setActiveProjectSection: (s: 'generate' | 'history' | 'suite' | 'execute') => void;
  projectActiveSuites: Record<string, TestSuite>;
  setProjectActiveSuite: (projectName: string, suite: TestSuite) => void;
  clearProjectActiveSuite: (projectName: string) => void;
  projectExecutionResults: Record<string, ExecutionResult>;
  setProjectExecutionResult: (projectName: string, result: ExecutionResult) => void;

  // Reset
  reset: () => Promise<void>;
}

// ─── Agent Chat Session State ───────────────────────────────────────────────
// Persists to sessionStorage: survives navigation but clears on browser refresh.

export interface AgentMessage {
  id: string;
  type: 'user' | 'agent' | 'system';
  content: string;
  timestamp: string; // ISO string (Date not JSON-serializable directly)
  status?: 'thinking' | 'complete' | 'error';
  testCases?: unknown[];
}

export interface AgentExecutionLog {
  id: string;
  timestamp: string; // ISO string
  type: string;
  testId?: string;
  step?: number;
  status?: string;
  message: string;
  level?: string;
  agent?: string;
  subAgent?: string;
  phase?: string;
  method?: string;
  url?: string;
  payload?: Record<string, unknown>;
  response?: Record<string, unknown>;
  attempt?: number;
  maxRetries?: number;
}

export interface AgentProgressState {
  totalTests: number;
  totalSteps: number;
  completedTests: number;
  completedSteps: number;
  passedTests: number;
  failedTests: number;
}

export interface AgentChatSessionState {
  // Chat messages
  agentMessages: AgentMessage[];
  setAgentMessages: (msgs: AgentMessage[]) => void;
  addAgentMessage: (msg: AgentMessage) => void;

  // Execution state
  agentIsExecuting: boolean;
  setAgentIsExecuting: (v: boolean) => void;
  agentIsProcessing: boolean;
  setAgentIsProcessing: (v: boolean) => void;

  // Live log state
  agentShowLiveLog: boolean;
  setAgentShowLiveLog: (v: boolean) => void;

  // SSE logs
  agentLogs: AgentExecutionLog[];
  setAgentLogs: (logs: AgentExecutionLog[]) => void;
  addAgentLog: (log: AgentExecutionLog) => void;
  clearAgentLogs: () => void;

  // Progress
  agentProgress: AgentProgressState;
  setAgentProgress: (p: AgentProgressState) => void;
  updateAgentProgress: (partial: Partial<AgentProgressState>) => void;

  // Current test/step (transient — reset on reconnect)
  agentCurrentTest: string | null;
  setAgentCurrentTest: (t: string | null) => void;
  agentCurrentStep: number | null;
  setAgentCurrentStep: (s: number | null) => void;

  // Session ID — generated once per browser session
  agentSessionId: string;

  // Clear all execution state
  clearAgentSession: () => void;
}

const generateSessionId = () =>
  `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

const INITIAL_MESSAGES: AgentMessage[] = [
  {
    id: '1',
    type: 'agent',
    content:
      "Hello! I'm your Test Automation Agent. Upload an Excel or JSON file with your test cases, and I'll help you understand and execute them.\n\n**After uploading, you can:**\n\n**Ask questions:**\n• \"What does test 1 do?\"\n• \"Explain the login test steps\"\n• \"How many tests are there?\"\n\n**Run tests:**\n• **\"execute test 2\"** - Run a specific test\n• **\"run test 1, 3, 5\"** - Run multiple tests\n• **\"execute all\"** - Run all tests",
    timestamp: new Date().toISOString(),
    status: 'complete',
  },
];

const INITIAL_PROGRESS: AgentProgressState = {
  totalTests: 0,
  totalSteps: 0,
  completedTests: 0,
  completedSteps: 0,
  passedTests: 0,
  failedTests: 0,
};

// Plain in-memory store (no persistence middleware).
// State lives in JS memory → survives SPA navigation (component unmount/remount)
// but is wiped on browser refresh (F5 / Ctrl+R) exactly as intended.
export const useAgentChatStore = create<AgentChatSessionState>()((set) => ({
  agentMessages: INITIAL_MESSAGES,
  setAgentMessages: (msgs) => set({ agentMessages: msgs }),
  addAgentMessage: (msg) =>
    set((s) => ({ agentMessages: [...s.agentMessages, msg] })),

  agentIsExecuting: false,
  setAgentIsExecuting: (v) => set({ agentIsExecuting: v }),
  agentIsProcessing: false,
  setAgentIsProcessing: (v) => set({ agentIsProcessing: v }),

  agentShowLiveLog: false,
  setAgentShowLiveLog: (v) => set({ agentShowLiveLog: v }),

  agentLogs: [],
  setAgentLogs: (logs) => set({ agentLogs: logs }),
  addAgentLog: (log) =>
    set((s) => {
      const MAX = 500;
      const next = [...s.agentLogs, log];
      return { agentLogs: next.length > MAX ? next.slice(-MAX) : next };
    }),
  clearAgentLogs: () =>
    set({
      agentLogs: [],
      agentProgress: INITIAL_PROGRESS,
      agentCurrentTest: null,
      agentCurrentStep: null,
    }),

  agentProgress: INITIAL_PROGRESS,
  setAgentProgress: (p) => set({ agentProgress: p }),
  updateAgentProgress: (partial) =>
    set((s) => ({ agentProgress: { ...s.agentProgress, ...partial } })),

  agentCurrentTest: null,
  setAgentCurrentTest: (t) => set({ agentCurrentTest: t }),
  agentCurrentStep: null,
  setAgentCurrentStep: (s) => set({ agentCurrentStep: s }),

  agentSessionId: generateSessionId(),

  clearAgentSession: () =>
    set({
      agentMessages: INITIAL_MESSAGES,
      agentIsExecuting: false,
      agentIsProcessing: false,
      agentShowLiveLog: false,
      agentLogs: [],
      agentProgress: INITIAL_PROGRESS,
      agentCurrentTest: null,
      agentCurrentStep: null,
    }),
}));

// ─── Main App Store ──────────────────────────────────────────────────────────

export const useStore = create<AppState>()(
  persist(
    (set) => ({
      // Navigation
      currentView: 'upload',
      setCurrentView: (view) => set({ currentView: view }),

      // Execution Mode (Multi-Agent only)
      executionMode: 'multi-agent',
      setExecutionMode: (mode) => set({ executionMode: mode }),

      // LLM Provider (default to groq - cost-effective and fast)
      llmProvider: 'groq',
      setLlmProvider: (provider) => set({ llmProvider: provider }),
      initializeLlmProvider: async () => {
        try {
          const response = await fetch(`${API_BASE_URL}/api/v1/llm-providers`);
          if (response.ok) {
            const config = await response.json();
            const provider = config.default_provider as LLMProvider;
            if (provider && ['groq', 'openai', 'anthropic'].includes(provider)) {
              set({ llmProvider: provider });
              console.log(`🤖 Initialized LLM provider from backend: ${provider}`);
            } else {
              console.warn(`Unknown provider from backend: ${provider}, keeping default`);
            }
          }
        } catch (error) {
          console.warn('Failed to fetch default LLM provider, using fallback:', error);
          // Keep default 'groq' as fallback
        }
      },

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
      uploadId: null,
      setUploadId: (id) => set({ uploadId: id }),
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

      // Last completed test
      lastCompletedTestId: null,
      setLastCompletedTestId: (id) => set({ lastCompletedTestId: id }),

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

      // Terminal Logs
      terminalLogs: [],
      addTerminalLog: (log) =>
        set((state) => {
          const MAX_LOGS = 1000;
          const newLogs = [...state.terminalLogs, log];
          // Keep only last 1000 logs
          return {
            terminalLogs: newLogs.length > MAX_LOGS ? newLogs.slice(-MAX_LOGS) : newLogs,
          };
        }),
      clearTerminalLogs: () => set({ terminalLogs: [] }),

      // AI Suggested Load Test Config
      aiSuggestedConfig: null,
      setAiSuggestedConfig: (config) => set({ aiSuggestedConfig: config }),

      // Settings State
      healthCheckEnabled: true,
      setHealthCheckEnabled: (enabled) => set({ healthCheckEnabled: enabled }),
      healthCheckInterval: 120,  // 2 hours default
      setHealthCheckInterval: (interval) => set({ healthCheckInterval: interval }),
      lastHealthCheck: null,
      setLastHealthCheck: (date) => set({ lastHealthCheck: date }),

      // Application Settings
      useDefaultLandingPage: false,
      setUseDefaultLandingPage: (enabled) => set({ useDefaultLandingPage: enabled }),
      defaultLandingPage: 'upload',  // Default to Functional Test
      setDefaultLandingPage: (page) => set({ defaultLandingPage: page }),

      // Browser Behaviour Settings
      keepBrowserOpenAgent: false,  // default OFF: browser closes between test cases
      setKeepBrowserOpenAgent: (enabled) => set({ keepBrowserOpenAgent: enabled }),
      liveBrowserEnabled: false,    // default OFF: headless (screenshots in-app)
      setLiveBrowserEnabled: (enabled) => set({ liveBrowserEnabled: enabled }),

      // Projects
      selectedProjectName: null,
      setSelectedProjectName: (name) => set({ selectedProjectName: name }),

      // Per-project workspace
      activeProjectSection: 'generate',
      setActiveProjectSection: (s) => set({ activeProjectSection: s }),
      projectActiveSuites: {},
      setProjectActiveSuite: (projectName, suite) =>
        set((state) => ({ projectActiveSuites: { ...state.projectActiveSuites, [projectName]: suite } })),
      clearProjectActiveSuite: (projectName) =>
        set((state) => {
          const next = { ...state.projectActiveSuites };
          delete next[projectName];
          return { projectActiveSuites: next };
        }),
      projectExecutionResults: {},
      setProjectExecutionResult: (projectName, result) =>
        set((state) => ({ projectExecutionResults: { ...state.projectExecutionResults, [projectName]: result } })),

      // Image Analysis (Vision) Settings — OFF by default
      imageAnalysisEnabled: false,
      setImageAnalysisEnabled: (enabled) => {
        set({ imageAnalysisEnabled: enabled });
        // Sync to backend so the server-side toggle is also updated
        fetch('/api/v1/image-analysis/toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled }),
        }).catch(() => { /* ignore network errors */ });
      },

      // Reset - also clears localStorage
      reset: async () => {
        // Clear persisted storage
        localStorage.removeItem('test-automation-storage');

        // Fetch default provider from backend
        let defaultProvider: LLMProvider = 'groq';
        try {
          const response = await fetch(`${API_BASE_URL}/api/v1/llm-providers`);
          if (response.ok) {
            const config = await response.json();
            defaultProvider = config.default as LLMProvider;
          }
        } catch (error) {
          console.warn('Failed to fetch default LLM provider on reset, using fallback');
        }

        set({
          currentView: 'upload',
          executionMode: 'multi-agent',
          llmProvider: defaultProvider,
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
        terminalLogs: state.terminalLogs,
        // Settings state persistence
        healthCheckEnabled: state.healthCheckEnabled,
        healthCheckInterval: state.healthCheckInterval,
        lastHealthCheck: state.lastHealthCheck,
        // Application settings
        useDefaultLandingPage: state.useDefaultLandingPage,
        defaultLandingPage: state.defaultLandingPage,
        // Browser behaviour settings
        keepBrowserOpenAgent: state.keepBrowserOpenAgent,
        liveBrowserEnabled: state.liveBrowserEnabled,
        // Image analysis settings
        imageAnalysisEnabled: state.imageAnalysisEnabled,
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
        // Restore lastHealthCheck as Date object
        if (state?.lastHealthCheck) {
          state.lastHealthCheck = new Date(state.lastHealthCheck);
        }
      },
    }
  )
);
