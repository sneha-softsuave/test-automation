import { useEffect } from 'react';
import { FlaskConical, Sparkles, Clock } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { TestSuiteViewer } from '../TestSuiteViewer';
import styles from './ProjectWorkspace.module.css';

interface Props {
  projectName: string;
}

export const ProjectTestSuite = ({ projectName }: Props) => {
  const { projectActiveSuites, setTestSuite, setActiveProjectSection } = useStore();

  const activeSuite = projectActiveSuites[projectName] ?? null;

  // Sync active suite into global store so TestSuiteViewer reads from it
  useEffect(() => {
    if (activeSuite) {
      setTestSuite(activeSuite);
    }
  }, [activeSuite, setTestSuite]);

  if (!activeSuite) {
    return (
      <div className={styles.emptyState}>
        <FlaskConical size={40} className={styles.emptyStateIcon} />
        <p className={styles.emptyStateTitle}>No test suite loaded</p>
        <p className={styles.emptyStateHint}>Generate a test case or load one from history first.</p>
        <div className={styles.emptyStateActions}>
          <button className={styles.btnPrimary} onClick={() => setActiveProjectSection('generate')}>
            <Sparkles size={14} />
            Generate Test Case
          </button>
          <button className={styles.btnSecondary} onClick={() => setActiveProjectSection('history')}>
            <Clock size={14} />
            Load from History
          </button>
        </div>
      </div>
    );
  }

  return <TestSuiteViewer />;
};
