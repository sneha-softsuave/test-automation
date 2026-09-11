import { useState, useEffect, useCallback, useRef } from 'react';

export interface StepUpdate {
  type: 'step_update';
  test_id: string;
  step: number;
  status: 'running' | 'passed' | 'failed';
  message: string;
  details: {
    action?: string;
    selector?: string;
    error?: string;
  };
}

export interface TestUpdate {
  type: 'test_update';
  test_id: string;
  status: 'running' | 'passed' | 'failed';
  message: string;
}

export interface ExecutionStart {
  type: 'execution_start';
  total_tests: number;
  total_steps: number;
}

export interface ExecutionComplete {
  type: 'execution_complete';
  passed: number;
  failed: number;
  total: number;
}

export interface LogMessage {
  type: 'log';
  level: 'info' | 'error' | 'warn';
  message: string;
}

export interface ScreenshotMessage {
  type: 'screenshot';
  test_id: string;
  step: number;
  status: 'passed' | 'failed' | 'progress' | 'running';
  image: string;  // base64 encoded
  url: string;
  title: string;
}

export interface ApiCallMessage {
  type: 'api_call';
  method: string;
  url: string;
  payload: Record<string, unknown>;
  response: Record<string, unknown>;
}

// Deep Agent specific message types
export interface AgentPhaseMessage {
  type: 'agent_phase';
  phase: 'starting' | 'parse' | 'execute' | 'validate' | 'error_recovery' | 'report' | 'complete';
  message: string;
}

export interface NodeStartedMessage {
  type: 'node_started';
  node: 'parse' | 'execute' | 'validate' | 'report' | 'error_recovery';
  message: string;
}

export interface NodeCompletedMessage {
  type: 'node_completed';
  node: 'parse' | 'execute' | 'validate' | 'report' | 'error_recovery';
  status?: 'success' | 'error';
  message: string;
  data?: Record<string, unknown>;
}

export interface ThoughtsMessage {
  type: 'thoughts';
  message: string;
}

export interface DeepAgentCompleteMessage {
  type: 'deep_agent_complete';
  status?: 'success' | 'error';
  message: string;
  data?: {
    status: string;
    passed: number;
    failed: number;
    total: number;
    has_script: boolean;
  };
}

export type WebSocketMessage =
  | StepUpdate
  | TestUpdate
  | ExecutionStart
  | ExecutionComplete
  | LogMessage
  | ScreenshotMessage
  | ApiCallMessage
  | AgentPhaseMessage
  | NodeStartedMessage
  | NodeCompletedMessage
  | ThoughtsMessage
  | DeepAgentCompleteMessage;

export interface ExecutionLog {
  id: string;
  timestamp: Date;
  type: WebSocketMessage['type'] | 'delegation' | 'sub_agent_started' | 'sub_agent_completed' | 'test_started' | 'test_completed' | 'step_started' | 'step_completed' | 'execution_started' | 'execution_completed' | 'browser_status' | 'step_retry' | 'step_retry_success' | 'step_retry_exhausted';
  testId?: string;
  step?: number;
  status?: string;
  message: string;
  level?: string;
  // Agent info for styling
  agent?: string;
  subAgent?: string;
  phase?: string;
  // API call specific
  method?: string;
  url?: string;
  payload?: Record<string, unknown>;
  response?: Record<string, unknown>;
  // Retry info
  attempt?: number;
  maxRetries?: number;
}

export interface BrowserState {
  screenshot: string | null;
  url: string;
  title: string;
  currentStep: number;
  status: 'idle' | 'running' | 'passed' | 'failed';
}

export interface ScreenshotHistoryItem {
  id: string;
  testId: string;
  step: number;
  status: 'running' | 'passed' | 'failed';
  image: string;
  url: string;
  title: string;
  timestamp: Date;
}

export type ActiveAgent = 'Supervisor' | 'Parser' | 'Executor' | 'Validator' | 'Reporter' | null;

