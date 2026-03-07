import React, { useState, useEffect } from 'react';
import styles from './AISuggestionsPanel.module.css';
import { PerformanceScore } from './PerformanceScore';
import { SuggestionCard } from './SuggestionCard';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:9000';

interface SuggestionMetrics {
  current_value?: number;
  target_value?: number;
  recommended_users?: number;
  recommended_spawn_rate?: number;
  recommended_duration?: string;
  recommended_think_time_min?: number;
  recommended_think_time_max?: number;
  improvement_needed?: string;
  current_users?: number;
  current_spawn_rate?: number;
  current_duration?: string;
  current_error_rate?: number;
  target_error_rate?: number;
  failed_requests?: number;
  total_requests?: number;
  current_p95?: number;
  target_p95?: number;
  current_p99?: number;
  target_p99?: number;
}

interface TestSuggestion {
  id: string;
  type: string;
  severity: 'critical' | 'warning' | 'good';
  title: string;
  description: string;
  reasoning: string;
  metrics: SuggestionMetrics;
}

interface APISuggestion {
  id: string;
  type: string;
  severity: 'critical' | 'warning' | 'good';
  category: string;
  title: string;
  description: string;
  high_level: string;
  technical: string;
  metrics: SuggestionMetrics;
}

interface AIAnalysis {
  test_id: string;
  performance_score: number;
  performance_level: 'critical' | 'warning' | 'good';
  test_suggestions: TestSuggestion[];
  api_suggestions: APISuggestion[];
  generated_at: string;
}

interface AISuggestionsPanelProps {
  testId: string;
  llmProvider: 'groq' | 'openai' | 'anthropic';
  onRetestWithSuggestion: (config: SuggestionMetrics) => void;
}

export const AISuggestionsPanel: React.FC<AISuggestionsPanelProps> = ({
  testId,
  llmProvider,
  onRetestWithSuggestion
}) => {
  const [analysis, setAnalysis] = useState<AIAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState({
    testSuggestions: true,
    apiSuggestions: true
  });

  // Track ongoing request to prevent duplicates
  const abortControllerRef = React.useRef<AbortController | null>(null);

  // Fetch analysis when testId or llmProvider changes
  useEffect(() => {
    // Cancel any ongoing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Create new AbortController for this request
    abortControllerRef.current = new AbortController();

    fetchAnalysis(abortControllerRef.current.signal);

    // Cleanup: abort request if component unmounts or deps change
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [testId, llmProvider]);

  const fetchAnalysis = async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/load-test/analysis/${testId}?llm_provider=${llmProvider}`,
        { signal }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to fetch analysis');
      }

      const data = await response.json();
      setAnalysis(data);
    } catch (err) {
      // Ignore abort errors (these are intentional cancellations)
      if (err instanceof Error && err.name === 'AbortError') {
        console.log('AI analysis request was cancelled');
        return;
      }

      console.error('Failed to fetch AI analysis:', err);
      setError(err instanceof Error ? err.message : 'Failed to load AI analysis');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className={styles.loadingContainer}>
        <div className={styles.spinner}></div>
        <p>🤖 AI is analyzing your test results...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.errorContainer}>
        <div className={styles.errorIcon}>⚠️</div>
        <h3>Failed to Generate AI Insights</h3>
        <p>{error}</p>
        <button
          className={styles.retryButton}
          onClick={() => {
            const controller = new AbortController();
            abortControllerRef.current = controller;
            fetchAnalysis(controller.signal);
          }}
        >
          Try Again
        </button>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className={styles.noDataContainer}>
        <p>No analysis data available</p>
      </div>
    );
  }

  const toggleSection = (section: 'testSuggestions' | 'apiSuggestions') => {
    setExpanded(prev => ({ ...prev, [section]: !prev[section] }));
  };

  return (
    <div className={styles.aiSuggestionsPanel}>
      {/* Performance Score */}
      <PerformanceScore
        score={analysis.performance_score}
        level={analysis.performance_level}
        testId={testId}
      />

      {/* Test Optimization Suggestions */}
      {analysis.test_suggestions.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader} onClick={() => toggleSection('testSuggestions')}>
            <h2>
              <span className={styles.sectionIcon}>🎯</span>
              Test Optimization Suggestions
              <span className={styles.badge}>{analysis.test_suggestions.length}</span>
            </h2>
            <span className={styles.toggleIcon}>
              {expanded.testSuggestions ? '▼' : '▶'}
            </span>
          </div>

          {expanded.testSuggestions && (
            <div className={styles.sectionContent}>
              {analysis.test_suggestions.map(suggestion => (
                <SuggestionCard
                  key={suggestion.id}
                  suggestion={suggestion}
                  type="test"
                  onApply={onRetestWithSuggestion}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* API Performance Suggestions */}
      {analysis.api_suggestions.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader} onClick={() => toggleSection('apiSuggestions')}>
            <h2>
              <span className={styles.sectionIcon}>⚡</span>
              API Performance Suggestions
              <span className={styles.badge}>{analysis.api_suggestions.length}</span>
            </h2>
            <span className={styles.toggleIcon}>
              {expanded.apiSuggestions ? '▼' : '▶'}
            </span>
          </div>

          {expanded.apiSuggestions && (
            <div className={styles.sectionContent}>
              {analysis.api_suggestions.map(suggestion => (
                <SuggestionCard
                  key={suggestion.id}
                  suggestion={suggestion}
                  type="api"
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* No Suggestions */}
      {analysis.test_suggestions.length === 0 && analysis.api_suggestions.length === 0 && (
        <div className={styles.noSuggestions}>
          <p>✨ Great! No critical issues found. Your API is performing well.</p>
        </div>
      )}
    </div>
  );
};
