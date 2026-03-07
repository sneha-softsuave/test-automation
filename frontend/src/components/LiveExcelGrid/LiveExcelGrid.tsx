import React from 'react';
import type { LiveExcelRow } from '../../hooks/useExecutionWebSocket';
import styles from './LiveExcelGrid.module.css';

interface LiveExcelGridProps {
  rows: LiveExcelRow[];
  isExecuting: boolean;
}

const COLUMNS = [
  { letter: 'A', name: 'T.C.No',           width: 56 },
  { letter: 'B', name: 'Test Case',         width: 170 },
  { letter: 'C', name: 'Test Case Steps',   width: 260 },
  { letter: 'D', name: 'Expected Result',   width: 190 },
  { letter: 'E', name: 'Input data',        width: 190 },
  { letter: 'F', name: 'Status',            width: 88 },
  { letter: 'G', name: 'Error',             width: 160 },
];

function StatusBadge({ status }: { status: LiveExcelRow['status'] }) {
  switch (status) {
    case 'running':
      return <span className={`${styles.badge} ${styles.badgeRunning}`}>⟳ Running</span>;
    case 'passed':
      return <span className={`${styles.badge} ${styles.badgePassed}`}>✓ PASSED</span>;
    case 'failed':
      return <span className={`${styles.badge} ${styles.badgeFailed}`}>✗ FAILED</span>;
    default:
      return <span className={`${styles.badge} ${styles.badgePending}`}>—</span>;
  }
}

function StepsCell({ stepsText, currentStep }: { stepsText: string; currentStep: number }) {
  const lines = stepsText.split('\n');
  return (
    <div className={styles.stepsContent}>
      {lines.map((line, i) => {
        // Lines are numbered like "1. ..." — match step number
        const lineNum = i + 1;
        const isActive = currentStep > 0 && lineNum === currentStep;
        return (
          <span key={i} className={isActive ? styles.activeStep : undefined}>
            {line}
            {i < lines.length - 1 ? '\n' : ''}
          </span>
        );
      })}
    </div>
  );
}

function rowClass(status: LiveExcelRow['status']) {
  switch (status) {
    case 'running': return styles.rowRunning;
    case 'passed':  return styles.rowPassed;
    case 'failed':  return styles.rowFailed;
    default:        return styles.rowPending;
  }
}

export const LiveExcelGrid = ({ rows, isExecuting }: LiveExcelGridProps) => {
  const totalWidth = 40 + COLUMNS.reduce((sum, c) => sum + c.width, 0);

  if (rows.length === 0) {
    return (
      <div className={styles.emptyState}>
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.emptyIcon}>
          <rect x="4" y="4" width="32" height="32" rx="3" stroke="#cbd5e1" strokeWidth="2" fill="none"/>
          <line x1="4" y1="13" x2="36" y2="13" stroke="#cbd5e1" strokeWidth="1.5"/>
          <line x1="4" y1="21" x2="36" y2="21" stroke="#e2e8f0" strokeWidth="1"/>
          <line x1="4" y1="29" x2="36" y2="29" stroke="#e2e8f0" strokeWidth="1"/>
          <line x1="14" y1="4" x2="14" y2="36" stroke="#e2e8f0" strokeWidth="1"/>
          <line x1="24" y1="4" x2="24" y2="36" stroke="#e2e8f0" strokeWidth="1"/>
        </svg>
        <span className={styles.emptyText}>
          {isExecuting ? 'Waiting for first test to start…' : 'Excel view updates live during execution'}
        </span>
        <span className={styles.emptySubtext}>Rows appear here as each test case begins</span>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.grid} style={{ gridTemplateColumns: `40px ${COLUMNS.map(c => `${c.width}px`).join(' ')}`, minWidth: `${totalWidth}px` }}>
        {/* Column letter row */}
        <div className={styles.cornerCell}>#</div>
        {COLUMNS.map(col => (
          <div key={col.letter} className={styles.headerLetterCell}>{col.letter}</div>
        ))}

        {/* Column name row */}
        <div className={`${styles.headerNameCell} ${styles.rowNumHeader}`}>Row</div>
        {COLUMNS.map(col => (
          <div key={col.name} className={styles.headerNameCell}>{col.name}</div>
        ))}

        {/* Data rows */}
        {rows.map((row, rowIdx) => {
          const rc = rowClass(row.status);
          return (
            <React.Fragment key={row.testId}>
              {/* Row number cell */}
              <div className={`${styles.cell} ${styles.rowNumCell} ${rc}`}>
                {rowIdx + 1}
              </div>
              {/* T.C.No */}
              <div className={`${styles.cell} ${rc}`}>
                {row.tcNo > 0 ? row.tcNo : rowIdx + 1}
              </div>
              {/* Test Case */}
              <div className={`${styles.cell} ${rc}`}>
                {row.testName}
              </div>
              {/* Test Case Steps */}
              <div className={`${styles.cell} ${styles.stepsCell} ${rc}`}>
                <StepsCell stepsText={row.stepsText} currentStep={row.currentStep} />
              </div>
              {/* Expected Result */}
              <div className={`${styles.cell} ${rc}`}>
                {row.expectedResult}
              </div>
              {/* Input data */}
              <div className={`${styles.cell} ${rc}`}>
                {row.inputData}
              </div>
              {/* Status */}
              <div className={`${styles.cell} ${styles.statusCell} ${rc}`}>
                <StatusBadge status={row.status} />
              </div>
              {/* Error */}
              <div className={`${styles.cell} ${styles.errorCell} ${rc}`}>
                {row.error || ''}
              </div>
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};
