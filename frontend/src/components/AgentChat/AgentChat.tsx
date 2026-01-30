import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload,
  FileSpreadsheet,
  FileJson,
  Send,
  Bot,
  User,
  Loader2,
  CheckCircle,
  Zap,
  Brain,
  Code,
  Play,
  List,
  Terminal,
  XCircle,
  Activity,
  Wifi,
  WifiOff,
  CircleDot,
  Monitor,
  Globe,
  ExternalLink,
  FileText,
  Cpu,
  Shield,
  FileCheck,
  ArrowRight,
  Sparkles,
  ChevronDown,
  Image,
  Clock,
  Rocket,
  BarChart3,
  TrendingUp,
} from 'lucide-react';
import { useStore, LLM_OPTIONS, type LLMProvider } from '../../store/useStore';
import { uploadExcel, executeMultiAgent, chatWithAgent } from '../../services/api';
import type { TestCaseRaw, UploadResponse, AgentChatResponse } from '../../services/api';
import { useExecutionWebSocket } from '../../hooks/useExecutionWebSocket';
import type { ExecutionLog } from '../../hooks/useExecutionWebSocket';
import { TerminalDisplay } from '../TerminalDisplay/TerminalDisplay';
import { AgentAtomDiagram } from '../AgentAtomDiagram/AgentAtomDiagram';
import styles from './AgentChat.module.css';

interface Message {
  id: string;
  type: 'user' | 'agent' | 'system';
  content: string;
  timestamp: Date;
  status?: 'thinking' | 'complete' | 'error';
  testCases?: TestCaseRaw[];
}

interface ThinkingStep {
  id: string;
  icon: React.ElementType;
  text: string;
  status: 'pending' | 'active' | 'complete' | 'error';
  detail?: string;
}

type AgentPhase = 'thinking' | 'planning' | 'executing' | 'debugging' | 'complete';

interface AgentThought {
  id: string;
  phase: AgentPhase;
  text: string;
  timestamp: Date;
}

interface AgentTodo {
  id: string;
  text: string;
  status: 'pending' | 'in_progress' | 'done' | 'error';
}

