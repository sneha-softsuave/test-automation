import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles, Globe, ChevronDown, ChevronRight,
  Play, FileSpreadsheet, AlertCircle, Check,
  Eye, EyeOff, RotateCcw, Video, MonitorPlay, Monitor,
  Circle, CheckCircle2, XCircle, Loader2, Camera, X, Send,
  Zap, Save, FileJson, Pencil, Copy
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import { SaveToProjectModal } from './SaveToProjectModal';
import { saveTestToProject } from '../../services/api';
import type { TestSuite } from '../../store/useStore';
import styles from './GenerateTestCase.module.css';

const API_BASE = '';

// ── Shared types ──────────────────────────────────────────────────────────────

interface GeneratedSuite {
  project: string;
  base_url: string;
  test_cases: Array<{
    id: string;
    name: string;
    steps: Array<{
      step_number: number;
      instruction: string;
      action: { type: string; playwright_method: string };
      selector_hints: { element_name: string | null; element_type: string | null; suggested_selectors: string[] };
      test_data: Record<string, unknown> | null;
      assertions: Array<{ type: string; expected_value: string; playwright_assertion: string }> | null;
    }>;
    expected_results: string[];
  }>;
  common_selectors: Record<string, unknown>;
  test_data: Record<string, unknown>;
}

interface ApiResult {
  success: boolean;
  message: string;
  llm_provider: string;
  model: string;
  page_summary: Record<string, number>;
  test_suite: GeneratedSuite;
}

// ── Chatbot generate types ────────────────────────────────────────────────────

type ChatPhase = 'url_input' | 'analyzing' | 'chatting' | 'generating' | 'executing' | 'done';
type ChatIntent = 'execute' | 'edit' | 'informational' | 'generate';

interface ExecStepMsg {
  test_id: string;
  test_name: string;
  step_number: number;
  instruction: string;
  status: 'running' | 'passed' | 'failed' | 'pending';
  duration_ms?: number;
  error?: string;
}

interface ExecSummary {
  total: number;
  passed: number;
  failed: number;
}

interface ExecTestResult {
  id: string;
  name: string;
  status: 'passed' | 'failed';
  steps: GeneratedSuite['test_cases'][0]['steps'];
  expected_results: string[];
  test_data: Record<string, unknown>;
  error?: string;
}

interface ChatMsg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  testSuite?: GeneratedSuite;
  execSummary?: ExecSummary;
  execTestCases?: ExecTestResult[];
}

// ── Intent detection ──────────────────────────────────────────────────────────

const _EXECUTE_RE = /\b(execute|run)\s+\d+|\b(execute|run|play|start)\b.*(all|test|tests|them|it)\b|\b(execute|run)\s+test\s*\d+|\bexecute all\b|\brun all\b/i;
const _EDIT_RE = /\b(edit|change|update|modify|replace|remove|delete)\b.*(step|test case|expected|selector|instruction)|\bstep\s+\d+\b|\btest\s+case\s+\d+\b/i;
const _INFO_RE = /^(what|which|how|why|where|when|is|are|does|do|can|could|should|would|tell me|show me|list|explain)\b/i;

function detectIntent(msg: string): ChatIntent {
  if (_EXECUTE_RE.test(msg)) return 'execute';
  if (_EDIT_RE.test(msg)) return 'edit';
  if (_INFO_RE.test(msg.trim())) return 'informational';
  return 'generate';
}

function upsertExecStep(prev: ExecStepMsg[], incoming: ExecStepMsg): ExecStepMsg[] {
  const idx = prev.findIndex(s => s.test_id === incoming.test_id && s.step_number === incoming.step_number);
  if (idx === -1) return [...prev, incoming];
  const next = [...prev];
  next[idx] = incoming;
  return next;
}

// ── Recorder types ────────────────────────────────────────────────────────────

type RecordingStatus = 'idle' | 'starting' | 'active' | 'executing' | 'completing' | 'done' | 'error';

interface RecordedStep {
  step_number: number;
  action_type: string;
  instruction: string;
  command: string;
  error?: string | null;
  executed_at?: string;
  // Extra fields from backend — used to build clean ref instructions + input data
  element_name?: string | null;
  element_type?: string | null;
  test_data?: Record<string, string> | null;
  assertions?: Array<{ type: string; expected_value: string }> | null;
  validation_errors?: string[] | null;
  ai_suggestion?: string | null;
}

interface RecorderMessage {
  id: string;
  paragraph: string;
  steps: RecordedStep[];
  status: 'executing' | 'done' | 'error';
  startUrl?: string; // browser URL before this message was executed
}

type Mode = 'generate' | 'record';

/** Port of backend _make_ref_instruction — replaces literal values with reference keys */
function makeRefInstruction(step: RecordedStep): string {
  const { action_type, instruction, element_name, element_type, test_data } = step;
  const td = test_data || {};

  if (action_type === 'goto') return 'Navigate to Application url';

  if (action_type === 'verify_url') return instruction;

  if (action_type === 'fill') {
    let refKey: string | null = null;
    // Use first test_data key to derive the reference label (mirrors backend logic)
    const firstKey = Object.keys(td)[0];
    if (firstKey) {
      refKey = firstKey.toLowerCase() === 'email' ? 'Email'
             : firstKey.toLowerCase() === 'password' ? 'Password'
             : firstKey.toLowerCase() === 'text' ? 'Test data'
             : firstKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }
    // Fallback: scan instruction / element_name for known keywords
    if (!refKey) {
      const lc = instruction.toLowerCase();
      const en = (element_name || '').toLowerCase();
      if (lc.includes('email') || en.includes('email')) refKey = 'Email';
      else if (lc.includes('password') || en.includes('password')) refKey = 'Password';
    }
    const fieldLabel = element_name || element_type || 'field';
    return refKey ? `Fill ${fieldLabel} with ${refKey}` : instruction;
  }

  return instruction;
}

