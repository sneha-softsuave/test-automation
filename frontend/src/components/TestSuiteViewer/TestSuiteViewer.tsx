import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FlaskConical,
  ChevronDown,
  ChevronRight,
  Play,
  MousePointer,
  Type,
  Eye,
  Clock,
  Link,
  FileText,
  Database,
  Code,
  Copy,
  Check,
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import type { TestCase, TestStep } from '../../store/useStore';
import styles from './TestSuiteViewer.module.css';

const actionIcons: Record<string, React.ElementType> = {
  goto: Link,
  click: MousePointer,
  fill: Type,
  assert: Eye,
  wait: Clock,
  select: ChevronDown,
  upload: FileText,
  capture: Database,
  screenshot: FileText,
};

export const TestSuiteViewer = () => {
  const { testSuite, setCurrentView } = useStore();
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set());
  const [copiedId, setCopiedId] = useState<string | null>(null);

  if (!testSuite) {
    return (
      <div className={styles.empty}>
        <FlaskConical size={48} />
        <h2>No Test Suite Loaded</h2>
        <p>Upload a test file to get started</p>
      </div>
    );
  }

  const toggleCase = (id: string) => {
    setExpandedCases((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(id)) {
        newSet.delete(id);
      } else {
        newSet.add(id);
      }
      return newSet;
    });
  };

  const copyToClipboard = async (text: string, id: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const totalSteps = testSuite.test_cases.reduce((acc, tc) => acc + tc.steps.length, 0);

  return (
    <div className={styles.container}>
      {/* Header */}
      <motion.div
        className={styles.header}
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className={styles.headerContent}>
          <div className={styles.headerIcon}>
            <FlaskConical size={28} />
          </div>
          <div className={styles.headerText}>
            <h1 className={styles.title}>{testSuite.project}</h1>
            <p className={styles.subtitle}>{testSuite.base_url}</p>
          </div>
        </div>
        <motion.button
          className={styles.executeButton}
          onClick={() => setCurrentView('execution')}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          <Play size={18} />
          Execute Tests
        </motion.button>
      </motion.div>

      {/* Stats */}
      <motion.div
        className={styles.stats}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <div className={styles.statCard}>
          <span className={styles.statValue}>{testSuite.test_cases.length}</span>
          <span className={styles.statLabel}>Test Cases</span>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statValue}>{totalSteps}</span>
          <span className={styles.statLabel}>Total Steps</span>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statValue}>
            {Object.keys(testSuite.common_selectors).length}
          </span>
          <span className={styles.statLabel}>Selector Groups</span>
        </div>
      </motion.div>

      {/* Test Cases */}
      <div className={styles.testCases}>
        <h2 className={styles.sectionTitle}>Test Cases</h2>
        <div className={styles.caseList}>
          {testSuite.test_cases.map((testCase, index) => (
            <TestCaseCard
              key={testCase.id}
              testCase={testCase}
              index={index}
              isExpanded={expandedCases.has(testCase.id)}
              onToggle={() => toggleCase(testCase.id)}
              onCopy={copyToClipboard}
              copiedId={copiedId}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

interface TestCaseCardProps {
  testCase: TestCase;
  index: number;
  isExpanded: boolean;
  onToggle: () => void;
  onCopy: (text: string, id: string) => void;
  copiedId: string | null;
}

const TestCaseCard = ({
  testCase,
  index,
  isExpanded,
  onToggle,
  onCopy,
  copiedId,
}: TestCaseCardProps) => {
  return (
    <motion.div
      className={styles.caseCard}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
    >
      <motion.div
        className={styles.caseHeader}
        onClick={onToggle}
        whileHover={{ backgroundColor: 'rgba(255,255,255,0.02)' }}
      >
        <motion.div
          className={styles.expandIcon}
          animate={{ rotate: isExpanded ? 90 : 0 }}
        >
          <ChevronRight size={20} />
        </motion.div>
        <div className={styles.caseInfo}>
          <div className={styles.caseId}>
            <span className={styles.idBadge}>{testCase.id}</span>
          </div>
          <h3 className={styles.caseName}>{testCase.name}</h3>
        </div>
        <div className={styles.caseMeta}>
          <span className={styles.stepCount}>{testCase.steps.length} steps</span>
        </div>
      </motion.div>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            className={styles.caseBody}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
          >
            <div className={styles.stepsList}>
              {testCase.steps.map((step, stepIndex) => (
                <StepCard
                  key={step.step_number}
                  step={step}
                  index={stepIndex}
                  testCaseId={testCase.id}
                  onCopy={onCopy}
                  copiedId={copiedId}
                />
              ))}
            </div>

            {testCase.expected_results.length > 0 && (
              <div className={styles.expectedResults}>
                <h4 className={styles.resultsTitle}>Expected Results</h4>
                <ul className={styles.resultsList}>
                  {testCase.expected_results.map((result, i) => (
                    <li key={i} className={styles.resultItem}>
                      {result}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

interface StepCardProps {
  step: TestStep;
  index: number;
  testCaseId: string;
  onCopy: (text: string, id: string) => void;
  copiedId: string | null;
}

const StepCard = ({ step, index, testCaseId, onCopy, copiedId }: StepCardProps) => {
  const [showDetails, setShowDetails] = useState(false);
  const ActionIcon = actionIcons[step.action.type] || Code;
  const copyId = `${testCaseId}-${step.step_number}`;

  return (
    <motion.div
      className={styles.stepCard}
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.02 }}
    >
      <div className={styles.stepHeader} onClick={() => setShowDetails(!showDetails)}>
        <div className={styles.stepNumber}>{step.step_number}</div>
        <div className={styles.stepIcon}>
          <ActionIcon size={16} />
        </div>
        <div className={styles.stepContent}>
          <span className={styles.stepAction}>{step.action.type}</span>
          <span className={styles.stepInstruction}>
            {step.instruction.length > 80
              ? step.instruction.slice(0, 80) + '...'
              : step.instruction}
          </span>
        </div>
        <motion.div
          className={styles.detailsToggle}
          animate={{ rotate: showDetails ? 180 : 0 }}
        >
          <ChevronDown size={16} />
        </motion.div>
      </div>

      <AnimatePresence>
        {showDetails && (
          <motion.div
            className={styles.stepDetails}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
          >
            {/* Full Instruction */}
            <div className={styles.detailSection}>
              <h5 className={styles.detailTitle}>Instruction</h5>
              <p className={styles.detailText}>{step.instruction}</p>
            </div>

            {/* Selector Hints */}
            {step.selector_hints.suggested_selectors.length > 0 && (
              <div className={styles.detailSection}>
                <h5 className={styles.detailTitle}>Suggested Selectors</h5>
                <div className={styles.selectors}>
                  {step.selector_hints.suggested_selectors.map((selector, i) => (
                    <div key={i} className={styles.selectorItem}>
                      <code className={styles.selectorCode}>{selector}</code>
                      <button
                        className={styles.copyButton}
                        onClick={() => onCopy(selector, `${copyId}-${i}`)}
                      >
                        {copiedId === `${copyId}-${i}` ? (
                          <Check size={12} />
                        ) : (
                          <Copy size={12} />
                        )}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Test Data */}
            {step.test_data && Object.keys(step.test_data).length > 0 && (
              <div className={styles.detailSection}>
                <h5 className={styles.detailTitle}>Test Data</h5>
                <pre className={styles.jsonBlock}>
                  {JSON.stringify(step.test_data, null, 2)}
                </pre>
              </div>
            )}

            {/* Assertions */}
            {step.assertions && step.assertions.length > 0 && (
              <div className={styles.detailSection}>
                <h5 className={styles.detailTitle}>Assertions</h5>
                <div className={styles.assertions}>
                  {step.assertions.map((assertion, i) => (
                    <div key={i} className={styles.assertionItem}>
                      <span className={styles.assertionType}>{assertion.type}</span>
                      <span className={styles.assertionValue}>
                        {assertion.expected_value}
                      </span>
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
