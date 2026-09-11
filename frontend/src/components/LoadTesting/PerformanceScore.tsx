import React from 'react';
import styles from './PerformanceScore.module.css';

interface PerformanceScoreProps {
  score: number;
  level: 'critical' | 'warning' | 'good';
  testId?: string;
}

export const PerformanceScore: React.FC<PerformanceScoreProps> = ({ score, level, testId }) => {
  const getScoreColor = () => {
    if (score >= 80) return '#10b981';
    if (score >= 60) return '#f59e0b';
    return '#ef4444';
  };

  const getLevelInfo = () => {
    if (level === 'good') return { icon: '🟢', label: 'Excellent', message: 'API is production-ready' };
    if (level === 'warning') return { icon: '🟡', label: 'Fair', message: 'Some improvements needed' };
    return { icon: '🔴', label: 'Poor', message: 'Critical issues detected' };
  };

  const info = getLevelInfo();

  return (
    <div className={styles.performanceScore}>
      <div className={styles.leftSection}>
        <div className={styles.scoreCircle} style={{ borderColor: getScoreColor() }}>
          <div className={styles.scoreValue}>{score}</div>
          <div className={styles.scoreLabel}>Performance Score</div>
        </div>
      </div>
      <div className={styles.rightSection}>
        <div className={styles.scoreInfo}>
          <div className={styles.levelBadge} style={{ backgroundColor: getScoreColor() }}>
            {info.icon} {info.label}
          </div>
          <p className={styles.message}>{info.message}</p>
        </div>
        {testId && (
          <div className={styles.testIdSection}>
            <span className={styles.testIdLabel}>Test ID:</span>
            <code className={styles.testIdValue}>{testId}</code>
          </div>
        )}
      </div>
    </div>
  );
};
