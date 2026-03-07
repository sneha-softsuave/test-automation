import { useState, useEffect, useCallback } from 'react';
import { FolderOpen, Trash2, Download, Plus, Loader2, AlertCircle, FolderPlus } from 'lucide-react';
import { useStore } from '../../store/useStore';
import {
  listProjects,
  listProjectTests,
  loadTestFromProject,
  deleteProjectTest,
  deleteProject,
  createProject,
  type ProjectSummary,
  type SavedTestMeta,
} from '../../services/api';
import styles from './ProjectsView.module.css';

export const ProjectsView = () => {
  const { selectedProjectName, setSelectedProjectName, setTestSuite, setGeneratedScript, setRawTestCases, setCurrentView, addNotification } = useStore();

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [tests, setTests] = useState<SavedTestMeta[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingTests, setLoadingTests] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newProjectName, setNewProjectName] = useState('');
  const [creatingProject, setCreatingProject] = useState(false);

  const [deletingTest, setDeletingTest] = useState<string | null>(null);
  const [deletingProject, setDeletingProject] = useState<string | null>(null);
  const [loadingTest, setLoadingTest] = useState<string | null>(null);

  const fetchProjects = useCallback(async () => {
    setLoadingProjects(true);
    setError(null);
    try {
      const data = await listProjects();
      setProjects(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load projects');
    } finally {
      setLoadingProjects(false);
    }
  }, []);

  const fetchTests = useCallback(async (projectName: string) => {
    setLoadingTests(true);
    setTests([]);
    try {
      const data = await listProjectTests(projectName);
      setTests(data);
    } catch (e) {
      addNotification('error', e instanceof Error ? e.message : 'Failed to load tests');
    } finally {
      setLoadingTests(false);
    }
  }, [addNotification]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    if (selectedProjectName) {
      fetchTests(selectedProjectName);
    } else {
      setTests([]);
    }
  }, [selectedProjectName, fetchTests]);

  const handleSelectProject = (name: string) => {
    setSelectedProjectName(name);
  };

  const handleCreateProject = async () => {
    const name = newProjectName.trim();
    if (!name) return;
    setCreatingProject(true);
    try {
      const created = await createProject(name);
      setNewProjectName('');
      await fetchProjects();
      setSelectedProjectName(created.name);
      addNotification('success', `Project "${created.name}" created`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to create project';
      addNotification('error', msg);
    } finally {
      setCreatingProject(false);
    }
  };

  const handleLoadTest = async (filename: string) => {
    if (!selectedProjectName) return;
    setLoadingTest(filename);
    try {
      const suite = await loadTestFromProject(selectedProjectName, filename);
      setTestSuite(suite as any);
      setGeneratedScript(null);  // clear stale scripts from previous sessions
      setRawTestCases(null);     // clear stale Excel data — suite is already parsed
      addNotification('success', 'Test suite loaded — navigate to Test Suite to view');
      setCurrentView('suite');
    } catch (e) {
      addNotification('error', e instanceof Error ? e.message : 'Failed to load test');
    } finally {
      setLoadingTest(null);
    }
  };

  const handleDeleteTest = async (filename: string) => {
    if (!selectedProjectName) return;
    setDeletingTest(filename);
    try {
      await deleteProjectTest(selectedProjectName, filename);
      setTests(prev => prev.filter(t => t.filename !== filename));
      // Refresh project list to update test_count
      const data = await listProjects();
      setProjects(data);
      addNotification('success', 'Test deleted');
    } catch (e) {
      addNotification('error', e instanceof Error ? e.message : 'Failed to delete test');
    } finally {
      setDeletingTest(null);
    }
  };

  const handleDeleteProject = async (name: string) => {
    setDeletingProject(name);
    try {
      await deleteProject(name);
      if (selectedProjectName === name) {
        setSelectedProjectName(null);
        setTests([]);
      }
      await fetchProjects();
      addNotification('success', `Project "${name}" deleted`);
    } catch (e) {
      addNotification('error', e instanceof Error ? e.message : 'Failed to delete project');
    } finally {
      setDeletingProject(null);
    }
  };

  const formatSavedAt = (savedAt: string) => {
    // savedAt format: "YYYY-MM-DD_HH-MM-SS"
    const parts = savedAt.split('_');
    if (parts.length === 2) {
      const date = parts[0]; // YYYY-MM-DD
      const time = parts[1].replace(/-/g, ':'); // HH:MM:SS
      return `${date} ${time}`;
    }
    return savedAt;
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <FolderOpen size={22} className={styles.headerIcon} />
        <div>
          <h1 className={styles.title}>Projects</h1>
          <p className={styles.subtitle}>Saved test suites from Generate Test Case</p>
        </div>
      </div>

      {error && (
        <div className={styles.errorCard}>
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      <div className={styles.body}>
        {/* Left column — project list */}
        <div className={styles.projectCol}>
          <div className={styles.newProjectRow}>
            <input
              className={styles.newProjectInput}
              type="text"
              placeholder="New project name…"
              value={newProjectName}
              onChange={e => setNewProjectName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreateProject()}
            />
            <button
              className={styles.createBtn}
              onClick={handleCreateProject}
              disabled={!newProjectName.trim() || creatingProject}
              title="Create project"
            >
              {creatingProject ? <Loader2 size={14} className={styles.spin} /> : <Plus size={14} />}
            </button>
          </div>

          {loadingProjects ? (
            <div className={styles.loadingRow}>
              <Loader2 size={16} className={styles.spin} />
              <span>Loading projects…</span>
            </div>
          ) : projects.length === 0 ? (
            <div className={styles.emptyProjects}>
              <FolderPlus size={28} className={styles.emptyIcon} />
              <p>No projects yet</p>
              <p className={styles.emptyHint}>Create one above, or save a test suite from Generate Test Case</p>
            </div>
          ) : (
            <ul className={styles.projectList}>
              {projects.map(p => (
                <li
                  key={p.name}
                  className={`${styles.projectItem} ${selectedProjectName === p.name ? styles.selected : ''}`}
                  onClick={() => handleSelectProject(p.name)}
                >
                  <FolderOpen size={15} className={styles.folderIcon} />
                  <span className={styles.projectName}>{p.name}</span>
                  <span className={styles.testCountBadge}>{p.test_count}</span>
                  <button
                    className={styles.deleteProjectBtn}
                    onClick={e => { e.stopPropagation(); handleDeleteProject(p.name); }}
                    disabled={deletingProject === p.name}
                    title="Delete project"
                  >
                    {deletingProject === p.name
                      ? <Loader2 size={12} className={styles.spin} />
                      : <Trash2 size={12} />}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Right column — test list */}
        <div className={styles.testCol}>
          {!selectedProjectName ? (
            <div className={styles.emptyTests}>
              <FolderOpen size={40} className={styles.emptyTestsIcon} />
              <p>Select a project to view saved tests</p>
            </div>
          ) : loadingTests ? (
            <div className={styles.loadingRow}>
              <Loader2 size={16} className={styles.spin} />
              <span>Loading tests…</span>
            </div>
          ) : tests.length === 0 ? (
            <div className={styles.emptyTests}>
              <FolderOpen size={40} className={styles.emptyTestsIcon} />
              <p>No saved tests in <strong>{selectedProjectName}</strong></p>
              <p className={styles.emptyHint}>Generate a test suite and click "Save to Project"</p>
            </div>
          ) : (
            <>
              <h2 className={styles.testColTitle}>{selectedProjectName}</h2>
              <div className={styles.testList}>
                {tests.map(t => (
                  <div key={t.filename} className={styles.testCard}>
                    <div className={styles.testCardBody}>
                      <div className={styles.testCardDate}>{formatSavedAt(t.saved_at)}</div>
                      <div className={styles.testCardUrl}>{t.base_url || '—'}</div>
                      <span className={styles.testCaseBadge}>
                        {t.test_case_count} test case{t.test_case_count !== 1 ? 's' : ''}
                      </span>
                    </div>
                    <div className={styles.testCardActions}>
                      <button
                        className={styles.loadBtn}
                        onClick={() => handleLoadTest(t.filename)}
                        disabled={loadingTest === t.filename}
                      >
                        {loadingTest === t.filename
                          ? <Loader2 size={13} className={styles.spin} />
                          : <Download size={13} />}
                        Load
                      </button>
                      <button
                        className={styles.deleteTestBtn}
                        onClick={() => handleDeleteTest(t.filename)}
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
            </>
          )}
        </div>
      </div>
    </div>
  );
};