function makeSessionId() {
  return `rec_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

// =============================================================================
// Main component
// =============================================================================

interface GenerateTestCaseProps {
  projectName?: string;
}

export const GenerateTestCase = ({ projectName }: GenerateTestCaseProps = {}) => {
  const { llmProvider, setTestSuite, setCurrentView, addNotification, imageAnalysisEnabled, setProjectActiveSuite } = useStore();

  // ── Mode ─────────────────────────────────────────────────────────────────
  const [mode, setMode] = useState<Mode>('generate');

  // ── Generate mode state ──────────────────────────────────────────────────
  const [url, setUrl] = useState('');
  const [intent, setIntent] = useState('');
  const [appName, setAppName] = useState('');
  const [testEmail, setTestEmail] = useState('');
  const [testPassword, setTestPassword] = useState('');
  const [selectedProvider, setSelectedProvider] = useState(llmProvider);
  const [showOptional, setShowOptional] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState<0 | 1 | 2>(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ApiResult | null>(null);
  const [expandedTc, setExpandedTc] = useState<string | null>(null);

  // ── Chatbot generate mode state ──────────────────────────────────────────
  const [chatPhase, setChatPhase] = useState<ChatPhase>('url_input');
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([]);
  const [chatUrlInput, setChatUrlInput] = useState('');
  const [chatTextInput, setChatTextInput] = useState('');
  const [chatExpandedTc, setChatExpandedTc] = useState<string | null>(null);
  const chatMessagesEndRef = useRef<HTMLDivElement>(null);
  const chatInputRef = useRef<HTMLTextAreaElement>(null);

  // ── Execution state (chatbot execute mode) ────────────────────────────────
  const [execSessionId, setExecSessionId] = useState<string | null>(null);
  const execSseRef = useRef<EventSource | null>(null);
  const [execSteps, setExecSteps] = useState<ExecStepMsg[]>([]);
  const [execSummary, setExecSummary] = useState<ExecSummary | null>(null);
  const execStepsEndRef = useRef<HTMLDivElement>(null);
  const [execScreenshot, setExecScreenshot] = useState<string | null>(null);
  const [execCurrentUrl, setExecCurrentUrl] = useState('');
  const [execPanelView, setExecPanelView] = useState<'browser' | 'excel'>('browser');
  const [confirmedExecResults, setConfirmedExecResults] = useState<ExecTestResult[]>([]);
  const [confirmedTcIds, setConfirmedTcIds] = useState<Set<string>>(new Set());
  // Last generated test suite (for suggestion buttons)
  const [lastTestSuite, setLastTestSuite] = useState<GeneratedSuite | null>(null);

  // ── Record mode state ────────────────────────────────────────────────────
  const [recUrl, setRecUrl] = useState('');
  const [recProvider, setRecProvider] = useState(llmProvider);
  const [recAppName, setRecAppName] = useState('');
  const [recStatus, setRecStatus] = useState<RecordingStatus>('idle');
  const [recError, setRecError] = useState<string | null>(null);
  const [recMessages, setRecMessages] = useState<RecorderMessage[]>([]);
  const [recScreenshot, setRecScreenshot] = useState<string | null>(null);
  const [recCurrentUrl, setRecCurrentUrl] = useState('');
  const recCurrentUrlRef = useRef('');
  const [recResult, setRecResult] = useState<{ test_suite: GeneratedSuite; step_count: number; export_json?: object } | null>(null);
  const [recInstruction, setRecInstruction] = useState('');
  const [collapsedMessages, setCollapsedMessages] = useState<Set<string>>(new Set());
  const [confirmedMessages, setConfirmedMessages] = useState<Set<string>>(new Set());
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editingText, setEditingText] = useState('');
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [recPanelView, setRecPanelView] = useState<'browser' | 'excel'>('browser');
  // Finalized cases from "Start new case" — each entry holds steps for one row (for Excel)
  const [finalizedCases, setFinalizedCases] = useState<Array<{ name: string; steps: RecordedStep[] }>>([]);
  // Message index where each new case starts — used to show dividers and compute current-case steps
  const [caseBoundaries, setCaseBoundaries] = useState<number[]>([]);

  // ── Save to Project state ─────────────────────────────────────────────────
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [suiteToSave, setSuiteToSave] = useState<GeneratedSuite | null>(null);

  const sessionIdRef = useRef<string>(makeSessionId());
  const sseRef = useRef<EventSource | null>(null);
  const activeMsgIdRef = useRef<string | null>(null); // tracks which message is currently executing
  const instructionRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesListRef = useRef<HTMLDivElement>(null);

  // Auto-size textarea
  const chatTextareaRef = useRef<HTMLTextAreaElement>(null);

  // Steps in the current in-progress case only (messages after the last case boundary)
  const currentCaseStartMsgIdx = caseBoundaries.length > 0 ? caseBoundaries[caseBoundaries.length - 1] : 0;
  const allRecSteps = recMessages.slice(currentCaseStartMsgIdx).flatMap(m =>
    confirmedMessages.has(m.id) ? m.steps : []
  );
  // Total steps across all finalized cases + current case
  const totalRecSteps = finalizedCases.reduce((sum, c) => sum + c.steps.length, 0) + allRecSteps.length;
  const currentCaseNumber = finalizedCases.length + 1;

  // Derive Excel cell content from accumulated steps — mirrors backend _steps_to_input_data
  const recExcelInputData = (() => {
    const collected: Record<string, string> = {};
    for (const step of allRecSteps) {
      const td = step.test_data || {};
      // URL from goto steps
      if (step.action_type === 'goto' && td.url) collected['Application url'] = td.url;
      // All test_data keys (same logic as backend)
      for (const [k, v] of Object.entries(td)) {
        if (!v) continue;
        if (k === 'url') continue; // handled above for goto; verify_url assertions handle it below
        else if (k === 'email') collected['Email'] = v;
        else if (k === 'password') collected['Password'] = v;
        else if (k === 'text') collected['Test data'] = v;
        else collected[k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())] = v;
      }
      // Assertions (e.g. verify_url inserts url assertion)
      const assertions = step.assertions || [];
      for (const a of assertions) {
        if (!a.expected_value) continue;
        if (a.type === 'url') collected['Expected URL'] = a.expected_value;
        else if (a.type === 'heading' || a.type === 'text') collected['Expected heading'] = a.expected_value;
        else if (a.type === 'toast') collected['Expected Toast Message'] = a.expected_value;
        else if (a.type === 'status') collected['Expected status'] = a.expected_value;
        else collected[`Expected ${a.type}`] = a.expected_value;
      }
    }
    return Object.entries(collected).map(([k, v]) => `${k}: ${v}`).join('\n');
  })();

  const recExcelStatus: 'running' | 'passed' | 'failed' =
    recStatus === 'done'
      ? (allRecSteps.some(s => s.error || s.validation_errors?.length) ? 'failed' : 'passed')
      : 'running';

  const recExcelError = (() => {
    for (const s of allRecSteps) {
      if (s.error) return s.error;
      if (s.validation_errors?.length) return s.validation_errors[0];
    }
    return null;
  })();

  // Auto-scroll messages
  useEffect(() => {
    const el = messagesListRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [recMessages]);

  // Auto-resize textarea
  const autoResizeTextarea = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  // ── SSE connection ────────────────────────────────────────────────────────
  const connectSSE = useCallback((sid: string) => {
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
    const es = new EventSource(`${API_BASE}/api/v1/sse/${sid}`);
    sseRef.current = es;
    es.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.type === 'recorder_screenshot') {
          setRecScreenshot(data.image_b64);
          recCurrentUrlRef.current = data.current_url || '';
          setRecCurrentUrl(data.current_url || '');
        } else if (data.type === 'recorder_step' && activeMsgIdRef.current) {
          const s = data.step;
          const newStep: RecordedStep = {
            step_number: s.step_number ?? 0,
            action_type: s.action_type || '',
            instruction: s.instruction || '',
            command: s.command || '',
            error: s.error || null,
            executed_at: s.executed_at,
            element_name: s.element_name ?? null,
            element_type: s.element_type ?? null,
            test_data: s.test_data ?? null,
            assertions: s.assertions ?? null,
            validation_errors: s.validation_errors ?? null,
            ai_suggestion: s.ai_suggestion ?? null,
          };
          const msgId = activeMsgIdRef.current;
          setRecMessages(prev =>
            prev.map(m =>
              m.id === msgId
                ? { ...m, steps: [...m.steps, newStep] }
                : m
            )
          );
        }
      } catch { /* ignore */ }
    };
  }, []);

  const disconnectSSE = useCallback(() => {
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
  }, []);

  useEffect(() => () => disconnectSSE(), [disconnectSSE]);

  // ── Computed flags ────────────────────────────────────────────────────────
  const canGenerate = url.trim().length > 0 && intent.trim().length > 0 && !loading;
  const canStartRecording = recUrl.trim().length > 0 && (recStatus === 'idle' || recStatus === 'error');
  const canExecuteSteps = recInstruction.trim().length > 0 && recStatus === 'active';

  // ==========================================================================
  // Generate mode handlers
  // ==========================================================================

  const handleGenerate = async () => {
    setError(null);
    setResult(null);
    setLoading(true);
    setLoadingStep(1);
    try {
      const body = {
        url: url.trim(),
        intent: intent.trim(),
        app_name: appName.trim() || undefined,
        test_email: testEmail.trim() || undefined,
        test_password: testPassword.trim() || undefined,
      };
      await new Promise(r => setTimeout(r, 100));
      const params = new URLSearchParams({ llm_provider: selectedProvider });
      const res = await fetch(`${API_BASE}/api/v1/generate-from-url?${params}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      setLoadingStep(2);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Server error');
      }
      const data: ApiResult = await res.json();
      setResult(data);
      if (data.test_suite?.test_cases?.length > 0) {
        setExpandedTc(data.test_suite.test_cases[0].id);
      }
      addNotification('success', `Generated ${data.test_suite?.test_cases?.length ?? 0} test case(s) successfully`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      addNotification('error', `Generation failed: ${msg}`);
    } finally {
      setLoading(false);
      setLoadingStep(0);
    }
  };

  const handleUseInAgent = () => {
    if (!result?.test_suite) return;
    setTestSuite(result.test_suite as any);
    addNotification('success', 'Test suite loaded — switch to Agent or Execute to run tests');
    setCurrentView('suite');
  };

  const handleExportExcel = async (suite: GeneratedSuite) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/export-to-excel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ test_suite: suite }),
      });
      if (!res.ok) throw new Error('Export failed');
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      const project = suite.project.replace(/\s+/g, '_') || 'test_cases';
      a.download = `${project}.xlsx`;
      a.click();
      URL.revokeObjectURL(href);
      addNotification('success', 'Excel file downloaded');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      addNotification('error', `Export failed: ${msg}`);
    }
  };

  const handleExportRecorderJson = (suite: GeneratedSuite, exportJson?: object) => {
    try {
      const data = exportJson ?? suite;
      const project = suite.project.replace(/\s+/g, '_') || 'test_cases';
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = `${project}.json`;
      a.click();
      URL.revokeObjectURL(href);
      addNotification('success', 'JSON file downloaded');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      addNotification('error', `Export failed: ${msg}`);
    }
  };

  const handleReset = () => {
    setResult(null);
    setError(null);
  };

  // ==========================================================================
  // Chatbot generate mode handlers
  // ==========================================================================

  // Auto-scroll chat to bottom
  useEffect(() => {
    chatMessagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, chatPhase]);

  const appendChatMsg = (msg: ChatMsg) =>
    setChatMessages(prev => [...prev, msg]);

  const _URL_PATTERN = /^(https?:\/\/|www\.)\S+/i;
  const looksLikeUrl = (text: string) => _URL_PATTERN.test(text.trim());


  const handleAnalyzeUrl = async (urlOverride?: string) => {
    const trimmedUrl = (urlOverride ?? chatUrlInput).trim();
    if (!trimmedUrl) return;

    setChatUrlInput(trimmedUrl);
    // Append user bubble with the URL
    appendChatMsg({ id: `cu_${Date.now()}`, role: 'user', content: trimmedUrl });
    setChatPhase('analyzing');

    try {
      const res = await fetch(`${API_BASE}/api/v1/analyze-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: trimmedUrl, llm_provider: selectedProvider }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Server error');
      }
      const data = await res.json();
      setChatSessionId(data.session_id);
      appendChatMsg({ id: `ca_${Date.now()}`, role: 'assistant', content: data.message });
      setChatPhase('chatting');
      setTimeout(() => chatInputRef.current?.focus(), 50);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      appendChatMsg({ id: `ce_${Date.now()}`, role: 'assistant', content: `Error: ${msg}` });
      setChatPhase('url_input');
      addNotification('error', `Analyse failed: ${msg}`);
    }
  };

  // ── Execution SSE connection ───────────────────────────────────────────────
  // Always-current ref so the SSE onmessage handler never uses a stale closure
  const handleExecSseEventRef = useRef<(data: Record<string, unknown>) => void>(() => {});

  const connectExecutionSSE = (sid: string) => {
    if (execSseRef.current) {
      execSseRef.current.close();
      execSseRef.current = null;
    }
    setExecSteps([]);
    setExecSummary(null);

    const es = new EventSource(`${API_BASE}/api/v1/sse/${sid}`);
    execSseRef.current = es;

    es.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        handleExecSseEventRef.current(data);
      } catch { /* ignore */ }
    };

    es.onerror = () => {
      // Connection dropped — unblock the UI so user isn't stuck forever
      if (execSseRef.current) {
        execSseRef.current.close();
        execSseRef.current = null;
      }
      setChatPhase(prev => prev === 'executing' ? 'chatting' : prev);
    };

    // Safety net: force-close after 15 minutes in case backend never sends exec_session_complete
    setTimeout(() => {
      if (execSseRef.current === es) {
        es.close();
        execSseRef.current = null;
        setChatPhase(prev => prev === 'executing' ? 'chatting' : prev);
      }
    }, 15 * 60 * 1000);
  };

  // Keep the ref pointing at the latest version of the handler
  useEffect(() => { handleExecSseEventRef.current = handleExecSseEvent; });

  const handleExecSseEvent = (data: Record<string, unknown>) => {
    switch (data.type) {
      case 'step_update': {
        const step: ExecStepMsg = {
          test_id: String(data.test_id ?? ''),
          test_name: String(data.test_name ?? ''),
          step_number: Number(data.step_number ?? 0),
          instruction: String(data.instruction ?? ''),
          status: (data.status as ExecStepMsg['status']) ?? 'running',
          duration_ms: data.duration_ms as number | undefined,
          error: data.error as string | undefined,
        };
        setExecSteps(prev => upsertExecStep(prev, step));
        execStepsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        break;
      }
      case 'test_update': {
        // Mark all steps of this test as passed/failed
        setExecSteps(prev => prev.map(s =>
          s.test_id === data.test_id
            ? { ...s, status: (data.status as ExecStepMsg['status']) ?? s.status }
            : s
        ));
        break;
      }
      case 'chat_execution_done': {
        // Show results and unblock input — keep SSE open for page_analysis_done that may follow
        const summary = data.summary as ExecSummary;
        setExecSummary(summary);
        setChatPhase('chatting');
        const tcResults = (data.tc_results as ExecTestResult[] | undefined) ?? [];
        appendChatMsg({
          id: `ca_${Date.now()}`,
          role: 'assistant',
          content: String(data.message ?? 'Execution complete.'),
          execSummary: summary,
          execTestCases: tcResults,
        });
        break;
      }
      case 'exec_session_complete': {
        // All backend post-processing done — safe to close SSE now
        if (execSseRef.current) { execSseRef.current.close(); execSseRef.current = null; }
        break;
      }
      case 'page_analysis_start': {
        // Backend is scraping the navigated page — show a transient status in chat
        appendChatMsg({
          id: `nav_start_${Date.now()}`,
          role: 'assistant',
          content: String(data.message ?? 'Analyzing the new page…'),
        });
        if (data.url) setExecCurrentUrl(String(data.url));
        break;
      }
      case 'page_analysis_done': {
        // Replace the "analyzing…" message with the full page intro
        const navMsg = String(data.message ?? '');
        if (navMsg) {
          appendChatMsg({ id: `nav_done_${Date.now()}`, role: 'assistant', content: navMsg });
        }
        if (data.url) { setExecCurrentUrl(String(data.url)); setChatUrlInput(String(data.url)); }
        break;
      }
      case 'exec_screenshot': {
        if (data.image_b64) setExecScreenshot(String(data.image_b64));
        if (data.url) setExecCurrentUrl(String(data.url));
        break;
      }
      case 'page_navigated': {
        const navUrl = String(data.url ?? '');
        const elemSummary = String(data.elements_summary ?? `Browser navigated to: ${navUrl}`);
        if (navUrl) setExecCurrentUrl(navUrl);
        if (data.image_b64) setExecScreenshot(String(data.image_b64));
        appendChatMsg({
          id: `nav_${Date.now()}`,
          role: 'assistant',
          content: elemSummary,
        });
        break;
      }
      case 'agent_phase':
        // Phase update — add a brief status step
        if (data.message) {
          setExecSteps(prev => [...prev, {
            test_id: 'system',
            test_name: 'System',
            step_number: Date.now(),
            instruction: String(data.message),
            status: 'running',
          }]);
        }
        break;
      case 'error':
        if (execSseRef.current) { execSseRef.current.close(); execSseRef.current = null; }
        appendChatMsg({ id: `ce_${Date.now()}`, role: 'assistant', content: `Execution error: ${data.message}` });
        setChatPhase('chatting');
        break;
    }
  };

  // ── Chat execute handler ──────────────────────────────────────────────────
  const handleChatExecute = async (userMessage: string) => {
    if (!chatSessionId) return;
    setChatPhase('executing');
    setExecSteps([]);
    setExecSummary(null);
    setExecScreenshot(null);
    setExecCurrentUrl('');
    setExecPanelView('browser');

    appendChatMsg({ id: `cu_${Date.now()}`, role: 'user', content: userMessage });

    try {
      const res = await fetch(`${API_BASE}/api/v1/chat-execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: chatSessionId,
          user_message: userMessage,
          llm_provider: selectedProvider,
          headless: true,
          timeout: 30000,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Server error');
      }
      const data = await res.json();
      setExecSessionId(data.exec_session_id);
      appendChatMsg({ id: `ca_${Date.now()}`, role: 'assistant', content: data.message });
      connectExecutionSSE(data.exec_session_id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      appendChatMsg({ id: `ce_${Date.now()}`, role: 'assistant', content: `Error: ${msg}` });
      setChatPhase('chatting');
      addNotification('error', `Execute failed: ${msg}`);
    }
  };

  // ── Chat edit handler ─────────────────────────────────────────────────────
  const handleChatEdit = async (userMessage: string) => {
    if (!chatSessionId) return;
    setChatPhase('generating');

    appendChatMsg({ id: `cu_${Date.now()}`, role: 'user', content: userMessage });

    try {
      const res = await fetch(`${API_BASE}/api/v1/chat-edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: chatSessionId,
          user_message: userMessage,
          llm_provider: selectedProvider,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Server error');
      }
      const data = await res.json();
      if (data.test_suite) {
        setLastTestSuite(data.test_suite);
        const firstTcId = data.test_suite.test_cases?.[0]?.id ?? null;
        if (firstTcId) setChatExpandedTc(firstTcId);
      }
      appendChatMsg({
        id: `ca_${Date.now()}`,
        role: 'assistant',
        content: data.message,
        testSuite: data.test_suite,
      });
      setChatPhase('chatting');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      appendChatMsg({ id: `ce_${Date.now()}`, role: 'assistant', content: `Error: ${msg}` });
      setChatPhase('chatting');
      addNotification('error', `Edit failed: ${msg}`);
    }
  };

  // ── Chat informational handler ────────────────────────────────────────────
  const handleChatInformational = async (userMessage: string) => {
    if (!chatSessionId) return;
    setChatPhase('generating');

    appendChatMsg({ id: `cu_${Date.now()}`, role: 'user', content: userMessage });

    try {
      const res = await fetch(`${API_BASE}/api/v1/chat-informational`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: chatSessionId,
          user_message: userMessage,
          llm_provider: selectedProvider,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Server error');
      }
      const data = await res.json();
      appendChatMsg({ id: `ca_${Date.now()}`, role: 'assistant', content: data.message });
      setChatPhase('chatting');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      appendChatMsg({ id: `ce_${Date.now()}`, role: 'assistant', content: `Error: ${msg}` });
      setChatPhase('chatting');
    }
  };

  const handleChatSend = async () => {
    const text = chatTextInput.trim();
    if (!text) return;
    setChatTextInput('');

    // In URL input phase, treat input as URL
    if (chatPhase === 'url_input') {
      if (looksLikeUrl(text)) {
        const url = text.startsWith('http') ? text : `https://${text}`;
        await handleAnalyzeUrl(url);
      } else {
        appendChatMsg({ id: `cu_${Date.now()}`, role: 'user', content: text });
        appendChatMsg({ id: `ca_${Date.now()}`, role: 'assistant', content: 'Please share a URL (starting with https://) so I can analyze the page.' });
      }
      return;
    }

    if (!chatSessionId) return;
    if (chatPhase === 'generating' || chatPhase === 'executing') return;

    if (chatInputRef.current) chatInputRef.current.style.height = 'auto';

    const intent = detectIntent(text);

    if (intent === 'execute') {
      await handleChatExecute(text);
    } else if (intent === 'edit') {
      await handleChatEdit(text);
    } else if (intent === 'informational') {
      await handleChatInformational(text);
    } else {
      // generate
      appendChatMsg({ id: `cu_${Date.now()}`, role: 'user', content: text });
      setChatPhase('generating');

      try {
        const res = await fetch(`${API_BASE}/api/v1/chat-generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: chatSessionId,
            user_message: text,
            llm_provider: selectedProvider,
          }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(err.detail || 'Server error');
        }
        const data = await res.json();
        const firstTcId = data.test_suite?.test_cases?.[0]?.id ?? null;
        if (firstTcId) setChatExpandedTc(firstTcId);
        if (data.test_suite) setLastTestSuite(data.test_suite);
        appendChatMsg({
          id: `ca_${Date.now()}`,
          role: 'assistant',
          content: data.message,
          testSuite: data.test_suite,
        });
        setChatPhase('chatting');
        addNotification('success', `Generated ${data.test_suite?.test_cases?.length ?? 0} test case(s)`);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        appendChatMsg({ id: `ce_${Date.now()}`, role: 'assistant', content: `Error: ${msg}` });
        setChatPhase('chatting');
        addNotification('error', `Generation failed: ${msg}`);
      }
    }
  };

  const handleChatUseInAgent = (suite: GeneratedSuite) => {
    setTestSuite(suite as any);
    addNotification('success', 'Test suite loaded — switch to Agent or Execute to run tests');
    setCurrentView('suite');
  };

  const handleChatReset = () => {
    if (execSseRef.current) { execSseRef.current.close(); execSseRef.current = null; }
    setChatPhase('url_input');
    setChatSessionId(null);
    setChatMessages([]);
    setChatUrlInput('');
    setChatTextInput('');
    setChatExpandedTc(null);
    setExecSteps([]);
    setExecSummary(null);
    setExecSessionId(null);
    setLastTestSuite(null);
    setExecScreenshot(null);
    setExecCurrentUrl('');
    setConfirmedExecResults([]);
    setConfirmedTcIds(new Set());
  };

  const handleConfirmResult = (tc: ExecTestResult) => {
    if (confirmedTcIds.has(tc.id)) return;
    setConfirmedExecResults(prev => [...prev, tc]);
    setConfirmedTcIds(prev => new Set([...prev, tc.id]));
    setExecPanelView('excel');
  };

  // Cleanup SSE on unmount
  useEffect(() => () => { execSseRef.current?.close(); }, []);

  // ==========================================================================
  // Record mode handlers
  // ==========================================================================

  const handleToggleConfirm = (msgId: string, e: React.MouseEvent) => {
    e.stopPropagation(); // prevent collapsing the card
    setConfirmedMessages(prev => {
      const next = new Set(prev);
      if (next.has(msgId)) next.delete(msgId);
      else next.add(msgId);
      return next;
    });
  };

  const handleStartEdit = (msg: RecorderMessage) => {
    setEditingMessageId(msg.id);
    setEditingText(msg.paragraph);
  };

  const handleCancelEdit = () => {
    setEditingMessageId(null);
    setEditingText('');
  };

  const handleCopyMessage = (msgId: string, text: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
    setCopiedMessageId(msgId);
    setTimeout(() => setCopiedMessageId(null), 2000);
  };

  const handleRerun = async (msg: RecorderMessage) => {
    const paragraph = editingText.trim();
    if (!paragraph || recStatus !== 'active') return;

    // Find this message's index within the current case messages
    const currentCaseMsgs = recMessages.slice(currentCaseStartMsgIdx);
    const msgIdx = currentCaseMsgs.findIndex(m => m.id === msg.id);
    if (msgIdx === -1) return;

    // Steps to preserve = sum of steps from messages BEFORE this one in the current case
    const stepsToKeep = currentCaseMsgs.slice(0, msgIdx).reduce((sum, m) => sum + m.steps.length, 0);

    // Close edit mode
    setEditingMessageId(null);
    setEditingText('');

    // Discard this message and all after it; clean up their confirm/collapse state
    const discardedIds = recMessages.slice(currentCaseStartMsgIdx + msgIdx).map(m => m.id);
    setConfirmedMessages(prev => { const n = new Set(prev); discardedIds.forEach(id => n.delete(id)); return n; });
    setCollapsedMessages(prev => { const n = new Set(prev); discardedIds.forEach(id => n.delete(id)); return n; });

    // Build new executing message
    const newMsgId = `msg_${Date.now()}`;
    activeMsgIdRef.current = newMsgId;
    const newMsg: RecorderMessage = {
      id: newMsgId, paragraph, steps: [], status: 'executing',
      startUrl: msg.startUrl,
    };
    setRecMessages([...recMessages.slice(0, currentCaseStartMsgIdx + msgIdx), newMsg]);
    setRecStatus('executing');

    try {
      const params = new URLSearchParams({ llm_provider: recProvider });
      const res = await fetch(`${API_BASE}/api/v1/recorder/rerun?${params}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          command: paragraph,
          start_url: msg.startUrl || undefined,
          truncate_to_step: stepsToKeep,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Rerun failed');
      }
      const data = await res.json();
      if (data.current_url) { recCurrentUrlRef.current = data.current_url; setRecCurrentUrl(data.current_url); }

      activeMsgIdRef.current = null;
      setRecMessages(prev =>
        prev.map(m => {
          if (m.id !== newMsgId) return m;
          const sseSteps = m.steps;
          if (sseSteps.length > 0) return { ...m, status: data.error ? 'error' : 'done' };
          const returnedSteps: RecordedStep[] = (data.steps || []).map((s: RecordedStep, i: number) => ({
            step_number: i + 1,
            instruction: s.instruction || '',
            action_type: s.action_type || '',
            selector_hints: { element_name: (s as any).element_name, element_type: (s as any).element_type, suggested_selectors: (s as any).selector ? [(s as any).selector] : [] },
            test_data: s.test_data,
            assertions: s.assertions,
            error: s.error,
            validation_errors: s.validation_errors,
            ai_suggestion: s.ai_suggestion,
          }));
          const hasError = returnedSteps.some(s => s.error);
          return { ...m, steps: returnedSteps, status: hasError ? 'error' : 'done' };
        })
      );
      setRecStatus('active');
      setTimeout(() => instructionRef.current?.focus(), 50);
    } catch (e: unknown) {
      activeMsgIdRef.current = null;
      const errMsg = e instanceof Error ? e.message : String(e);
      setRecMessages(prev => prev.map(m => m.id === newMsgId ? { ...m, status: 'error' } : m));
      setRecError(errMsg);
      setRecStatus('active');
      addNotification('error', `Rerun failed: ${errMsg}`);
    }
  };

  const handleStartRecording = async () => {
    setRecError(null);
    setRecMessages([]);
    setFinalizedCases([]);
    setCaseBoundaries([]);
    setRecScreenshot(null);
    recCurrentUrlRef.current = '';
    setRecCurrentUrl('');
    setRecResult(null);
    setCollapsedMessages(new Set());
    setConfirmedMessages(new Set());
    setRecStatus('starting');
    const firstInstruction = recInstruction.trim();

    sessionIdRef.current = makeSessionId();
    connectSSE(sessionIdRef.current);

    try {
      const res = await fetch(`${API_BASE}/api/v1/recorder/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: recUrl.trim(),
          session_id: sessionIdRef.current,
          app_name: recAppName.trim() || undefined,
          headless: false,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Failed to start recording');
      }
      const data = await res.json();
      if (data.screenshot_b64) setRecScreenshot(data.screenshot_b64);
      if (data.current_url) { recCurrentUrlRef.current = data.current_url; setRecCurrentUrl(data.current_url); }
      setRecStatus('active');

      if (firstInstruction) {
        setTimeout(() => executeStepsWithParagraph(firstInstruction), 50);
      } else {
        setTimeout(() => instructionRef.current?.focus(), 100);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setRecError(msg);
      setRecStatus('error');
      disconnectSSE();
      addNotification('error', `Failed to start recorder: ${msg}`);
    }
  };

  const executeStepsWithParagraph = async (paragraph: string) => {
    setRecInstruction('');
    if (chatTextareaRef.current) {
      chatTextareaRef.current.style.height = 'auto';
    }
    setRecStatus('executing');

    const msgId = `msg_${Date.now()}`;
    activeMsgIdRef.current = msgId; // SSE handler will append steps to this message
    const newMsg: RecorderMessage = { id: msgId, paragraph, steps: [], status: 'executing', startUrl: recCurrentUrlRef.current };
    setRecMessages(prev => [...prev, newMsg]);

    try {
      const params = new URLSearchParams({ llm_provider: recProvider });
      const res = await fetch(`${API_BASE}/api/v1/recorder/command?${params}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          command: paragraph,
          llm_provider: recProvider,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Command failed');
      }
      const data = await res.json();
      if (data.screenshot_b64) setRecScreenshot(data.screenshot_b64);
      if (data.current_url) { recCurrentUrlRef.current = data.current_url; setRecCurrentUrl(data.current_url); }

      // Steps were already streamed in via SSE (recorder_step events).
      // Use the HTTP response only to catch any steps that may have arrived
      // out of order or were missed, then mark the message as done.
      activeMsgIdRef.current = null;
      setRecMessages(prev =>
        prev.map(m => {
          if (m.id !== msgId) return m;
          // If SSE already populated steps, keep them; otherwise fall back to HTTP payload
          const sseSteps = m.steps;
          if (sseSteps.length > 0) {
            const hasError = sseSteps.some(s => s.error);
            return { ...m, status: hasError ? 'error' : 'done' };
          }
          // Fallback: use HTTP response steps (SSE may have been missed)
          const returnedSteps: RecordedStep[] = (data.steps || []).map((s: any, idx: number) => ({
            step_number: s.step_number ?? (allRecSteps.length + idx + 1),
            action_type: s.action_type || '',
            instruction: s.instruction || paragraph,
            command: paragraph,
            error: s.error || null,
            executed_at: s.executed_at,
            element_name: s.element_name ?? null,
            element_type: s.element_type ?? null,
            test_data: s.test_data ?? null,
            assertions: s.assertions ?? null,
            validation_errors: s.validation_errors ?? null,
            ai_suggestion: s.ai_suggestion ?? null,
          }));
          const hasError = returnedSteps.some(s => s.error);
          return { ...m, steps: returnedSteps, status: hasError ? 'error' : 'done' };
        })
      );
      setRecStatus('active');
      setTimeout(() => instructionRef.current?.focus(), 50);
    } catch (e: unknown) {
      activeMsgIdRef.current = null;
      const msg = e instanceof Error ? e.message : String(e);
      setRecMessages(prev => prev.map(m => m.id === msgId ? { ...m, status: 'error' } : m));
      setRecError(msg);
      setRecStatus('active');
      addNotification('error', `Command failed: ${msg}`);
    }
  };

  const handleExecuteSteps = () => {
    if (!canExecuteSteps) return;
    executeStepsWithParagraph(recInstruction.trim());
  };

  const handleCompleteRecording = async () => {
    setRecStatus('completing');
    try {
      const res = await fetch(`${API_BASE}/api/v1/recorder/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          app_name: recAppName.trim() || undefined,
          base_url: recUrl.trim() || undefined,
        }),
      });
      disconnectSSE();
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Failed to complete recording');
      }
      const data = await res.json();

      // Filter the test suite to only include steps from user-confirmed messages.
      // Build a set of instructions from all confirmed messages' steps.
      const confirmedInstructions = new Set<string>(
        recMessages
          .filter(m => confirmedMessages.has(m.id))
          .flatMap(m => m.steps.map(s => s.instruction))
      );
      const testSuite = confirmedInstructions.size > 0
        ? {
            ...data.test_suite,
            test_cases: (data.test_suite.test_cases as GeneratedSuite['test_cases'])
              .map(tc => ({ ...tc, steps: tc.steps.filter(s => confirmedInstructions.has(s.instruction)) }))
              .filter(tc => tc.steps.length > 0),
          }
        : data.test_suite;
      const filteredStepCount = confirmedInstructions.size > 0
        ? testSuite.test_cases.reduce((sum: number, tc: GeneratedSuite['test_cases'][0]) => sum + tc.steps.length, 0)
        : data.step_count;

      setRecResult({ test_suite: testSuite, step_count: filteredStepCount, export_json: data.export_json });
      setRecStatus('done');
      addNotification('success', `Recorded test suite saved: ${filteredStepCount} step(s)`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setRecError(msg);
      setRecStatus('error');
      addNotification('error', `Failed to complete: ${msg}`);
    }
  };

  const handleNewCase = async () => {
    if (allRecSteps.length === 0 || recStatus !== 'active') return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/recorder/new-case`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionIdRef.current }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Failed to start new case');
      }
      const data = await res.json();
      // Store finalized case steps for Excel, but keep ALL messages visible for context
      setFinalizedCases(prev => [...prev, { name: data.case_name, steps: allRecSteps }]);
      setCaseBoundaries(prev => [...prev, recMessages.length]);
      addNotification('success', `${data.case_name} saved (${data.steps_finalized} step(s)). Recording Case ${data.case_number + 1}…`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      addNotification('error', `Failed to start new case: ${msg}`);
    }
  };

  const handleCancelRecording = async () => {
    try {
      await fetch(`${API_BASE}/api/v1/recorder/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionIdRef.current }),
      });
    } catch { /* ignore */ }
    disconnectSSE();
    setRecStatus('idle');
    setRecMessages([]);
    setFinalizedCases([]);
    setCaseBoundaries([]);
    setRecScreenshot(null);
    recCurrentUrlRef.current = '';
    setRecCurrentUrl('');
    setRecError(null);
    setRecResult(null);
    setCollapsedMessages(new Set());
    setConfirmedMessages(new Set());
  };

  const handleUseRecordedInAgent = () => {
    if (!recResult?.test_suite) return;
    setTestSuite(recResult.test_suite as any);
    addNotification('success', 'Recorded test suite loaded — switch to Agent or Execute to run tests');
    setCurrentView('suite');
  };

  const handleInstructionKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && canExecuteSteps) {
      e.preventDefault();
      handleExecuteSteps();
    }
    // Enter without shift sends (like ChatGPT)
    if (e.key === 'Enter' && !e.shiftKey && canExecuteSteps) {
      e.preventDefault();
      handleExecuteSteps();
    }
  };

  const toggleMessageCollapse = (msgId: string) => {
    setCollapsedMessages(prev => {
      const next = new Set(prev);
      if (next.has(msgId)) next.delete(msgId);
      else next.add(msgId);
      return next;
    });
  };

  // ==========================================================================
  // Render helpers
  // ==========================================================================

  const renderStepIcon = (step: RecordedStep) => {
    if (step.error) return <XCircle size={13} style={{ color: '#ef4444', flexShrink: 0 }} />;
    return <CheckCircle2 size={13} style={{ color: '#22c55e', flexShrink: 0 }} />;
  };

  const renderActionBadge = (type: string) => (
    <span
      className={styles.stepAction}
      style={type === 'verify_url' ? { background: '#dcfce7', color: '#15803d' } : undefined}
    >
      {type === 'verify_url' ? 'verify url' : type}
    </span>
  );

  // ==========================================================================
  // Render
  // ==========================================================================

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.headerIcon}>
            <Sparkles size={20} />
          </div>
          <h1 className={styles.title}>Generate Test Cases</h1>
          {/* LLM Provider — top-right corner */}
          <select
            className={styles.headerProviderSelect}
            value={mode === 'record' ? recProvider : selectedProvider}
            onChange={e => {
              const val = e.target.value as typeof recProvider;
              if (mode === 'record') setRecProvider(val);
              else setSelectedProvider(val);
            }}
            disabled={loading || recStatus === 'executing' || recStatus === 'completing'}
            title="AI Provider"
          >
            <option value="groq">Groq (Llama 3.1)</option>
            <option value="openai">OpenAI (GPT-4o)</option>
            <option value="anthropic">Anthropic (Claude)</option>
            <option value="waymore">Waymore AI</option>
          </select>
        </div>
        <p className={styles.subtitle}>
          Auto-generate from URL or record tests interactively in a live browser.
        </p>
      </div>

      {/* Mode tabs */}
      <div className={styles.modeTabs}>
        <button
          className={`${styles.modeTab} ${mode === 'generate' ? styles.modeTabActive : ''}`}
          onClick={() => setMode('generate')}
        >
          <Sparkles size={14} />
          Generate from URL
        </button>
        <button
          className={`${styles.modeTab} ${mode === 'record' ? styles.modeTabActive : ''}`}
          onClick={() => setMode('record')}
        >
          <Video size={14} />
          Record Mode
        </button>
      </div>

      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* GENERATE MODE — Chatbot UI                                         */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      {mode === 'generate' && (
        <div className={`${styles.chatLayout} ${styles.genExecutionLayout}`}>

          {/* ── RIGHT PANEL: browser + excel view (always visible) ── */}
          {(
            <div className={styles.genExecPanel}>

              {/* Status bar */}
              <div className={styles.genExecStatusBar}>
                <span className={`${styles.recStatusDot} ${chatPhase === 'executing' ? styles.recStatusExecuting : styles.recStatusActive}`} />
                <span className={styles.genExecStatusText}>
                  {chatPhase === 'executing'
                    ? (execSteps.filter(s => s.test_id !== 'system' && s.status === 'running').length > 0
                        ? `Running: ${execSteps.find(s => s.test_id !== 'system' && s.status === 'running')?.test_name ?? '…'}`
                        : 'Preparing execution…')
                    : chatPhase === 'analyzing'
                    ? 'Analyzing page…'
                    : confirmedExecResults.length > 0
                    ? `${confirmedExecResults.length} result${confirmedExecResults.length !== 1 ? 's' : ''} confirmed`
                    : 'Ready — run test cases to see live browser'}
                </span>
                {chatPhase === 'executing' && (
                  <span className={styles.genExecPanelBadge}>
                    {execSteps.filter(s => s.step_number === 0 && (s.status === 'passed' || s.status === 'failed')).length}
                    /{execSteps.filter(s => s.step_number === 0).length} done
                  </span>
                )}
              </div>

              {/* View toggle */}
              <div className={styles.genExecViewToggle}>
                <button
                  className={`${styles.genExecViewToggleBtn} ${execPanelView === 'browser' ? styles.genExecViewToggleActive : ''}`}
                  onClick={() => setExecPanelView('browser')}
                >
                  <Monitor size={13} />
                  Browser View
                </button>
                <button
                  className={`${styles.genExecViewToggleBtn} ${execPanelView === 'excel' ? styles.genExecViewToggleActive : ''}`}
                  onClick={() => setExecPanelView('excel')}
                >
                  <FileSpreadsheet size={13} />
                  Excel View
                  {confirmedExecResults.length > 0 && (
                    <span className={styles.recExcelBadge}>{confirmedExecResults.length}</span>
                  )}
                </button>
              </div>

              {/* Browser screenshot view */}
              {execPanelView === 'browser' && (
                <>
                  <div className={styles.browserPanelHeader}>
                    <Camera size={13} />
                    <span>Live Browser View</span>
                    {execCurrentUrl && (
                      <span className={styles.screenshotCurrentUrl} title={execCurrentUrl}>
                        {execCurrentUrl}
                      </span>
                    )}
                  </div>
                  <div className={styles.browserPanelBody}>
                    {execScreenshot ? (
                      <img
                        src={`data:image/png;base64,${execScreenshot}`}
                        alt="Browser screenshot"
                        className={styles.screenshotImg}
                        style={{ width: '100%', height: '100%', objectFit: 'contain', objectPosition: 'top', display: 'block' }}
                      />
                    ) : (
                      <div className={styles.screenshotPlaceholder}>
                        <MonitorPlay size={48} style={{ color: '#cbd5e1' }} />
                        <span>
                          {chatPhase === 'analyzing'
                            ? 'Analysing page…'
                            : 'Execute a test case to see live browser'}
                        </span>
                      </div>
                    )}
                    {chatPhase === 'executing' && (
                      <div className={styles.screenshotExecutingOverlay}>
                        <Loader2 size={28} className={styles.spin} style={{ color: '#6366f1' }} />
                      </div>
                    )}
                  </div>
                </>
              )}

              {/* Excel view — confirmed execution results */}
              {execPanelView === 'excel' && (
                <div className={styles.genExcelView}>
                  {confirmedExecResults.length === 0 ? (
                    <div className={styles.genExcelEmpty}>
                      <FileSpreadsheet size={36} style={{ color: '#cbd5e1' }} />
                      <span>Run and confirm test cases to see results here</span>
                    </div>
                  ) : (
                    <div className={styles.genExcelTable}>
                      <div className={styles.recExcelCorner} />
                      {['A','B','C','D','E','F','G'].map(l => (
                        <div key={l} className={styles.recExcelLetterCell}>{l}</div>
                      ))}
                      <div className={`${styles.recExcelCell} ${styles.recExcelRowNumHeader}`}>Row</div>
                      {['T.C.No','Test Case','Steps','Expected Result','Input Data','Status','Error'].map(h => (
                        <div key={h} className={`${styles.recExcelCell} ${styles.recExcelHeaderCell}`}>{h}</div>
                      ))}
                      {confirmedExecResults.map((r, idx) => {
                        const rowCls = r.status === 'passed' ? styles.recExcelRowPassed : styles.recExcelRowFailed;
                        return (
                          <React.Fragment key={r.id}>
                            <div className={`${styles.recExcelCell} ${styles.recExcelRowNumCell} ${rowCls}`}>{idx + 1}</div>
                            <div className={`${styles.recExcelCell} ${rowCls}`}>{idx + 1}</div>
                            <div className={`${styles.recExcelCell} ${rowCls}`}>{r.name}</div>
                            <div className={`${styles.recExcelCell} ${styles.recExcelStepsCell} ${rowCls}`}>
                              {r.steps.map((s, i) => (
                                <span key={s.step_number}>{s.step_number}. {s.instruction}{i < r.steps.length - 1 ? '\n' : ''}</span>
                              ))}
                            </div>
                            <div className={`${styles.recExcelCell} ${rowCls}`}>{r.expected_results?.join('; ') || 'N/A'}</div>
                            <div className={`${styles.recExcelCell} ${rowCls}`}>
                              {Object.entries(r.test_data || {}).map(([k, v]) => `${k}: ${v}`).join(' | ')}
                            </div>
                            <div className={`${styles.recExcelCell} ${styles.recExcelStatusCell} ${rowCls}`}>
                              {r.status === 'passed'
                                ? <span className={styles.recExcelBadgePassed}>✓ PASSED</span>
                                : <span className={styles.recExcelBadgeFailed}>✗ FAILED</span>}
                            </div>
                            <div className={`${styles.recExcelCell} ${styles.recExcelErrorCell} ${rowCls}`}>{r.error || ''}</div>
                          </React.Fragment>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── LEFT / MAIN PANEL: chat ── */}
          <div className={styles.genChatPanel}>
          {/* Scrollable messages area */}
          <div className={styles.chatMessages}>

            {/* Static greeting bubble */}
            <motion.div
              className={styles.chatBotMessage}
              style={{ marginBottom: 16 }}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <div className={styles.chatBotAvatar}><Sparkles size={14} /></div>
              <div className={styles.chatBotContent}>
                <div className={styles.genAssistantBubble}>
                  Hi! I'm your AI test assistant. Share the URL of the page you'd like me to analyze, and I'll generate test cases based on the real elements found on that page.
                </div>
              </div>
            </motion.div>

            {/* Rendered conversation messages */}
            {chatMessages.map(msg => (
              <motion.div key={msg.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                {msg.role === 'user' ? (
                  <div className={styles.chatUserMessage} style={{ marginBottom: 16 }}>
                    <div className={styles.chatUserBubble}>{msg.content}</div>
                  </div>
                ) : (
                  <div className={styles.chatBotMessage} style={{ marginBottom: 16 }}>
                    <div className={styles.chatBotAvatar}><Sparkles size={14} /></div>
                    <div className={styles.chatBotContent}>
                      {msg.content.startsWith('Error:') ? (
                        <div className={styles.genErrorBubble}>
                          <AlertCircle size={14} style={{ flexShrink: 0 }} />
                          <span>{msg.content}</span>
                        </div>
                      ) : (
                        <div className={styles.genAssistantBubble}>{msg.content}</div>
                      )}
                      {/* Execution result card with per-TC confirm buttons */}
                      {msg.execSummary && (
                        <div className={styles.genExecResultCard}>
                          <div className={styles.genExecSummary}>
                            <div className={`${styles.genExecStat} ${styles.genExecStatTotal}`}>
                              <div className={styles.genExecStatValue}>{msg.execSummary.total}</div>
                              <div className={styles.genExecStatLabel}>Total</div>
                            </div>
                            <div className={`${styles.genExecStat} ${styles.genExecStatPassed}`}>
                              <div className={styles.genExecStatValue}>{msg.execSummary.passed}</div>
                              <div className={styles.genExecStatLabel}>Passed</div>
                            </div>
                            <div className={`${styles.genExecStat} ${styles.genExecStatFailed}`}>
                              <div className={styles.genExecStatValue}>{msg.execSummary.failed}</div>
                              <div className={styles.genExecStatLabel}>Failed</div>
                            </div>
                          </div>
                          {msg.execTestCases && msg.execTestCases.length > 0 && (
                            <div className={styles.genExecTcList}>
                              {msg.execTestCases.map(tc => (
                                <div key={tc.id} className={`${styles.genExecTcRow} ${tc.status === 'passed' ? styles.genExecTcPassed : styles.genExecTcFailed}`}>
                                  {tc.status === 'passed'
                                    ? <CheckCircle2 size={13} style={{ color: '#16a34a', flexShrink: 0 }} />
                                    : <XCircle size={13} style={{ color: '#dc2626', flexShrink: 0 }} />}
                                  <span className={styles.genExecTcName}>{tc.name}</span>
                                  {confirmedTcIds.has(tc.id)
                                    ? <span className={styles.genExecTcConfirmed}><Check size={11} /> Confirmed</span>
                                    : <button className={styles.genExecTcConfirmBtn} onClick={() => handleConfirmResult(tc)}>
                                        <Check size={11} /> Confirm
                                      </button>}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Inline test suite preview */}
                      {msg.testSuite && (
                        <div style={{ maxWidth: '88%' }}>
                          <div className={styles.genTestSuiteInChat}>
                            {msg.testSuite.test_cases?.map(tc => (
                              <div key={tc.id} className={styles.tcCard} style={{ borderRadius: 0, border: 'none', borderBottom: '1px solid #e2e8f0' }}>
                                <div
                                  className={styles.tcHeader}
                                  onClick={() => setChatExpandedTc(chatExpandedTc === tc.id ? null : tc.id)}
                                >
                                  <span className={styles.tcBadge}>{tc.id}</span>
                                  <span className={styles.tcName}>{tc.name}</span>
                                  <span className={styles.tcMeta}>{tc.steps.length} steps</span>
                                  <ChevronDown
                                    size={14}
                                    className={`${styles.tcChevron} ${chatExpandedTc === tc.id ? styles.open : ''}`}
                                  />
                                </div>
                                <AnimatePresence>
                                  {chatExpandedTc === tc.id && (
                                    <motion.div
                                      className={styles.tcSteps}
                                      initial={{ opacity: 0, height: 0 }}
                                      animate={{ opacity: 1, height: 'auto' }}
                                      exit={{ opacity: 0, height: 0 }}
                                      transition={{ duration: 0.2 }}
                                    >
                                      {tc.steps.map(step => (
                                        <div key={step.step_number} className={styles.step}>
                                          <div className={styles.stepNum}>{step.step_number}</div>
                                          <div className={styles.stepContent}>
                                            <p className={styles.stepInstruction}>{step.instruction}</p>
                                            <div className={styles.stepMeta}>
                                              <span className={styles.stepAction}>{step.action.type}</span>
                                              {step.selector_hints?.suggested_selectors?.[0] && (
                                                <span className={styles.stepSelector} title={step.selector_hints.suggested_selectors[0]}>
                                                  {step.selector_hints.suggested_selectors[0]}
                                                </span>
                                              )}
                                            </div>
                                          </div>
                                        </div>
                                      ))}
                                    </motion.div>
                                  )}
                                </AnimatePresence>
                              </div>
                            ))}
                          </div>
                          {/* Action buttons */}
                          <div className={styles.genTestSuiteActions}>
                            <button className={styles.btnSecondary} onClick={handleChatReset}>
                              <RotateCcw size={14} /> New URL
                            </button>
                            <button className={styles.btnSecondary} onClick={() => handleExportExcel(msg.testSuite!)}>
                              <FileSpreadsheet size={14} /> Export Excel
                            </button>
                            {projectName ? (
                              <button className={styles.btnSecondary} onClick={async () => {
                                try {
                                  await saveTestToProject(projectName, msg.testSuite!);
                                  setProjectActiveSuite(projectName, msg.testSuite! as unknown as TestSuite);
                                  addNotification('success', `Saved to ${projectName}`);
                                } catch (e) {
                                  addNotification('error', e instanceof Error ? e.message : 'Save failed');
                                }
                              }}>
                                <Save size={14} /> Save to History
                              </button>
                            ) : (
                              <button className={styles.btnSecondary} onClick={() => { setSuiteToSave(msg.testSuite!); setShowSaveModal(true); }}>
                                <Save size={14} /> Save to Project
                              </button>
                            )}
                            <button className={styles.btnPrimary} onClick={() => handleChatUseInAgent(msg.testSuite!)}>
                              <Play size={14} /> Use in Agent
                            </button>
                          </div>
                          {/* Suggestion chips — populate text input on click */}
                          <div className={styles.genSuggestionChips}>
                            {msg.testSuite.test_cases?.map((tc, idx) => (
                              <button
                                key={tc.id}
                                className={styles.genSuggestionChip}
                                onClick={() => {
                                  setChatTextInput(`Execute ${idx + 1}`);
                                  setTimeout(() => chatInputRef.current?.focus(), 50);
                                }}
                              >
                                <Play size={11} /> Execute {idx + 1}
                              </button>
                            ))}
                            <button
                              className={styles.genSuggestionChip}
                              onClick={() => {
                                setChatTextInput('Execute all');
                                setTimeout(() => chatInputRef.current?.focus(), 50);
                              }}
                            >
                              <Play size={11} /> Execute All
                            </button>
                            <button
                              className={`${styles.genSuggestionChip} ${styles.genSuggestionChipExcel}`}
                              onClick={() => handleExportExcel(msg.testSuite!)}
                            >
                              <FileSpreadsheet size={11} /> Export Excel
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </motion.div>
            ))}

            {/* Typing indicator while analyzing or generating */}
            {(chatPhase === 'analyzing' || chatPhase === 'generating') && (
              <motion.div
                className={styles.chatBotMessage}
                style={{ marginBottom: 16 }}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
              >
                <div className={styles.chatBotAvatar}><Sparkles size={14} /></div>
                <div className={styles.chatBotContent}>
                  <div className={styles.genTypingIndicator}>
                    <div className={styles.genTypingDot} />
                    <div className={styles.genTypingDot} />
                    <div className={styles.genTypingDot} />
                  </div>
                </div>
              </motion.div>
            )}

            <div ref={chatMessagesEndRef} />
          </div>

          {/* ── Unified bottom input bar — all phases ── */}
          <div className={styles.chatInputBar}>
            <div className={styles.chatInputInner}>
              {/* Action buttons row (New Chat + Save to Project) */}
              {chatSessionId && (
                <div className={styles.chatInputActions}>
                  <button
                    className={styles.chatActionBtn}
                    onClick={handleChatReset}
                    title="New Chat"
                  >
                    <RotateCcw size={14} />
                    <span>New Chat</span>
                  </button>
                  {lastTestSuite && (
                    <button
                      className={styles.chatActionBtn}
                      onClick={() => { setSuiteToSave(lastTestSuite); setShowSaveModal(true); }}
                      title="Save to Project"
                    >
                      <Save size={14} />
                      <span>Save to Project</span>
                    </button>
                  )}
                </div>
              )}
              <div className={styles.chatInputBox}>
                <textarea
                  ref={chatInputRef}
                  className={styles.chatTextarea}
                  rows={1}
                  placeholder={
                    chatPhase === 'url_input'
                      ? 'Enter a URL to analyze (e.g. https://myapp.com/login)…'
                      : chatPhase === 'analyzing'
                      ? 'Analyzing page…'
                      : chatPhase === 'executing'
                      ? 'Waiting for execution to finish…'
                      : 'Ask a question, share credentials, or type "Execute all"…'
                  }
                  value={chatTextInput}
                  onChange={e => {
                    setChatTextInput(e.target.value);
                    autoResizeTextarea(e.target);
                  }}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      const isDisabled = chatPhase === 'analyzing' || chatPhase === 'generating' || chatPhase === 'executing';
                      if (chatTextInput.trim() && !isDisabled) handleChatSend();
                    }
                  }}
                  disabled={chatPhase === 'analyzing' || chatPhase === 'generating' || chatPhase === 'executing'}
                  autoFocus={chatPhase === 'url_input'}
                />
                <button
                  className={styles.chatSendBtn}
                  onClick={handleChatSend}
                  disabled={chatPhase === 'analyzing' || chatPhase === 'generating' || chatPhase === 'executing' || !chatTextInput.trim()}
                  title="Send (Enter)"
                >
                  {(chatPhase === 'analyzing' || chatPhase === 'generating' || chatPhase === 'executing')
                    ? <Loader2 size={16} className={styles.spin} />
                    : <Send size={16} />
                  }
                </button>
              </div>
              <div className={styles.chatInputHint}>
                {chatPhase === 'url_input' && <span>Paste a URL and press Enter to analyze</span>}
                {chatPhase === 'analyzing' && <span style={{ color: '#6366f1' }}>Scraping page elements…</span>}
                {chatPhase === 'executing' && <span style={{ color: '#f59e0b', fontWeight: 600 }}>Executing tests…</span>}
                {(chatPhase === 'chatting' || chatPhase === 'generating' || chatPhase === 'done') && (
                  <span>Enter to send · Shift+Enter for newline · share credentials to use in tests</span>
                )}
              </div>
            </div>
          </div>
          </div>{/* end genChatPanel */}
        </div>
      )}


      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* RECORD MODE — ChatGPT style                                        */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      {mode === 'record' && (
        <div className={styles.chatLayout}>

          {/* ── IDLE / SETUP STATE — chatbot style ── */}
          {(recStatus === 'idle' || recStatus === 'error') && !recResult && (
            <div className={styles.chatMessages}>
              {/* Image analysis warning (shown in idle state too) */}
              {imageAnalysisEnabled && (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '8px 14px',
                  background: '#fef9c3',
                  border: '1px solid #fde047',
                  borderRadius: 8,
                  fontSize: '0.78rem',
                  color: '#713f12',
                  marginBottom: 12,
                }}>
                  <Zap size={13} style={{ color: '#b45309', flexShrink: 0 }} />
                  <span>
                    <strong>Image analysis is ON</strong> — when a selector cannot be found, a screenshot is sent to the vision model. Be aware of token usage.
                  </span>
                </div>
              )}
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                {/* Bot greeting bubble */}
                <div className={styles.chatBotMessage} style={{ marginBottom: 24 }}>
                  <div className={styles.chatBotAvatar}>
                    <Sparkles size={14} />
                  </div>
                  <div className={styles.chatBotContent}>
                    <div className={styles.idleGreetingBubble}>
                      <p className={styles.idleGreetingText}>
                        Hi! I'm your AI test recorder. Open a browser session by entering a URL below —
                        then describe actions in plain English and I'll execute them step by step.
                      </p>
                      <div className={styles.idleChips}>
                        <span className={styles.idleChip}><Globe size={11} /> Navigate pages</span>
                        <span className={styles.idleChip}><Play size={11} /> Click &amp; fill forms</span>
                        <span className={styles.idleChip}><Check size={11} /> Auto-generate test suite</span>
                      </div>
                    </div>
                  </div>
                </div>
              </motion.div>
            </div>
          )}

          {/* ── STARTING STATE ── */}
          {recStatus === 'starting' && (
            <div className={styles.chatMessages}>
              <motion.div
                className={styles.loadingCard}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <div className={styles.spinner} />
                <p className={styles.loadingTitle}>Launching browser…</p>
                <p className={styles.loadingStep}>
                  {recInstruction.trim()
                    ? `Opening ${recUrl} — will execute your test steps automatically`
                    : `Opening ${recUrl}`}
                </p>
              </motion.div>
            </div>
          )}

          {/* ── ACTIVE / EXECUTING / COMPLETING — chat messages ── */}
          {(recStatus === 'active' || recStatus === 'executing' || recStatus === 'completing') && (
            <>
              {/* Status bar */}
              <div className={styles.chatStatusBar}>
                <span className={`${styles.recStatusDot} ${recStatus === 'executing' || recStatus === 'completing' ? styles.recStatusExecuting : styles.recStatusActive}`} />
                <span className={styles.recStatusText}>
                  {recStatus === 'executing' ? 'Executing steps…'
                    : recStatus === 'completing' ? 'Completing recording…'
                    : 'Recording active'}
                </span>
                <span className={styles.recStepCount}>
                  {finalizedCases.length > 0
                    ? `Case ${currentCaseNumber} · ${allRecSteps.length} step${allRecSteps.length !== 1 ? 's' : ''} (${totalRecSteps} total)`
                    : `${allRecSteps.length} step${allRecSteps.length !== 1 ? 's' : ''}`
                  }
                </span>
              </div>

              {/* Image analysis warning banner */}
              {imageAnalysisEnabled && (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '7px 14px',
                  background: '#fef9c3',
                  border: '1px solid #fde047',
                  borderRadius: 6,
                  fontSize: '0.78rem',
                  color: '#713f12',
                  margin: '0 0 6px',
                }}>
                  <Zap size={13} style={{ color: '#b45309', flexShrink: 0 }} />
                  <span>
                    <strong>Image analysis is ON</strong> — screenshots are sent to the vision model when a selector fails. Be aware of token usage.
                  </span>
                </div>
              )}

              {/* Split layout: left = recording steps, right = large browser view */}
              <div className={styles.recSplitLayout}>

                {/* Left panel — recording steps + input */}
                <div className={styles.recLeftPanel}>
                  {/* Messages */}
                  <div className={styles.chatMessages} ref={messagesListRef}>
                    {recMessages.length === 0 && (
                      <motion.div
                        className={styles.chatEmptyState}
                        style={{ minHeight: 180 }}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                      >
                        <div className={styles.chatEmptyIcon} style={{ width: 44, height: 44 }}>
                          <Camera size={20} />
                        </div>
                        <p className={styles.chatEmptySubtitle} style={{ marginBottom: 0 }}>
                          Browser is open. Type an instruction below and press Enter.
                        </p>
                      </motion.div>
                    )}

                    {recMessages.map((msg, msgIdx) => {
                      const isCollapsed = collapsedMessages.has(msg.id);
                      // Which case boundary starts at this message index?
                      const boundaryIdx = caseBoundaries.indexOf(msgIdx);
                      // Show a "Case N complete / Case N+1 starts" divider before this message
                      const showCaseDivider = boundaryIdx !== -1;
                      const completedCaseNum = boundaryIdx + 1;
                      const nextCaseNum = boundaryIdx + 2;
                      return (
                        <React.Fragment key={msg.id}>
                          {showCaseDivider && (
                            <div className={styles.caseDivider}>
                              <div className={styles.caseDividerLine} />
                              <div className={styles.caseDividerLabel}>
                                <CheckCircle2 size={12} style={{ color: '#22c55e' }} />
                                <span>Test Case {completedCaseNum} complete — now recording Test Case {nextCaseNum}</span>
                              </div>
                              <div className={styles.caseDividerLine} />
                            </div>
                          )}
                        <motion.div
                          initial={{ opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                        >
                          {/* User bubble */}
                          {editingMessageId === msg.id ? (
                            <div className={styles.chatEditBox}>
                              <textarea
                                className={styles.chatEditTextarea}
                                value={editingText}
                                onChange={e => setEditingText(e.target.value)}
                                onKeyDown={e => { if (e.key === 'Escape') handleCancelEdit(); }}
                                autoFocus
                                rows={3}
                              />
                              <div className={styles.chatEditActions}>
                                <button className={styles.chatEditCancel} onClick={handleCancelEdit}>Cancel</button>
                                <button
                                  className={styles.chatEditRerun}
                                  disabled={editingText.trim() === msg.paragraph.trim() || editingText.trim() === '' || recStatus !== 'active'}
                                  onClick={() => handleRerun(msg)}
                                >Rerun</button>
                              </div>
                            </div>
                          ) : (
                            <div className={styles.chatUserMessage}>
                              <div className={styles.chatUserBubbleWrap}>
                                <div className={styles.chatUserActions}>
                                  <button
                                    className={`${styles.chatUserActionBtn} ${copiedMessageId === msg.id ? styles.chatUserActionBtnCopied : ''}`}
                                    onClick={() => handleCopyMessage(msg.id, msg.paragraph)}
                                    title={copiedMessageId === msg.id ? 'Copied!' : 'Copy'}
                                  >
                                    {copiedMessageId === msg.id
                                      ? <Check size={13} />
                                      : <Copy size={13} />
                                    }
                                  </button>
                                  {msgIdx >= currentCaseStartMsgIdx && (
                                    <button
                                      className={styles.chatUserActionBtn}
                                      onClick={() => handleStartEdit(msg)}
                                      title="Edit"
                                    >
                                      <Pencil size={13} />
                                    </button>
                                  )}
                                </div>
                                <div className={styles.chatUserBubble}>{msg.paragraph}</div>
                              </div>
                            </div>
                          )}

                          {/* Bot response */}
                          <div className={styles.chatBotMessage}>
                            <div className={styles.chatBotAvatar}>
                              <Sparkles size={14} />
                            </div>
                            <div className={styles.chatBotContent}>
                              <div className={`${styles.chatStepCard} ${msg.status === 'error' ? styles.chatStepCardError : ''}`}>
                                <div
                                  className={styles.chatStepHeader}
                                  onClick={() => toggleMessageCollapse(msg.id)}
                                >
                                  <div className={styles.chatStepLabelGroup}>
                                    <span className={styles.chatStepParagraph}>
                                      {msg.status === 'executing' ? 'Parsing and executing steps…'
                                        : msg.status === 'done' ? `Completed ${msg.steps.length} step${msg.steps.length !== 1 ? 's' : ''}`
                                        : `Error — ${msg.steps.length} step${msg.steps.length !== 1 ? 's' : ''} attempted`}
                                    </span>
                                    {msg.status === 'executing' && (
                                      <Loader2 size={14} className={styles.spin} style={{ color: '#6366f1' }} />
                                    )}
                                    {msg.status === 'done' && (
                                      <CheckCircle2 size={14} style={{ color: '#22c55e' }} />
                                    )}
                                    {msg.status === 'error' && (
                                      <XCircle size={14} style={{ color: '#ef4444' }} />
                                    )}
                                  </div>
                                  <div className={styles.chatStepHeaderRight}>
                                    {msg.status === 'done' && msg.steps.length > 0 && (
                                      <button
                                        className={`${styles.confirmBtn} ${confirmedMessages.has(msg.id) ? styles.confirmBtnActive : styles.confirmBtnInactive}`}
                                        onClick={(e) => handleToggleConfirm(msg.id, e)}
                                        title={confirmedMessages.has(msg.id) ? 'Remove from export' : 'Approve steps for export'}
                                      >
                                        <Check size={10} />
                                      </button>
                                    )}
                                    {msg.steps.length > 0 && (
                                      <span className={styles.chatStepCount}>{msg.steps.length}</span>
                                    )}
                                    {isCollapsed
                                      ? <ChevronRight size={13} style={{ color: '#94a3b8' }} />
                                      : <ChevronDown size={13} style={{ color: '#94a3b8' }} />
                                    }
                                  </div>
                                </div>

                                {!isCollapsed && msg.steps.length > 0 && (
                                  <div className={styles.chatSubSteps}>
                                    {msg.steps.map((step) => (
                                      <div key={step.step_number} className={`${styles.recStep} ${step.error ? styles.recStepError : ''}`}>
                                        <div className={styles.recStepNum}>{step.step_number}</div>
                                        <div className={styles.recStepContent}>
                                          <div className={styles.recStepInstruction}>{step.instruction}</div>
                                          <div className={styles.recStepMeta}>
                                            {renderActionBadge(step.action_type)}
                                            {renderStepIcon(step)}
                                            {step.error && <span className={styles.recStepErrorText}>{step.error}</span>}
                                          </div>
                                          {(step.validation_errors?.length ?? 0) > 0 && (
                                            <div className={styles.validationWarning}>
                                              <AlertCircle size={13} />
                                              <div>
                                                <div className={styles.valErrors}>
                                                  {step.validation_errors!.map((e, i) => <span key={i}>{e}</span>)}
                                                </div>
                                                {step.ai_suggestion && (
                                                  <p className={styles.aiSuggestion}>💡 {step.ai_suggestion}</p>
                                                )}
                                              </div>
                                            </div>
                                          )}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        </motion.div>
                        </React.Fragment>
                      );
                    })}

                    {recError && (
                      <div className={styles.errorCard}>
                        <AlertCircle size={16} className={styles.errorIcon} />
                        <div>
                          <p className={styles.errorTitle}>Error</p>
                          <p className={styles.errorMessage}>{recError}</p>
                        </div>
                      </div>
                    )}
                    <div ref={messagesEndRef} />
                  </div>

                  {/* Action bar: Complete / New Case / Cancel */}
                  <div className={styles.chatActionBar}>
                    <button
                      className={styles.btnPrimary}
                      onClick={handleCompleteRecording}
                      disabled={totalRecSteps === 0 || recStatus !== 'active'}
                    >
                      <CheckCircle2 size={14} />
                      Complete Test
                    </button>
                    <button
                      className={styles.btnSecondary}
                      onClick={handleNewCase}
                      disabled={allRecSteps.length === 0 || recStatus !== 'active'}
                      title={`Finalize Case ${currentCaseNumber} and start recording the next case`}
                    >
                      <Save size={14} />
                      Start New Case
                      {finalizedCases.length > 0 && (
                        <span className={styles.recExcelBadge}>{finalizedCases.length}</span>
                      )}
                    </button>
                    <button
                      className={styles.btnSecondary}
                      onClick={handleCancelRecording}
                      disabled={recStatus === 'completing'}
                    >
                      <X size={14} />
                      Cancel
                    </button>
                  </div>

                  {/* Chat input inside the right panel */}
                  <div className={styles.chatInputBar}>
                    <div className={styles.chatInputInner} style={{ maxWidth: '100%' }}>
                      <div className={styles.chatInputBox}>
                        <textarea
                          ref={(el) => {
                            (instructionRef as any).current = el;
                            (chatTextareaRef as any).current = el;
                          }}
                          className={styles.chatTextarea}
                          rows={1}
                          placeholder='Describe what to do next, e.g. "Login with email test@example.com and password abc123"'
                          value={recInstruction}
                          onChange={e => {
                            setRecInstruction(e.target.value);
                            autoResizeTextarea(e.target);
                          }}
                          onKeyDown={handleInstructionKeyDown}
                          disabled={recStatus === 'executing' || recStatus === 'completing'}
                        />
                        <button
                          className={styles.chatSendBtn}
                          onClick={handleExecuteSteps}
                          disabled={
                            recStatus === 'executing' ||
                            recStatus === 'completing' ||
                            !canExecuteSteps
                          }
                          title="Execute Steps (Enter)"
                        >
                          {recStatus === 'executing'
                            ? <Loader2 size={16} className={styles.spin} />
                            : <Send size={16} />
                          }
                        </button>
                      </div>
                      <div className={styles.chatInputHint}>
                        <span>Ctrl+Enter to execute</span>
                        {recStatus === 'active' && (
                          <span>
                            {finalizedCases.length > 0
                              ? `Case ${currentCaseNumber}: ${allRecSteps.length} step${allRecSteps.length !== 1 ? 's' : ''}`
                              : `${allRecSteps.length} step${allRecSteps.length !== 1 ? 's' : ''} recorded`
                            }
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>{/* end recLeftPanel */}

                {/* Right panel — Browser / Excel view */}
                <div className={styles.recRightPanel}>
                  {/* View toggle */}
                  <div className={styles.recViewToggle}>
                    <button
                      className={`${styles.recViewToggleBtn} ${recPanelView === 'browser' ? styles.recViewToggleActive : ''}`}
                      onClick={() => setRecPanelView('browser')}
                    >
                      <Monitor size={13} />
                      Browser View
                    </button>
                    <button
                      className={`${styles.recViewToggleBtn} ${recPanelView === 'excel' ? styles.recViewToggleActive : ''}`}
                      onClick={() => setRecPanelView('excel')}
                    >
                      <FileSpreadsheet size={13} />
                      Excel View
                      {totalRecSteps > 0 && (
                        <span className={styles.recExcelBadge}>{totalRecSteps}</span>
                      )}
                    </button>
                  </div>

                  {recPanelView === 'browser' && (
                    <>
                      <div className={styles.browserPanelHeader}>
                        <Camera size={13} />
                        <span>Live Browser View</span>
                        {recCurrentUrl && (
                          <span className={styles.screenshotCurrentUrl} title={recCurrentUrl}>
                            {recCurrentUrl}
                          </span>
                        )}
                      </div>
                      <div className={styles.browserPanelBody}>
                        {recScreenshot ? (
                          <img
                            src={`data:image/png;base64,${recScreenshot}`}
                            alt="Browser screenshot"
                            className={styles.screenshotImg}
                            style={{ width: '100%', height: '100%', objectFit: 'contain', objectPosition: 'top', display: 'block' }}
                          />
                        ) : (
                          <div className={styles.screenshotPlaceholder}>
                            <MonitorPlay size={48} style={{ color: '#cbd5e1' }} />
                            <span>Screenshot will appear after each action</span>
                          </div>
                        )}
                        {recStatus === 'executing' && (
                          <div className={styles.screenshotExecutingOverlay}>
                            <Loader2 size={28} className={styles.spin} style={{ color: '#6366f1' }} />
                          </div>
                        )}
                      </div>
                    </>
                  )}

                  {recPanelView === 'excel' && (
                    <div className={styles.recExcelGrid}>
                      {totalRecSteps === 0 ? (
                        <div className={styles.recExcelEmpty}>
                          <svg width="36" height="36" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <rect x="4" y="4" width="32" height="32" rx="3" stroke="#cbd5e1" strokeWidth="2" fill="none"/>
                            <line x1="4" y1="13" x2="36" y2="13" stroke="#cbd5e1" strokeWidth="1.5"/>
                            <line x1="4" y1="21" x2="36" y2="21" stroke="#e2e8f0" strokeWidth="1"/>
                            <line x1="4" y1="29" x2="36" y2="29" stroke="#e2e8f0" strokeWidth="1"/>
                            <line x1="14" y1="4" x2="14" y2="36" stroke="#e2e8f0" strokeWidth="1"/>
                            <line x1="24" y1="4" x2="24" y2="36" stroke="#e2e8f0" strokeWidth="1"/>
                          </svg>
                          <span>Steps appear here as you record</span>
                        </div>
                      ) : (
                        <div className={styles.recExcelTable}>
                          {/* Column letter row */}
                          <div className={styles.recExcelCorner}></div>
                          {['A','B','C','D','E','F','G'].map(l => (
                            <div key={l} className={styles.recExcelLetterCell}>{l}</div>
                          ))}
                          {/* Column name header row */}
                          <div className={`${styles.recExcelCell} ${styles.recExcelRowNumHeader}`}>Row</div>
                          {['T.C.No','Test Case','Test Case Steps','Expected Result','Input data','Status','Error'].map(h => (
                            <div key={h} className={`${styles.recExcelCell} ${styles.recExcelHeaderCell}`}>{h}</div>
                          ))}

                          {/* Finalized cases — one row each, shown as DONE */}
                          {finalizedCases.map((fc, idx) => (
                            <React.Fragment key={`fc-${idx}`}>
                              <div className={`${styles.recExcelCell} ${styles.recExcelRowNumCell} ${styles.recExcelRowPassed}`}>{idx + 1}</div>
                              <div className={`${styles.recExcelCell} ${styles.recExcelRowPassed}`}>{idx + 1}</div>
                              <div className={`${styles.recExcelCell} ${styles.recExcelRowPassed}`}>{fc.name}</div>
                              <div className={`${styles.recExcelCell} ${styles.recExcelStepsCell} ${styles.recExcelRowPassed}`}>
                                {fc.steps.map((s, i) => (
                                  <span key={s.step_number}>
                                    {`${s.step_number}. ${makeRefInstruction(s)}`}
                                    {i < fc.steps.length - 1 ? '\n' : ''}
                                  </span>
                                ))}
                              </div>
                              <div className={`${styles.recExcelCell} ${styles.recExcelRowPassed}`}>All recorded steps execute successfully</div>
                              <div className={`${styles.recExcelCell} ${styles.recExcelRowPassed}`}>
                                {Object.entries(fc.steps.reduce((acc, s) => {
                                  const td = s.test_data || {};
                                  Object.entries(td).forEach(([k, v]) => { if (v) acc[k] = String(v); });
                                  return acc;
                                }, {} as Record<string, string>)).map(([k, v]) => `${k}: ${v}`).join(' | ')}
                              </div>
                              <div className={`${styles.recExcelCell} ${styles.recExcelStatusCell} ${styles.recExcelRowPassed}`}>
                                <span className={styles.recExcelBadgePassed}>✓ DONE</span>
                              </div>
                              <div className={`${styles.recExcelCell} ${styles.recExcelErrorCell} ${styles.recExcelRowPassed}`}>
                                {fc.steps.reduce<string | null>((acc, s) => {
                                  if (acc) return acc;
                                  if (s.error) return s.error;
                                  if (s.validation_errors?.length) return s.validation_errors[0];
                                  return null;
                                }, null) || ''}
                              </div>
                            </React.Fragment>
                          ))}

                          {/* Current in-progress case */}
                          {allRecSteps.length > 0 && (() => {
                            const rowNum = finalizedCases.length + 1;
                            const rc = recExcelStatus === 'passed' ? styles.recExcelRowPassed
                                     : recExcelStatus === 'failed' ? styles.recExcelRowFailed
                                     : styles.recExcelRowRunning;
                            return (
                              <React.Fragment>
                                <div className={`${styles.recExcelCell} ${styles.recExcelRowNumCell} ${rc}`}>{rowNum}</div>
                                <div className={`${styles.recExcelCell} ${rc}`}>{rowNum}</div>
                                <div className={`${styles.recExcelCell} ${rc}`}>{`Test Case ${rowNum}`}</div>
                                <div className={`${styles.recExcelCell} ${styles.recExcelStepsCell} ${rc}`}>
                                  {allRecSteps.map((s, i) => (
                                    <span key={s.step_number} className={
                                      recStatus === 'executing' && i === allRecSteps.length - 1
                                        ? styles.recExcelActiveStep
                                        : undefined
                                    }>
                                      {`${s.step_number}. ${makeRefInstruction(s)}`}
                                      {i < allRecSteps.length - 1 ? '\n' : ''}
                                    </span>
                                  ))}
                                </div>
                                <div className={`${styles.recExcelCell} ${rc}`}>All recorded steps execute successfully</div>
                                <div className={`${styles.recExcelCell} ${rc}`}>{recExcelInputData}</div>
                                <div className={`${styles.recExcelCell} ${styles.recExcelStatusCell} ${rc}`}>
                                  {recExcelStatus === 'running'
                                    ? <span className={styles.recExcelBadgeRunning}>⟳ Recording</span>
                                    : recExcelStatus === 'passed'
                                    ? <span className={styles.recExcelBadgePassed}>✓ PASSED</span>
                                    : <span className={styles.recExcelBadgeFailed}>✗ FAILED</span>
                                  }
                                </div>
                                <div className={`${styles.recExcelCell} ${styles.recExcelErrorCell} ${rc}`}>{recExcelError || ''}</div>
                              </React.Fragment>
                            );
                          })()}

                          {/* Empty placeholder rows to fill the grid */}
                          {Array.from({ length: Math.max(0, 8 - finalizedCases.length - (allRecSteps.length > 0 ? 1 : 0)) }, (_, i) => {
                            const n = finalizedCases.length + (allRecSteps.length > 0 ? 1 : 0) + i + 1;
                            return (
                              <React.Fragment key={`empty-${n}`}>
                                <div className={`${styles.recExcelCell} ${styles.recExcelRowNumCell}`}>{n}</div>
                                {[0,1,2,3,4,5,6].map(c => (
                                  <div key={c} className={styles.recExcelCell}></div>
                                ))}
                              </React.Fragment>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>{/* end recRightPanel */}
              </div>{/* end recSplitLayout */}
            </>
          )}

          {/* ── COMPLETING STATE ── */}
          {recStatus === 'completing' && (
            <motion.div
              className={styles.loadingCard}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              style={{ marginTop: 12 }}
            >
              <div className={styles.spinner} />
              <p className={styles.loadingTitle}>Finalizing test suite…</p>
              <p className={styles.loadingStep}>Closing browser and building test suite from {allRecSteps.length} step(s)</p>
            </motion.div>
          )}

          {/* ── DONE — show result ── */}
          {recStatus === 'done' && recResult && (
            <div className={styles.chatMessages}>
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <div className={styles.pageSummary}>
                  <div className={styles.summaryItem}>
                    <span className={styles.summaryValue}>{recResult.step_count}</span>
                    <span className={styles.summaryLabel}>steps recorded</span>
                  </div>
                  <div className={styles.summaryItem}>
                    <span className={styles.summaryValue}>{recResult.test_suite.test_cases.length}</span>
                    <span className={styles.summaryLabel}>test cases</span>
                  </div>
                  <div className={styles.summaryItem}>
                    <span className={styles.summaryValue}>{recMessages.length}</span>
                    <span className={styles.summaryLabel}>instructions</span>
                  </div>
                </div>

                <div className={styles.resultsHeader}>
                  <h2 className={styles.resultsTitle}>
                    <Check size={18} style={{ color: '#22c55e' }} />
                    Recorded Test Suite
                    <span className={`${styles.badge} ${styles.badgeGreen}`}>
                      {recResult.step_count} steps
                    </span>
                  </h2>
                  <div className={styles.resultsActions}>
                    <button
                      className={styles.btnSecondary}
                      onClick={() => {
                        setRecStatus('idle');
                        setRecResult(null);
                        setRecMessages([]);
                        setRecScreenshot(null);
                        setRecError(null);
                        setCollapsedMessages(new Set());
                      }}
                    >
                      <RotateCcw size={14} />
                      Record Again
                    </button>
                    <button
                      className={styles.btnSecondary}
                      onClick={() => handleExportExcel(recResult.test_suite)}
                    >
                      <FileSpreadsheet size={14} />
                      Export Excel
                    </button>
                    <button
                      className={styles.btnSecondary}
                      onClick={() => handleExportRecorderJson(recResult.test_suite, recResult.export_json)}
                    >
                      <FileJson size={14} />
                      Export JSON
                    </button>
                    {projectName ? (
                      <button
                        className={styles.btnSecondary}
                        onClick={async () => {
                          try {
                            await saveTestToProject(projectName, recResult.test_suite);
                            setProjectActiveSuite(projectName, recResult.test_suite as unknown as TestSuite);
                            addNotification('success', `Saved to ${projectName}`);
                          } catch (e) {
                            addNotification('error', e instanceof Error ? e.message : 'Save failed');
                          }
                        }}
                      >
                        <Save size={14} />
                        Save to History
                      </button>
                    ) : (
                      <button
                        className={styles.btnSecondary}
                        onClick={() => { setSuiteToSave(recResult.test_suite); setShowSaveModal(true); }}
                      >
                        <Save size={14} />
                        Save to Project
                      </button>
                    )}
                    <button className={styles.btnPrimary} onClick={handleUseRecordedInAgent}>
                      <Play size={14} />
                      Use in Agent
                    </button>
                  </div>
                </div>

                {recResult.test_suite.test_cases.map(tc => (
                  <div key={tc.id} className={styles.tcCard}>
                    <div
                      className={styles.tcHeader}
                      onClick={() => setExpandedTc(expandedTc === tc.id ? null : tc.id)}
                    >
                      <span className={styles.tcBadge}>{tc.id}</span>
                      <span className={styles.tcName}>{tc.name}</span>
                      <span className={styles.tcMeta}>{tc.steps.length} steps</span>
                      <ChevronDown
                        size={16}
                        className={`${styles.tcChevron} ${expandedTc === tc.id ? styles.open : ''}`}
                      />
                    </div>
                    <AnimatePresence>
                      {expandedTc === tc.id && (
                        <motion.div
                          className={styles.tcSteps}
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: 'auto' }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ duration: 0.2 }}
                        >
                          {tc.steps.map(step => (
                            <div key={step.step_number} className={styles.step}>
                              <div className={styles.stepNum}>{step.step_number}</div>
                              <div className={styles.stepContent}>
                                <p className={styles.stepInstruction}>{step.instruction}</p>
                                <div className={styles.stepMeta}>
                                  <span className={styles.stepAction}>{step.action.type}</span>
                                  {step.selector_hints?.suggested_selectors?.[0] && (
                                    <span className={styles.stepSelector} title={step.selector_hints.suggested_selectors[0]}>
                                      {step.selector_hints.suggested_selectors[0]}
                                    </span>
                                  )}
                                  {step.assertions?.[0] && (
                                    <span style={{ color: '#16a34a', fontSize: '0.6875rem' }}>
                                      ✓ assert {step.assertions[0].type}: {step.assertions[0].expected_value}
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>
                          ))}
                          {tc.expected_results?.length > 0 && (
                            <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid #e2e8f0' }}>
                              <p style={{ fontSize: '0.75rem', color: '#64748b', margin: '0 0 4px', fontWeight: 600 }}>
                                Expected Result
                              </p>
                              {tc.expected_results.map((r, i) => (
                                <p key={i} style={{ fontSize: '0.8125rem', color: '#475569', margin: 0 }}>{r}</p>
                              ))}
                            </div>
                          )}
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                ))}
              </motion.div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════
              FIXED BOTTOM CHAT BAR
              Shown in idle/error states only (active/executing has its own bar inside the left panel)
              ══════════════════════════════════════════════════════ */}
          {(recStatus === 'idle' || recStatus === 'error') && !recResult && (
            <div className={styles.chatInputBar}>
              {/* URL config row — sits above the input box */}
              <div className={styles.chatInputInner}>
                <div className={styles.idleUrlRow}>
                  <input
                    className={styles.idleConfigInput}
                    type="url"
                    placeholder="https://myapp.com/login  — Enter the URL to open"
                    value={recUrl}
                    onChange={e => setRecUrl(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && canStartRecording) handleStartRecording();
                    }}
                    autoFocus
                  />
                  <input
                    className={styles.idleConfigInputSm}
                    type="text"
                    placeholder="App name (optional)"
                    value={recAppName}
                    onChange={e => setRecAppName(e.target.value)}
                  />
                </div>
                {recError && (
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, margin: '6px 0', padding: '7px 12px', background: '#fef2f2', borderRadius: 8, border: '1px solid #fecaca' }}>
                    <AlertCircle size={14} style={{ color: '#ef4444', flexShrink: 0, marginTop: 1 }} />
                    <span style={{ fontSize: '0.8125rem', color: '#dc2626' }}>{recError}</span>
                  </div>
                )}
              </div>
              <div className={styles.chatInputInner}>
                <div className={styles.chatInputBox}>
                  <textarea
                    ref={(el) => {
                      (instructionRef as any).current = el;
                      (chatTextareaRef as any).current = el;
                    }}
                    className={styles.chatTextarea}
                    rows={1}
                    placeholder='Optional: describe first steps to auto-execute after browser opens…'
                    value={recInstruction}
                    onChange={e => {
                      setRecInstruction(e.target.value);
                      autoResizeTextarea(e.target);
                    }}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !e.shiftKey && canStartRecording) {
                        e.preventDefault();
                        handleStartRecording();
                      }
                    }}
                    disabled={recStatus === 'error'}
                  />
                  <button
                    className={styles.chatSendBtn}
                    onClick={handleStartRecording}
                    disabled={!canStartRecording}
                    title="Open browser & start recording"
                  >
                    <MonitorPlay size={16} />

                    
                  </button>
                </div>
                <div className={styles.chatInputHint}>
                  <span>Enter a URL above · Press Enter to launch browser</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Floating screenshot panel removed — browser view is now always visible in split layout */}

      {/* Save to Project Modal — only in standalone mode (no projectName) */}
      {!projectName && showSaveModal && suiteToSave && (
        <SaveToProjectModal
          suite={suiteToSave}
          onClose={() => { setShowSaveModal(false); setSuiteToSave(null); }}
          onSaved={(projectName, _filename) => {
            setShowSaveModal(false);
            setSuiteToSave(null);
            addNotification('success', `Saved to project "${projectName}"`);
          }}
        />
      )}
    </div>
  );
};
