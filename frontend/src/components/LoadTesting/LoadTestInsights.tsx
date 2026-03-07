import React from 'react';
import { useStore } from '../../store/useStore';
import { AISuggestionsPanel } from './AISuggestionsPanel';
import styles from './LoadTestInsights.module.css';

export const LoadTestInsights: React.FC = () => {
  const {
    activeLoadTestId,
    sequentialTestId,
    lastCompletedTestId,
    llmProvider,
    setCurrentView,
    addNotification,
    setAiSuggestedConfig
  } = useStore();

  // Determine which test ID to use
  // Priority: 1) lastCompletedTestId (if a test is completed and new one is running)
  //           2) sequentialTestId (if sequential test is active)
  //           3) activeLoadTestId (if single test is active)
  const testId = lastCompletedTestId || sequentialTestId || activeLoadTestId;

  const handleRetestWithSuggestion = (suggestedConfig: any) => {
    console.log('handleRetestWithSuggestion called with:', suggestedConfig);

    // Extract the recommended values from the suggestion metrics
    const aiConfig = {
      users: suggestedConfig.recommended_users,
      spawn_rate: suggestedConfig.recommended_spawn_rate,
      run_time: suggestedConfig.recommended_duration,
      think_time_min: suggestedConfig.recommended_think_time_min,
      think_time_max: suggestedConfig.recommended_think_time_max,
    };

    console.log('Extracted AI config:', aiConfig);

    // Save to store so LoadTestDashboard can use it
    setAiSuggestedConfig(aiConfig);

    // Navigate to Load Test Dashboard
    setCurrentView('loadtest');

    // Show notification
    addNotification('info', 'Test configuration updated with AI suggestions. Review and click Run Test.');
  };

  if (!testId) {
    return (
      <div className={styles.noInsights}>
        <div className={styles.noInsightsIcon}>🤖</div>
        <h2>AI-Powered Insights</h2>
        <p>No load test results available yet.</p>
        <p className={styles.hint}>Run a load test to see AI-powered insights and recommendations.</p>
        <button className={styles.goToTestButton} onClick={() => setCurrentView('loadtest')}>
          Go to Load Test
        </button>
      </div>
    );
  }

  return (
    <div className={styles.insightsContainer}>
      <div className={styles.header}>
        <div className={styles.headerContent}>
          <div className={styles.titleRow}>
            <span className={styles.icon}>🤖</span>
            <h1>AI-Powered Insights</h1>
          </div>
          <p className={styles.subtitle}>
            Get actionable recommendations to improve your API and load tests
          </p>
        </div>
      </div>

      <AISuggestionsPanel
        testId={testId}
        llmProvider={llmProvider}
        onRetestWithSuggestion={handleRetestWithSuggestion}
      />
    </div>
  );
};
