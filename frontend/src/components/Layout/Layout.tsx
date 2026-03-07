import { motion } from 'framer-motion';
import { Bot, MessageSquare, FlaskConical, Play, FileCheck, Download, Menu, X, Zap, Wrench, ChevronDown, ChevronRight, BarChart3, Terminal, Brain, Settings, Sparkles, FolderOpen } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useStore } from '../../store/useStore';
import { listProjects, type ProjectSummary } from '../../services/api';
import styles from './Layout.module.css';

interface LayoutProps {
  children: React.ReactNode;
}

// Functional test sub-items
const functionalTestItems = [
  { id: 'generate', label: 'Generate Test Case', icon: Sparkles },
  { id: 'upload', label: 'Agent', icon: MessageSquare },
  { id: 'suite', label: 'Test Suite', icon: FlaskConical },
  { id: 'execution', label: 'Execute', icon: Play },
  { id: 'results', label: 'Results', icon: FileCheck },
  { id: 'download', label: 'Download', icon: Download },
] as const;

// Load Test sub-items
const loadTestItems = [
  { id: 'loadtest', label: 'Agent', icon: Zap },
  { id: 'loadtest-logs', label: 'Logs', icon: Terminal },
  { id: 'loadtest-reports', label: 'Reports', icon: BarChart3 },
  { id: 'loadtest-insights', label: 'AI Insights', icon: Brain },
] as const;

