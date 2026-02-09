import React, { useMemo, useRef } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import type { ChartOptions } from 'chart.js';
import { Line } from 'react-chartjs-2';
import zoomPlugin from 'chartjs-plugin-zoom';
import styles from './LiveCharts.module.css';
import { ZoomIn, ZoomOut, RotateCcw } from 'lucide-react';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  zoomPlugin
);

export interface MetricsHistoryPoint {
  timestamp: string;
  requests_per_second: number;
  failures_per_second: number;
  median_response_time: number;
  percentile_95: number;
  current_users: number;
}

interface LiveChartsProps {
  metricsHistory: MetricsHistoryPoint[];
}

export const LiveCharts: React.FC<LiveChartsProps> = ({ metricsHistory }) => {
  // Refs for chart instances to control zoom
  const rpsChartRef = useRef<ChartJS<'line'>>(null);
  const responseTimeChartRef = useRef<ChartJS<'line'>>(null);
  const usersChartRef = useRef<ChartJS<'line'>>(null);

  // Extract timestamps for x-axis
  const timestamps = useMemo(
    () => metricsHistory.map((m) => new Date(m.timestamp).toLocaleTimeString()),
    [metricsHistory]
  );

  // Chart 1: Total Requests per Second
  const rpsChartData = useMemo(
    () => ({
      labels: timestamps,
      datasets: [
        {
          label: 'RPS',
          data: metricsHistory.map((m) => m.requests_per_second),
          borderColor: 'rgb(34, 197, 94)',
          backgroundColor: 'rgba(34, 197, 94, 0.1)',
          tension: 0.4,
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
        },
        {
          label: 'Failures/s',
          data: metricsHistory.map((m) => m.failures_per_second),
          borderColor: 'rgb(239, 68, 68)',
          backgroundColor: 'rgba(239, 68, 68, 0.1)',
          tension: 0.4,
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
        },
      ],
    }),
    [metricsHistory, timestamps]
  );

  // Chart 2: Response Times
  const responseTimeChartData = useMemo(
    () => ({
      labels: timestamps,
      datasets: [
        {
          label: '50th Percentile',
          data: metricsHistory.map((m) => m.median_response_time),
          borderColor: 'rgb(249, 115, 22)',
          backgroundColor: 'rgba(249, 115, 22, 0.1)',
          tension: 0.4,
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
        },
        {
          label: '95th Percentile',
          data: metricsHistory.map((m) => m.percentile_95),
          borderColor: 'rgb(168, 85, 247)',
          backgroundColor: 'rgba(168, 85, 247, 0.1)',
          tension: 0.4,
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
        },
      ],
    }),
    [metricsHistory, timestamps]
  );

  // Chart 3: Number of Users
  const usersChartData = useMemo(
    () => ({
      labels: timestamps,
      datasets: [
        {
          label: 'Users',
          data: metricsHistory.map((m) => m.current_users),
          borderColor: 'rgb(59, 130, 246)',
          backgroundColor: 'rgba(59, 130, 246, 0.1)',
          tension: 0.4,
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
          fill: true,
        },
      ],
    }),
    [metricsHistory, timestamps]
  );

  // Zoom/pan handlers
  const handleZoomIn = () => {
    rpsChartRef.current?.zoom(1.1);
    responseTimeChartRef.current?.zoom(1.1);
    usersChartRef.current?.zoom(1.1);
  };

  const handleZoomOut = () => {
    rpsChartRef.current?.zoom(0.9);
    responseTimeChartRef.current?.zoom(0.9);
    usersChartRef.current?.zoom(0.9);
  };

  const handleResetZoom = () => {
    rpsChartRef.current?.resetZoom();
    responseTimeChartRef.current?.resetZoom();
    usersChartRef.current?.resetZoom();
  };

  // Common chart options
  const commonOptions: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top' as const,
        labels: {
          usePointStyle: true,
          padding: 15,
          font: {
            size: 12,
          },
        },
      },
      tooltip: {
        mode: 'index',
        intersect: false,
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        padding: 12,
        titleFont: {
          size: 13,
        },
        bodyFont: {
          size: 12,
        },
      },
      zoom: {
        pan: {
          enabled: true,
          mode: 'x',
        },
        zoom: {
          wheel: {
            enabled: true,
          },
          pinch: {
            enabled: true,
          },
          mode: 'x',
        },
      },
    },
    scales: {
      x: {
        grid: {
          display: true,
          color: 'rgba(255, 255, 255, 0.05)',
        },
        ticks: {
          maxTicksLimit: 10,
          font: {
            size: 11,
          },
        },
      },
      y: {
        beginAtZero: true,
        grid: {
          display: true,
          color: 'rgba(255, 255, 255, 0.05)',
        },
        ticks: {
          font: {
            size: 11,
          },
        },
      },
    },
    interaction: {
      mode: 'nearest',
      axis: 'x',
      intersect: false,
    },
  };

  if (metricsHistory.length === 0) {
    return (
      <div className={styles.emptyState}>
        <p>No metrics data available yet. Start a load test to see real-time charts.</p>
      </div>
    );
  }

  return (
    <div className={styles.chartsContainer}>
      <div className={styles.zoomControls}>
        <button onClick={handleZoomIn} className={styles.zoomButton} title="Zoom In">
          <ZoomIn size={18} />
        </button>
        <button onClick={handleZoomOut} className={styles.zoomButton} title="Zoom Out">
          <ZoomOut size={18} />
        </button>
        <button onClick={handleResetZoom} className={styles.zoomButton} title="Reset Zoom">
          <RotateCcw size={18} />
        </button>
        <span className={styles.zoomHint}>Scroll wheel to zoom • Drag to pan</span>
      </div>

      <div className={styles.chartCard}>
        <h3>Total Requests per Second</h3>
        <div className={styles.chartWrapper}>
          <Line ref={rpsChartRef} data={rpsChartData} options={commonOptions} />
        </div>
      </div>

      <div className={styles.chartCard}>
        <h3>Response Times (ms)</h3>
        <div className={styles.chartWrapper}>
          <Line ref={responseTimeChartRef} data={responseTimeChartData} options={commonOptions} />
        </div>
      </div>

      <div className={styles.chartCard}>
        <h3>Number of Users</h3>
        <div className={styles.chartWrapper}>
          <Line ref={usersChartRef} data={usersChartData} options={commonOptions} />
        </div>
      </div>
    </div>
  );
};
