import React, { useState, useEffect } from 'react';
import { FileText, AlertCircle, RefreshCw } from 'lucide-react';
import { useStore } from '../../store/useStore';
import styles from './LoadTestReports.module.css';

const API_BASE_URL = '';

interface ReportInfo {
  filename: string;
  test_id: string;
  type: 'manual' | 'sequential';
  timestamp: string;
  api_name?: string;
}

export const LoadTestReports: React.FC = () => {
  const { setCurrentView, addNotification } = useStore();
  const [currentReport, setCurrentReport] = useState<ReportInfo | null>(null);
  const [reportHtml, setReportHtml] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const fetchCurrentReport = async (clearCache = false) => {
    setLoading(true);
    setError(null);

    try {
      // Add cache-busting query parameter to force reload
      const timestamp = Date.now();
      const cacheParam = clearCache ? `?_=${timestamp}` : '';

      const response = await fetch(`${API_BASE_URL}/api/v1/load-test/current-report${cacheParam}`, {
        cache: clearCache ? 'no-cache' : 'default',
        headers: clearCache ? {
          'Cache-Control': 'no-cache',
          'Pragma': 'no-cache'
        } : {}
      });

      if (!response.ok) {
        if (response.status === 404) {
          setCurrentReport(null);
          setReportHtml('');
          setError('No test report available. Complete a load test to generate a report.');
          return;
        }
        throw new Error('Failed to fetch current report');
      }

      const data = await response.json();
      setCurrentReport(data);

      // Fetch the HTML content with cache busting
      const htmlResponse = await fetch(`${API_BASE_URL}/api/v1/load-test/report/${data.filename}${cacheParam}`, {
        cache: clearCache ? 'no-cache' : 'default',
        headers: clearCache ? {
          'Cache-Control': 'no-cache',
          'Pragma': 'no-cache'
        } : {}
      });

      if (!htmlResponse.ok) {
        throw new Error('Failed to fetch report HTML');
      }

      const html = await htmlResponse.text();
      setReportHtml(html);
    } catch (err) {
      console.error('Error fetching report:', err);
      setError(err instanceof Error ? err.message : 'Failed to load report');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCurrentReport();
  }, []);

  const handleRefresh = () => {
    // Clear all report state
    setRefreshKey(prev => prev + 1);
    setReportHtml('');
    setCurrentReport(null);
    setError('No test report available. Complete a load test to generate a report.');
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.titleSection}>
          <FileText size={32} className={styles.icon} />
          <div>
            <h1>Load Test Reports</h1>
            <p>View the current test report</p>
          </div>
        </div>
        <button
          className={styles.refreshButton}
          onClick={handleRefresh}
          disabled={loading}
          title="Refresh Report"
        >
          <RefreshCw size={18} className={loading ? styles.spinning : ''} />
        </button>
      </div>

      {loading && !reportHtml && (
        <div className={styles.loadingState}>
          <RefreshCw size={48} className={styles.spinning} />
          <p>Loading report...</p>
        </div>
      )}

      {error && !currentReport && (
        <div className={styles.emptyState}>
          <AlertCircle size={64} />
          <h2>No Report Available</h2>
          <p>{error}</p>
          <div className={styles.emptyHint}>
            <p>💡 <strong>Tip:</strong> Run a load test from the Agent section to generate a report</p>
          </div>
        </div>
      )}

      {currentReport && (
        <div className={styles.reportInfo}>
          <div className={styles.infoCard}>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Report Type:</span>
              <span className={styles.infoBadge}>
                {currentReport.type === 'sequential' ? '🔄 Sequential Test' : '⚡ Manual Test'}
              </span>
            </div>
            {currentReport.api_name && (
              <div className={styles.infoItem}>
                <span className={styles.infoLabel}>API:</span>
                <span className={styles.infoValue}>{currentReport.api_name}</span>
              </div>
            )}
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Generated:</span>
              <span className={styles.infoValue}>{new Date(currentReport.timestamp).toLocaleString()}</span>
            </div>
          </div>
        </div>
      )}

      {reportHtml && (
        <div className={styles.reportContent}>
          <iframe
            key={refreshKey}
            srcDoc={reportHtml}
            className={styles.reportFrame}
            title="Load Test Report"
            sandbox="allow-same-origin allow-scripts allow-downloads allow-popups allow-popups-to-escape-sandbox"
          />
        </div>
      )}
    </div>
  );
};
