import axios from 'axios';
import type { TestSuite, ExecutionResult } from '../store/useStore';

// Use relative URL for proxy support in development
const API_BASE_URL = '/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // 2 minutes default timeout for long-running operations
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add response interceptor for better error logging
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      // Log detailed error info
      console.error('=== API Error Details ===');
      console.error('Status:', error.response.status);
      console.error('URL:', error.config?.url);
      console.error('Method:', error.config?.method);
      console.error('Response Data:', JSON.stringify(error.response.data, null, 2));
      console.error('Request Body:', error.config?.data);
      console.error('========================');

      // Extract FastAPI validation error details
      if (error.response.status === 422) {
        const responseData = error.response.data;
        if (responseData?.detail) {
          const details = responseData.detail;
          if (Array.isArray(details)) {
            const errorMessages = details.map((d: { loc?: string[]; msg?: string; type?: string }) =>
              `Field: ${d.loc?.join('.')} | Error: ${d.msg} | Type: ${d.type || 'unknown'}`
            ).join('\n');
            console.error('Validation Errors:\n', errorMessages);
            error.message = `Validation error: ${details.map((d: { loc?: string[]; msg?: string }) =>
              `${d.loc?.join('.')}: ${d.msg}`
            ).join('; ')}`;
          } else if (typeof details === 'string') {
            error.message = `Validation error: ${details}`;
          }
        }
      }
    } else if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
      console.error('Request timeout:', error.config?.url);
      error.message = 'Request timed out. The operation is taking longer than expected. Please try again.';
    } else if (error.request) {
      console.error('No response received:', error.request);
      error.message = 'No response from server. Please check your connection.';
    } else {
      console.error('Error setting up request:', error.message);
    }
    return Promise.reject(error);
  }
);

// Response type from upload-excel
export interface UploadResponse {
  filename: string;
  rows: number;
  data: TestCaseRaw[];
}

// Raw test case from Excel
export interface TestCaseRaw {
  'T.C.No': number;
  'Test Case': string;
  'Test Case Steps': string;
  'Expected Result': string;
  [key: string]: unknown;
}

// Health check
export const checkHealth = async (): Promise<{ status: string }> => {
  const response = await api.get('/health');
  return response.data;
};

// Get LLM providers
export const getLLMProviders = async (): Promise<{
  providers: string[];
  default_provider: string;
  configured: Record<string, boolean>;
}> => {
  const response = await api.get('/llm-providers');
  return response.data;
};

// Upload Excel file
export const uploadExcel = async (
  file: File,
  onProgress?: (progress: number) => void
): Promise<UploadResponse> => {
  const formData = new FormData();
  formData.append('file', file);

  const response = await api.post('/upload-excel', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent) => {
      if (progressEvent.total && onProgress) {
        const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        onProgress(progress);
      }
    },
  });

  return response.data;
};

// Response from parse-enhanced API
export interface ParseEnhancedResponse {
  success: boolean;
  message: string;
  llm_provider: string;
  model: string;
  statistics: {
    total_test_cases: number;
    total_steps: number;
    total_assertions: number;
  };
  result: TestSuite;
}

// Parse to enhanced format with LLM provider selection
export const parseEnhanced = async (
  data: TestCaseRaw[],
  projectName?: string,
  baseUrl?: string,
  llmProvider: string = 'groq',
  model: string = 'llama-3.1-8b-instant'
): Promise<ParseEnhancedResponse> => {
  // Build request body - only include base_url if it has a value
  const requestBody: { data: TestCaseRaw[]; project_name: string; base_url?: string } = {
    data,
    project_name: projectName || 'Test Project',
  };

  if (baseUrl) {
    requestBody.base_url = baseUrl;
  }

  // Debug logging
  console.log('=== parseEnhanced Request ===');
  console.log('URL:', `/parse-enhanced?llm_provider=${llmProvider}&model=${model}`);
  console.log('Request Body:', JSON.stringify(requestBody, null, 2));
  console.log('Data items:', data.length);
  console.log('First item:', JSON.stringify(data[0], null, 2));
  console.log('=============================');

  const response = await api.post(
    `/parse-enhanced?llm_provider=${llmProvider}&model=${model}`,
    requestBody,
    { timeout: 180000 } // 3 minutes timeout for LLM parsing
  );

  return response.data;
};


