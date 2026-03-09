import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles, Globe, ChevronDown, ChevronRight,
  Play, FileSpreadsheet, AlertCircle, Check,
  Eye, EyeOff, RotateCcw, Video, MonitorPlay, Monitor,
  Circle, CheckCircle2, XCircle, Loader2, Camera, X, Send,
  Zap, Save
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

  // ── Record mode state ────────────────────────────────────────────────────
  const [recUrl, setRecUrl] = useState('');
  const [recProvider, setRecProvider] = useState(llmProvider);
  const [recAppName, setRecAppName] = useState('');
  const [recStatus, setRecStatus] = useState<RecordingStatus>('idle');
  const [recError, setRecError] = useState<string | null>(null);
  const [recMessages, setRecMessages] = useState<RecorderMessage[]>([]);
  const [recScreenshot, setRecScreenshot] = useState<string | null>(null);
  const [recCurrentUrl, setRecCurrentUrl] = useState('');
  const [recResult, setRecResult] = useState<{ test_suite: GeneratedSuite; step_count: number } | null>(null);
  const [recInstruction, setRecInstruction] = useState('');
  const [collapsedMessages, setCollapsedMessages] = useState<Set<string>>(new Set());
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
  const allRecSteps = recMessages.slice(currentCaseStartMsgIdx).flatMap(m => m.steps);
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
      ? (allRecSteps.some(s => s.error) ? 'failed' : 'passed')
      : 'running';

  const recExcelError = allRecSteps.find(s => s.error)?.error ?? null;

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

  const handleReset = () => {
    setResult(null);
    setError(null);
  };

  // ==========================================================================
  // Record mode handlers
  // ==========================================================================

  const handleStartRecording = async () => {
    setRecError(null);
    setRecMessages([]);
    setFinalizedCases([]);
    setCaseBoundaries([]);
    setRecScreenshot(null);
    setRecCurrentUrl('');
    setRecResult(null);
    setCollapsedMessages(new Set());
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
      if (data.current_url) setRecCurrentUrl(data.current_url);
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
    const newMsg: RecorderMessage = { id: msgId, paragraph, steps: [], status: 'executing' };
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
      if (data.current_url) setRecCurrentUrl(data.current_url);

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
      setRecResult({ test_suite: data.test_suite, step_count: data.step_count });
      setRecStatus('done');
      addNotification('success', `Recorded test suite saved: ${data.step_count} step(s)`);
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
    setRecCurrentUrl('');
    setRecError(null);
    setRecResult(null);
    setCollapsedMessages(new Set());
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
      {/* GENERATE MODE                                                      */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      {mode === 'generate' && (
        <div className={styles.chatLayout}>
          {/* Scrollable content area */}
          <div className={styles.chatMessages}>
            {/* Input form — only when no result */}
            {!result && !loading && (
              <motion.div
                className={styles.card}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <h2 className={styles.cardTitle}>
                  <Globe size={16} className={styles.cardTitleIcon} />
                  App Details
                </h2>

                <div className={styles.field}>
                  <label className={`${styles.label} ${styles.labelRequired}`}>Application URL</label>
                  <span className={styles.hint}>The page you want to generate tests for</span>
                  <input
                    className={styles.input}
                    type="url"
                    placeholder="https://myapp.com/login"
                    value={url}
                    onChange={e => setUrl(e.target.value)}
                    disabled={loading}
                  />
                </div>

                <div className={styles.field}>
                  <label className={`${styles.label} ${styles.labelRequired}`}>What do you want to test?</label>
                  <span className={styles.hint}>Describe the scenarios in plain English</span>
                  <textarea
                    className={`${styles.input} ${styles.textarea}`}
                    placeholder={`Examples:\n• Test the login page with valid and invalid credentials\n• Test the signup flow including email validation\n• Test the product search and add-to-cart flow`}
                    value={intent}
                    onChange={e => setIntent(e.target.value)}
                    disabled={loading}
                  />
                </div>

                <button
                  className={styles.optionalToggle}
                  onClick={() => setShowOptional(v => !v)}
                  type="button"
                >
                  {showOptional ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  {showOptional ? 'Hide' : 'Show'} optional settings (credentials, app name)
                </button>

                <AnimatePresence>
                  {showOptional && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.2 }}
                    >
                      <div className={styles.field}>
                        <label className={styles.label}>App Name</label>
                        <input
                          className={styles.input}
                          type="text"
                          placeholder="MyApp"
                          value={appName}
                          onChange={e => setAppName(e.target.value)}
                          disabled={loading}
                        />
                      </div>
                      <div className={styles.grid2}>
                        <div className={styles.field}>
                          <label className={styles.label}>Test Email</label>
                          <input
                            className={styles.input}
                            type="email"
                            placeholder="test@example.com"
                            value={testEmail}
                            onChange={e => setTestEmail(e.target.value)}
                            disabled={loading}
                          />
                        </div>
                        <div className={styles.field}>
                          <label className={styles.label}>Test Password</label>
                          <div style={{ position: 'relative' }}>
                            <input
                              className={styles.input}
                              type={showPassword ? 'text' : 'password'}
                              placeholder="password123"
                              value={testPassword}
                              onChange={e => setTestPassword(e.target.value)}
                              disabled={loading}
                              style={{ paddingRight: '40px' }}
                            />
                            <button
                              type="button"
                              onClick={() => setShowPassword(v => !v)}
                              style={{
                                position: 'absolute', right: 10, top: '50%',
                                transform: 'translateY(-50%)', background: 'none',
                                border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 0,
                              }}
                            >
                              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                            </button>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>

                <div className={styles.actions}>
                  <button
                    className={styles.btnPrimary}
                    onClick={handleGenerate}
                    disabled={!canGenerate}
                  >
                    <Sparkles size={16} />
                    Generate Test Cases
                  </button>
                </div>
              </motion.div>
            )}

            {/* Loading */}
            <AnimatePresence>
              {loading && (
                <motion.div
                  className={styles.loadingCard}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                >
                  <div className={styles.spinner} />
                  <p className={styles.loadingTitle}>AI is generating your test cases…</p>
                  <p className={styles.loadingStep}>This takes about 15–30 seconds</p>
                  <div className={styles.loadingSteps}>
                    <div className={styles.loadingStepItem}>
                      <div className={`${styles.loadingStepDot} ${loadingStep >= 1 ? (loadingStep > 1 ? styles.done : styles.active) : ''}`} />
                      <span>Crawling page with Playwright to extract real selectors</span>
                    </div>
                    <div className={styles.loadingStepItem}>
                      <div className={`${styles.loadingStepDot} ${loadingStep >= 2 ? styles.active : ''}`} />
                      <span>AI generating test cases from page structure + your intent</span>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Error */}
            <AnimatePresence>
              {error && !loading && (
                <motion.div
                  className={styles.errorCard}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                >
                  <AlertCircle size={18} className={styles.errorIcon} />
                  <div>
                    <p className={styles.errorTitle}>Generation Failed</p>
                    <p className={styles.errorMessage}>{error}</p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Results */}
            <AnimatePresence>
              {result && !loading && (
                <motion.div
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                >
                  {result.page_summary && (
                    <div className={styles.pageSummary}>
                      {Object.entries(result.page_summary)
                        .filter(([k]) => !k.startsWith('total') && !k.startsWith('with'))
                        .map(([k, v]) => (
                          <div key={k} className={styles.summaryItem}>
                            <span className={styles.summaryValue}>{v}</span>
                            <span className={styles.summaryLabel}>{k}</span>
                          </div>
                        ))}
                      <div className={styles.summaryItem}>
                        <span className={styles.summaryValue}>{result.test_suite?.test_cases?.length ?? 0}</span>
                        <span className={styles.summaryLabel}>test cases</span>
                      </div>
                    </div>
                  )}

                  <div className={styles.resultsHeader}>
                    <h2 className={styles.resultsTitle}>
                      <Check size={18} style={{ color: '#22c55e' }} />
                      Generated Test Suite
                      <span className={`${styles.badge} ${styles.badgePurple}`}>
                        {result.llm_provider} / {result.model}
                      </span>
                    </h2>
                    <div className={styles.resultsActions}>
                      <button className={styles.btnSecondary} onClick={handleReset}>
                        <RotateCcw size={14} />
                        Regenerate
                      </button>
                      <button className={styles.btnSecondary} onClick={() => handleExportExcel(result.test_suite)}>
                        <FileSpreadsheet size={14} />
                        Export Excel
                      </button>
                      {projectName ? (
                        <button className={styles.btnSecondary} onClick={async () => {
                          try {
                            await saveTestToProject(projectName, result.test_suite);
                            setProjectActiveSuite(projectName, result.test_suite as unknown as TestSuite);
                            addNotification('success', `Saved to ${projectName}`);
                          } catch (e) {
                            addNotification('error', e instanceof Error ? e.message : 'Save failed');
                          }
                        }}>
                          <Save size={14} />
                          Save to History
                        </button>
                      ) : (
                        <button className={styles.btnSecondary} onClick={() => { setSuiteToSave(result.test_suite); setShowSaveModal(true); }}>
                          <Save size={14} />
                          Save to Project
                        </button>
                      )}
                      <button className={styles.btnPrimary} onClick={handleUseInAgent}>
                        <Play size={14} />
                        Use in Agent
                      </button>
                    </div>
                  </div>

                  {result.test_suite?.test_cases?.map(tc => (
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
              )}
            </AnimatePresence>
          </div>
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
                          <div className={styles.chatUserMessage}>
                            <div className={styles.chatUserBubble}>{msg.paragraph}</div>
                          </div>

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
                                  <span className={styles.chatStepParagraph}>
                                    {msg.status === 'executing' ? 'Parsing and executing steps…'
                                      : msg.status === 'done' ? `Completed ${msg.steps.length} step${msg.steps.length !== 1 ? 's' : ''}`
                                      : `Error — ${msg.steps.length} step${msg.steps.length !== 1 ? 's' : ''} attempted`}
                                  </span>
                                  <div className={styles.chatStepHeaderRight}>
                                    {msg.status === 'executing' && (
                                      <Loader2 size={14} className={styles.spin} style={{ color: '#6366f1' }} />
                                    )}
                                    {msg.status === 'done' && (
                                      <CheckCircle2 size={14} style={{ color: '#22c55e' }} />
                                    )}
                                    {msg.status === 'error' && (
                                      <XCircle size={14} style={{ color: '#ef4444' }} />
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
                              <div className={`${styles.recExcelCell} ${styles.recExcelErrorCell} ${styles.recExcelRowPassed}`}></div>
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
                    disabled={recStatus === 'starting'}
                  />
                  <button
                    className={styles.chatSendBtn}
                    onClick={handleStartRecording}
                    disabled={recStatus === 'starting' || !canStartRecording}
                    title="Open browser & start recording"
                  >
                    {recStatus === 'starting'
                      ? <Loader2 size={16} className={styles.spin} />
                      : <MonitorPlay size={16} />
                    }
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
