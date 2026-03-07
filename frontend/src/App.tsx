import { useEffect, Component, type ReactNode } from 'react';
import { Layout } from './components/Layout';
import { GenerateTestCase } from './components/GenerateTestCase';
import { AgentChat } from './components/AgentChat';
import { TestSuiteViewer } from './components/TestSuiteViewer';
import { ExecutionPanel } from './components/ExecutionPanel';
import { ResultsViewer } from './components/ResultsViewer';
import { DownloadReport } from './components/DownloadReport';
import { LoadTestDashboard } from './components/LoadTesting/LoadTestDashboard';
import LoadTestLogs from './components/LoadTesting/LoadTestLogs';
import { LoadTestReports } from './components/LoadTesting/LoadTestReports';
import { LoadTestInsights } from './components/LoadTesting/LoadTestInsights';
import { Settings } from './components/Settings/Settings';
import { ProjectsView } from './components/Projects/ProjectsView';
import { ProjectWorkspace } from './components/Projects/ProjectWorkspace';
import { Notifications } from './components/Notifications';
import { useStore } from './store/useStore';
import { usePeriodicHealthCheck } from './hooks/usePeriodicHealthCheck';
import { stopOrphanedSession } from './services/api';

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error('[ErrorBoundary] Caught render error:', error, info.componentStack);
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: '2rem', fontFamily: 'monospace' }}>
          <h2 style={{ color: '#dc2626' }}>Something went wrong</h2>
          <pre style={{ background: '#fee2e2', padding: '1rem', borderRadius: '8px', whiteSpace: 'pre-wrap', fontSize: '0.8rem' }}>
            {this.state.error.message}
            {'\n\n'}
            {this.state.error.stack}
          </pre>
          <button
            style={{ marginTop: '1rem', padding: '0.5rem 1rem', cursor: 'pointer' }}
            onClick={() => this.setState({ error: null })}
          >
            Try Again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function App() {
  const {
    currentView,
    setCurrentView,
    initializeLlmProvider,
    useDefaultLandingPage,
    defaultLandingPage
  } = useStore();

  // On startup: kill any backend session that was running before a browser refresh
  useEffect(() => {
    stopOrphanedSession();
  }, []);

  // Initialize LLM provider from backend on app load
  useEffect(() => {
    initializeLlmProvider();
  }, [initializeLlmProvider]);

  // Auto-navigate to default landing page on startup
  useEffect(() => {
    if (useDefaultLandingPage && defaultLandingPage) {
      setCurrentView(defaultLandingPage);
    }
  }, []); // Run only once on mount

  // Enable periodic health checks
  usePeriodicHealthCheck();

  const renderView = () => {
    switch (currentView) {
      case 'generate':
        return <GenerateTestCase />;
      case 'upload':
        return <AgentChat />;
      case 'suite':
        return <TestSuiteViewer />;
      case 'execution':
        return <ExecutionPanel />;
      case 'results':
        return <ResultsViewer />;
      case 'download':
        return <DownloadReport />;
      case 'loadtest':
        return <LoadTestDashboard />;
      case 'loadtest-logs':
        return <LoadTestLogs />;
      case 'loadtest-reports':
        return <LoadTestReports />;
      case 'loadtest-insights':
        return <LoadTestInsights />;
      case 'settings':
        return <Settings />;
      case 'projects':
        return <ProjectsView />;
      case 'project-workspace':
        return <ProjectWorkspace />;
      default:
        return <AgentChat />;
    }
  };

  return (
    <ErrorBoundary>
      <Layout>{renderView()}</Layout>
      <Notifications />
    </ErrorBoundary>
  );
}

export default App;