// Upload and parse result type
export interface UploadAndParseResult {
  testSuite: TestSuite;
  rawData: TestCaseRaw[];
}

// Upload and parse in one step
export const uploadAndParse = async (
  file: File,
  projectName?: string,
  baseUrl?: string,
  onProgress?: (progress: number) => void
): Promise<UploadAndParseResult> => {
  const uploadResult = await uploadExcel(file, onProgress);
  const parseResult = await parseEnhanced(uploadResult.data, projectName, baseUrl);
  return {
    testSuite: parseResult.result,
    rawData: uploadResult.data,  // Also return raw data for Deep Agent
  };
};

// Generate script from test suite
export const generateScript = async (
  testSuite: TestSuite
): Promise<{ script: string; test_count: number }> => {
  const response = await api.post('/generate-enhanced-script', testSuite);

  console.log('Raw script generation response:', response.data);

  // The backend returns:
  // {
  //   pytest_script: { filename: "test_suite.py", script: "..." },
  //   individual_scripts: [{ test_id, test_name, filename, script }]
  // }
  let script = '';

  // Try pytest_script.script first (it's an object with { filename, script })
  if (response.data.pytest_script && typeof response.data.pytest_script.script === 'string') {
    script = response.data.pytest_script.script;
    console.log('Extracted pytest_script.script');
  }
  // Try individual_scripts array
  else if (response.data.individual_scripts && Array.isArray(response.data.individual_scripts)) {
    const firstScript = response.data.individual_scripts[0];
    if (firstScript && typeof firstScript.script === 'string') {
      script = firstScript.script;
      console.log('Extracted individual_scripts[0].script');
    }
  }
  // Fallback: direct script property
  else if (typeof response.data.script === 'string') {
    script = response.data.script;
    console.log('Extracted direct script property');
  }

  if (!script) {
    console.warn('Could not extract script string, response keys:', Object.keys(response.data));
  } else {
    console.log('Script extracted, length:', script.length);
  }

  return {
    script,
    test_count: response.data.total_test_cases || 0,
  };
};

// Parse JSON test cases
export const parseJsonTestCases = async (
  data: Record<string, unknown>[],
  projectName?: string,
  baseUrl?: string
): Promise<TestSuite> => {
  const response = await api.post('/parse-json-test-cases', {
    raw_data: data,
    project_name: projectName || 'Test Project',
    base_url: baseUrl,
  });

  return response.data;
};

// Multi-Agent response type
export interface MultiAgentResponse {
  status: 'success' | 'error' | 'completed';
  message: string;
  validation_status: 'passed' | 'failed' | 'needs_retry' | 'unknown';
  summary: {
    total: number;
    passed: number;
    failed: number;
    retries: number;
  };
  execution_results: ExecutionResult;
  parsed_suite: TestSuite | null;
  report: {
    project: string;
    base_url: string;
    generated_at: string;
    stats: {
      total: number;
      passed: number;
      failed: number;
      pass_rate: number;
    };
  } | null;
  generated_script: string | null;
  orchestration: {
    iterations: number;
    action_history: Array<{
      agent: string;
      action: string;
      result: string;
      timestamp: string;
    }>;
    sub_agents_used: string[];
  };
  errors: string[];
  completed_at: string;
}

// Agent Chat types
export interface AgentChatRequest {
  message: string;
  test_cases?: TestCaseRaw[];
  parsed_suite?: TestSuite;
  llm_provider?: string;
  model?: string;
}

export interface AgentChatResponse {
  response: string;
  intent: 'question' | 'execute' | 'list' | 'help' | 'view' | 'error' | 'unknown';
  execute_tests?: string[] | null;
}

