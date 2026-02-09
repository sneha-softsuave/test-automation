import { Layout } from './components/Layout';
import { AgentChat } from './components/AgentChat';
import { TestSuiteViewer } from './components/TestSuiteViewer';
import { ExecutionPanel } from './components/ExecutionPanel';
import { ResultsViewer } from './components/ResultsViewer';
import { DownloadReport } from './components/DownloadReport';
import { LoadTestDashboard } from './components/LoadTesting/LoadTestDashboard';
import { Notifications } from './components/Notifications';
import { useStore } from './store/useStore';

function App() {
  const { currentView } = useStore();

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
