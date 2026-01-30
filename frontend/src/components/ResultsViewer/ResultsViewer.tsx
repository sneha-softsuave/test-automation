import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FileCheck,
  CheckCircle,
  XCircle,
  AlertCircle,
  ChevronRight,
  Clock,
  Target,
  Repeat,
  Download,
  RotateCcw,
  Camera,
  Code,
  Copy,
  Check,
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import type { TestResult, StepResult } from '../../store/useStore';
import styles from './ResultsViewer.module.css';

// Syntax highlighter for Python/TypeScript code
const highlightCode = (code: string): string => {
  if (!code) return '';

  // Token types and their patterns
  const tokens: { type: string; regex: RegExp }[] = [
    { type: 'comment', regex: /#.*$/gm },
    { type: 'comment', regex: /\/\/.*$/gm },
    { type: 'string', regex: /"""[\s\S]*?"""/g },
    { type: 'string', regex: /'''[\s\S]*?'''/g },
    { type: 'string', regex: /"(?:[^"\\]|\\.)*"/g },
    { type: 'string', regex: /'(?:[^'\\]|\\.)*'/g },
    { type: 'decorator', regex: /@\w+(?:\.\w+)*/g },
    { type: 'keyword', regex: /\b(import|from|async|await|def|class|return|if|else|elif|for|while|try|except|finally|with|as|in|not|and|or|True|False|None|const|let|var|function|export|default|pytest|assert|yield|lambda|pass|break|continue)\b/g },
    { type: 'function', regex: /\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?=\()/g },
    { type: 'number', regex: /\b\d+(?:\.\d+)?\b/g },
  ];

  // Collect all matches with their positions
  interface Match {
    type: string;
    start: number;
    end: number;
    text: string;
  }

  const matches: Match[] = [];

  for (const { type, regex } of tokens) {
    let match;
    const re = new RegExp(regex.source, regex.flags);
    while ((match = re.exec(code)) !== null) {
      matches.push({
        type,
        start: match.index,
        end: match.index + match[0].length,
        text: match[0],
      });
    }
  }

  // Sort by start position
  matches.sort((a, b) => a.start - b.start);

  // Remove overlapping matches (keep the first one)
  const filteredMatches: Match[] = [];
  let lastEnd = 0;
  for (const match of matches) {
    if (match.start >= lastEnd) {
      filteredMatches.push(match);
      lastEnd = match.end;
    }
  }

  // Build the highlighted string
  let result = '';
  let pos = 0;

  for (const match of filteredMatches) {
    // Add text before this match (escaped)
    if (match.start > pos) {
      result += escapeHtml(code.slice(pos, match.start));
    }
    // Add the highlighted match
    result += `<span class="code-${match.type}">${escapeHtml(match.text)}</span>`;
    pos = match.end;
  }

  // Add remaining text
  if (pos < code.length) {
    result += escapeHtml(code.slice(pos));
  }

  return result;
};

const escapeHtml = (text: string): string => {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
};