// Chat with the agent
export const chatWithAgent = async (
  message: string,
  testCases?: TestCaseRaw[],
  parsedSuite?: TestSuite,
  llmProvider: string = 'groq',
  model?: string,
  chatHistory?: Array<{ role: 'user' | 'assistant'; content: string }>
): Promise<AgentChatResponse> => {
  const response = await api.post<AgentChatResponse>(
    '/agent/chat',
    {
      message,
      test_cases: testCases,
      parsed_suite: parsedSuite,
      llm_provider: llmProvider,
      model,
      chat_history: chatHistory,
    },
    { timeout: 60000 } // 1 minute timeout for LLM responses
  );

  return response.data;
};

// Run Multi-Agent workflow (Supervisor + Sub-agents)
export const executeMultiAgent = async (
  rawData: TestCaseRaw[],
  sessionId: string,
  options: {
    projectName?: string;
    baseUrl?: string;
    llmProvider?: string;
    model?: string;
    headless?: boolean;
    keepBrowserOpen?: boolean;
    timeout?: number;
    maxRetries?: number;
  } = {}
): Promise<MultiAgentResponse> => {
  const {
    projectName = 'Automation Project',
    baseUrl,
    llmProvider = 'groq',
    model,
    headless = true,
    keepBrowserOpen = true,
    timeout = 30000,
    maxRetries = 2,
  } = options;

  const params = new URLSearchParams({
    session_id: sessionId,
    llm_provider: llmProvider,
    project_name: projectName,
    headless: headless.toString(),
    keep_browser_open: keepBrowserOpen.toString(),
    timeout: timeout.toString(),
    max_retries: maxRetries.toString(),
  });

  if (model) {
    params.append('model', model);
  }
  if (baseUrl) {
    params.append('base_url', baseUrl);
  }

  console.log('=== executeMultiAgent Request ===');
  console.log('URL:', `/deep-agent/run-multi-agent?${params.toString()}`);
  console.log('Raw data items:', rawData.length);
  console.log('================================');

  const response = await api.post(
    `/deep-agent/run-multi-agent?${params.toString()}`,
    { raw_data: rawData },
    { timeout: 900000 } // 15 minutes timeout for Multi-Agent
  );

  return response.data;
};

export const getLastResult = async (sessionId: string): Promise<MultiAgentResponse | null> => {
  try {
    const response = await api.get(`/deep-agent/last-result/${sessionId}`, { timeout: 10000 });
    if (response.data?.status === 'not_found') return null;
    return response.data as MultiAgentResponse;
  } catch {
    return null;
  }
};

export const executeFromParsed = async (
  testSuite: object,
  sessionId: string,
  options: {
    headless?: boolean;
    keepBrowserOpen?: boolean;
    timeout?: number;
    maxRetries?: number;
  } = {}
): Promise<MultiAgentResponse> => {
  const {
    headless = true,
    keepBrowserOpen = true,
    timeout = 30000,
    maxRetries = 2,
  } = options;

  const params = new URLSearchParams({
    session_id: sessionId,
    headless: headless.toString(),
    keep_browser_open: keepBrowserOpen.toString(),
    timeout: timeout.toString(),
    max_retries: maxRetries.toString(),
  });

  const response = await api.post(
    `/deep-agent/run-from-parsed?${params.toString()}`,
    testSuite,
    { timeout: 900000 }
  );

  return response.data;
};

// Result from execute-with-script endpoint
export interface ScriptRunResult {
  test_id: string;
  status: 'PASSED' | 'FAILED' | 'ERROR' | 'TIMEOUT';
  stdout: string;
  stderr: string;
  executed_at: string;
}