export const Layout = ({ children }: LayoutProps) => {
  const { currentView, setCurrentView, testSuite, executionResult, rawTestCases, selectedProjectName, setSelectedProjectName } = useStore();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [functionalTestExpanded, setFunctionalTestExpanded] = useState(false);
  const [loadTestExpanded, setLoadTestExpanded] = useState(false);
  const [projectsExpanded, setProjectsExpanded] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);

  useEffect(() => {
    listProjects().then(setProjects).catch(() => {});
  }, [currentView]);

  const canNavigateTo = (view: string): boolean => {
    switch (view) {
      case 'generate':
        return true;
      case 'upload':
        return true;
      case 'suite':
        return !!testSuite;
      case 'execution':
        return !!testSuite;
      case 'results':
        return !!executionResult;
      case 'download':
        return !!(testSuite || rawTestCases || executionResult);
      case 'loadtest':
        return true; // Load Test Agent is always accessible
      case 'loadtest-logs':
        return true; // Load Test Logs is always accessible
      case 'loadtest-reports':
        return true; // Load Test Reports is always accessible
      case 'loadtest-insights':
        return true; // AI Insights is always accessible
      case 'settings':
        return true; // Settings is always accessible
      case 'projects':
        return true; // Projects is always accessible
      default:
        return false;
    }
  };

  // Check if any functional test item is active
  const isFunctionalTestActive = functionalTestItems.some(item => item.id === currentView);

  // Check if any load test item is active
  const isLoadTestActive = loadTestItems.some(item => item.id === currentView);

  // Handle functional test parent click
  const handleFunctionalTestClick = () => {
    if (!functionalTestExpanded) {
      // If collapsed, expand and navigate to Agent
      setFunctionalTestExpanded(true);
      setCurrentView('upload');
    } else {
      // If expanded, navigate to Agent (first child)
      setCurrentView('upload');
    }
    setMobileMenuOpen(false);
  };

  // Toggle expand/collapse
  const toggleFunctionalTest = (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent parent click
    setFunctionalTestExpanded(!functionalTestExpanded);
  };

  // Handle load test parent click
  const handleLoadTestClick = () => {
    if (!loadTestExpanded) {
      // If collapsed, expand and navigate to Agent
      setLoadTestExpanded(true);
      setCurrentView('loadtest');
    } else {
      // If expanded, navigate to Agent (first child)
      setCurrentView('loadtest');
    }
    setMobileMenuOpen(false);
  };

  // Toggle expand/collapse
  const toggleLoadTest = (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent parent click
    setLoadTestExpanded(!loadTestExpanded);
  };

  return (
    <div className={styles.layout}>
      {/* Sidebar */}
      <motion.aside
        className={`${styles.sidebar} ${mobileMenuOpen ? styles.open : ''}`}
        initial={{ x: -100, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
      >
        {/* Logo */}
        <motion.div
          className={styles.logo}
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          <div className={styles.logoIcon}>
            <Bot size={28} />
            <div className={styles.logoGlow} />
          </div>
          <div className={styles.logoText}>
            <span className={styles.logoTitle}>DEEP</span>
            <span className={styles.logoSubtitle}>AGENT</span>
          </div>
        </motion.div>

        {/* Navigation */}
        <nav className={styles.nav}>
          {/* Projects Section */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.05 }}
          >
            <button
              className={`${styles.navItem} ${styles.navParent} ${currentView === 'projects' ? styles.active : ''}`}
              onClick={() => {
                if (!projectsExpanded) setProjectsExpanded(true);
                setCurrentView('projects');
                setMobileMenuOpen(false);
              }}
            >
              <div className={styles.navItemIcon}>
                <FolderOpen size={20} />
              </div>
              <span className={styles.navItemLabel}>Projects</span>
              <button
                className={styles.expandButton}
                onClick={e => { e.stopPropagation(); setProjectsExpanded(!projectsExpanded); }}
                aria-label={projectsExpanded ? 'Collapse' : 'Expand'}
              >
                {projectsExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </button>
              {currentView === 'projects' && (
                <motion.div
                  className={styles.navItemIndicator}
                  layoutId="navIndicator"
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                />
              )}
            </button>

            {projectsExpanded && (
              <motion.div
                className={styles.navChildren}
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2 }}
                style={{ maxHeight: 180, overflowY: 'auto' }}
              >
                {projects.length === 0 ? (
                  <span style={{ display: 'block', padding: '6px 16px', fontSize: '0.75rem', color: '#94a3b8' }}>
                    No projects yet
                  </span>
                ) : (
                  projects.map((p, index) => {
                    const isProjectActive = currentView === 'project-workspace' && selectedProjectName === p.name;
                    return (
                      <motion.button
                        key={p.name}
                        className={`${styles.navItem} ${styles.navChild} ${isProjectActive ? styles.active : ''}`}
                        onClick={() => {
                          setSelectedProjectName(p.name);
                          setCurrentView('project-workspace');
                          setMobileMenuOpen(false);
                        }}
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.05 * (index + 1) }}
                        whileHover={{ x: 4 }}
                        whileTap={{ scale: 0.98 }}
                      >
                        <div className={styles.navItemIcon}>
                          <FolderOpen size={16} />
                        </div>
                        <span className={styles.navItemLabel}>{p.name}</span>
                        <span style={{ fontSize: '0.6875rem', background: '#e2e8f0', color: '#475569', padding: '1px 5px', borderRadius: 8, flexShrink: 0 }}>
                          {p.test_count}
                        </span>
                      </motion.button>
                    );
                  })
                )}
              </motion.div>
            )}
          </motion.div>

          {/* Functional Test Parent */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.1 }}
          >
            <button
              className={`${styles.navItem} ${styles.navParent} ${isFunctionalTestActive ? styles.active : ''}`}
              onClick={handleFunctionalTestClick}
            >
              <div className={styles.navItemIcon}>
                <Wrench size={20} />
              </div>
              <span className={styles.navItemLabel}>Functional Test</span>
              <button
                className={styles.expandButton}
                onClick={toggleFunctionalTest}
                aria-label={functionalTestExpanded ? 'Collapse' : 'Expand'}
              >
                {functionalTestExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </button>
              {isFunctionalTestActive && (
                <motion.div
                  className={styles.navItemIndicator}
                  layoutId="navIndicator"
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                />
              )}
            </button>

            {/* Functional Test Children */}
            {functionalTestExpanded && (
              <motion.div
                className={styles.navChildren}
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2 }}
              >
                {functionalTestItems.map((item, index) => {
                  const Icon = item.icon;
                  const isActive = currentView === item.id;
                  const isDisabled = !canNavigateTo(item.id);

                  return (
                    <motion.button
                      key={item.id}
                      className={`${styles.navItem} ${styles.navChild} ${isActive ? styles.active : ''} ${isDisabled ? styles.disabled : ''}`}
                      onClick={() => {
                        if (!isDisabled) {
                          setCurrentView(item.id);
                          setMobileMenuOpen(false);
                        }
                      }}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.05 * (index + 1) }}
                      whileHover={!isDisabled ? { x: 4 } : {}}
                      whileTap={!isDisabled ? { scale: 0.98 } : {}}
                    >
                      <div className={styles.navItemIcon}>
                        <Icon size={18} />
                      </div>
                      <span className={styles.navItemLabel}>{item.label}</span>
                      {isActive && (
                        <motion.div
                          className={styles.navItemIndicator}
                          layoutId="navChildIndicator"
                          transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                        />
                      )}
                    </motion.button>
                  );
                })}
              </motion.div>
            )}
          </motion.div>

          {/* Load Test Parent */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.5 }}
          >
            <button
              className={`${styles.navItem} ${styles.navParent} ${isLoadTestActive ? styles.active : ''}`}
              onClick={handleLoadTestClick}
            >
              <div className={styles.navItemIcon}>
                <Zap size={20} />
              </div>
              <span className={styles.navItemLabel}>Load Test</span>
              <button
                className={styles.expandButton}
                onClick={toggleLoadTest}
                aria-label={loadTestExpanded ? 'Collapse' : 'Expand'}
              >
                {loadTestExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </button>
              {isLoadTestActive && (
                <motion.div
                  className={styles.navItemIndicator}
                  layoutId="navIndicator"
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                />
              )}
            </button>

            {/* Load Test Children */}
            {loadTestExpanded && (
              <motion.div
                className={styles.navChildren}
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2 }}
              >
                {loadTestItems.map((item, index) => {
                  const Icon = item.icon;
                  const isActive = currentView === item.id;
                  const isDisabled = !canNavigateTo(item.id);

                  return (
                    <motion.button
                      key={item.id}
                      className={`${styles.navItem} ${styles.navChild} ${isActive ? styles.active : ''} ${isDisabled ? styles.disabled : ''}`}
                      onClick={() => {
                        if (!isDisabled) {
                          setCurrentView(item.id);
                          setMobileMenuOpen(false);
                        }
                      }}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.05 * (index + 1) }}
                      whileHover={!isDisabled ? { x: 4 } : {}}
                      whileTap={!isDisabled ? { scale: 0.98 } : {}}
                    >
                      <div className={styles.navItemIcon}>
                        <Icon size={18} />
                      </div>
                      <span className={styles.navItemLabel}>{item.label}</span>
                      {isActive && (
                        <motion.div
                          className={styles.navItemIndicator}
                          layoutId="navChildIndicator"
                          transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                        />
                      )}
                    </motion.button>
                  );
                })}
              </motion.div>
            )}
          </motion.div>

          {/* Settings Section */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.6 }}
          >
            <button
              className={`${styles.navItem} ${currentView === 'settings' ? styles.active : ''}`}
              onClick={() => {
                setCurrentView('settings');
                setMobileMenuOpen(false);
              }}
            >
              <div className={styles.navItemIcon}>
                <Settings size={20} />
              </div>
              <span className={styles.navItemLabel}>Settings</span>
              {currentView === 'settings' && (
                <motion.div
                  className={styles.navItemIndicator}
                  layoutId="navIndicator"
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                />
              )}
            </button>
          </motion.div>
        </nav>

        {/* Status */}
        <div className={styles.status}>
          <div className={styles.statusItem}>
            <div className={`${styles.statusDot} ${testSuite ? styles.active : ''}`} />
            <span>Test Suite {testSuite ? 'Loaded' : 'Empty'}</span>
          </div>
          {testSuite && (
            <motion.div
              className={styles.statusStats}
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
            >
              <span>{testSuite.test_cases.length} Test Cases</span>
              <span>
                {testSuite.test_cases.reduce((acc, tc) => acc + tc.steps.length, 0)} Steps
              </span>
            </motion.div>
          )}
        </div>
      </motion.aside>

      {/* Mobile Header */}
      <div className={styles.mobileHeader}>
        <button
          className={styles.menuButton}
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        >
          {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
        <div className={styles.mobileLogo}>
          <Bot size={24} />
          <span>DEEP AGENT</span>
        </div>
      </div>

      {/* Main Content */}
      <main className={styles.main}>
        <motion.div
          className={styles.content}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}
        >
          {children}
        </motion.div>
      </main>

      {/* Mobile Overlay */}
      {mobileMenuOpen && (
        <motion.div
          className={styles.overlay}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => setMobileMenuOpen(false)}
        />
      )}
    </div>
  );
};