export const ResultsViewer = () => {
  const { executionResult, setCurrentView, reset, generatedScript } = useStore();
  const [expandedResults, setExpandedResults] = useState<Set<string>>(new Set());
  const [scriptCopied, setScriptCopied] = useState(false);
  const [showScript, setShowScript] = useState(false);

  const copyScript = async () => {
    if (generatedScript) {
      await navigator.clipboard.writeText(generatedScript);
      setScriptCopied(true);
      setTimeout(() => setScriptCopied(false), 2000);
    }
  };

  if (!executionResult) {
    return (
      <div className={styles.empty}>
        <FileCheck size={48} />
        <h2>No Results Available</h2>
        <p>Execute tests to see results</p>
      </div>
    );
  }

  const toggleResult = (id: string) => {
    setExpandedResults((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(id)) {
        newSet.delete(id);
      } else {
        newSet.add(id);
      }
      return newSet;
    });
  };

  // Safely extract values with fallbacks
  const total = executionResult.total ?? executionResult.results?.length ?? 0;
  const passed = executionResult.passed ?? executionResult.results?.filter(r => r.status === 'PASSED').length ?? 0;
  const failed = executionResult.failed ?? executionResult.results?.filter(r => r.status === 'FAILED' || r.status === 'ERROR').length ?? 0;

  // Calculate pass rate safely (avoid NaN)
  const passRate = total > 0 ? Math.round((passed / total) * 100) : 0;

  // Parse execution date safely
  const executionDate = executionResult.executed_at
    ? new Date(executionResult.executed_at)
    : new Date();

  const downloadResults = () => {
    const blob = new Blob([JSON.stringify(executionResult, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `test-results-${executionDate.toISOString().split('T')[0]}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <motion.div
        className={styles.header}
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className={styles.headerContent}>
          <div
            className={`${styles.headerIcon} ${
              failed > 0 ? styles.failed : styles.passed
            }`}
          >
            {failed > 0 ? (
              <AlertCircle size={32} />
            ) : (
              <CheckCircle size={32} />
            )}
          </div>
          <div className={styles.headerText}>
            <h1 className={styles.title}>Test Results</h1>
            <p className={styles.subtitle}>{executionResult.project}</p>
          </div>
        </div>
        <div className={styles.headerActions}>
          <motion.button
            className={styles.actionButton}
            onClick={downloadResults}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
          >
            <Download size={18} />
            Export
          </motion.button>
          <motion.button
            className={styles.actionButton}
            onClick={() => setCurrentView('execution')}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
          >
            <Repeat size={18} />
            Re-run
          </motion.button>
          <motion.button
            className={styles.resetButton}
            onClick={reset}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
          >
            <RotateCcw size={18} />
            New Test
          </motion.button>
        </div>
      </motion.div>

      {/* Summary Cards */}
      <motion.div
        className={styles.summary}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        {/* Pass Rate Circle */}
        <div className={styles.passRateCard}>
          <div className={styles.passRateCircle}>
            <svg viewBox="0 0 100 100" className={styles.passRateSvg}>
              <circle
                cx="50"
                cy="50"
                r="45"
                fill="none"
                stroke="var(--bg-tertiary)"
                strokeWidth="8"
              />
              <motion.circle
                cx="50"
                cy="50"
                r="45"
                fill="none"
                stroke={passRate >= 80 ? 'var(--accent-success)' : passRate >= 50 ? 'var(--accent-warning)' : 'var(--accent-error)'}
                strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray={`${passRate * 2.83} 283`}
                transform="rotate(-90 50 50)"
                initial={{ strokeDasharray: '0 283' }}
                animate={{ strokeDasharray: `${passRate * 2.83} 283` }}
                transition={{ duration: 1, ease: 'easeOut' }}
              />
            </svg>
            <div className={styles.passRateValue}>
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.5 }}
              >
                {passRate}%
              </motion.span>
              <span className={styles.passRateLabel}>Pass Rate</span>
            </div>
          </div>
        </div>

        {/* Stats Grid */}
        <div className={styles.statsGrid}>
          <div className={`${styles.statCard} ${styles.passed}`}>
            <CheckCircle size={24} />
            <div className={styles.statInfo}>
              <span className={styles.statValue}>{passed}</span>
              <span className={styles.statLabel}>Passed</span>
            </div>
          </div>
          <div className={`${styles.statCard} ${styles.failed}`}>
            <XCircle size={24} />
            <div className={styles.statInfo}>
              <span className={styles.statValue}>{failed}</span>
              <span className={styles.statLabel}>Failed</span>
            </div>
          </div>
          <div className={styles.statCard}>
            <Target size={24} />
            <div className={styles.statInfo}>
              <span className={styles.statValue}>{total}</span>
              <span className={styles.statLabel}>Total</span>
            </div>
          </div>
          <div className={styles.statCard}>
            <Clock size={24} />
            <div className={styles.statInfo}>
              <span className={styles.statValue}>
                {executionDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
              <span className={styles.statLabel}>Executed</span>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Results List */}
      <div className={styles.results}>
        <h2 className={styles.sectionTitle}>Test Case Results</h2>
        <div className={styles.resultsList}>
          {(executionResult.results || []).map((result, index) => (
            <TestResultCard
              key={result.test_id || index}
              result={result}
              index={index}
              isExpanded={expandedResults.has(result.test_id)}
              onToggle={() => toggleResult(result.test_id)}
            />
          ))}
        </div>
      </div>

      {/* Playwright Script Section */}
      {generatedScript && (
        <motion.div
          className={styles.scriptSection}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <div className={styles.scriptHeader}>
            <div className={styles.scriptTitle}>
              <Code size={20} />
              <h2>Playwright Script</h2>
              <span className={styles.scriptBadge}>Ready to Run</span>
            </div>
            <div className={styles.scriptActions}>
              <motion.button
                className={styles.scriptToggle}
                onClick={() => setShowScript(!showScript)}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                {showScript ? 'Hide' : 'Show'} Script
              </motion.button>
              <motion.button
                className={`${styles.copyButton} ${scriptCopied ? styles.copied : ''}`}
                onClick={copyScript}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                {scriptCopied ? <Check size={16} /> : <Copy size={16} />}
                {scriptCopied ? 'Copied!' : 'Copy Script'}
              </motion.button>
            </div>
          </div>

          <AnimatePresence>
            {showScript && (
              <motion.div
                className={styles.scriptContent}
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
              >
                <pre className={styles.scriptCode}>
                  <code
                    dangerouslySetInnerHTML={{ __html: highlightCode(generatedScript || '') }}
                  />
                </pre>
              </motion.div>
            )}
          </AnimatePresence>

          <div className={styles.scriptInfo}>
            <p>Run this script with: <code>npx playwright test your-test-file.spec.ts</code></p>
          </div>
        </motion.div>
      )}
    </div>
  );
};

interface TestResultCardProps {
  result: TestResult;
  index: number;
  isExpanded: boolean;
  onToggle: () => void;
}

const TestResultCard = ({ result, index, isExpanded, onToggle }: TestResultCardProps) => {
  const statusStyles = {
    PASSED: styles.statusPassed,
    FAILED: styles.statusFailed,
    ERROR: styles.statusError,
  };

  const StatusIcon = result.status === 'PASSED' ? CheckCircle : XCircle;
  const passedSteps = result.steps?.filter((s) => s.status === 'PASSED').length || 0;
  const totalSteps = result.steps?.length || 0;

  return (
    <motion.div
      className={`${styles.resultCard} ${statusStyles[result.status]}`}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
    >
      <motion.div
        className={styles.resultHeader}
        onClick={onToggle}
        whileHover={{ backgroundColor: 'rgba(255,255,255,0.02)' }}
      >
        <div className={styles.resultStatus}>
          <StatusIcon size={24} />
        </div>
        <div className={styles.resultInfo}>
          <span className={styles.resultId}>{result.test_id}</span>
          <h3 className={styles.resultName}>{result.test_name}</h3>
          {result.error && (
            <span className={styles.resultError}>{result.error}</span>
          )}
        </div>
        <div className={styles.resultMeta}>
          <span className={styles.stepsProgress}>
            {passedSteps}/{totalSteps} steps
          </span>
          <motion.div
            className={styles.expandIcon}
            animate={{ rotate: isExpanded ? 90 : 0 }}
          >
            <ChevronRight size={20} />
          </motion.div>
        </div>
      </motion.div>

      <AnimatePresence>
        {isExpanded && result.steps && (
          <motion.div
            className={styles.resultBody}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
          >
            <div className={styles.stepResults}>
              {result.steps.map((step, stepIndex) => (
                <StepResultItem key={step.step} step={step} index={stepIndex} />
              ))}
            </div>

            {result.screenshots && result.screenshots.length > 0 && (
              <div className={styles.screenshots}>
                <h4 className={styles.screenshotsTitle}>
                  <Camera size={16} />
                  Screenshots
                </h4>
                <div className={styles.screenshotsList}>
                  {result.screenshots.map((path, i) => (
                    <div key={i} className={styles.screenshot}>
                      {path}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

interface StepResultItemProps {
  step: StepResult;
  index: number;
}

const StepResultItem = ({ step, index }: StepResultItemProps) => {
  const isPassed = step.status === 'PASSED';

  return (
    <motion.div
      className={`${styles.stepResult} ${isPassed ? styles.stepPassed : styles.stepFailed}`}
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.02 }}
    >
      <div className={styles.stepResultIcon}>
        {isPassed ? <CheckCircle size={16} /> : <XCircle size={16} />}
      </div>
      <div className={styles.stepResultContent}>
        <div className={styles.stepResultHeader}>
          <span className={styles.stepResultNum}>Step {step.step}</span>
          <span className={styles.stepResultAction}>{step.action}</span>
        </div>
        <p className={styles.stepResultInstruction}>
          {step.instruction.length > 100
            ? step.instruction.slice(0, 100) + '...'
            : step.instruction}
        </p>
        {step.error && (
          <p className={styles.stepResultError}>{step.error}</p>
        )}
        {step.selector_used && (
          <code className={styles.stepResultSelector}>{step.selector_used}</code>
        )}
      </div>
    </motion.div>
  );
};
