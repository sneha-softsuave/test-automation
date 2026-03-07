import { Sparkles, Clock, FlaskConical, Play, ChevronRight } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { ProjectGenerateTestCase } from './ProjectGenerateTestCase';
import { ProjectHistory } from './ProjectHistory';
import { ProjectTestSuite } from './ProjectTestSuite';
import { ProjectExecute } from './ProjectExecute';
import styles from './ProjectWorkspace.module.css';

const SECTIONS = [
  { id: 'generate' as const, label: 'Generate Test Case', icon: Sparkles },
  { id: 'history' as const, label: 'History', icon: Clock },
  { id: 'suite' as const, label: 'Test Suite', icon: FlaskConical },
  { id: 'execute' as const, label: 'Execute', icon: Play },
];

export const ProjectWorkspace = () => {
  const {
    selectedProjectName,
    activeProjectSection,
    setActiveProjectSection,
    setCurrentView,
  } = useStore();

  if (!selectedProjectName) {
    return (
      <div className={styles.emptyState}>
        <p className={styles.emptyStateTitle}>No project selected</p>
      </div>
    );
  }

  const sectionLabel = SECTIONS.find(s => s.id === activeProjectSection)?.label ?? '';

  const renderSection = () => {
    switch (activeProjectSection) {
      case 'generate':
        return <ProjectGenerateTestCase projectName={selectedProjectName} />;
      case 'history':
        return <ProjectHistory projectName={selectedProjectName} />;
      case 'suite':
        return <ProjectTestSuite projectName={selectedProjectName} />;
      case 'execute':
        return <ProjectExecute projectName={selectedProjectName} />;
    }
  };

  return (
    <div className={styles.workspace}>
      {/* Breadcrumb */}
      <div className={styles.breadcrumb}>
        <button className={styles.breadcrumbLink} onClick={() => setCurrentView('projects')}>
          Projects
        </button>
        <ChevronRight size={13} className={styles.breadcrumbSep} />
        <span className={styles.breadcrumbCurrent}>{selectedProjectName}</span>
        <ChevronRight size={13} className={styles.breadcrumbSep} />
        <span>{sectionLabel}</span>
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        {SECTIONS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`${styles.tab} ${activeProjectSection === id ? styles.activeTab : ''}`}
            onClick={() => setActiveProjectSection(id)}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className={styles.content}>
        {renderSection()}
      </div>
    </div>
  );
};
