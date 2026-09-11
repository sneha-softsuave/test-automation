import { useEffect, useCallback } from 'react';
import { useStore } from '../store/useStore';

export const usePeriodicHealthCheck = () => {
  const {
    healthCheckEnabled,
    healthCheckInterval,
    setLastHealthCheck
  } = useStore();

  const performHealthCheck = useCallback(async () => {
    if (!healthCheckEnabled) return;

    try {
      const response = await fetch('/api/v1/ai-providers/validate', {
        method: 'POST'
      });

      if (response.ok) {
        setLastHealthCheck(new Date());
        console.log('Periodic health check completed');
      }
    } catch (error) {
      console.error('Periodic health check failed:', error);
    }
  }, [healthCheckEnabled, setLastHealthCheck]);

  useEffect(() => {
    if (!healthCheckEnabled) return;

    // Initial check on mount
    performHealthCheck();

    // Schedule periodic checks
    const intervalMs = healthCheckInterval * 60 * 1000;  // Convert minutes to ms
    const interval = setInterval(performHealthCheck, intervalMs);

    return () => clearInterval(interval);
  }, [healthCheckEnabled, healthCheckInterval, performHealthCheck]);
};
