import { useState, useEffect } from 'react';
import { X, Loader2, Plus, FolderOpen, AlertCircle, Check } from 'lucide-react';
import { listProjects, createProject, saveTestToProject, type ProjectSummary } from '../../services/api';
import styles from './SaveToProjectModal.module.css';

interface GeneratedSuite {
  project: string;
  base_url: string;
  test_cases: Array<unknown>;
  common_selectors: Record<string, unknown>;
  test_data: Record<string, unknown>;
}

interface Props {
  suite: GeneratedSuite;
  onClose: () => void;
  onSaved: (projectName: string, filename: string) => void;
}

export const SaveToProjectModal = ({ suite, onClose, onSaved }: Props) => {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [newProjectName, setNewProjectName] = useState('');
  const [creatingProject, setCreatingProject] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load projects'))
      .finally(() => setLoadingProjects(false));
  }, []);

  const handleCreateProject = async () => {
    const name = newProjectName.trim();
    if (!name) return;
    setCreatingProject(true);
    setError(null);
    try {
      const created = await createProject(name);
      const updated = await listProjects();
      setProjects(updated);
      setSelectedProject(created.name);
      setNewProjectName('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create project');
    } finally {
      setCreatingProject(false);
    }
  };

  const handleSave = async () => {
    if (!selectedProject) return;
    setSaving(true);
    setError(null);
    try {
      const result = await saveTestToProject(selectedProject, suite);
      onSaved(selectedProject, result.filename);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save test');
      setSaving(false);
    }
  };

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.card} onClick={e => e.stopPropagation()}>
        <div className={styles.cardHeader}>
          <div className={styles.cardTitle}>
            <FolderOpen size={18} className={styles.cardIcon} />
            Save to Project
          </div>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className={styles.cardBody}>
          {error && (
            <div className={styles.errorBox}>
              <AlertCircle size={14} />
              <span>{error}</span>
            </div>
          )}

          <p className={styles.sectionLabel}>Select project</p>

          {loadingProjects ? (
            <div className={styles.loadingRow}>
              <Loader2 size={15} className={styles.spin} />
              <span>Loading projects…</span>
            </div>
          ) : (
            <div className={styles.projectList}>
              {projects.length === 0 && (
                <p className={styles.noProjects}>No projects yet. Create one below.</p>
              )}
              {projects.map(p => (
                <button
                  key={p.name}
                  className={`${styles.projectItem} ${selectedProject === p.name ? styles.selected : ''}`}
                  onClick={() => setSelectedProject(p.name)}
                >
                  <FolderOpen size={14} className={styles.folderIcon} />
                  <span className={styles.projectName}>{p.name}</span>
                  <span className={styles.count}>{p.test_count}</span>
                  {selectedProject === p.name && <Check size={14} className={styles.checkIcon} />}
                </button>
              ))}
            </div>
          )}

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
            >
              {creatingProject ? <Loader2 size={13} className={styles.spin} /> : <Plus size={13} />}
              Create &amp; Select
            </button>
          </div>
        </div>

        <div className={styles.cardFooter}>
          <button className={styles.cancelBtn} onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button
            className={styles.saveBtn}
            onClick={handleSave}
            disabled={!selectedProject || saving}
          >
            {saving ? <Loader2 size={14} className={styles.spin} /> : null}
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
};
