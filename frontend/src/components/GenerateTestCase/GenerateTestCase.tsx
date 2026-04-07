import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles, Globe, ChevronDown, ChevronRight,
  Play, FileSpreadsheet, AlertCircle, Check,
  Eye, EyeOff, RotateCcw, Video, MonitorPlay, Monitor, MonitorOff,
  Circle, CheckCircle2, XCircle, Loader2, Camera, X, Send,
  Zap, Save, FileJson, Pencil, Copy, PanelRightOpen, Maximize2, StopCircle
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import { SaveToProjectModal } from './SaveToProjectModal';
import { saveTestToProject } from '../../services/api';
import type { TestSuite } from '../../store/useStore';
import { ProviderSelect } from '../ProviderSelect/ProviderSelect';
import { WaterfallLoader } from '../WaterfallLoader';
import styles from './GenerateTestCase.module.css';
import ReactMarkdown from 'react-markdown';

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
  source?: string;
}

// ── Chatbot generate types ────────────────────────────────────────────────────

type ChatPhase = 'url_input' | 'analyzing' | 'chatting' | 'generating' | 'executing' | 'awaiting_input' | 'done';

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

interface FailedStep {
  step: number;
  action: string;
  instruction: string;
  error?: string;
}

interface NetworkError {
  url: string;
  status: number;
}

interface ExecTestResult {
  id: string;
  name: string;
  status: 'passed' | 'failed';
  steps: GeneratedSuite['test_cases'][0]['steps'];
  expected_results: string[];
  test_data: Record<string, unknown>;
  error?: string;
  grouped_ids?: string[];  // TS IDs merged into this row when using group mode
  failed_steps?: FailedStep[];
  console_errors?: string[];
  network_errors?: NetworkError[];
  start_url?: string;    // URL the browser was on when step 1 of this TC started
  step_urls?: string[];  // URL per step: [url_step1, url_step2, ...]
}

interface ChatMsg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  thinking?: boolean;
  testSuite?: GeneratedSuite;
  execSummary?: ExecSummary;
  execTestCases?: ExecTestResult[];
  tokens_used?: number;
  cost_usd?: number;
  session_total_tokens?: number;
  session_total_cost?: number;
  tsrId?: string; // TSR rerun badge label e.g. "TSR_001"
  isBrowserClosedMsg?: boolean; // True for "Test Interrupted" messages — renders Reopen + New Chat buttons
  browserClosedActioned?: boolean; // True once Reopen or New Chat was clicked — disables both buttons
}

interface RerunResult {
  tsrId: string;
  testId: string;
  testName: string;
  timestamp: string;
  status: 'running' | 'passed' | 'failed';
  error?: string;
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
  tokens_used?: number;
  cost_usd?: number;
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
  const { llmProvider, setTestSuite, setCurrentView, addNotification, imageAnalysisEnabled, setProjectActiveSuite, setHasUnsavedEditChanges, pendingNavigation, setPendingNavigation } = useStore();

  // ── Mode ─────────────────────────────────────────────────────────────────
  const [mode, setMode] = useState<Mode>('generate');

  // ── Generate mode state ──────────────────────────────────────────────────
  const [selectedProvider, setSelectedProvider] = useState(llmProvider);
  const [expandedTc, setExpandedTc] = useState<string | null>(null);

  // ── Chatbot generate mode state ──────────────────────────────────────────
  const [chatPhase, setChatPhase] = useState<ChatPhase>('url_input');
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const chatSessionIdRef = useRef<string | null>(null); // stable ref — always mirrors chatSessionId
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([]);
  const [typingMsg, setTypingMsg] = useState<{ id: string; full: string; shown: number } | null>(null);
  const [chatUrlInput, setChatUrlInput] = useState('');
  const [chatTextInput, setChatTextInput] = useState('');
  const [chatExpandedTc, setChatExpandedTc] = useState<string | null>(null);
  const chatMessagesEndRef = useRef<HTMLDivElement>(null);
  const chatScrollContainerRef = useRef<HTMLDivElement>(null);
  const chatContentRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUpRef = useRef(false);
  const chatInputRef = useRef<HTMLTextAreaElement>(null);
  const lastExecMsgRef = useRef<ChatMsg | null>(null);

  // ── Execution state (chatbot execute mode) ────────────────────────────────
  const [, setExecSessionId] = useState<string | null>(null);
  const execSseRef = useRef<EventSource | null>(null);
  const [execSteps, setExecSteps] = useState<ExecStepMsg[]>([]);
  const [, setExecSummary] = useState<ExecSummary | null>(null);
  const execStepsEndRef = useRef<HTMLDivElement>(null);
  const [execScreenshot, setExecScreenshot] = useState<string | null>(null);
  const [execCurrentUrl, setExecCurrentUrl] = useState('');
  const [browserPreviewLoading, setBrowserPreviewLoading] = useState(false);
  const [execPanelView, setExecPanelView] = useState<'browser' | 'excel'>('browser');
  const [confirmedExecResults, setConfirmedExecResults] = useState<ExecTestResult[]>([]);
  const [confirmedTcIds, setConfirmedTcIds] = useState<Set<string>>(new Set());
  const [browserClosed, setBrowserClosed] = useState(false);
  const browserClosedAlertedRef = useRef(false);
  const isAnalyzingRef = useRef(false); // guard against concurrent handleAnalyzeUrl calls

