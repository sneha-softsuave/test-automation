import { useEffect } from 'react';
import { Layout } from './components/Layout';
import { AgentChat } from './components/AgentChat';
import { TestSuiteViewer } from './components/TestSuiteViewer';
import { ExecutionPanel } from './components/ExecutionPanel';
import { ResultsViewer } from './components/ResultsViewer';
import { DownloadReport } from './components/DownloadReport';
import { LoadTestDashboard } from './components/LoadTesting/LoadTestDashboard';
import LoadTestLogs from './components/LoadTesting/LoadTestLogs';
import { LoadTestReports } from './components/LoadTesting/LoadTestReports';
import { LoadTestInsights } from './components/LoadTesting/LoadTestInsights';
import { Notifications } from './components/Notifications';
import { useStore } from './store/useStore';

function App() {
  const { currentView, initializeLlmProvider } = useStore();

  // Initialize LLM provider from backend on app load
  useEffect(() => {
    initializeLlmProvider();
  }, [initializeLlmProvider]);

  const renderView = () => {
    switch (currentView) {
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
      default:
        return <AgentChat />;
    }
  };

  return (
    <>
      <Layout>{renderView()}</Layout>
      <Notifications />
    </>
  );
}

export default App;
