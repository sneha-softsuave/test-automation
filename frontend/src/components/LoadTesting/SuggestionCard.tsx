import React, { useState } from 'react';
import styles from './SuggestionCard.module.css';

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

interface SuggestionCardProps {
  suggestion: TestSuggestion | APISuggestion;
  type: 'test' | 'api';
  onApply?: (metrics: SuggestionMetrics) => void;
}

export const SuggestionCard: React.FC<SuggestionCardProps> = ({
  suggestion,
  type,
  onApply
}) => {
  const [showTechnical, setShowTechnical] = useState(false);

  const severityConfig = {
    critical: { icon: '🔴', color: '#ef4444', label: 'Critical' },
    warning: { icon: '🟡', color: '#f59e0b', label: 'Warning' },
    good: { icon: '🟢', color: '#10b981', label: 'Good' }
  };

  const config = severityConfig[suggestion.severity];

  const formatLabel = (key: string): string => {
    return key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, l => l.toUpperCase());
  };

  const renderMetrics = () => {
    if (!suggestion.metrics || Object.keys(suggestion.metrics).length === 0) {
      return null;
    }

    return (
      <div className={styles.metrics}>
        {Object.entries(suggestion.metrics).map(([key, value]) => {
          if (value === null || value === undefined) return null;
          return (
            <div key={key} className={styles.metric}>
              <span className={styles.metricLabel}>{formatLabel(key)}:</span>
              <span className={styles.metricValue}>{value}</span>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className={styles.suggestionCard} style={{ borderLeft: `4px solid ${config.color}` }}>
      {/* Header */}
      <div className={styles.header}>
        <span className={styles.severityBadge} style={{ backgroundColor: config.color }}>
          {config.icon} {config.label}
        </span>
        {type === 'api' && 'category' in suggestion && (
          <span className={styles.categoryBadge}>
            {suggestion.category.replace(/_/g, ' ')}
          </span>
        )}
      </div>

      {/* Title & Description */}
      <h4 className={styles.title}>{suggestion.title}</h4>
      <p className={styles.description}>{suggestion.description}</p>

      {/* Metrics */}
      {renderMetrics()}

      {/* Technical Details (for API suggestions) */}
      {type === 'api' && 'high_level' in suggestion && (
        <div className={styles.technicalSection}>
          <div className={styles.highLevel}>
            <strong>💡 Recommendation:</strong> {suggestion.high_level}
          </div>

          <button
            className={styles.toggleTechnical}
            onClick={() => setShowTechnical(!showTechnical)}
          >
            {showTechnical ? '▼' : '▶'} Technical Details
          </button>

          {showTechnical && (
            <div className={styles.technical}>
              <strong>🔧 Technical Implementation:</strong>
              <pre>{suggestion.technical}</pre>
            </div>
          )}
        </div>
      )}

      {/* Reasoning (for test suggestions) */}
      {type === 'test' && 'reasoning' in suggestion && (
        <div className={styles.reasoning}>
          <strong>📝 Reasoning:</strong> {suggestion.reasoning}
        </div>
      )}

      {/* Action Button (for test suggestions) */}
      {type === 'test' && onApply && (
        <button
          className={styles.applyButton}
          onClick={() => onApply(suggestion.metrics)}
        >
          🚀 Test Again with This Suggestion
        </button>
      )}
    </div>
  );
};