export interface LiveExcelRow {
  testId: string;
  tcNo: number;
  testName: string;
  stepsText: string;
  expectedResult: string;
  inputData: string;
  status: 'pending' | 'running' | 'passed' | 'failed';
  currentStep: number;   // 0 = none active
  totalSteps: number;
  error: string | null;
}

export interface UseExecutionWebSocketReturn {
  isConnected: boolean;
  sessionId: string;
  logs: ExecutionLog[];
  currentTest: string | null;
  currentStep: number | null;
  currentAgent: ActiveAgent;
  progress: {
    totalTests: number;
    totalSteps: number;
    completedTests: number;
    completedSteps: number;
    passedTests: number;
    failedTests: number;
  };
  browserState: BrowserState;
  screenshots: ScreenshotHistoryItem[];
  liveExcelRows: LiveExcelRow[];
  connect: () => void;
  disconnect: () => void;
  clearLogs: () => void;
  addLog: (log: Omit<ExecutionLog, 'id' | 'timestamp'>) => void;
}

export const useExecutionWebSocket = (
  fixedSessionId?: string,
  onDeepAgentComplete?: (data: Record<string, unknown>) => void,
): UseExecutionWebSocketReturn => {
  const [isConnected, setIsConnected] = useState(false);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [currentTest, setCurrentTest] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState<number | null>(null);
  const [currentAgent, setCurrentAgent] = useState<ActiveAgent>(null);
  const [screenshots, setScreenshots] = useState<ScreenshotHistoryItem[]>([]);
  const [progress, setProgress] = useState({
    totalTests: 0,
    totalSteps: 0,
    completedTests: 0,
    completedSteps: 0,
    passedTests: 0,
    failedTests: 0,
  });
  const [browserState, setBrowserState] = useState<BrowserState>({
    screenshot: null,
    url: '',
    title: '',
    currentStep: 0,
    status: 'idle',
  });
  const [liveExcelRows, setLiveExcelRows] = useState<LiveExcelRow[]>([]);

  const eventSourceRef = useRef<EventSource | null>(null);
  const onDeepAgentCompleteRef = useRef(onDeepAgentComplete);
  onDeepAgentCompleteRef.current = onDeepAgentComplete;
  // Use the provided fixed session ID (for persistence) or generate a new one
  const sessionIdRef = useRef<string>(
    fixedSessionId ?? `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  );

  const addLog = useCallback((log: Omit<ExecutionLog, 'id' | 'timestamp'>) => {
    setLogs((prev) => [
      ...prev,
      {
        ...log,
        id: `log_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        timestamp: new Date(),
      },
    ]);
  }, []);

  // Helper to map agent names to ActiveAgent type
  const mapToActiveAgent = useCallback((agentName: string | undefined): ActiveAgent => {
    if (!agentName) return null;
    const normalized = agentName.toLowerCase();
    if (normalized.includes('parser') || normalized === 'parse') return 'Parser';
    if (normalized.includes('executor') || normalized === 'execute') return 'Executor';
    if (normalized.includes('validator') || normalized === 'validate') return 'Validator';
    if (normalized.includes('reporter') || normalized === 'report') return 'Reporter';
    if (normalized.includes('supervisor')) return 'Supervisor';
    return null;
  }, []);

  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);
      console.log('📨 SSE message received:', data.type);

      // Extract agent info from any event
      const eventAgent = data.agent || data.sub_agent || null;

      switch (data.type) {
        case 'connected':
          console.log('✅ SSE connection confirmed by server');
          break;

        case 'execution_start':
          setProgress({
            totalTests: data.total_tests,
            totalSteps: data.total_steps,
            completedTests: 0,
            completedSteps: 0,
            passedTests: 0,
            failedTests: 0,
          });
          setBrowserState((prev) => ({ ...prev, status: 'running' }));
          // Set initial agent to Supervisor when orchestration starts
          setCurrentAgent('Supervisor');
          addLog({
            type: 'execution_start',
            agent: eventAgent || 'Executor',
            message: `Starting execution: ${data.total_tests} tests, ${data.total_steps} steps`,
          });
          break;

        case 'test_update':
          setCurrentTest(data.test_id);
          if (data.status === 'running') {
            addLog({
              type: 'test_update',
              testId: data.test_id,
              status: data.status,
              agent: eventAgent || 'Executor',
              message: data.message,
            });
          } else {
            setProgress((prev) => ({
              ...prev,
              completedTests: prev.completedTests + 1,
              passedTests: data.status === 'passed' ? prev.passedTests + 1 : prev.passedTests,
              failedTests: data.status === 'failed' ? prev.failedTests + 1 : prev.failedTests,
            }));
            addLog({
              type: 'test_update',
              testId: data.test_id,
              status: data.status,
              agent: eventAgent || 'Executor',
              message: data.message,
            });
          }
          break;

        case 'step_update':
          setCurrentStep(data.step);
          setBrowserState((prev) => ({
            ...prev,
            currentStep: data.step,
            status: data.status === 'running' ? 'running' : data.status === 'passed' ? 'passed' : 'failed',
          }));
          if (data.status !== 'running') {
            setProgress((prev) => ({
              ...prev,
              completedSteps: prev.completedSteps + 1,
            }));
          }
          addLog({
            type: 'step_update',
            testId: data.test_id,
            step: data.step,
            status: data.status,
            agent: eventAgent || 'Executor',
            message: data.message,
          });
          break;

        case 'screenshot':
          console.log('📸 Screenshot received:', {
            step: data.step,
            status: data.status,
            imageLength: data.image?.length || 0
          });
          setBrowserState({
            screenshot: data.image,
            url: data.url,
            title: data.title,
            currentStep: data.step,
            status: data.status === 'passed' ? 'passed' : data.status === 'failed' ? 'failed' : 'running',
          });
          // Store completed step screenshots in history
          if (data.status === 'passed' || data.status === 'failed') {
            setScreenshots((prev) => [
              ...prev,
              {
                id: `screenshot_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                testId: data.test_id,
                step: data.step,
                status: data.status,
                image: data.image,
                url: data.url,
                title: data.title,
                timestamp: new Date(),
              },
            ]);
          }
          break;

        case 'api_call':
          addLog({
            type: 'api_call',
            method: data.method,
            url: data.url,
            payload: data.payload,
            response: data.response,
            message: `${data.method} ${data.url}`,
          });
          break;

        case 'log':
          addLog({
            type: 'log',
            level: data.level,
            agent: eventAgent,
            message: data.message,
          });
          break;

        case 'execution_complete':
          setCurrentTest(null);
          setCurrentStep(null);
          setCurrentAgent(null);
          setBrowserState((prev) => ({ ...prev, status: 'idle' }));
          setProgress((prev) => ({
            ...prev,
            completedTests: data.total,
            passedTests: data.passed,
            failedTests: data.failed,
          }));
          addLog({
            type: 'execution_complete',
            agent: eventAgent || 'Executor',
            message: `Execution complete: ${data.passed}/${data.total} passed`,
          });
          break;

        // Deep Agent specific events
        case 'agent_phase':
          console.log('🤖 Agent phase:', data.phase, data.message);
          addLog({
            type: 'agent_phase',
            level: 'info',
            agent: 'Supervisor',
            phase: data.phase,
            message: data.message,
          });
          break;

        case 'node_started':
          console.log('🔄 Node started:', data.node);
          // Update current agent when node starts
          const nodeAgent = mapToActiveAgent(data.node);
          if (nodeAgent) {
            setCurrentAgent(nodeAgent);
          }
          addLog({
            type: 'node_started',
            level: 'info',
            agent: data.node,
            message: data.message,
          });
          break;

        case 'node_completed':
          console.log('✅ Node completed:', data.node, data.status);
          // After node completes, supervisor takes over
          setCurrentAgent('Supervisor');
          addLog({
            type: 'node_completed',
            level: data.status === 'error' ? 'error' : 'info',
            agent: data.node,
            status: data.status,
            message: data.message,
          });
          break;

        case 'thoughts':
          console.log('💭 Agent thoughts:', data.message);
          addLog({
            type: 'thoughts',
            level: 'info',
            agent: data.agent || 'Supervisor',
            message: data.message,
          });
          break;

        case 'deep_agent_complete':
          console.log('🎉 Deep Agent complete:', data);
          setCurrentTest(null);
          setCurrentStep(null);
          setCurrentAgent(null);
          setBrowserState((prev) => ({ ...prev, status: 'idle' }));
          if (data.data) {
            setProgress((prev) => ({
              ...prev,
              completedTests: data.data?.total ?? prev.completedTests,
              passedTests: data.data?.passed ?? prev.passedTests,
              failedTests: data.data?.failed ?? prev.failedTests,
            }));
          }
          addLog({
            type: 'execution_complete',
            message: `[Deep Agent] ${data.message}`,
          });
          // Notify caller so it can resolve the result without waiting for HTTP response
          if (onDeepAgentCompleteRef.current) {
            onDeepAgentCompleteRef.current(data);
          }
          break;

        case 'execution_started':
          // Handle execution_started event (from Deep Agent execute node)
          setProgress({
            totalTests: data.total_tests || 0,
            totalSteps: data.total_steps || 0,
            completedTests: 0,
            completedSteps: 0,
            passedTests: 0,
            failedTests: 0,
          });
          setBrowserState((prev) => ({ ...prev, status: 'running' }));
          addLog({
            type: 'execution_started',
            agent: eventAgent || 'Executor',
            message: data.message || `Starting execution: ${data.total_tests} tests`,
          });
          break;

        case 'execution_completed':
          // Handle execution_completed event from subprocess
          setCurrentTest(null);
          setCurrentStep(null);
          setBrowserState((prev) => ({ ...prev, status: 'idle' }));
          setProgress((prev) => ({
            ...prev,
            completedTests: data.total || prev.totalTests,
            passedTests: data.passed || 0,
            failedTests: data.failed || 0,
          }));
          addLog({
            type: 'execution_completed',
            agent: eventAgent || 'Executor',
            message: data.message || `Execution complete: ${data.passed}/${data.total} passed`,
          });
          break;

        case 'browser_status':
          // Handle browser launch/close status
          console.log('🌐 Browser status:', data.status, data.message);
          addLog({
            type: 'browser_status',
            level: 'info',
            agent: 'Browser',
            message: data.message,
          });
          if (data.status === 'ready') {
            setBrowserState((prev) => ({ ...prev, status: 'running' }));
          } else if (data.status === 'closed') {
            setBrowserState((prev) => ({ ...prev, status: 'idle' }));
          }
          break;

        case 'test_started':
          // Handle individual test start
          console.log('🧪 Test started:', data.test_id);
          setCurrentTest(data.test_id);
          setProgress((prev) => ({
            ...prev,
            totalTests: data.total_tests || prev.totalTests,
          }));
          addLog({
            type: 'test_started',
            testId: data.test_id,
            status: 'running',
            agent: eventAgent || 'Executor',
            message: data.message || `Starting test: ${data.test_name}`,
          });
          break;

        case 'test_completed':
          // Handle individual test completion
          console.log('🧪 Test completed:', data.test_id, data.status);
          setProgress((prev) => ({
            ...prev,
            completedTests: prev.completedTests + 1,
            passedTests: data.status === 'PASSED' ? prev.passedTests + 1 : prev.passedTests,
            failedTests: data.status === 'FAILED' ? prev.failedTests + 1 : prev.failedTests,
          }));
          setLiveExcelRows(prev => prev.map(r =>
            r.testId === data.test_id
              ? { ...r, status: data.status === 'PASSED' ? 'passed' : 'failed', currentStep: 0 }
              : r
          ));
          addLog({
            type: 'test_completed',
            testId: data.test_id,
            status: data.status === 'PASSED' ? 'passed' : 'failed',
            agent: eventAgent || 'Executor',
            message: data.message || `Test ${data.status}: ${data.test_name}`,
          });
          break;

        case 'excel_row_init':
          setLiveExcelRows(prev => [...prev, {
            testId: data.test_id,
            tcNo: data.tc_no,
            testName: data.test_name,
            stepsText: data.steps_text,
            expectedResult: data.expected_result,
            inputData: data.input_data,
            status: 'running',
            currentStep: 0,
            totalSteps: data.total_steps,
            error: null,
          }]);
          break;

        case 'step_started':
          // Handle step start
          console.log('📍 Step started:', data.step_number);
          setCurrentStep(data.step_number);
          setCurrentTest(data.test_id);
          setBrowserState((prev) => ({
            ...prev,
            currentStep: data.step_number,
            status: 'running',
          }));
          setLiveExcelRows(prev => prev.map(r =>
            r.testId === data.test_id ? { ...r, currentStep: data.step_number } : r
          ));
          addLog({
            type: 'step_started',
            testId: data.test_id,
            step: data.step_number,
            status: 'running',
            agent: eventAgent || 'Executor',
            message: data.message || `Step ${data.step_number}: ${data.action}`,
          });
          break;

        case 'step_completed':
          // Handle step completion
          console.log('📍 Step completed:', data.step_number, data.status);
          setBrowserState((prev) => ({
            ...prev,
            currentStep: data.step_number,
            status: data.status === 'PASSED' ? 'passed' : data.status === 'FAILED' ? 'failed' : prev.status,
          }));
          setProgress((prev) => ({
            ...prev,
            completedSteps: prev.completedSteps + 1,
          }));
          if (data.status === 'FAILED' && data.error) {
            setLiveExcelRows(prev => prev.map(r =>
              r.testId === data.test_id ? { ...r, error: data.error } : r
            ));
          }
          addLog({
            type: 'step_completed',
            testId: data.test_id,
            step: data.step_number,
            status: data.status === 'PASSED' ? 'passed' : 'failed',
            agent: eventAgent || 'Executor',
            message: data.message || `Step ${data.step_number} ${data.status}`,
          });
          break;

        case 'delegation':
          // Handle supervisor delegation events
          console.log('📤 Delegation:', data.sub_agent, data.message);
          // Map sub_agent names to our ActiveAgent type
          const delegatedAgent = mapToActiveAgent(data.sub_agent);
          if (delegatedAgent) {
            setCurrentAgent(delegatedAgent);
          }
          addLog({
            type: 'delegation',
            level: 'info',
            agent: 'Supervisor',
            subAgent: data.sub_agent,
            message: data.message,
          });
          break;

        case 'sub_agent_started':
          // Handle sub-agent start
          console.log('🤖 Sub-agent started:', data.node);
          const startedAgent = mapToActiveAgent(data.node);
          if (startedAgent) {
            setCurrentAgent(startedAgent);
          }
          addLog({
            type: 'sub_agent_started',
            level: 'info',
            agent: data.node || 'Agent',
            message: data.message,
          });
          break;

        case 'sub_agent_completed':
          // Handle sub-agent completion
          console.log('✅ Sub-agent completed:', data.node, data.status);
          // After agent completes, supervisor takes over
          setCurrentAgent('Supervisor');
          addLog({
            type: 'sub_agent_completed',
            level: data.status === 'error' ? 'error' : 'info',
            agent: data.node || 'Agent',
            status: data.status,
            message: data.message,
          });
          break;

        // Step-level retry events
        case 'step_retry':
          // Handle step retry (step failed, retrying with alternative selectors)
          console.log('🔄 Step retry:', data.step_number, `attempt ${data.attempt}/${data.max_retries}`);
          addLog({
            type: 'step_retry',
            level: 'warn',
            testId: data.test_id,
            step: data.step_number,
            agent: eventAgent || 'Executor',
            attempt: data.attempt,
            maxRetries: data.max_retries,
            message: data.message || `Step ${data.step_number} failed, retrying (${data.attempt}/${data.max_retries})...`,
          });
          break;

        case 'step_retry_success':
          // Handle step retry success (step passed on retry)
          console.log('✅ Step retry success:', data.step_number, `attempt ${data.attempt}`);
          addLog({
            type: 'step_retry_success',
            level: 'info',
            testId: data.test_id,
            step: data.step_number,
            status: 'passed',
            agent: eventAgent || 'Executor',
            attempt: data.attempt,
            message: data.message || `Step ${data.step_number} succeeded on retry ${data.attempt}`,
          });
          break;

        case 'step_retry_exhausted':
          // Handle step retry exhausted (step failed after all retries)
          console.log('❌ Step retry exhausted:', data.step_number, `after ${data.total_attempts} attempts`);
          addLog({
            type: 'step_retry_exhausted',
            level: 'error',
            testId: data.test_id,
            step: data.step_number,
            status: 'failed',
            agent: eventAgent || 'Executor',
            message: data.message || `Step ${data.step_number} failed after ${data.total_attempts} attempts`,
          });
          break;

        default:
          // Handle unknown event types gracefully
          console.log('📨 Unknown SSE event:', data.type, data);
          if (data.message) {
            addLog({
              type: 'log',
              level: 'info',
              message: data.message,
            });
          }
          break;
      }
    } catch (error) {
      console.error('Failed to parse SSE message:', error);
    }
  }, [addLog, mapToActiveAgent]);

  const connect = useCallback(() => {
    // Always close any existing connection before opening a new one.
    // Avoids the stale-connection bug where a second run gets no events
    // because the old EventSource is still assigned but the server session ended.
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      setIsConnected(false);
    }

    const sessionId = sessionIdRef.current;
    const sseUrl = `/api/v1/sse/${sessionId}`;

    console.log('📡 Connecting to SSE:', sseUrl);

    try {
      const eventSource = new EventSource(sseUrl);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        console.log('✅ SSE connected successfully');
        setIsConnected(true);
        addLog({
          type: 'log',
          level: 'info',
          message: 'Connected to execution server',
        });
      };

      eventSource.onmessage = handleMessage;

      eventSource.onerror = (error) => {
        console.error('❌ SSE error:', error, 'readyState:', eventSource.readyState);
        // Only mark as disconnected when fully closed — not during transient
        // CONNECTING states which the browser handles automatically.
        if (eventSource.readyState === EventSource.CLOSED) {
          console.log('📡 SSE closed, marking disconnected');
          setIsConnected(false);
        }
        // If readyState is CONNECTING (0), the browser is auto-reconnecting — stay connected.
      };
    } catch (error) {
      console.error('SSE connection error:', error);
    }
  }, [addLog, handleMessage]);

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const clearLogs = useCallback(() => {
    setLogs([]);
    setScreenshots([]);
    setLiveExcelRows([]);
    setProgress({
      totalTests: 0,
      totalSteps: 0,
      completedTests: 0,
      completedSteps: 0,
      passedTests: 0,
      failedTests: 0,
    });
    setCurrentTest(null);
    setCurrentStep(null);
    setBrowserState({
      screenshot: null,
      url: '',
      title: '',
      currentStep: 0,
      status: 'idle',
    });
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    isConnected,
    sessionId: sessionIdRef.current,
    logs,
    currentTest,
    currentStep,
    currentAgent,
    progress,
    browserState,
    screenshots,
    liveExcelRows,
    connect,
    disconnect,
    addLog,
    clearLogs,
  };
};