// Run a single pre-built script string for a given test case
export async function runSingleScript(
  script: string,
  testId: string,
  options: { headless: boolean; timeout: number; sessionId: string }
): Promise<ScriptRunResult> {
  const params = new URLSearchParams({
    session_id: options.sessionId,
    headless: String(options.headless),
    timeout: String(options.timeout),
  });
  const response = await api.post(
    `/deep-agent/execute-with-script?${params}`,
    { script, test_id: testId },
    { timeout: 300000 } // 5 minutes timeout for a single script run
  );
  return response.data;
}

// Stop the currently running test execution for a session
export async function stopExecution(sessionId: string): Promise<void> {
  await api.post(`/deep-agent/stop-execution?session_id=${sessionId}`);
}

// Send a step-level control signal: 'next' marks current step complete, 'skip' skips it
export async function stepControl(sessionId: string, action: 'next' | 'skip'): Promise<void> {
  await api.post(`/deep-agent/step-control?session_id=${sessionId}&action=${action}`);
}

// ─── Active session tracking (survives browser refresh) ─────────────────────
// We store the active session ID in localStorage so that if the user refreshes
// the browser while a test is running, we can kill the backend on next startup.

const ACTIVE_SESSION_KEY = 'agent_active_session_id';

export function saveActiveSession(sessionId: string): void {
  localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
}

export function clearActiveSession(): void {
  localStorage.removeItem(ACTIVE_SESSION_KEY);
}

export function getActiveSession(): string | null {
  return localStorage.getItem(ACTIVE_SESSION_KEY);
}

/**
 * Called once on app startup. If a session ID was saved before a refresh,
 * the backend may still be running — stop it silently.
 */
export async function stopOrphanedSession(): Promise<void> {
  const sessionId = getActiveSession();
  if (!sessionId) return;
  clearActiveSession(); // clear first so a crash here doesn't loop
  try {
    await stopExecution(sessionId);
    console.log('[Startup] Stopped orphaned backend session:', sessionId);
  } catch {
    // Backend may have already finished — ignore errors
  }
}

// ─── Projects API ────────────────────────────────────────────────────────────

export interface ProjectSummary {
  name: string;
  test_count: number;
}

export interface SavedTestMeta {
  filename: string;
  saved_at: string;
  base_url: string;
  test_case_count: number;
}

export async function listProjects(): Promise<ProjectSummary[]> {
  const response = await api.get('/projects/');
  return response.data;
}

export async function createProject(name: string): Promise<{ name: string }> {
  const response = await api.post('/projects/', { name });
  return response.data;
}

export async function listProjectTests(name: string): Promise<SavedTestMeta[]> {
  const response = await api.get(`/projects/${encodeURIComponent(name)}/tests`);
  return response.data;
}

export async function saveTestToProject(name: string, suite: object): Promise<{ filename: string; name: string }> {
  const response = await api.post(`/projects/${encodeURIComponent(name)}/tests`, { suite });
  return response.data;
}

export async function loadTestFromProject(name: string, filename: string): Promise<object> {
  const response = await api.get(`/projects/${encodeURIComponent(name)}/tests/${encodeURIComponent(filename)}`);
  return response.data;
}

export async function deleteProjectTest(name: string, filename: string): Promise<void> {
  await api.delete(`/projects/${encodeURIComponent(name)}/tests/${encodeURIComponent(filename)}`);
}

export async function deleteProject(name: string): Promise<void> {
  await api.delete(`/projects/${encodeURIComponent(name)}`);
}

export interface TokenUsageStats {
  total_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  total_cost_usd: number;
  by_provider: Record<string, {
    calls: number; input_tokens: number;
    output_tokens: number; total_tokens: number; cost_usd: number;
  }>;
  recent_calls: Array<{
    timestamp: string; agent: string; provider: string; model: string;
    input_tokens: number; output_tokens: number; total_tokens: number; cost_usd: number;
  }>;
}
export const fetchTokenUsage = async (): Promise<TokenUsageStats> =>
  (await api.get('/token-usage')).data;
export const resetTokenUsage = async (): Promise<void> => {
  await api.post('/token-usage/reset');
};

export default api;