export const AgentChat = () => {
  const { setExecutionResult, setCurrentView, addNotification, setRawTestCases, clearScreenshots, setGeneratedScript, setTestSuite, rawTestCases, llmProvider, setLlmProvider } = useStore();
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      type: 'agent',
      content: "Hello! I'm your Test Automation Agent. Upload an Excel or JSON file with your test cases, and I'll help you understand and execute them.\n\n**After uploading, you can:**\n\n**Ask questions:**\n• \"What does test 1 do?\"\n• \"Explain the login test steps\"\n• \"How many tests are there?\"\n\n**Run tests:**\n• **\"execute test 2\"** - Run a specific test\n• **\"run test 1, 3, 5\"** - Run multiple tests\n• **\"execute all\"** - Run all tests",
      timestamp: new Date(),
      status: 'complete',
    },
  ]);
  const [inputValue, setInputValue] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [thinkingSteps, _setThinkingSteps] = useState<ThinkingStep[]>([]);
  const [agentThoughts, setAgentThoughts] = useState<AgentThought[]>([]);
  const [agentTodos, setAgentTodos] = useState<AgentTodo[]>([]);
  const [currentPhase, setCurrentPhase] = useState<AgentPhase | null>(null);
  const [rawData, setRawData] = useState<TestCaseRaw[] | null>(null);
  const [uploadResponse, setUploadResponse] = useState<UploadResponse | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [showLiveLog, setShowLiveLog] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [selectedScreenshotIndex, setSelectedScreenshotIndex] = useState<number | null>(null);
  const [showScreenshotDropdown, setShowScreenshotDropdown] = useState(false);

  // Use LLM_OPTIONS from store (centralized config)
  const llmOptions = LLM_OPTIONS;

  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Hook for execution logs and browser state
  const {
    isConnected,
    sessionId,
    logs,
    currentTest,
    currentStep,
    currentAgent,
    progress,
    browserState,
    screenshots,
    connect,
    disconnect,
    clearLogs,
    addLog,
  } = useExecutionWebSocket();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const scrollLogToBottom = () => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, thinkingSteps]);

  useEffect(() => {
    if (showLiveLog) {
      scrollLogToBottom();
    }
  }, [logs, showLiveLog]);

  // Auto-show live log when execution starts
  useEffect(() => {
    if (isExecuting && logs.length > 0 && !showLiveLog) {
      setShowLiveLog(true);
    }
  }, [isExecuting, logs.length, showLiveLog]);

  // Get setScreenshots from store
  const { setScreenshots: setGlobalScreenshots } = useStore();

  // Sync screenshots from hook to global store for reports
  // Limit to last 50 screenshots to prevent memory issues
  // Use setScreenshots to replace the array instead of adding duplicates
  useEffect(() => {
    if (screenshots.length > 0) {
      try {
        // Keep only the last 50 screenshots to prevent memory overflow
        const limitedScreenshots = screenshots.slice(-50);
        setGlobalScreenshots(limitedScreenshots.map((screenshot) => ({
          id: screenshot.id,
          testId: screenshot.testId,
          step: screenshot.step,
          status: screenshot.status,
          image: screenshot.image,
          url: screenshot.url,
          title: screenshot.title,
          timestamp: screenshot.timestamp,
        })));
      } catch (error) {
        console.warn('Failed to sync screenshots to store:', error);
      }
    }
  }, [screenshots, setGlobalScreenshots]);

  // Close screenshot dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (showScreenshotDropdown && !target.closest(`.${styles.screenshotSelector}`)) {
        setShowScreenshotDropdown(false);
      }
    };

    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, [showScreenshotDropdown]);

  // Initialize rawData from persisted store on mount
  useEffect(() => {
    if (rawTestCases && rawTestCases.length > 0 && !rawData) {
      setRawData(rawTestCases);
      // Show welcome back message with restored data
      const testList = rawTestCases.map(tc =>
        `**${tc['T.C.No']}** - ${tc['Test Case']}`
      ).join('\n');

      setMessages([{
        id: '1',
        type: 'agent',
        content: `Welcome back! I've restored your **${rawTestCases.length} test case(s)**:\n\n${testList}\n\n` +
          `What would you like to do?\n` +
          `• **"execute test 1"** - Run specific test\n` +
          `• **"execute all"** - Run all tests\n` +
          `• Ask me anything about your tests!`,
        timestamp: new Date(),
        status: 'complete',
      }]);
    }
  }, [rawTestCases, rawData]);

  const addMessage = (
    type: Message['type'],
    content: string,
    status?: Message['status'],
    testCases?: TestCaseRaw[]
  ) => {
    const newMessage: Message = {
      id: Date.now().toString(),
      type,
      content,
      timestamp: new Date(),
      status,
      testCases,
    };
    setMessages((prev) => [...prev, newMessage]);
    return newMessage.id;
  };

  const addThought = (phase: AgentPhase, text: string) => {
    const thought: AgentThought = {
      id: `thought_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      phase,
      text,
      timestamp: new Date(),
    };
    setAgentThoughts((prev) => [...prev, thought]);
    setCurrentPhase(phase);
  };

  const setTodos = (todos: { text: string; status?: AgentTodo['status'] }[]) => {
    setAgentTodos(todos.map((t, i) => ({
      id: `todo_${Date.now()}_${i}`,
      text: t.text,
      status: t.status || 'pending',
    })));
  };

  const updateTodo = (index: number, status: AgentTodo['status']) => {
    setAgentTodos((prev) =>
      prev.map((t, i) => (i === index ? { ...t, status } : t))
    );
  };

  const clearAgentState = () => {
    setAgentThoughts([]);
    setAgentTodos([]);
    setCurrentPhase(null);
  };

  const handleFileSelect = async (file: File) => {
    const validTypes = ['.xlsx', '.xls', '.json'];
    const isValid = validTypes.some((type) => file.name.toLowerCase().endsWith(type));

    if (!isValid) {
      addThought('debugging', 'Invalid file type detected');
      addMessage('agent', "I can only process Excel (.xlsx, .xls) or JSON files. Please upload a valid file.", 'error');
      clearAgentState();
      return;
    }

    setUploadedFile(file);
    addMessage('user', `Uploaded: ${file.name}`);

    setIsProcessing(true);
    clearAgentState();

    // Phase 1: Thinking
    addThought('thinking', 'Analyzing the uploaded file...');
    await new Promise((r) => setTimeout(r, 300));
    addThought('thinking', `File type: ${file.name.endsWith('.json') ? 'JSON' : 'Excel spreadsheet'}`);
    await new Promise((r) => setTimeout(r, 200));
    addThought('thinking', `File size: ${(file.size / 1024).toFixed(1)} KB`);

    // Phase 2: Planning
    await new Promise((r) => setTimeout(r, 400));
    addThought('planning', 'Creating execution plan...');
    setTodos([
      { text: 'Upload file to server', status: 'in_progress' },
      { text: 'Parse document structure' },
      { text: 'Extract test cases' },
      { text: 'Validate test data' },
    ]);

    try {
      // Log API call
      addLog({
        type: 'api_call',
        method: 'POST',
        url: '/api/v1/upload-excel',
        payload: { filename: file.name, size: file.size },
        response: { status: 'sending' },
        message: 'POST /api/v1/upload-excel',
      });

      // Phase 3: Executing
      await new Promise((r) => setTimeout(r, 300));
      addThought('executing', 'Uploading file to server...');

      const response = await uploadExcel(file);
      setUploadResponse(response);
      setRawData(response.data);
      setRawTestCases(response.data); // Save to global store for reports

      updateTodo(0, 'done');
      addThought('executing', `Server received ${response.rows} rows`);

      // Log API response
      addLog({
        type: 'api_call',
        method: 'POST',
        url: '/api/v1/upload-excel',
        payload: { filename: file.name },
        response: { rows: response.rows, test_cases: response.data.length },
        message: `Response: ${response.rows} rows, ${response.data.length} test cases`,
      });

      await new Promise((r) => setTimeout(r, 300));
      updateTodo(1, 'in_progress');
      addThought('executing', 'Parsing document structure...');
      await new Promise((r) => setTimeout(r, 400));
      updateTodo(1, 'done');
      addThought('executing', 'Document structure parsed successfully');

      updateTodo(2, 'in_progress');
      addThought('executing', 'Extracting test cases...');
      await new Promise((r) => setTimeout(r, 300));
      updateTodo(2, 'done');
      addThought('executing', `Found ${response.data.length} test case(s)`);

      updateTodo(3, 'in_progress');
      addThought('executing', 'Validating test data...');
      await new Promise((r) => setTimeout(r, 300));
      updateTodo(3, 'done');

      // Phase 4: Complete
      addThought('complete', 'File processed successfully!');
      await new Promise((r) => setTimeout(r, 500));
      clearAgentState();

      // Build test case list
      const testCaseList = response.data.map((tc) =>
        `**${tc['T.C.No']}** - ${tc['Test Case']}`
      ).join('\n');

      addMessage(
        'agent',
        `I found **${response.data.length} test case(s)** in "${response.filename}":\n\n${testCaseList}\n\n` +
        `What would you like to do?\n` +
        `• **"execute test 1"** - Run specific test\n` +
        `• **"execute test 1, 2, 3"** - Run multiple tests\n` +
        `• **"execute all"** - Run all tests`,
        'complete',
        response.data
      );

    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Failed to process file';

      // Phase: Debugging
      addThought('debugging', `Error encountered: ${errorMsg}`);
      await new Promise((r) => setTimeout(r, 300));
      addThought('debugging', 'Analyzing error...');
      await new Promise((r) => setTimeout(r, 400));
      addThought('debugging', 'Possible causes: Invalid file format or server issue');

      // Mark remaining todos as error
      setAgentTodos((prev) =>
        prev.map((t) => (t.status === 'pending' || t.status === 'in_progress' ? { ...t, status: 'error' } : t))
      );

      await new Promise((r) => setTimeout(r, 500));
      clearAgentState();
      addMessage('agent', `Error: ${errorMsg}. Please try uploading again.`, 'error');
    } finally {
      setIsProcessing(false);
    }
  };

  const executeTests = async (testNumbers: number[] | 'all') => {
    if (!rawData || rawData.length === 0) {
      addMessage('agent', "Please upload a test file first.", 'error');
      return;
    }

    // Filter test cases
    let selectedTests: TestCaseRaw[];
    let testDescription: string;

    if (testNumbers === 'all') {
      selectedTests = rawData;
      testDescription = `all ${rawData.length} test case(s)`;
    } else {
      selectedTests = rawData.filter((tc) => testNumbers.includes(tc['T.C.No']));
      if (selectedTests.length === 0) {
        const available = rawData.map((tc) => tc['T.C.No']).join(', ');
        addMessage('agent', `No test cases found with number(s): ${testNumbers.join(', ')}.\n\nAvailable test numbers: ${available}`, 'error');
        return;
      }
      testDescription = selectedTests.length === 1
        ? `Test Case ${selectedTests[0]['T.C.No']}: "${selectedTests[0]['Test Case']}"`
        : `${selectedTests.length} test case(s): ${selectedTests.map(t => t['T.C.No']).join(', ')}`;
    }

    setIsProcessing(true);
    setIsExecuting(true);
    clearLogs();
    clearAgentState();
    clearScreenshots(); // Clear previous screenshots for new execution
    setSelectedScreenshotIndex(null); // Reset to live view for new execution

    // Connect to SSE for real-time updates
    connect();

    // Wait for connection to establish (up to 2 seconds)
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, 100));
      if (isConnected) {
        console.log('✅ SSE connected after', (i + 1) * 100, 'ms');
        break;
      }
    }

    // Show live panel
    setShowLiveLog(true);

    // Phase 1: Thinking
    addThought('thinking', `Analyzing ${testDescription}...`);
    await new Promise((r) => setTimeout(r, 300));
    addThought('thinking', 'Determining execution strategy...');

    // Phase 2: Planning
    await new Promise((r) => setTimeout(r, 400));
    addThought('planning', 'Creating test execution plan...');
    setTodos([
      { text: `Initialize LLM (${llmOptions[llmProvider].label} - ${llmOptions[llmProvider].model})`, status: 'in_progress' },
      { text: 'Parse test steps with AI' },
      { text: 'Generate element selectors' },
      { text: 'Launch browser and execute' },
      { text: 'Collect and validate results' },
    ]);

    try {
      // Log API call - Multi-Agent
      addLog({
        type: 'api_call',
        method: 'POST',
        url: `/api/v1/deep-agent/run-multi-agent?session_id=${sessionId}`,
        payload: { test_cases: selectedTests.length },
        response: { status: 'sending' },
        message: 'POST /api/v1/deep-agent/run-multi-agent',
      });

      // Phase 3: Executing - Multi-Agent
      await new Promise((r) => setTimeout(r, 400));
      addThought('executing', `Starting Multi-Agent orchestration...`);
      updateTodo(0, 'done');

      addMessage('agent', `Running ${testDescription} with Multi-Agent...`, 'thinking');

      updateTodo(1, 'in_progress');
      addThought('executing', 'ParserAgent analyzing test cases...');

      // Call Multi-Agent API - it handles parsing, execution, validation, and reporting
      // headless: true means browser runs in background, screenshots shown in app
      const result = await executeMultiAgent(
        selectedTests,
        sessionId,
        {
          projectName: uploadResponse?.filename || 'Test Project',
          llmProvider: llmProvider,  // Use selected LLM provider
          model: llmOptions[llmProvider].model,  // Use corresponding model
          headless: true,
          timeout: 30000,
          maxRetries: 2,
        }
      );

      // Log API response
      addLog({
        type: 'api_call',
        method: 'POST',
        url: '/api/v1/deep-agent/run-multi-agent',
        payload: {},
        response: {
          total: result.summary.total,
          passed: result.summary.passed,
          failed: result.summary.failed,
        },
        message: `Response: ${result.summary.passed}/${result.summary.total} passed`,
      });

      updateTodo(1, 'done');
      addThought('executing', `ParserAgent completed parsing`);

      updateTodo(2, 'in_progress');
      addThought('executing', 'ExecutorAgent running tests...');
      await new Promise((r) => setTimeout(r, 300));
      updateTodo(2, 'done');
      addThought('executing', `ExecutorAgent completed`);

      updateTodo(3, 'in_progress');
      addThought('executing', 'ValidatorAgent analyzing results...');
      await new Promise((r) => setTimeout(r, 300));
      updateTodo(3, 'done');

      updateTodo(4, 'in_progress');
      addThought('executing', 'ReporterAgent generating report...');
      await new Promise((r) => setTimeout(r, 300));
      updateTodo(4, 'done');

      // Phase: Complete
      addThought('complete', `Execution complete: ${result.summary.passed}/${result.summary.total} passed`);
      await new Promise((r) => setTimeout(r, 500));
      clearAgentState();

      // Set execution result from Multi-Agent response
      if (result.execution_results) {
        setExecutionResult(result.execution_results);
      }
      setIsExecuting(false);

      // Set parsed test suite to enable Test Suite and Execute tabs
      if (result.parsed_suite) {
        setTestSuite(result.parsed_suite);
        console.log('Parsed test suite saved to store');
      }

      // Set generated script if available from Multi-Agent
      if (result.generated_script) {
        setGeneratedScript(result.generated_script);
        console.log('Playwright script from Multi-Agent saved');
      }

      // Build result summary
      const statusIcon = result.summary.failed > 0 ? '⚠️' : '✅';
      const resultSummary = result.execution_results?.results?.map((r: { test_id: string; status: string; steps?: Array<{ status: string }> }) => {
        const icon = r.status === 'PASSED' ? '✅' : '❌';
        const stepsInfo = r.steps ? `(${r.steps.filter((s: { status: string }) => s.status === 'PASSED').length}/${r.steps.length} steps)` : '';
        return `${icon} **${r.test_id}**: ${r.status} ${stepsInfo}`;
      }).join('\n') || 'No detailed results available';

      addMessage(
        'agent',
        `${statusIcon} **Multi-Agent Execution Complete**\n\n` +
        `**Sub-agents used:** ${result.orchestration?.sub_agents_used?.join(', ') || 'ParserAgent, ExecutorAgent, ValidatorAgent, ReporterAgent'}\n\n` +
        `**Results:**\n${resultSummary}\n\n` +
        `**Summary:** ${result.summary.passed}/${result.summary.total} passed` +
        (result.summary.retries > 0 ? ` (${result.summary.retries} retries)` : '') +
        `\n\nType **"view results"** to see detailed results, or execute another test.`,
        'complete'
      );

      addNotification(
        result.summary.failed > 0 ? 'warning' : 'success',
        `Multi-Agent complete: ${result.summary.passed}/${result.summary.total} passed`
      );

    } catch (error) {
      setIsExecuting(false);
      const errorMsg = error instanceof Error ? error.message : 'Execution failed';

      // Phase: Debugging
      addThought('debugging', `Error encountered: ${errorMsg}`);
      await new Promise((r) => setTimeout(r, 300));
      addThought('debugging', 'Analyzing failure...');
      await new Promise((r) => setTimeout(r, 400));
      addThought('debugging', 'Check: Network connectivity, API availability, test data validity');

      // Mark remaining todos as error
      setAgentTodos((prev) =>
        prev.map((t) => (t.status === 'pending' || t.status === 'in_progress' ? { ...t, status: 'error' } : t))
      );

      await new Promise((r) => setTimeout(r, 500));
      clearAgentState();

      addMessage('agent', `❌ **Execution Failed**\n\nError: ${errorMsg}`, 'error');
      addNotification('error', errorMsg);
      addLog({
        type: 'log',
        level: 'error',
        message: `Execution failed: ${errorMsg}`,
      });
    } finally {
      setIsProcessing(false);
      // Disconnect SSE after execution
      setTimeout(() => disconnect(), 2000);
    }
  };

  const handleCommand = async (command: string) => {
    const cmd = command.toLowerCase().trim();

    // Clear command - handle locally
    if (cmd === 'clear' || cmd === 'reset') {
      setMessages([{
        id: '1',
        type: 'agent',
        content: "Chat cleared! Upload a new file to get started.\n\nYou can ask me questions about your test cases or use commands like **\"execute test 1\"**.",
        timestamp: new Date(),
        status: 'complete',
      }]);
      setUploadedFile(null);
      setRawData(null);
      setRawTestCases(null);
      setUploadResponse(null);
      clearLogs();
      setShowLiveLog(false);
      return;
    }

    // View commands - handle locally
    if (cmd === 'view' || cmd === 'view suite' || cmd === 'show suite') {
      if (useStore.getState().testSuite) {
        setCurrentView('suite');
      } else {
        addMessage('user', command);
        addMessage('agent', "No test suite available. Please upload and parse a file first.", 'error');
      }
      return;
    }

    if (cmd === 'view results' || cmd === 'results' || cmd === 'show results') {
      if (useStore.getState().executionResult) {
        setCurrentView('results');
      } else {
        addMessage('user', command);
        addMessage('agent', "No results available. Please execute tests first.", 'error');
      }
      return;
    }

    // Add user message
    addMessage('user', command);

    // Show thinking indicator
    setIsProcessing(true);
    addThought('thinking', 'Understanding your request...');

    try {
      // Call the chat API
      const response: AgentChatResponse = await chatWithAgent(
        command,
        rawData || undefined,
        useStore.getState().testSuite || undefined,
        llmProvider,
        llmOptions[llmProvider].model
      );

      clearAgentState();

      // Handle response based on intent
      switch (response.intent) {
        case 'execute':
          // Execute tests
          if (response.execute_tests === null) {
            // Execute all
            await executeTests('all');
          } else if (response.execute_tests && response.execute_tests.length > 0) {
            // Execute specific tests
            await executeTests(response.execute_tests);
          } else {
            addMessage('agent', response.response, 'error');
          }
          break;

        case 'list':
        case 'help':
        case 'question':
          // Display the response
          addMessage('agent', response.response, 'complete');
          break;

        case 'view':
          addMessage('agent', response.response, 'complete');
          break;

        case 'error':
          addMessage('agent', response.response, 'error');
          break;

        default:
          addMessage('agent', response.response, 'complete');
      }

    } catch (error) {
      clearAgentState();
      const errorMsg = error instanceof Error ? error.message : 'Failed to process your request';
      addMessage('agent', `Sorry, I encountered an error: ${errorMsg}`, 'error');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim() || isProcessing) return;

    const command = inputValue.trim();
    setInputValue('');
    handleCommand(command);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  };

  const getLogIcon = (log: ExecutionLog) => {
    const agent = log.agent?.toLowerCase() || '';
    const subAgent = log.subAgent?.toLowerCase() || '';
    const type = log.type?.toLowerCase() || '';

    // For delegation events, show icon based on target agent
    if (type === 'delegation' && subAgent) {
      if (subAgent.includes('parser')) return <FileText size={16} />;
      if (subAgent.includes('executor')) return <Cpu size={16} />;
      if (subAgent.includes('validator')) return <Shield size={16} />;
      if (subAgent.includes('reporter')) return <FileCheck size={16} />;
      return <ArrowRight size={16} />;
    }

    // Agent-specific icons
    if (agent.includes('parser') || agent === 'parse') return <FileText size={16} />;
    if (agent.includes('executor') || agent === 'execute') return <Cpu size={16} />;
    if (agent.includes('validator') || agent === 'validate') return <Shield size={16} />;
    if (agent.includes('reporter') || agent === 'report') return <FileCheck size={16} />;
    if (agent.includes('supervisor')) return <Bot size={16} />;
    if (agent === 'browser') return <Globe size={16} />;

    // Event-type specific icons
    if (type === 'thoughts') return <Brain size={16} />;
    if (type === 'agent_phase') return <Sparkles size={16} />;
    if (type.includes('browser')) return <Globe size={16} />;

    // Default type-based icons
    switch (log.type) {
      case 'execution_start':
        return <Play size={16} />;
      case 'test_update':
        return log.status === 'passed' ? <CheckCircle size={16} /> :
               log.status === 'failed' ? <XCircle size={16} /> :
               <CircleDot size={16} />;
      case 'step_update':
        return log.status === 'passed' ? <CheckCircle size={16} /> :
               log.status === 'failed' ? <XCircle size={16} /> :
               <Loader2 size={16} className={styles.spinnerSmall} />;
      case 'execution_complete':
        return <Zap size={16} />;
      case 'api_call':
        return <Code size={16} />;
      case 'log':
        return log.level === 'error' ? <XCircle size={16} /> :
               log.level === 'warn' ? <Activity size={16} /> :
               <Terminal size={16} />;
      // Step retry icons
      case 'step_retry':
        return <Loader2 size={16} className={styles.spinnerSmall} />;
      case 'step_retry_success':
        return <CheckCircle size={16} />;
      case 'step_retry_exhausted':
        return <XCircle size={16} />;
      default:
        return <Activity size={16} />;
    }
  };

  const getLogClass = (log: ExecutionLog) => {
    // Check for agent-specific styling first
    const agent = log.agent?.toLowerCase() || '';
    const subAgent = log.subAgent?.toLowerCase() || '';
    const type = log.type?.toLowerCase() || '';

    // For delegation events, color based on the sub-agent being delegated to
    if (type === 'delegation' && subAgent) {
      if (subAgent.includes('parser')) return styles.logParser;
      if (subAgent.includes('executor')) return styles.logExecutor;
      if (subAgent.includes('validator')) return styles.logValidator;
      if (subAgent.includes('reporter')) return styles.logReporter;
      return styles.logDelegation;
    }

    // Check agent field for agent-specific coloring
    if (agent.includes('parser') || agent === 'parse') return styles.logParser;
    if (agent.includes('executor') || agent === 'execute') return styles.logExecutor;
    if (agent.includes('validator') || agent === 'validate') return styles.logValidator;
    if (agent.includes('reporter') || agent === 'report') return styles.logReporter;
    if (agent.includes('supervisor')) return styles.logSupervisor;
    if (agent === 'browser') return styles.logBrowser;

    // Check event type for coloring
    if (type === 'thoughts') return styles.logThoughts;
    if (type === 'agent_phase') return styles.logSupervisor;
    if (type.includes('browser')) return styles.logBrowser;

    // Step retry event types
    if (type === 'step_retry') return styles.logStepRetry;
    if (type === 'step_retry_success') return styles.logStepRetrySuccess;
    if (type === 'step_retry_exhausted') return styles.logStepRetryExhausted;

    // Fall back to status-based styling
    if (log.status === 'passed') return styles.logPassed;
    if (log.status === 'failed') return styles.logFailed;
    if (log.status === 'running') return styles.logRunning;
    if (log.type === 'api_call') return styles.logApi;
    if (log.type === 'execution_start') return styles.logStart;
    if (log.type === 'execution_complete') return styles.logComplete;
    if (log.type === 'test_update') return styles.logTest;
    if (log.level === 'error') return styles.logError;
    if (log.level === 'warn') return styles.logWarn;
    return styles.logInfo;
  };

  const getLogTypeLabel = (log: ExecutionLog): string | null => {
    const agent = log.agent?.toLowerCase() || '';
    const subAgent = log.subAgent?.toLowerCase() || '';
    const type = log.type?.toLowerCase() || '';

    // For delegation events, show the target agent
    if (type === 'delegation' && log.subAgent) {
      return log.subAgent.replace('Agent', '');
    }

    // For sub_agent and node events, show formatted agent name
    if (type === 'sub_agent_started' || type === 'sub_agent_completed' || type === 'node_started' || type === 'node_completed') {
      const agentMap: Record<string, string> = {
        'parse': 'Parser',
        'execute': 'Executor',
        'validate': 'Validator',
        'report': 'Reporter',
        'error_recovery': 'Recovery',
      };
      return agentMap[agent] || log.agent || 'Agent';
    }

    // For thoughts, show Thoughts label
    if (type === 'thoughts') return 'Thoughts';

    // For agent_phase, show Phase label
    if (type === 'agent_phase') return 'Phase';

    // Step retry labels
    if (type === 'step_retry') return 'RETRY';
    if (type === 'step_retry_success') return 'RETRY OK';
    if (type === 'step_retry_exhausted') return 'RETRY FAIL';

    // Check if agent field indicates a specific agent
    if (agent.includes('parser') || agent === 'parse') return 'Parser';
    if (agent.includes('executor') || agent === 'execute') return 'Executor';
    if (agent.includes('validator') || agent === 'validate') return 'Validator';
    if (agent.includes('reporter') || agent === 'report') return 'Reporter';
    if (agent.includes('supervisor')) return 'Supervisor';
    if (agent === 'browser') return 'Browser';

    // Default labels
    switch (log.type) {
      case 'execution_start': return 'START';
      case 'execution_complete': return 'DONE';
      case 'test_update': return 'TEST';
      case 'step_update': return null; // Hide badge, step number shown in message
      case 'api_call': return null; // Hide badge, method shown in message
      case 'log': return log.level?.toUpperCase() || 'LOG';
      default: return null;
    }
  };

  const formatLogMessage = (log: ExecutionLog): React.ReactNode => {
    switch (log.type) {
      case 'execution_start':
        return (
          <span className={styles.logMessageText}>
            Starting execution with <strong>{log.message.match(/\d+/g)?.[0] || '?'}</strong> tests
          </span>
        );
      case 'execution_complete':
        return (
          <span className={styles.logMessageText}>
            Completed: <strong className={styles.successText}>{log.message.match(/\d+/g)?.[0] || '?'}</strong>/<strong>{log.message.match(/\d+/g)?.[1] || '?'}</strong> passed
          </span>
        );
      case 'test_update':
        return (
          <span className={styles.logMessageText}>
            <strong>{log.testId}</strong> — {log.status === 'running' ? 'Running...' : log.status === 'passed' ? 'Passed' : 'Failed'}
          </span>
        );
      case 'step_update':
        return (
          <span className={styles.logMessageText}>
            <span className={styles.stepBadge}>Step {log.step}</span>
            {log.message.length > 60 ? log.message.substring(0, 60) + '...' : log.message}
          </span>
        );
      case 'api_call':
        return (
          <span className={styles.logMessageText}>
            <span className={`${styles.methodBadge} ${styles[`method${log.method}`]}`}>{log.method}</span>
            <span className={styles.apiPath}>{log.url?.split('?')[0]}</span>
          </span>
        );
      default:
        return <span className={styles.logMessageText}>{log.message}</span>;
    }
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <motion.div
        className={styles.header}
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className={styles.headerIcon}>
          <Bot size={28} />
          <div className={styles.headerPulse} />
        </div>
        <div className={styles.headerText}>
          <h1 className={styles.title}>Test Automation Agent</h1>
          <p className={styles.subtitle}>
            {isProcessing ? (
              <span className={styles.processingText}>
                <Loader2 size={14} className={styles.spinnerSmall} />
                Processing...
              </span>
            ) : rawData ? (
              <span className={styles.readyText}>
                <CheckCircle size={14} />
                {rawData.length} test case(s) loaded
              </span>
            ) : (
              'Upload a file to get started'
            )}
          </p>
        </div>
        {/* LLM Provider Selector */}
        <div className={styles.llmSelector}>
          <Brain size={16} />
          <select
            value={llmProvider}
            onChange={(e) => setLlmProvider(e.target.value as LLMProvider)}
            className={styles.llmSelect}
            disabled={isProcessing || isExecuting}
          >
            <option value="groq">Groq (Fast)</option>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
      </motion.div>

      {/* Main Content Area */}
      <div className={`${styles.mainContent} ${!showLiveLog ? styles.splitView : ''}`}>
        {/* AI Dashboard Panel - Shows when not executing */}
        {!showLiveLog && (
          <motion.div
            className={styles.aiDashboardPanel}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5 }}
          >
            <div className={styles.dashboardHeader}>
              <div className={styles.dashboardIcon}>
                <Sparkles size={20} />
              </div>
              <div className={styles.dashboardTitle}>
                <h3>AI Test Automation</h3>
                <p>Deep Agent Orchestration</p>
              </div>
            </div>

            <div className={styles.agentVisual}>
              <div className={styles.agentOrbit}>
                <div className={styles.orbitRing} />
                <div className={styles.orbitRing} style={{ animationDelay: '-2s' }} />
                <div className={styles.orbitCenter}>
                  <Brain size={32} />
                </div>
                <div className={styles.orbitDot} style={{ animationDelay: '0s' }}><Code size={14} /></div>
                <div className={styles.orbitDot} style={{ animationDelay: '-1.5s' }}><Zap size={14} /></div>
                <div className={styles.orbitDot} style={{ animationDelay: '-3s' }}><Shield size={14} /></div>
                <div className={styles.orbitDot} style={{ animationDelay: '-4.5s' }}><FileCheck size={14} /></div>
              </div>
            </div>

            <div className={styles.dashboardStats}>
              <div className={styles.statItem}>
                <Rocket size={18} />
                <div>
                  <span className={styles.statValue}>{rawData?.length || 0}</span>
                  <span className={styles.statLabel}>Test Cases</span>
                </div>
              </div>
              <div className={styles.statItem}>
                <BarChart3 size={18} />
                <div>
                  <span className={styles.statValue}>{progress.passedTests || 0}</span>
                  <span className={styles.statLabel}>Passed</span>
                </div>
              </div>
              <div className={styles.statItem}>
                <TrendingUp size={18} />
                <div>
                  <span className={styles.statValue}>
                    {progress.totalTests > 0
                      ? Math.round((progress.passedTests / progress.totalTests) * 100)
                      : 0}%
                  </span>
                  <span className={styles.statLabel}>Success Rate</span>
                </div>
              </div>
            </div>

            <div className={styles.dashboardTips}>
              <h4>Quick Start</h4>
              <ul>
                <li><FileSpreadsheet size={14} /> Upload Excel test cases</li>
                <li><Send size={14} /> Type "execute all" to run tests</li>
                <li><Brain size={14} /> Ask questions about your tests</li>
              </ul>
            </div>
          </motion.div>
        )}

        {/* Chat Area */}
        <div
          className={`${styles.chatArea} ${isDragging ? styles.dragging : ''} ${showLiveLog ? styles.withLog : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <AnimatePresence>
            {isDragging && (
              <motion.div
                className={styles.dragOverlay}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <Upload size={48} />
                <span>Drop your file here</span>
              </motion.div>
            )}
          </AnimatePresence>

          <div className={styles.messages}>
            <AnimatePresence>
              {messages.map((message) => (
                <motion.div
                  key={message.id}
                  className={`${styles.message} ${styles[message.type]} ${message.status === 'error' ? styles.error : ''}`}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}
                >
                  <div className={styles.messageIcon}>
                    {message.type === 'agent' ? (
                      message.status === 'error' ? <XCircle size={20} /> : <Bot size={20} />
                    ) : (
                      <User size={20} />
                    )}
                  </div>
                  <div className={styles.messageContent}>
                    <div className={styles.messageText}>
                      {message.content.split('\n').map((line, i) => (
                        <p key={i} dangerouslySetInnerHTML={{
                          __html: line
                            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                            .replace(/`(.+?)`/g, '<code>$1</code>')
                        }} />
                      ))}
                    </div>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>

            {/* AI Thinking Panel */}
            <AnimatePresence>
              {(agentThoughts.length > 0 || agentTodos.length > 0) && (
                <motion.div
                  className={styles.agentPanel}
                  initial={{ opacity: 0, y: 20, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -10, scale: 0.98 }}
                  transition={{ duration: 0.3 }}
                >
                  {/* Phase Indicator */}
                  <div className={`${styles.phaseIndicator} ${styles[currentPhase || 'thinking']}`}>
                    <div className={styles.phaseIcon}>
                      {currentPhase === 'thinking' && <Brain size={18} />}
                      {currentPhase === 'planning' && <List size={18} />}
                      {currentPhase === 'executing' && <Zap size={18} />}
                      {currentPhase === 'debugging' && <XCircle size={18} />}
                      {currentPhase === 'complete' && <CheckCircle size={18} />}
                    </div>
                    <span className={styles.phaseText}>
                      {currentPhase === 'thinking' && 'Thinking...'}
                      {currentPhase === 'planning' && 'Planning'}
                      {currentPhase === 'executing' && 'Executing'}
                      {currentPhase === 'debugging' && 'Debugging'}
                      {currentPhase === 'complete' && 'Complete'}
                    </span>
                    {currentPhase && currentPhase !== 'complete' && (
                      <Loader2 size={14} className={styles.phaseSpinner} />
                    )}
                  </div>

                  {/* Thoughts Stream */}
                  <div className={styles.thoughtsStream}>
                    {agentThoughts.map((thought, index) => (
                      <motion.div
                        key={thought.id}
                        className={`${styles.thought} ${styles[thought.phase]}`}
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.2, delay: index * 0.05 }}
                      >
                        <span className={styles.thoughtDot} />
                        <span className={styles.thoughtText}>{thought.text}</span>
                      </motion.div>
                    ))}
                  </div>

                  {/* Todo List */}
                  {agentTodos.length > 0 && (
                    <div className={styles.todoList}>
                      <div className={styles.todoHeader}>
                        <List size={14} />
                        <span>Plan</span>
                      </div>
                      {agentTodos.map((todo, index) => (
                        <motion.div
                          key={todo.id}
                          className={`${styles.todoItem} ${styles[todo.status]}`}
                          initial={{ opacity: 0, x: -10 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ duration: 0.2, delay: index * 0.1 }}
                        >
                          <div className={styles.todoCheck}>
                            {todo.status === 'done' && <CheckCircle size={14} />}
                            {todo.status === 'in_progress' && <Loader2 size={14} className={styles.spinner} />}
                            {todo.status === 'pending' && <CircleDot size={14} />}
                            {todo.status === 'error' && <XCircle size={14} />}
                          </div>
                          <span className={styles.todoText}>{todo.text}</span>
                        </motion.div>
                      ))}
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>

            {/* Agent Atom Diagram - Shows during execution */}
            {/* HIDDEN FOR DEMO - Uncomment to restore
            <AnimatePresence>
              {isExecuting && (
                <AgentAtomDiagram
                  currentAgent={currentAgent}
                  isExecuting={isExecuting}
                />
              )}
            </AnimatePresence>
            */}

            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Live Execution Panel - Bottom Panel - Show when executing OR when screenshots available */}
        <AnimatePresence>
          {(isExecuting || screenshots.length > 0) && (
        <motion.div
          className={styles.liveLogPanel}
          initial={{ opacity: 0, y: 100, height: 0 }}
          animate={{ opacity: 1, y: 0, height: 'auto' }}
          exit={{ opacity: 0, y: 100, height: 0 }}
          transition={{ duration: 0.3 }}
        >
          {/* Header */}
          <div className={styles.liveLogHeader}>
            <div className={styles.liveLogTitle}>
              <Monitor size={18} />
              <span>{isExecuting ? 'Live Execution' : 'Execution Results'}</span>
              {isExecuting ? (
                <span className={styles.liveIndicator}>
                  <span className={styles.liveDot} />
                  LIVE
                </span>
              ) : screenshots.length > 0 && (
                <span className={styles.completedIndicator}>
                  <CheckCircle size={12} />
                  {screenshots.length} screenshots
                </span>
              )}
            </div>
            <div className={styles.connectionStatus}>
              {isExecuting ? (
                isConnected ? (
                  <span className={styles.connected}>
                    <Wifi size={14} />
                    Connected
                  </span>
                ) : (
                  <span className={styles.disconnected}>
                    <WifiOff size={14} />
                    Offline
                  </span>
                )
              ) : (
                <button
                  className={styles.closeResultsBtn}
                  onClick={() => {
                    clearLogs();
                    setSelectedScreenshotIndex(null);
                  }}
                  title="Close results panel"
                >
                  <XCircle size={16} />
                </button>
              )}
            </div>
          </div>

          {/* Left Section - Browser View */}
          <div className={styles.browserSection}>
            {/* Screenshot History Dropdown */}
            {screenshots.length > 0 && (
              <div className={styles.screenshotSelector}>
                <button
                  className={styles.screenshotDropdownBtn}
                  onClick={() => setShowScreenshotDropdown(!showScreenshotDropdown)}
                >
                  <Image size={14} />
                  <span>
                    {selectedScreenshotIndex !== null
                      ? `Step ${screenshots[selectedScreenshotIndex]?.step} - ${screenshots[selectedScreenshotIndex]?.testId}`
                      : isExecuting ? 'Live View' : `${screenshots.length} Screenshots`
                    }
                  </span>
                  <ChevronDown size={14} className={showScreenshotDropdown ? styles.rotated : ''} />
                </button>

                <AnimatePresence>
                  {showScreenshotDropdown && (
                    <motion.div
                      className={styles.screenshotDropdown}
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                    >
                      {isExecuting && (
                        <button
                          className={`${styles.screenshotOption} ${selectedScreenshotIndex === null ? styles.active : ''}`}
                          onClick={() => {
                            setSelectedScreenshotIndex(null);
                            setShowScreenshotDropdown(false);
                          }}
                        >
                          <Monitor size={14} />
                          <span>Live View</span>
                          <span className={styles.liveBadge}>LIVE</span>
                        </button>
                      )}
                      {screenshots.map((ss, index) => (
                        <button
                          key={ss.id}
                          className={`${styles.screenshotOption} ${selectedScreenshotIndex === index ? styles.active : ''}`}
                          onClick={() => {
                            setSelectedScreenshotIndex(index);
                            setShowScreenshotDropdown(false);
                          }}
                        >
                          <span className={`${styles.stepBadge} ${styles[ss.status]}`}>
                            Step {ss.step}
                          </span>
                          <span className={styles.screenshotTestId}>{ss.testId}</span>
                          <span className={styles.screenshotTime}>
                            {ss.timestamp.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                          </span>
                          {ss.status === 'passed' && <CheckCircle size={12} className={styles.passedIcon} />}
                          {ss.status === 'failed' && <XCircle size={12} className={styles.failedIcon} />}
                        </button>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}

            <div className={styles.browserView}>
              <div className={styles.browserChrome}>
                <div className={styles.browserDots}>
                  <span className={styles.dotRed} />
                  <span className={styles.dotYellow} />
                  <span className={styles.dotGreen} />
                </div>
                <div className={styles.browserUrl}>
                  <Globe size={12} />
                  <span>
                    {selectedScreenshotIndex !== null && screenshots[selectedScreenshotIndex]
                      ? screenshots[selectedScreenshotIndex].url
                      : browserState.url || 'about:blank'
                    }
                  </span>
                  {(selectedScreenshotIndex !== null ? screenshots[selectedScreenshotIndex]?.url : browserState.url) && (
                    <a
                      href={selectedScreenshotIndex !== null ? screenshots[selectedScreenshotIndex]?.url : browserState.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <ExternalLink size={12} />
                    </a>
                  )}
                </div>
              </div>

              <div className={`${styles.browserScreen} ${
                selectedScreenshotIndex !== null && screenshots[selectedScreenshotIndex]
                  ? styles[screenshots[selectedScreenshotIndex].status]
                  : styles[browserState.status]
              }`}>
                {/* Show selected screenshot from history or live screenshot */}
                {selectedScreenshotIndex !== null && screenshots[selectedScreenshotIndex] ? (
                  <img
                    src={`data:image/png;base64,${screenshots[selectedScreenshotIndex].image}`}
                    alt={`Screenshot Step ${screenshots[selectedScreenshotIndex].step}`}
                    className={styles.screenshot}
                  />
                ) : browserState.screenshot ? (
                  <img
                    src={`data:image/jpeg;base64,${browserState.screenshot}`}
                    alt="Browser Screenshot"
                    className={styles.screenshot}
                  />
                ) : screenshots.length > 0 ? (
                  // Show last screenshot when execution is done
                  <img
                    src={`data:image/png;base64,${screenshots[screenshots.length - 1].image}`}
                    alt="Last Screenshot"
                    className={styles.screenshot}
                  />
                ) : (
                  <div className={styles.browserPlaceholder}>
                    <Monitor size={48} />
                    <span>Browser preview</span>
                    <span className={styles.placeholderSubtext}>Screenshots appear here during execution</span>
                  </div>
                )}

                {/* Step indicator */}
                {selectedScreenshotIndex !== null && screenshots[selectedScreenshotIndex] ? (
                  <div className={styles.stepIndicator}>
                    Step {screenshots[selectedScreenshotIndex].step}
                  </div>
                ) : browserState.currentStep > 0 && (
                  <div className={styles.stepIndicator}>Step {browserState.currentStep}</div>
                )}

                {/* Status overlay */}
                {selectedScreenshotIndex !== null && screenshots[selectedScreenshotIndex] ? (
                  <>
                    {screenshots[selectedScreenshotIndex].status === 'passed' && (
                      <div className={`${styles.statusOverlay} ${styles.passed}`}>
                        <CheckCircle size={18} />
                      </div>
                    )}
                    {screenshots[selectedScreenshotIndex].status === 'failed' && (
                      <div className={`${styles.statusOverlay} ${styles.failed}`}>
                        <XCircle size={18} />
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    {browserState.status === 'passed' && (
                      <div className={`${styles.statusOverlay} ${styles.passed}`}>
                        <CheckCircle size={18} />
                      </div>
                    )}
                    {browserState.status === 'failed' && (
                      <div className={`${styles.statusOverlay} ${styles.failed}`}>
                        <XCircle size={18} />
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>

            {/* Progress */}
            {progress.totalSteps > 0 && (
              <div className={styles.progressSection}>
                <div className={styles.progressBar}>
                  <motion.div
                    className={styles.progressFill}
                    initial={{ width: 0 }}
                    animate={{ width: `${(progress.completedSteps / progress.totalSteps) * 100}%` }}
                  />
                </div>
                <div className={styles.progressStats}>
                  <span>Steps: {progress.completedSteps}/{progress.totalSteps}</span>
                  <span>Tests: {progress.completedTests}/{progress.totalTests}</span>
                  {progress.completedTests > 0 && (
                    <span className={styles.passFailStats}>
                      <span className={styles.passed}>{progress.passedTests}✓</span>
                      <span className={styles.failed}>{progress.failedTests}✗</span>
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Current Status */}
            {currentTest && (
              <div className={styles.currentStatus}>
                <Activity size={12} />
                <span>{currentTest}{currentStep && ` • Step ${currentStep}`}</span>
              </div>
            )}
          </div>

          {/* Right Section - Terminal Display */}
          <div className={styles.logEntries}>
            <TerminalDisplay
              logs={logs}
              progress={progress}
              isConnected={isConnected}
              currentTest={currentTest}
              currentStep={currentStep}
            />
          </div>
        </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Input Area */}
      <div className={styles.inputArea}>
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls,.json"
          onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
          className={styles.fileInput}
        />

        <motion.button
          className={styles.uploadButton}
          onClick={() => fileInputRef.current?.click()}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          disabled={isProcessing}
        >
          {uploadedFile ? (
            <>
              {uploadedFile.name.endsWith('.json') ? <FileJson size={20} /> : <FileSpreadsheet size={20} />}
              <span className={styles.fileName}>{uploadedFile.name}</span>
            </>
          ) : (
            <>
              <Upload size={20} />
              <span>Upload</span>
            </>
          )}
        </motion.button>

        <form onSubmit={handleSubmit} className={styles.inputForm}>
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder={
              isProcessing
                ? 'Processing...'
                : rawData
                  ? 'Ask a question or type "execute test 1"...'
                  : 'Upload a file first...'
            }
            disabled={isProcessing}
            className={styles.textInput}
          />
          <motion.button
            type="submit"
            className={styles.sendButton}
            disabled={!inputValue.trim() || isProcessing}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <Send size={20} />
          </motion.button>
        </form>
      </div>
    </div>
  );
};
