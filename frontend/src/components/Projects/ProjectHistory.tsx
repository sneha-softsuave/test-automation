import { useState, useEffect, useCallback } from 'react';
import { Clock, Download, Trash2, Loader2, FolderOpen, Sparkles, Video } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { listProjectTests, loadTestFromProject, deleteProjectTest, type SavedTestMeta } from '../../services/api';
import type { TestSuite } from '../../store/useStore';
import styles from './ProjectsView.module.css';

interface Props {
  projectName: string;
}

const formatSavedAt = (savedAt: string) => {
  const parts = savedAt.split('_');
  if (parts.length === 2) {
    return `${parts[0]} ${parts[1].replace(/-/g, ':')}`;
  }
  return savedAt;
};

export const ProjectHistory = ({ projectName }: Props) => {
  const { setTestSuite, setProjectActiveSuite, setActiveProjectSection, addNotification } = useStore();

  const [tests, setTests] = useState<SavedTestMeta[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingTest, setLoadingTest] = useState<string | null>(null);
  const [deletingTest, setDeletingTest] = useState<string | null>(null);

  const fetchTests = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listProjectTests(projectName);
      setTests(data);
    } catch (e) {
      addNotification('error', e instanceof Error ? e.message : 'Failed to load tests');
    } finally {
      setLoading(false);
    }
  }, [projectName, addNotification]);

  useEffect(() => {
    fetchTests();
  }, [fetchTests]);

  const handleLoad = async (filename: string) => {
    setLoadingTest(filename);
    try {
      const suite = await loadTestFromProject(projectName, filename);
      setTestSuite(suite as TestSuite);
      setProjectActiveSuite(projectName, suite as TestSuite);
      addNotification('success', 'Test suite loaded');
      setActiveProjectSection('suite');
    } catch (e) {
      addNotification('error', e instanceof Error ? e.message : 'Failed to load test');
    } finally {
      setLoadingTest(null);
    }
  };

  const handleDelete = async (filename: string) => {
    setDeletingTest(filename);
    try {
      await deleteProjectTest(projectName, filename);
      setTests(prev => prev.filter(t => t.filename !== filename));
      addNotification('success', 'Test deleted');
    } catch (e) {
      addNotification('error', e instanceof Error ? e.message : 'Failed to delete test');
    } finally {
      setDeletingTest(null);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '32px', display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', fontSize: '0.875rem' }}>
        <Loader2 size={16} className={styles.spin} />
        Loading tests…
      </div>
    );
  }

  if (tests.length === 0) {
    return (
      <div className={styles.emptyTests} style={{ padding: '32px' }}>
        <Clock size={40} className={styles.emptyTestsIcon} />
        <p>No tests saved yet in <strong>{projectName}</strong></p>
        <p className={styles.emptyHint}>Generate a test case first to save it here.</p>
      </div>
    );
  }

  return (
    <div style={{ padding: '24px 32px' }}>
      <h2 className={styles.testColTitle}>{projectName} — History</h2>
      <div className={styles.testList}>
        {tests.map(t => (
          <div key={t.filename} className={styles.testCard}>
            <div className={styles.testCardBody}>
              <div className={styles.testCardDate}>{formatSavedAt(t.saved_at)}</div>
              <div className={styles.testCardUrl}>{t.base_url || '—'}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <span className={styles.testCaseBadge}>
                  {t.test_case_count} test case{t.test_case_count !== 1 ? 's' : ''}
                </span>
                {t.source === 'generate' && (
                  <span className={styles.sourceBadgeGenerate}>
                    <Sparkles size={10} />
                    Generate AI
                  </span>
                )}
                {t.source === 'record' && (
                  <span className={styles.sourceBadgeRecord}>
                    <Video size={10} />
                    Record AI
                  </span>
                )}
              </div>
            </div>
            <div className={styles.testCardActions}>
              <button
                className={styles.loadBtn}
                onClick={() => handleLoad(t.filename)}
                disabled={loadingTest === t.filename}
              >
                {loadingTest === t.filename
                  ? <Loader2 size={13} className={styles.spin} />
                  : <Download size={13} />}
                Load
              </button>
              <button
                className={styles.deleteTestBtn}
                onClick={() => handleDelete(t.filename)}
                disabled={deletingTest === t.filename}
                title="Delete test"
              >
                {deletingTest === t.filename
                  ? <Loader2 size={13} className={styles.spin} />
                  : <Trash2 size={13} />}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