  // ── Excel edit mode ───────────────────────────────────────────────────────
  const [isExcelEditMode, setIsExcelEditMode] = useState(false);
  const [editedExcelData, setEditedExcelData] = useState<ExecTestResult[]>([]);
  const [editedRowIds, setEditedRowIds] = useState<Set<string>>(new Set());
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false);

  // ── Rerun tracking ────────────────────────────────────────────────────────
  const [rerunCounter, setRerunCounter] = useState(0);
  const [rerunResults, setRerunResults] = useState<RerunResult[]>([]);
  const rerunSessionRef = useRef<{ tsrId: string; testId: string } | null>(null);

  // ── Per-step URL tracking ─────────────────────────────────────────────────
  // Sync shadow of execCurrentUrl — always current inside SSE callbacks
  const currentUrlRef = useRef<string>('');
  // Captures browser URL at the start of every step: { testId: urlPerStep[] }
  const stepUrlMapRef = useRef<Record<string, string[]>>({});
  // Last storage state (cookies/localStorage) received from page_navigated SSE — used for Reopen
  const lastStorageStateRef = useRef<object | null>(null);

  // Last generated test suite (for suggestion buttons)
  const [lastTestSuite, setLastTestSuite] = useState<GeneratedSuite | null>(null);
  // Stored execute message to replay after user provides missing input data
  const [pendingExecuteMsg, setPendingExecuteMsg] = useState<string | null>(null);

  // ── Record mode state ────────────────────────────────────────────────────
  const [recUrl, setRecUrl] = useState('');
  const [recProvider, setRecProvider] = useState(llmProvider);
  const [recAppName] = useState('');
  const [recStatus, setRecStatus] = useState<RecordingStatus>('idle');
  const [recError, setRecError] = useState<string | null>(null);
  const [recMessages, setRecMessages] = useState<RecorderMessage[]>([]);
  const [recScreenshot, setRecScreenshot] = useState<string | null>(null);
  const [, setRecCurrentUrl] = useState('');
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

  // ── Browser overlay ───────────────────────────────────────────────────────
  const [showBrowserOverlay, setShowBrowserOverlay] = useState(false);
  const [browserSplit, setBrowserSplit] = useState(false);

  // ── Save to Project state ─────────────────────────────────────────────────
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [suiteToSave, setSuiteToSave] = useState<GeneratedSuite | null>(null);

  // ── Export Excel confirm dialog ───────────────────────────────────────────
  const [showExportConfirm, setShowExportConfirm] = useState(false);

  // ── New Chat confirm dialog ───────────────────────────────────────────────
  const [showNewChatConfirm, setShowNewChatConfirm] = useState(false);
  const newChatMsgIdRef = useRef<string | null>(null); // msg ID of the browser-closed button that triggered the dialog

  const sessionIdRef = useRef<string>(makeSessionId());
  const sseRef = useRef<EventSource | null>(null);
  const activeMsgIdRef = useRef<string | null>(null); // tracks which message is currently executing
  const chatThinkingIdRef = useRef<string | null>(null); // ID of the current typing-indicator bubble
  const execStepMsgIdRef = useRef<string | null>(null); // ID of the live "Executing step…" chat bubble
  const modeRef = useRef<Mode>(mode); // kept current so stale closures can read it
  useEffect(() => { modeRef.current = mode; }, [mode]);
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
  // Helpers to show / replace the typing indicator in the generate chat
  const _showThinking = (message: string) => {
    if (modeRef.current !== 'generate') return; // only relevant in generate chat
    if (chatThinkingIdRef.current) return; // already showing one
    const id = `thinking_${Date.now()}`;
    chatThinkingIdRef.current = id;
    setChatMessages(prev => [...prev, { id, role: 'assistant', content: message, thinking: true }]);
  };

  const _resolveThinking = (replacement: ChatMsg) => {
    const tid = chatThinkingIdRef.current;
    chatThinkingIdRef.current = null;
    setChatMessages(prev => {
      const filtered = tid ? prev.filter(m => m.id !== tid) : prev;
      return [...filtered, replacement];
    });
    // Start typewriter for the text content of every assistant message
    if (replacement.content) {
      setTypingMsg({ id: replacement.id, full: replacement.content, shown: 0 });
    }
  };

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

        // ── Generate-mode chat events ──────────────────────────────────────
        if (data.type === 'chat_thinking') {
          _showThinking(String(data.message ?? 'Thinking…'));

        } else if (data.type === 'chat_page_ready') {
          _resolveThinking({
            id: `ca_${Date.now()}`,
            role: 'assistant',
            content: String(data.message ?? ''),
          });
          setChatPhase('chatting');
          setTimeout(() => chatInputRef.current?.focus(), 50);

        } else if (data.type === 'browser_closed_during_exec') {
          setBrowserClosed(true);
          setExecScreenshot(null);
          setChatMessages(prev => [...prev, {
            id: `sys_${Date.now()}`,
            role: 'assistant',
            content: '*Execution aborted because the browser was closed manually.*',
            isBrowserClosedMsg: true,
          }]);
        } else if (data.type === 'chat_test_suite') {
          const suite = data.test_suite as GeneratedSuite | undefined;
          _resolveThinking({
            id: `ca_${Date.now()}`,
            role: 'assistant',
            content: String(data.message ?? ''),
            testSuite: suite,
            tokens_used: data.tokens_used,
            cost_usd: data.cost_usd,
            session_total_tokens: data.session_total_tokens,
            session_total_cost: data.session_total_cost,
          });
          if (suite) {
            setLastTestSuite(suite);
            setChatExpandedTc(null);
            if (data.intent !== 'edit') {
              addNotification('success', `Generated ${suite.test_cases?.length ?? 0} test case(s)`);
            }
          }
          setChatPhase('chatting');

        } else if (data.type === 'chat_response') {
          _resolveThinking({
            id: `ca_${Date.now()}`,
            role: 'assistant',
            content: String(data.message ?? ''),
            tokens_used: data.tokens_used,
            cost_usd: data.cost_usd,
            session_total_tokens: data.session_total_tokens,
            session_total_cost: data.session_total_cost,
          });
          setChatPhase('chatting');

        } else if (data.type === 'chat_approve') {
          const directResults = data.results as ExecTestResult[] | undefined;
          const targets = data.targets as 'all' | number[] | string[];

          let toConfirm: ExecTestResult[] = [];

          if (directResults && directResults.length > 0) {
            // Primary path: full result objects embedded directly in SSE event
            toConfirm = directResults;
          } else {
            // Fallback: resolve from lastExecMsgRef (backward compat)
            const lastExec = lastExecMsgRef.current;
            if (lastExec?.execTestCases?.length) {
              if (targets === 'all') {
                toConfirm = lastExec.execTestCases;
              } else if (Array.isArray(targets) && typeof (targets as unknown[])[0] === 'number') {
                toConfirm = (targets as number[])
                  .map(n => lastExec.execTestCases![n - 1])
                  .filter(Boolean) as ExecTestResult[];
              } else {
                toConfirm = lastExec.execTestCases.filter(tc =>
                  (targets as string[]).some(name =>
                    tc.name.toLowerCase().includes(name.toLowerCase())
                  )
                );
              }
            }
          }

          if (toConfirm.length > 0) {
            setConfirmedExecResults(prev => {
              const existingIds = new Set(prev.map(tc => tc.id));
              const existingGroupedIds = new Set(prev.flatMap(tc => tc.grouped_ids ?? []));
              return [
                ...prev,
                ...toConfirm.filter(tc =>
                  !existingIds.has(tc.id) &&
                  !(tc.grouped_ids ?? []).some(gid => existingGroupedIds.has(gid))
                ),
              ];
            });
            setConfirmedTcIds(prev => {
              const next = new Set(prev);
              toConfirm.forEach(tc => {
                next.add(tc.id);
                (tc.grouped_ids ?? []).forEach(gid => next.add(gid));
              });
              return next;
            });
            setExecPanelView('excel');
          }

          _resolveThinking({
            id: `ca_${Date.now()}`,
            role: 'assistant',
            content: String(data.message ?? 'Done.'),
          });
          setChatPhase('chatting');

        } else if (data.type === 'chat_error') {
          _resolveThinking({
            id: `ce_${Date.now()}`,
            role: 'assistant',
            content: String(data.message ?? 'Something went wrong. Please try again.'),
          });
          setChatPhase('chatting');

        // ── Browser preview (loaded on URL submit, before execution) ──────
        } else if (data.type === 'browser_preview') {
          setBrowserClosed(false);
          setExecScreenshot(data.image);
          if (data.url) setExecCurrentUrl(data.url);
          setBrowserPreviewLoading(false);

        // ── Recorder events ────────────────────────────────────────────────
        } else if (data.type === 'recorder_screenshot') {
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const disconnectSSE = useCallback(() => {
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
  }, []);

  useEffect(() => () => disconnectSSE(), [disconnectSSE]);

  // ── Session cleanup helper — callable from any code path ─────────────────
  // Uses a ref so it always sees the current session ID regardless of closure age.
  const closeBrowserSession = useCallback((sessionId?: string | null) => {
    const id = sessionId ?? chatSessionIdRef.current;
    if (!id) return;
    fetch(`${API_BASE}/api/v1/browser-session/${id}`, {
      method: 'DELETE',
      keepalive: true,
    }).catch(() => {});
  }, []);

  // Keep ref in sync with state so closeBrowserSession always has the latest ID.
  // Also update the ref synchronously via a wrapper used throughout this component.
  const setSessionId = useCallback((id: string | null) => {
    chatSessionIdRef.current = id;
    setChatSessionId(id);
  }, []);

  useEffect(() => {
    chatSessionIdRef.current = chatSessionId;
  }, [chatSessionId]);

  // ── Session cleanup on tab close / page refresh ───────────────────────────
  // Registered ONCE — reads chatSessionIdRef.current at event time so it is
  // never stale regardless of when chatSessionId state changes.
  useEffect(() => {
    const onUnload = () => closeBrowserSession(); // always reads ref
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, [closeBrowserSession]);

  // ── Session cleanup on component unmount (route change) ───────────────────
  useEffect(() => {
    return () => closeBrowserSession(); // reads ref at unmount time
  }, [closeBrowserSession]);

  // ── Periodic live-browser screenshot (every 10 s) ─────────────────────────
  // Polls the current page screenshot from the persistent executor session so
  // the browser panel stays live even when no test is running (loaders, idle, etc.)
  // Skipped while chatPhase === 'executing' — SSE already streams screenshots then.
  useEffect(() => {
    if (!chatSessionId) return;
    const poll = async () => {
      if (chatPhase === 'executing' || chatPhase === 'analyzing') return;
      try {
        const res = await fetch(`${API_BASE}/api/v1/browser-screenshot/${chatSessionId}`);
        if (!res.ok) return;
        const data = await res.json();
        
        if (data.browser_closed) {
          setBrowserClosed(true);
          setExecScreenshot(null);
          setExecCurrentUrl('');

          // Stop any in-flight LLM response from being rendered after the interrupt.
          // Close the SSE so the backend's chat_test_suite / chat_response never arrives.
          if (sseRef.current) {
            sseRef.current.close();
            sseRef.current = null;
          }
          // Dismiss the thinking spinner if one is showing.
          const tid = chatThinkingIdRef.current;
          if (tid) {
            chatThinkingIdRef.current = null;
            setChatMessages(prev => prev.filter(m => m.id !== tid));
          }
          // Unblock the input so the user isn't stuck.
          setChatPhase(prev => prev === 'generating' ? 'chatting' : prev);

          if (!browserClosedAlertedRef.current) {
            browserClosedAlertedRef.current = true;
            setChatMessages(prev => [...prev, {
              id: `sys_${Date.now()}`,
              role: 'assistant',
              content: '*Test Interrupted. The browser window was closed unfortunately.*',
              isBrowserClosedMsg: true,
            }]);
          }
          return;
        }

        if (data.image_b64) setExecScreenshot(data.image_b64);
        if (data.url) { setExecCurrentUrl(data.url); currentUrlRef.current = data.url; }
      } catch { setBrowserClosed(true); setExecScreenshot(null); }
    };
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, [chatSessionId, chatPhase]);

  // ── Computed flags ────────────────────────────────────────────────────────
  const canStartRecording = recUrl.trim().length > 0 && (recStatus === 'idle' || recStatus === 'error');
  const canExecuteSteps = recInstruction.trim().length > 0 && recStatus === 'active';

  // ==========================================================================
  // Generate mode helpers
  // ==========================================================================

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

  const handleExportConfirmedExcel = async () => {
    if (confirmedExecResults.length === 0) {
      addNotification('error', 'No confirmed results to export yet');
      return;
    }
    const suite: GeneratedSuite = {
      project: lastTestSuite?.project || 'Test Results',
      base_url: lastTestSuite?.base_url || '',
      test_cases: confirmedExecResults.map(r => ({
        id: r.id,
        name: r.name,
        steps: r.steps,
        expected_results: r.expected_results,
      })),
      common_selectors: lastTestSuite?.common_selectors || {},
      test_data: lastTestSuite?.test_data || {},
    };
    await handleExportExcel(suite);
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

  // ==========================================================================
  // Chatbot generate mode handlers
  // ==========================================================================

  // Auto-scroll chat to bottom — paused when user manually scrolls up
  const scrollChatToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    if (isUserScrolledUpRef.current) return;
    chatMessagesEndRef.current?.scrollIntoView({ behavior });
  }, []);

  const handleChatScroll = useCallback(() => {
    const el = chatScrollContainerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    // Resume auto-scroll when user returns within 50 px of the bottom
    isUserScrolledUpRef.current = distanceFromBottom > 50;
  }, []);

  // ResizeObserver — fires whenever the content div grows (new messages, test
  // suite cards, framer-motion layout, etc.) so scroll happens after actual DOM paint
  useEffect(() => {
    const content = chatContentRef.current;
    if (!content) return;
    const observer = new ResizeObserver(() => scrollChatToBottom());
    observer.observe(content);
    return () => observer.disconnect();
  }, [scrollChatToBottom]);

  // Scroll on every typewriter tick so streaming text feels live
  useEffect(() => {
    if (typingMsg) scrollChatToBottom();
  }, [typingMsg, scrollChatToBottom]);

  // Typewriter animation — advances 8 chars every 8ms ≈ ~1,000 chars/s
  // (~3× faster than before while keeping the smooth streaming feel)
  useEffect(() => {
    if (!typingMsg) return;
    if (typingMsg.shown >= typingMsg.full.length) {
      setTypingMsg(null);
      return;
    }
    const timer = setTimeout(() => {
      setTypingMsg(prev => prev ? { ...prev, shown: Math.min(prev.shown + 8, prev.full.length) } : null);
    }, 8);
    return () => clearTimeout(timer);
  }, [typingMsg]);

  const appendChatMsg = (msg: ChatMsg) => {
    setChatMessages(prev => [...prev, msg]);
    // Trigger typewriter for plain assistant messages (not thinking bubbles or exec summaries)
    if (msg.role === 'assistant' && !msg.thinking && !msg.execSummary && msg.content) {
      setTypingMsg({ id: msg.id, full: msg.content, shown: 0 });
    }
  };

  const markBrowserClosedActioned = (msgId: string) => {
    setChatMessages(prev => prev.map(m => m.id === msgId ? { ...m, browserClosedActioned: true } : m));
  };

  const _URL_PATTERN = /^(https?:\/\/|www\.)\S+/i;
  const looksLikeUrl = (text: string) => _URL_PATTERN.test(text.trim());


  const handleAnalyzeUrl = async (urlOverride?: string, storageState?: object | null, isReopen = false) => {
    const trimmedUrl = (urlOverride ?? chatUrlInput).trim();
    if (!trimmedUrl) return;
    // Prevent concurrent calls — second tap/click while first is in flight
    if (isAnalyzingRef.current) return;
    isAnalyzingRef.current = true;

    setChatUrlInput(trimmedUrl);
    appendChatMsg({
      id: `cu_${Date.now()}`,
      role: 'user',
      content: isReopen ? `Reopen the browser` : trimmedUrl,
    });
    setChatPhase('analyzing');
    setBrowserPreviewLoading(true);
    setBrowserClosed(false);
    browserClosedAlertedRef.current = false;

    // Close the previous browser synchronously. Don't set chatSessionId to ''
    // as an intermediate — that would deregister the beforeunload listener and
    // leave a gap where a page refresh can't clean up the new session.
    if (chatSessionIdRef.current) {
      closeBrowserSession(chatSessionIdRef.current);
    }

    chatThinkingIdRef.current = null; // reset any stale thinking state
    _showThinking('Analyzing page…'); // show dots immediately, before network round-trip

    try {
      const res = await fetch(`${API_BASE}/api/v1/analyze-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: trimmedUrl, llm_provider: selectedProvider, ...(storageState ? { storage_state: storageState } : {}) }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Server error');
      }
      const data = await res.json();
      setSessionId(data.session_id); // update ref + state atomically
      connectSSE(data.session_id);
      // chat_page_ready SSE event will call _resolveThinking + setChatPhase('chatting')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      _resolveThinking({ id: `ce_${Date.now()}`, role: 'assistant', content: msg });
      setChatPhase('url_input');
      addNotification('error', `Analyse failed: ${msg}`);
    } finally {
      isAnalyzingRef.current = false;
    }
  };

  // ── Reopen browser at last known URL with restored session state ───────────
  const handleReopen = useCallback(async () => {
    // Use the original session URL (what was submitted in the URL input) as the
    // reopen target. currentUrlRef tracks every navigation including error/redirect
    // pages (/no-access, etc.) so it is not reliable as a reopen target.
    const reopenUrl = chatUrlInput || currentUrlRef.current;
    if (!reopenUrl) return;

    // Remove execution result messages that were never confirmed to Excel.
    // Confirmed messages keep their "In Excel" badge; unconfirmed ones won't
    // match the restored page state so they are cleaned up.
    setChatMessages(prev => prev.filter(msg => {
      if (!msg.execTestCases?.length) return true;
      return msg.execTestCases.some(tc => confirmedTcIds.has(tc.id));
    }));

    // Reset browser state but keep confirmed Excel results and last test suite
    setExecSteps([]);
    setExecSummary(null);
    setExecScreenshot(null);

    // Reopen the original URL, restoring session cookies so the user stays logged in
    await handleAnalyzeUrl(reopenUrl, lastStorageStateRef.current, true);
  }, [confirmedTcIds, chatUrlInput]);

  // ── Execution SSE connection ───────────────────────────────────────────────
  // Always-current ref so the SSE onmessage handler never uses a stale closure
  const handleExecSseEventRef = useRef<(data: Record<string, unknown>) => void>(() => {});

  const connectExecutionSSE = (sid: string) => {
    if (execSseRef.current) {
      execSseRef.current.close();
      execSseRef.current = null;
      setBrowserClosed(false);
      setExecScreenshot(null);
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
        execStepMsgIdRef.current = null; // reset so next run gets a fresh bubble
        // Show results and unblock input — keep SSE open for page_analysis_done that may follow
        const summary = data.summary as ExecSummary;
        setExecSummary(summary);
        setChatPhase('chatting');
        const rawTcResults = (data.tc_results as ExecTestResult[] | undefined) ?? [];

        // Enrich each result with per-step URLs captured during execution
        const tcResults: ExecTestResult[] = rawTcResults.map(r => ({
          ...r,
          step_urls: stepUrlMapRef.current[r.id] ?? [],
          start_url: stepUrlMapRef.current[r.id]?.[0] ?? '',
        }));
        stepUrlMapRef.current = {}; // clear for next run

        // If this was a rerun, update only that row rather than clearing all results
        const currentRerun = rerunSessionRef.current;
        if (currentRerun) {
          const matchedTc = tcResults.find(r => r.id === currentRerun.testId)
            ?? tcResults.find(r => r.name && currentRerun.testId && r.name.toLowerCase().includes(currentRerun.testId.toLowerCase()));
          const newStatus = matchedTc?.status ?? (summary.failed > 0 ? 'failed' : 'passed');
          setRerunResults(prev => prev.map(r =>
            r.tsrId === currentRerun.tsrId ? { ...r, status: newStatus, error: matchedTc?.error } : r
          ));
          if (matchedTc) {
            setConfirmedExecResults(prev =>
              prev.map(r => r.id === matchedTc.id ? { ...matchedTc } : r)
            );
          }
          rerunSessionRef.current = null;
          const rerunDoneMsg: ChatMsg = {
            id: `ca_${Date.now()}`,
            role: 'assistant',
            content: String(data.message ?? 'Rerun complete.'),
            execSummary: summary,
            execTestCases: tcResults,
            tsrId: currentRerun.tsrId,
          };
          appendChatMsg(rerunDoneMsg);
          lastExecMsgRef.current = rerunDoneMsg;
          break;
        }

        const execDoneMsg: ChatMsg = {
          id: `ca_${Date.now()}`,
          role: 'assistant',
          content: String(data.message ?? 'Execution complete.'),
          execSummary: summary,
          execTestCases: tcResults,
        };
        appendChatMsg(execDoneMsg);
        lastExecMsgRef.current = execDoneMsg;
        break;
      }
      case 'exec_session_complete': {
        // All backend post-processing done — safe to close SSE now
        if (execSseRef.current) { execSseRef.current.close(); execSseRef.current = null; }
        // Safety net: if chat_execution_done was missed (e.g. oversized payload), unblock UI here
        setChatPhase(prev => prev === 'executing' ? 'chatting' : prev);
        break;
      }
      case 'page_analysis_start': {
        // Show gradient loading bubble while the new page is being analyzed
        const navThinkingId = `nav_thinking_${Date.now()}`;
        chatThinkingIdRef.current = navThinkingId;
        setChatMessages(prev => [...prev, { id: navThinkingId, role: 'assistant', content: String(data.message ?? 'Analyzing the new page…'), thinking: true }]);
        if (data.url) { setExecCurrentUrl(String(data.url)); currentUrlRef.current = String(data.url); }
        break;
      }
      case 'page_analysis_done': {
        // Replace the thinking bubble with the full page intro
        const tid = chatThinkingIdRef.current;
        chatThinkingIdRef.current = null;
        if (tid) setChatMessages(prev => prev.filter(m => m.id !== tid));
        const navMsg = String(data.message ?? '');
        if (navMsg) {
          appendChatMsg({ id: `nav_done_${Date.now()}`, role: 'assistant', content: navMsg });
        }
        if (data.url) { setExecCurrentUrl(String(data.url)); currentUrlRef.current = String(data.url); setChatUrlInput(String(data.url)); }
        // New page is ready — unblock the chat input so user can interact immediately
        // even if the background test execution hasn't fully completed yet
        setChatPhase(prev => prev === 'executing' ? 'chatting' : prev);
        break;
      }
      case 'exec_screenshot': {
        if (data.image_b64) setExecScreenshot(String(data.image_b64));
        if (data.url) { setExecCurrentUrl(String(data.url)); currentUrlRef.current = String(data.url); }
        break;
      }
      case 'page_navigated': {
        const navUrl = String(data.url ?? '');
        const elemSummary = String(data.elements_summary ?? `Browser navigated to: ${navUrl}`);
        if (navUrl) { setExecCurrentUrl(navUrl); currentUrlRef.current = navUrl; }
        if (data.image_b64) setExecScreenshot(String(data.image_b64));
        // Track latest session state for Reopen restore
        if (data.storage_state) lastStorageStateRef.current = data.storage_state as object;
        appendChatMsg({
          id: `nav_${Date.now()}`,
          role: 'assistant',
          content: elemSummary,
        });
        break;
      }
      case 'chat_step_executing': {
        // Show/update a single live "Executing…" bubble in the chat for each step
        const stepNum = Number(data.step_number ?? 0);
        const totalSteps = Number(data.total_steps ?? 0);
        const stepInstr = String(data.instruction ?? '');
        const stepContent = totalSteps > 0
          ? `▶ Step ${stepNum}/${totalSteps}: ${stepInstr}`
          : `▶ Step ${stepNum}: ${stepInstr}`;
        if (!execStepMsgIdRef.current) {
          // First step — create the bubble
          const msgId = `exec_step_${Date.now()}`;
          execStepMsgIdRef.current = msgId;
          appendChatMsg({ id: msgId, role: 'assistant', content: stepContent });
        } else {
          // Subsequent steps — update existing bubble in-place
          const msgId = execStepMsgIdRef.current;
          setChatMessages(prev => prev.map(m =>
            m.id === msgId ? { ...m, content: stepContent } : m
          ));
        }
        // Capture browser URL at the start of this step (irrespective of navigation).
        // Prefer the URL sent directly from the backend (page.url before step executes).
        if (stepNum > 0 && data.test_id) {
          const stId = String(data.test_id);
          const stepUrl = String(data.current_url || currentUrlRef.current || '');
          const existing = stepUrlMapRef.current[stId] ?? [];
          existing[stepNum - 1] = stepUrl;
          stepUrlMapRef.current[stId] = existing;
        }
        break;
      }
      case 'rerun_navigating': {
        // Browser is navigating to start_url before executing steps
        const navTarget = String(data.url ?? data.message ?? '');
        appendChatMsg({
          id: `rerun_nav_${Date.now()}`,
          role: 'assistant',
          content: `Navigating to ${navTarget} before running test...`,
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
        appendChatMsg({ id: `ce_${Date.now()}`, role: 'assistant', content: String(data.message ?? 'Execution failed. Please try again.') });
        setChatPhase('chatting');
        break;
    }
  };

  // ── Chat execute handler ──────────────────────────────────────────────────
  const handleChatExecute = async (userMessage: string, inputData?: Record<string, string>, rawInputText?: string) => {
    if (!chatSessionId) return;
    setChatPhase('executing');
    execStepMsgIdRef.current = null; // reset for fresh run
    setExecSteps([]);
    setExecSummary(null);
    setExecScreenshot(null);
    setExecCurrentUrl('');
    currentUrlRef.current = '';
    stepUrlMapRef.current = {};
    setExecPanelView('browser');

    if (!inputData) {
      // Only append user message on first call (not when re-calling after needs_input)
      appendChatMsg({ id: `cu_${Date.now()}`, role: 'user', content: userMessage });
    }

    try {
      const body: Record<string, unknown> = {
        session_id: chatSessionId,
        user_message: userMessage,
        llm_provider: selectedProvider,
        headless: true,
        timeout: 30000,
      };
      if (inputData) body.input_data = inputData;
      if (rawInputText) body.input_text = rawInputText;

      const res = await fetch(`${API_BASE}/api/v1/chat-execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Server error');
      }
      const data = await res.json();

      if (data.status === 'needs_input') {
        // Backend needs credentials / data before it can execute
        setPendingExecuteMsg(userMessage);
        appendChatMsg({ id: `ca_${Date.now()}`, role: 'assistant', content: data.message });
        setChatPhase('awaiting_input');
        return;
      }

      // Normal start
      setPendingExecuteMsg(null);
      setExecSessionId(data.exec_session_id);
      appendChatMsg({ id: `ca_${Date.now()}`, role: 'assistant', content: data.message });
      connectExecutionSSE(data.exec_session_id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      appendChatMsg({ id: `ce_${Date.now()}`, role: 'assistant', content: msg });
      setChatPhase('chatting');
      addNotification('error', `Execute failed: ${msg}`);
    }
  };

  // ── Excel edit handlers ───────────────────────────────────────────────────

  const handleExcelCellEdit = (id: string, field: 'name' | 'expected_results', value: string) => {
    setEditedExcelData(prev => prev.map(r => {
      if (r.id !== id) return r;
      return field === 'expected_results'
        ? { ...r, expected_results: value.split(';').map(s => s.trim()).filter(Boolean) }
        : { ...r, [field]: value };
    }));
    setEditedRowIds(prev => new Set([...prev, id]));
    setHasUnsavedChanges(true);
    setHasUnsavedEditChanges(true);
  };

  const handleExcelStepsEdit = (id: string, value: string) => {
    const lines = value.split('\n').filter(l => l.trim());
    setEditedExcelData(prev => prev.map(r => {
      if (r.id !== id) return r;
      const newSteps = lines.map((line, i) => {
        const existing = r.steps[i];
        const instruction = line.replace(/^\d+\.\s*/, '').trim();
        return existing
          ? { ...existing, instruction }
          : { ...r.steps[0], step_number: i + 1, instruction };
      });
      return { ...r, steps: newSteps };
    }));
    setEditedRowIds(prev => new Set([...prev, id]));
    setHasUnsavedChanges(true);
    setHasUnsavedEditChanges(true);
  };

  const handleExcelInputDataEdit = (id: string, value: string) => {
    const testData: Record<string, string> = {};
    value.split('\n').filter(l => l.includes(':')).forEach(line => {
      const colonIdx = line.indexOf(':');
      if (colonIdx > 0) {
        const k = line.slice(0, colonIdx).trim();
        const v = line.slice(colonIdx + 1).trim();
        if (k && v) testData[k] = v;
      }
    });
    setEditedExcelData(prev => prev.map(r =>
      r.id === id ? { ...r, test_data: testData } : r
    ));
    setEditedRowIds(prev => new Set([...prev, id]));
    setHasUnsavedChanges(true);
    setHasUnsavedEditChanges(true);
  };

  const handleExcelEditSave = () => {
    setConfirmedExecResults([...editedExcelData]);
    setHasUnsavedChanges(false);
    setHasUnsavedEditChanges(false);
    setIsExcelEditMode(false);
    setShowDiscardConfirm(false);
  };

  const handleExcelEditCancel = () => {
    if (hasUnsavedChanges) {
      setShowDiscardConfirm(true);
    } else {
      setIsExcelEditMode(false);
      setShowDiscardConfirm(false);
    }
  };

  const handleExcelEditDiscard = () => {
    setIsExcelEditMode(false);
    setHasUnsavedChanges(false);
    setHasUnsavedEditChanges(false);
    setShowDiscardConfirm(false);
    setEditedExcelData([]);
    setEditedRowIds(new Set());
  };

  // ── Rerun handler ─────────────────────────────────────────────────────────

  const handleExcelRerun = async (tc: ExecTestResult) => {
    if (!chatSessionId) return;

    const newCounter = rerunCounter + 1;
    setRerunCounter(newCounter);
    const tsrId = `TSR_${String(newCounter).padStart(3, '0')}`;

    const rerunEntry: RerunResult = {
      tsrId,
      testId: tc.id,
      testName: tc.name,
      timestamp: new Date().toISOString(),
      status: 'running',
    };
    setRerunResults(prev => [...prev, rerunEntry]);

    // Reset exec display state but preserve confirmedExecResults
    execStepMsgIdRef.current = null;
    setExecSteps([]);
    setExecSummary(null);
    setExecScreenshot(null);
    setExecCurrentUrl('');
    currentUrlRef.current = '';
    stepUrlMapRef.current = {};
    setExecPanelView('browser');
    setChatPhase('executing');

    // Tag so SSE handler knows this is a rerun
    rerunSessionRef.current = { tsrId, testId: tc.id };

    // Add TSR badge message to chat
    appendChatMsg({
      id: `tsr_${Date.now()}`,
      role: 'assistant',
      content: `Rerunning: _${tc.name.replace(/\*+/g, '').trim()}_`,
      tsrId,
    });

    try {
      const body: Record<string, unknown> = {
        session_id: chatSessionId,
        user_message: `execute "${tc.name.replace(/\*+/g, '').trim()}"`,
        llm_provider: selectedProvider,
        headless: true,
        timeout: 30000,
        start_url: tc.start_url ?? '',  // navigate here before running the test case
        tc_ids: [tc.id],                // fallback: ID-based selection
        // Send the full TC definition so backend never needs to look it up by ID —
        // this prevents drift when session IDs don't match frontend state.
        tc_definition: {
          id: tc.id,
          name: tc.name.replace(/\*+/g, '').trim(),
          steps: tc.steps ?? [],
          expected_results: tc.expected_results ?? [],
        },
      };

      const res = await fetch(`${API_BASE}/api/v1/chat-execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Server error');
      }
      const data = await res.json();
      setExecSessionId(data.exec_session_id);
      connectExecutionSSE(data.exec_session_id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setRerunResults(prev => prev.map(r =>
        r.tsrId === tsrId ? { ...r, status: 'failed', error: msg } : r
      ));
      rerunSessionRef.current = null;
      setChatPhase('chatting');
      addNotification('error', `Rerun failed: ${msg}`);
    }
  };

  // ── Navigation guard ──────────────────────────────────────────────────────

  const handleLeaveAnyway = () => {
    const dest = pendingNavigation;
    setHasUnsavedChanges(false);
    setHasUnsavedEditChanges(false);
    setIsExcelEditMode(false);
    setShowDiscardConfirm(false);
    setPendingNavigation(null);
    if (dest) setCurrentView(dest);
  };

  // ── Chat send ─────────────────────────────────────────────────────────────

  const handleChatSend = async () => {
    const text = chatTextInput.trim();
    if (!text) return;
    setChatTextInput('');

    const isUrl = looksLikeUrl(text);

    // In URL input phase OR if browser was closed, treat input as URL directly to restart browser
    if ((chatPhase === 'url_input' || browserClosed) && isUrl) {
      const url = text.startsWith('http') ? text : `https://${text}`;
      await handleAnalyzeUrl(url);
      return;
    }

    if (chatPhase === 'url_input') {
      appendChatMsg({ id: `cu_${Date.now()}`, role: 'user', content: text });
      _showThinking('Thinking…');
      try {
        const res = await fetch(`${API_BASE}/api/v1/chat-freeform`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_message: text, llm_provider: selectedProvider, context: 'url_input' }),
        });
        const data = await res.json();
        _resolveThinking({ id: `ca_${Date.now()}`, role: 'assistant', content: data.message });
      } catch {
        _resolveThinking({ id: `ca_${Date.now()}`, role: 'assistant', content: 'Could you share the URL of the page you\'d like to test?' });
      }
      return;
    }

    if (!chatSessionId) return;
    if (chatPhase === 'generating' || chatPhase === 'executing') return;

    if (chatInputRef.current) chatInputRef.current.style.height = 'auto';

    // User is responding to a needs_input prompt — extract values and retry execution
    if (chatPhase === 'awaiting_input' && pendingExecuteMsg) {
      appendChatMsg({ id: `cu_${Date.now()}`, role: 'user', content: text });
      const inputData: Record<string, string> = {};
      const emailMatch = text.match(/\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b/);
      if (emailMatch) inputData.email = emailMatch[1];
      const pwdMatch = text.match(/(?:password|pass(?:word)?|pwd)\s*(?:is|[:=])\s*([^\s,;]+)/i);
      if (pwdMatch) inputData.password = pwdMatch[1];
      const kvMatches = text.matchAll(/(\w+)\s*[:=]\s*([^\s,;]+)/g);
      for (const m of kvMatches) {
        const k = m[1].toLowerCase();
        if (!inputData[k]) inputData[k] = m[2];
      }
      await handleChatExecute(pendingExecuteMsg, inputData, text);
      return;
    }

    // ── Unified semantic intent call ────────────────────────────────────────
    appendChatMsg({ id: `cu_${Date.now()}`, role: 'user', content: text });
    setChatPhase('generating');
    _showThinking('Thinking…');

    try {
      const res = await fetch(`${API_BASE}/api/v1/chat-message`, {
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

      if (data.status === 'needs_input') {
        // Execute path: backend needs credentials before running
        setPendingExecuteMsg(text);
        _resolveThinking({ id: `ca_${Date.now()}`, role: 'assistant', content: data.message });
        setChatPhase('awaiting_input');
      } else if (data.exec_session_id) {
        // Execute path: started — wire up execution UI
        setExecSteps([]);
        setExecSummary(null);
        setExecScreenshot(null);
        setExecCurrentUrl('');
        setExecPanelView('browser');
        _resolveThinking({ id: `ca_${Date.now()}`, role: 'assistant', content: String(data.message ?? '') });
        setExecSessionId(data.exec_session_id);
        setChatPhase('executing');
        connectExecutionSSE(data.exec_session_id);
      }
      // All other intents (generate/edit/informational/approve/clarify):
      // SSE delivers chat_test_suite / chat_response / chat_approve — already handled by connectSSE
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      _resolveThinking({ id: `ce_${Date.now()}`, role: 'assistant', content: msg });
      setChatPhase('chatting');
    }
    // ────────────────────────────────────────────────────────────────────────
  };

  const handleStop = useCallback(() => {
    const wasExecuting = chatPhase === 'executing';

    // Close both SSE connections immediately
    sseRef.current?.close();
    sseRef.current = null;
    execSseRef.current?.close();
    execSseRef.current = null;

    // Clear the thinking bubble ("Interpreting...", "Thinking...") from chat messages
    const thinkingId = chatThinkingIdRef.current;
    chatThinkingIdRef.current = null;
    if (thinkingId) {
      setChatMessages(prev => prev.filter(m => m.id !== thinkingId));
    }

    // Clear typing animation and browser loading spinner
    setTypingMsg(null);
    setBrowserPreviewLoading(false);
    setBrowserClosed(false);
    browserClosedAlertedRef.current = false;

    // Reset UI to idle
    setChatPhase('chatting');

    // Tell backend to cancel if execution was running (it's long-running)
    if (wasExecuting && chatSessionId) {
      fetch(`${API_BASE}/api/v1/chat-stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: chatSessionId }),
      }).catch(() => {});
    }

    appendChatMsg({ id: `stop_${Date.now()}`, role: 'assistant', content: '_User Interrupted_' });

    // Reconnect the chat SSE so subsequent prompts can receive responses.
    // handleStop closes sseRef but the session is still alive on the backend —
    // without reconnecting, the next prompt fires but nobody listens.
    if (chatSessionId) {
      connectSSE(chatSessionId);
    }
  }, [chatPhase, chatSessionId, connectSSE]);

  const handleChatReset = () => {
    closeBrowserSession(); // close Playwright browser immediately, before state is wiped
    if (execSseRef.current) { execSseRef.current.close(); execSseRef.current = null; }
    disconnectSSE();
    chatThinkingIdRef.current = null;
    setTypingMsg(null);
    setChatPhase('url_input');
    setSessionId(null);
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
            return { ...m, status: hasError ? 'error' : 'done', tokens_used: data.tokens_used ?? 0, cost_usd: data.cost_usd ?? 0 };
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
          return { ...m, steps: returnedSteps, status: hasError ? 'error' : 'done', tokens_used: data.tokens_used ?? 0, cost_usd: data.cost_usd ?? 0 };
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

  // ── ESC closes browser overlay ────────────────────────────────────────────
  useEffect(() => {
    if (!showBrowserOverlay) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowBrowserOverlay(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [showBrowserOverlay]);

  // ── Shared browser panel body (status bar + view toggle + browser/excel) ──
  // Rendered once; used by both overlay and split panel via layoutId transition
  const browserPanelBody = (
    <>
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
          <Monitor size={13} /> Browser View
        </button>
        <button
          className={`${styles.genExecViewToggleBtn} ${execPanelView === 'excel' ? styles.genExecViewToggleActive : ''}`}
          onClick={() => setExecPanelView('excel')}
        >
          <FileSpreadsheet size={13} /> Excel View
          {confirmedExecResults.length > 0 && (
            <span className={styles.recExcelBadge}>{confirmedExecResults.length}</span>
          )}
        </button>
        {/* Right-side action buttons */}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          {execPanelView === 'excel' && !isExcelEditMode && (
            <button
              className={styles.genExecEditBtn}
              onClick={() => {
                setEditedExcelData([...confirmedExecResults]);
                setEditedRowIds(new Set());
                setHasUnsavedChanges(false);
                setShowDiscardConfirm(false);
                setIsExcelEditMode(true);
              }}
              disabled={confirmedExecResults.length === 0}
              title={confirmedExecResults.length === 0 ? 'No results to edit' : 'Edit test cases'}
            >
              <Pencil size={13} />
              Edit
            </button>
          )}
          {execPanelView === 'excel' && isExcelEditMode && (
            <>
              <button className={styles.excelEditSaveBtn} onClick={handleExcelEditSave}>
                <Save size={13} /> Save
              </button>
              <button className={styles.excelEditCancelBtn} onClick={handleExcelEditCancel}>
                Cancel
              </button>
            </>
          )}
          <button
            className={styles.genExecExportBtn}
            onClick={() => setShowExportConfirm(true)}
            disabled={confirmedExecResults.length === 0}
            title={confirmedExecResults.length === 0 ? 'No results added to Excel view yet' : 'Export confirmed results to Excel'}
          >
            <FileSpreadsheet size={13} />
            Export Excel
          </button>
        </div>
      </div>
      {/* Browser view */}
      {execPanelView === 'browser' && (
        <>
          <div className={styles.browserPanelHeader}>
            <Camera size={13} />
            <span>Live Browser View</span>
            {execCurrentUrl && (
              <span className={styles.screenshotCurrentUrl} title={execCurrentUrl}>{execCurrentUrl}</span>
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
                {browserClosed ? (
                  <>
                    <MonitorOff size={48} style={{ color: '#ef4444' }} />
                    <span style={{ color: '#ef4444', fontWeight: 500, marginTop: '8px' }}>Browser Closed</span>
                    <span style={{ fontSize: '12px', color: '#64748b', marginTop: '4px' }}>Submit a URL to reopen it.</span>
                  </>
                ) : browserPreviewLoading ? (
                  <>
                    <Loader2 size={36} className={styles.spin} style={{ color: '#6366f1' }} />
                    <span>Loading browser…</span>
                  </>
                ) : (
                  <>
                    <MonitorPlay size={48} style={{ color: '#cbd5e1' }} />
                    <span>Execute a test case to see live browser</span>
                  </>
                )}
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
      {/* Excel view */}
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
              {['A','B','C','D','E','F','G','H'].map(l => (
                <div key={l} className={styles.recExcelLetterCell}>{l}</div>
              ))}
              <div className={`${styles.recExcelCell} ${styles.recExcelRowNumHeader}`}>Row</div>
              {['T.C.No','Test Case','Steps','Expected Result','Input Data','Status','Error','Test Runs'].map(h => (
                <div key={h} className={`${styles.recExcelCell} ${styles.recExcelHeaderCell}`}>{h}</div>
              ))}
              {(isExcelEditMode ? editedExcelData : confirmedExecResults).map((r, idx) => {
                const rowCls = r.status === 'passed' ? styles.recExcelRowPassed : styles.recExcelRowFailed;
                const isEdited = isExcelEditMode && editedRowIds.has(r.id);
                return (
                  <React.Fragment key={r.id}>
                    <div className={`${styles.recExcelCell} ${styles.recExcelRowNumCell} ${rowCls}`}>{idx + 1}</div>
                    {/* T.C.No — read-only */}
                    <div className={`${styles.recExcelCell} ${rowCls}`}>{idx + 1}</div>
                    {/* Test Case — editable in edit mode */}
                    <div className={`${styles.recExcelCell} ${rowCls} ${isEdited ? styles.recExcelCellEdited : ''}`}>
                      {isExcelEditMode ? (
                        <textarea
                          className={styles.excelEditTextarea}
                          value={r.name.replace(/\*+/g, '').replace(/^[-\s]+/, '').trim()}
                          onChange={e => handleExcelCellEdit(r.id, 'name', e.target.value)}
                        />
                      ) : (
                        r.name.replace(/\*+/g, '').replace(/^[-\s]+/, '').trim()
                      )}
                    </div>
                    {/* Steps — editable in edit mode */}
                    <div className={`${styles.recExcelCell} ${styles.recExcelStepsCell} ${rowCls} ${isEdited ? styles.recExcelCellEdited : ''}`}>
                      {isExcelEditMode ? (
                        <textarea
                          className={styles.excelEditTextarea}
                          value={r.steps.map((s, i) => `${i + 1}. ${s.instruction}`).join('\n')}
                          onChange={e => handleExcelStepsEdit(r.id, e.target.value)}
                          rows={Math.max(3, r.steps.length)}
                        />
                      ) : (
                        r.steps.map((s, i) => (
                          <span key={i}>{i + 1}. {s.instruction}{i < r.steps.length - 1 ? '\n' : ''}</span>
                        ))
                      )}
                    </div>
                    {/* Expected Result — read-only */}
                    <div className={`${styles.recExcelCell} ${rowCls}`}>{r.expected_results?.join('; ') || 'N/A'}</div>
                    {/* Input Data — editable in edit mode */}
                    <div className={`${styles.recExcelCell} ${rowCls} ${isEdited ? styles.recExcelCellEdited : ''}`}>
                      {isExcelEditMode ? (
                        <textarea
                          className={styles.excelEditTextarea}
                          value={Object.entries(r.test_data || {}).flatMap(([k, v]) =>
                            v && typeof v === 'object'
                              ? Object.entries(v as Record<string, unknown>).map(([ik, iv]) => `${ik}: ${iv}`)
                              : [`${k}: ${v}`]
                          ).join('\n')}
                          onChange={e => handleExcelInputDataEdit(r.id, e.target.value)}
                        />
                      ) : (
                        Object.entries(r.test_data || {}).flatMap(([k, v]) =>
                          v && typeof v === 'object'
                            ? Object.entries(v as Record<string, unknown>).map(([ik, iv]) => `${ik}: ${iv}`)
                            : [`${k}: ${v}`]
                        ).join(' | ')
                      )}
                    </div>
                    {/* Status — read-only */}
                    <div className={`${styles.recExcelCell} ${styles.recExcelStatusCell} ${rowCls}`}>
                      {r.status === 'passed'
                        ? <span className={styles.recExcelBadgePassed}>✓ PASSED</span>
                        : <span className={styles.recExcelBadgeFailed}>✗ FAILED</span>}
                    </div>
                    {/* Error — read-only */}
                    <div className={`${styles.recExcelCell} ${styles.recExcelErrorCell} ${rowCls}`}>{r.error || ''}</div>
                    {/* Test Runs — hidden during edit mode */}
                    <div className={`${styles.recExcelCell} ${styles.recExcelTestRunsCell} ${rowCls}`}>
                      {!isExcelEditMode && (
                        <button
                          className={styles.excelRerunBtn}
                          disabled={chatPhase === 'executing'}
                          onClick={() => handleExcelRerun(r)}
                          title={`Rerun: ${r.name}`}
                        >
                          ↺ Rerun
                        </button>
                      )}
                    </div>
                  </React.Fragment>
                );
              })}
            </div>
          )}
        </div>
      )}
    </>
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
          <ProviderSelect
            value={mode === 'record' ? recProvider : selectedProvider}
            onChange={val => {
              if (mode === 'record') setRecProvider(val as typeof recProvider);
              else setSelectedProvider(val as typeof selectedProvider);
            }}
            disabled={
              chatPhase === 'analyzing' ||
              chatPhase === 'generating' ||
              chatPhase === 'executing' ||
              recStatus === 'executing' ||
              recStatus === 'completing'
            }
          />
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
          Generate with AI
        </button>
        <button
          className={`${styles.modeTab} ${mode === 'record' ? styles.modeTabActive : ''}`}
          onClick={() => setMode('record')}
        >
          <Video size={14} />
          Record with AI
        </button>
      </div>

      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* GENERATE MODE — Chatbot UI                                         */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      {mode === 'generate' && (
        <div className={`${styles.chatLayout} ${styles.genExecutionLayout}`}>

          {/* ── CHAT PANEL (full-width or split-left) ── */}
          <div className={styles.genChatPanel}>
          {/* Scrollable messages area */}
          <div
            className={styles.chatMessages}
            ref={chatScrollContainerRef}
            onScroll={handleChatScroll}
          >

            {/* Content wrapper — ResizeObserver watches this for auto-scroll */}
            <div ref={chatContentRef}>

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
                  <div className={styles.genMarkdown}>
                    <ReactMarkdown>
                      {"Hi! I'm your AI test assistant. Share the URL of the page you'd like me to analyze, and I'll generate test cases based on the real elements found on that page."}
                    </ReactMarkdown>
                  </div>
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
                      {/* TSR rerun badge — shown for rerun messages */}
                      {msg.tsrId && (
                        <div className={styles.tsrChatCard}>
                          <RotateCcw size={11} /> {msg.tsrId}
                        </div>
                      )}
                      {(() => {
                        if (msg.thinking) {
                          return (
                            <div style={{ paddingLeft: 16, paddingTop: 6 }}>
                              <WaterfallLoader compact />
                            </div>
                          );
                        }
                        const displayed = (typingMsg && typingMsg.id === msg.id)
                          ? typingMsg.full.slice(0, typingMsg.shown)
                          : msg.content;
                        return (
                          <>
                            <div className={styles.genAssistantBubble}>
                              <div className={styles.genMarkdown}>
                                <ReactMarkdown>{displayed}</ReactMarkdown>
                              </div>
                            </div>
                            {msg.isBrowserClosedMsg && (
                              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                                <button
                                  className={styles.chatActionBtn}
                                  disabled={!!msg.browserClosedActioned}
                                  onClick={() => { markBrowserClosedActioned(msg.id); handleReopen(); }}
                                  title="Reopen the last URL with your saved session"
                                >
                                  <MonitorPlay size={13} />
                                  <span>Reopen</span>
                                </button>
                                <button
                                  className={styles.chatActionBtn}
                                  disabled={!!msg.browserClosedActioned}
                                  onClick={() => { newChatMsgIdRef.current = msg.id; setShowNewChatConfirm(true); }}
                                  title="Start a new chat session"
                                >
                                  <RotateCcw size={13} />
                                  <span>New Chat</span>
                                </button>
                              </div>
                            )}
                          </>
                        );
                      })()}
                      {/* Token usage — shown below the bubble for LLM responses */}
                      {!msg.thinking && msg.tokens_used != null && msg.tokens_used > 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, paddingLeft: 2 }}>
                          <span style={{ fontSize: '0.68rem', color: '#94a3b8', whiteSpace: 'nowrap' }}>
                            {msg.tokens_used.toLocaleString()} tokens · ${(msg.cost_usd ?? 0).toFixed(5)}
                          </span>
                          {msg.session_total_tokens != null && msg.session_total_tokens > 0 && (
                            <span style={{ fontSize: '0.68rem', color: '#64748b', whiteSpace: 'nowrap' }}>
                              · session: {msg.session_total_tokens.toLocaleString()} tokens · ${(msg.session_total_cost ?? 0).toFixed(5)}
                            </span>
                          )}
                        </div>
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
                                <div key={tc.id} className={styles.genExecTcBlock}>
                                  <div className={`${styles.genExecTcRow} ${tc.status === 'passed' ? styles.genExecTcPassed : styles.genExecTcFailed}`}>
                                    {tc.status === 'passed'
                                      ? <CheckCircle2 size={13} style={{ color: '#16a34a', flexShrink: 0 }} />
                                      : <XCircle size={13} style={{ color: '#dc2626', flexShrink: 0 }} />}
                                    <span className={styles.genExecTcName}>{tc.name}</span>
                                    {confirmedTcIds.has(tc.id) && (
                                      <span className={styles.genExecTcConfirmed}><Check size={11} /> In Excel</span>
                                    )}
                                  </div>
                                  {tc.status === 'failed' && (
                                    <div className={styles.genExecTcDetail}>
                                      {tc.error && (
                                        <div className={styles.genExecFailReason}>
                                          <span className={styles.genExecDetailLabel}>Error:</span> {tc.error}
                                        </div>
                                      )}
                                      {tc.failed_steps && tc.failed_steps.length > 0 && (
                                        <div className={styles.genExecFailedSteps}>
                                          <div className={styles.genExecDetailLabel}>Failed Steps:</div>
                                          {tc.failed_steps.map(s => (
                                            <div key={s.step} className={styles.genExecFailedStep}>
                                              <span className={styles.genExecStepNum}>Step {s.step}</span>
                                              <span className={styles.genExecStepInstr}>{s.instruction}</span>
                                              {s.error && <span className={styles.genExecStepErr}>{s.error}</span>}
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                      {tc.network_errors && tc.network_errors.length > 0 && (
                                        <div className={styles.genExecNetErrors}>
                                          <div className={styles.genExecDetailLabel}>Network Errors:</div>
                                          {tc.network_errors.map((e, i) => (
                                            <div key={i} className={styles.genExecNetError}>
                                              <span className={`${styles.genExecStatusBadge} ${e.status >= 500 ? styles.genExecStatus5xx : styles.genExecStatus4xx}`}>{e.status}</span>
                                              <span className={styles.genExecNetUrl}>{e.url}</span>
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                      {tc.console_errors && tc.console_errors.length > 0 && (
                                        <div className={styles.genExecConsoleErrors}>
                                          <div className={styles.genExecDetailLabel}>Console:</div>
                                          {tc.console_errors.slice(0, 5).map((m, i) => (
                                            <div key={i} className={styles.genExecConsoleMsg}>{m}</div>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Inline test suite preview — waits for typewriter to finish */}
                      {msg.testSuite && !(typingMsg && typingMsg.id === msg.id) && (
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
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </motion.div>
            ))}

            {/* ── Floating loading bubble pinned after last message ── */}
            {(chatPhase === 'analyzing' || chatPhase === 'generating' || chatPhase === 'executing') && !chatMessages.some(m => m.thinking) && (
              <div className={styles.chatBotMessage} style={{ marginBottom: 16 }}>
                <div className={styles.chatBotAvatar}><Sparkles size={14} /></div>
                <div className={styles.chatBotContent}>
                  <div style={{ paddingLeft: 16, paddingTop: 6 }}>
                    <WaterfallLoader compact />
                  </div>
                </div>
              </div>
            )}

            </div>{/* end chatContentRef wrapper */}

            <div ref={chatMessagesEndRef} />
          </div>

          {/* ── Unified bottom input bar — all phases ── */}
          <div className={styles.chatInputBar}>
            <div className={styles.chatInputInner}>
              {/* Action buttons row (New Chat + Save to Project + View Live Browser) */}
              {chatSessionId && (
                <div className={styles.chatInputActions}>
                  <button
                    className={styles.chatActionBtn}
                    onClick={() => setShowNewChatConfirm(true)}
                    title="New Chat"
                  >
                    <RotateCcw size={14} />
                    <span>New Chat</span>
                  </button>
                  {lastTestSuite && (
                    <button
                      className={styles.chatActionBtn}
                      onClick={async () => {
                        const _genSuite = { ...lastTestSuite, source: 'generate' };
                        if (projectName) {
                          try {
                            await saveTestToProject(projectName, _genSuite);
                            setProjectActiveSuite(projectName, _genSuite as unknown as TestSuite);
                            addNotification('success', `Saved to ${projectName}`);
                          } catch (e) {
                            addNotification('error', e instanceof Error ? e.message : 'Save failed');
                          }
                        } else {
                          setSuiteToSave(_genSuite);
                          setShowSaveModal(true);
                        }
                      }}
                      title={projectName ? 'Save to History' : 'Save to Project'}
                    >
                      <Save size={14} />
                      <span>{projectName ? 'Save to History' : 'Save to Project'}</span>
                    </button>
                  )}
                  <button
                    className={styles.viewBrowserBtn}
                    onClick={() => setShowBrowserOverlay(true)}
                  >
                    <Monitor size={14} />
                    View Live Browser
                  </button>
                </div>
              )}
              <div className={styles.chatInputBox}>
                <textarea
                  ref={chatInputRef}
                  className={styles.chatTextarea}
                  rows={1}
                  placeholder={
                    browserClosed
                      ? 'Select Reopen or New Chat to continue…'
                      : chatPhase === 'url_input'
                      ? 'Enter a URL to analyze (e.g. https://myapp.com/login)…'
                      : chatPhase === 'analyzing'
                      ? 'Analyzing page…'
                      : chatPhase === 'executing'
                      ? 'Waiting for execution to finish…'
                      : chatPhase === 'awaiting_input'
                      ? 'e.g. email: user@example.com  password: mypassword'
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
                      const isDisabled = chatPhase === 'analyzing' || chatPhase === 'generating' || chatPhase === 'executing' || browserClosed;
                      if (chatTextInput.trim() && !isDisabled) handleChatSend();
                    }
                  }}
                  disabled={chatPhase === 'analyzing' || chatPhase === 'generating' || chatPhase === 'executing' || browserClosed}
                  autoFocus={chatPhase === 'url_input'}
                />
                {(!browserClosed && (chatPhase === 'analyzing' || chatPhase === 'generating' || chatPhase === 'executing')) ? (
                  <button
                    className={styles.chatStopBtn}
                    onClick={handleStop}
                    title="Stop"
                  >
                    <StopCircle size={16} />
                  </button>
                ) : (
                  <button
                    className={styles.chatSendBtn}
                    onClick={handleChatSend}
                    disabled={!chatTextInput.trim() || browserClosed}
                    title="Send (Enter)"
                  >
                    <Send size={16} />
                  </button>
                )}
              </div>
              <div className={styles.chatInputHint}>
                {chatPhase === 'url_input' && <span>Paste a URL and press Enter to analyze</span>}
                {chatPhase === 'analyzing' && <span style={{ color: '#6366f1' }}>Scraping page elements…</span>}
                {chatPhase === 'executing' && <span style={{ color: '#f59e0b', fontWeight: 600 }}>Executing tests…</span>}
                {chatPhase === 'awaiting_input' && <span style={{ color: '#f59e0b', fontWeight: 600 }}>Provide the missing values above, then press Enter</span>}
                {(chatPhase === 'chatting' || chatPhase === 'generating' || chatPhase === 'done') && (
                  <span>Enter to send · Shift+Enter for newline · share credentials to use in tests</span>
                )}
              </div>
            </div>
          </div>
          </div>{/* end genChatPanel */}

          {/* ── SPLIT BROWSER SIDE PANEL ── */}
          <AnimatePresence>
          {browserSplit && (
            <motion.div
              className={styles.genBrowserSidePanel}
              initial={{ width: 0 }}
              animate={{ width: '55%' }}
              exit={{ width: 0 }}
              transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            >
              {/* Header — split mode: expand + close */}
              <div className={styles.browserOverlayHeader}>
                <span className={styles.browserOverlayTitle}>
                  <Monitor size={15} /> Live Browser & Test Results
                </span>
                <div className={styles.browserOverlayHeaderBtns}>
                  <button
                    className={styles.browserOverlayClose}
                    title="Expand to full screen"
                    onClick={() => { setBrowserSplit(false); setShowBrowserOverlay(true); }}
                  >
                    <Maximize2 size={15} />
                  </button>
                  <button
                    className={styles.browserOverlayClose}
                    title="Close"
                    onClick={() => setBrowserSplit(false)}
                  >
                    <X size={16} />
                  </button>
                </div>
              </div>
              {browserPanelBody}
            </motion.div>
          )}
          </AnimatePresence>

        </div>
      )}


      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* RECORD MODE — ChatGPT style                                        */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      {mode === 'record' && (
        <div className={styles.chatLayout}>

          {/* ── IDLE / SETUP STATE — chatbot style ── */}
          {(recStatus === 'idle' || recStatus === 'error') && !recResult && (
            <div className={styles.chatMessages} style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-start' }}>
              {/* Image analysis warning (shown in idle state too) */}
              {imageAnalysisEnabled && (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '5px 10px',
                  background: 'transparent',
                  borderLeft: '2px solid #d4a800',
                  borderRadius: 0,
                  fontSize: '0.73rem',
                  color: '#92730a',
                  marginBottom: 10,
                }}>
                  <Zap size={11} style={{ color: '#d4a800', flexShrink: 0 }} />
                  <span>Vision fallback active — screenshots sent to vision model on selector failure.</span>
                </div>
              )}
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                {/* Bot greeting bubble */}
                <div className={styles.chatBotMessage} style={{ marginBottom: 0 }}>
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
                <WaterfallLoader />
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
                  gap: 6,
                  padding: '5px 10px',
                  background: 'transparent',
                  borderLeft: '2px solid #d4a800',
                  fontSize: '0.73rem',
                  color: '#92730a',
                  margin: '0 0 8px',
                }}>
                  <Zap size={11} style={{ color: '#d4a800', flexShrink: 0 }} />
                  <span>Vision fallback active — screenshots sent to vision model on selector failure.</span>
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
                                    {msg.status === 'done' && msg.tokens_used != null && msg.tokens_used > 0 && (
                                      <span style={{
                                        fontSize: '0.68rem', color: '#94a3b8',
                                        marginLeft: 4, whiteSpace: 'nowrap',
                                      }}>
                                        · {msg.tokens_used.toLocaleString()} tokens · ${(msg.cost_usd ?? 0).toFixed(5)}
                                      </span>
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
                                        {confirmedMessages.has(msg.id) ? 'Approved' : 'Approve'}
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
                    <div className={styles.browserPanelBody}>
                      {recScreenshot ? (
                        <img
                          src={`data:image/png;base64,${recScreenshot}`}
                          alt="Browser screenshot"
                          className={styles.screenshotImg}
                          style={{ width: '100%', height: '100%', objectFit: 'fill', display: 'block' }}
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
              <WaterfallLoader />
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
                          const _recSuite = { ...recResult.test_suite, source: 'record' };
                          try {
                            await saveTestToProject(projectName, _recSuite);
                            setProjectActiveSuite(projectName, _recSuite as unknown as TestSuite);
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
                        onClick={() => { setSuiteToSave({ ...recResult.test_suite, source: 'record' }); setShowSaveModal(true); }}
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

      {/* ── Discard edits confirmation dialog ── */}
      {showDiscardConfirm && (
        <div className={styles.exportConfirmOverlay}>
          <div className={styles.exportConfirmDialog} onClick={e => e.stopPropagation()}>
            <AlertCircle size={28} style={{ color: '#f59e0b' }} />
            <h3 className={styles.exportConfirmTitle}>Discard Changes?</h3>
            <p className={styles.exportConfirmDesc}>You have unsaved edits. Discard them and exit edit mode?</p>
            <div className={styles.exportConfirmActions}>
              <button className={styles.exportConfirmCancel} onClick={() => setShowDiscardConfirm(false)}>
                Keep editing
              </button>
              <button
                className={styles.exportConfirmOk}
                style={{ background: '#ef4444' }}
                onClick={handleExcelEditDiscard}
              >
                Discard
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Unsaved changes navigation warning ── */}
      {pendingNavigation && hasUnsavedChanges && (
        <div className={styles.exportConfirmOverlay}>
          <div className={styles.exportConfirmDialog} onClick={e => e.stopPropagation()}>
            <AlertCircle size={28} style={{ color: '#f59e0b' }} />
            <h3 className={styles.exportConfirmTitle}>Unsaved Changes</h3>
            <p className={styles.exportConfirmDesc}>You have unsaved edits. Your changes will be lost if you leave this page.</p>
            <div className={styles.exportConfirmActions}>
              <button className={styles.exportConfirmCancel} onClick={() => setPendingNavigation(null)}>
                Stay
              </button>
              <button
                className={styles.exportConfirmOk}
                style={{ background: '#ef4444' }}
                onClick={handleLeaveAnyway}
              >
                Leave anyway
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Export Excel confirmation dialog ── */}
      {showExportConfirm && (
        <div className={styles.exportConfirmOverlay} onClick={() => setShowExportConfirm(false)}>
          <div className={styles.exportConfirmDialog} onClick={e => e.stopPropagation()}>
            <FileSpreadsheet size={28} style={{ color: '#6366f1' }} />
            <h3 className={styles.exportConfirmTitle}>Export to Excel?</h3>
            <p className={styles.exportConfirmDesc}>All confirmed test results will be exported to an Excel file.</p>
            <div className={styles.exportConfirmActions}>
              <button className={styles.exportConfirmCancel} onClick={() => setShowExportConfirm(false)}>
                Cancel
              </button>
              <button
                className={styles.exportConfirmOk}
                onClick={() => { setShowExportConfirm(false); handleExportConfirmedExcel(); }}
              >
                Export
              </button>
            </div>
          </div>
        </div>
      )}

      {showNewChatConfirm && (
        <div className={styles.exportConfirmOverlay} onClick={() => setShowNewChatConfirm(false)}>
          <div className={styles.exportConfirmDialog} onClick={e => e.stopPropagation()}>
            <h3 className={styles.exportConfirmTitle}>Start a New Chat?</h3>
            <p className={styles.exportConfirmDesc}>
              This will close the current session and browser. Any unsaved work will be lost.
            </p>
            <div className={styles.exportConfirmActions}>
              <button
                className={styles.exportConfirmCancel}
                onClick={() => setShowNewChatConfirm(false)}
              >
                Cancel
              </button>
              <button
                className={styles.exportConfirmOk}
                onClick={() => {
                  setShowNewChatConfirm(false);
                  if (newChatMsgIdRef.current) {
                    markBrowserClosedActioned(newChatMsgIdRef.current);
                    newChatMsgIdRef.current = null;
                  }
                  handleChatReset();
                }}
              >
                Yes, proceed
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Browser overlay ── */}
      <AnimatePresence>
        {showBrowserOverlay && (
          <div className={styles.browserOverlay}>
            <motion.div
              className={styles.browserOverlayPanel}
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ duration: 0.38, ease: [0.16, 1, 0.3, 1] }}
            >
              {/* Left-edge divider — click to switch to split view */}
              <div className={styles.overlayLeftDivider}>
                <button
                  className={styles.overlayLeftDividerBtn}
                  title="Switch to split view"
                  onClick={() => { setShowBrowserOverlay(false); setBrowserSplit(true); }}
                >
                  <ChevronRight size={14} />
                </button>
              </div>

              {/* Header — overlay mode: close only */}
              <div className={styles.browserOverlayHeader}>
                <span className={styles.browserOverlayTitle}>
                  <Monitor size={15} /> Live Browser & Test Results
                </span>
                <button
                  className={styles.browserOverlayClose}
                  title="Close"
                  onClick={() => setShowBrowserOverlay(false)}
                >
                  <X size={16} />
                </button>
              </div>

              {browserPanelBody}
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

