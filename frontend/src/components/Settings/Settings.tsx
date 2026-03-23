import React, { useState, useEffect } from 'react';
import { useStore } from '../../store/useStore';
import {
  Settings as SettingsIcon,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Check,
  X,
  Zap,
  Activity,
  Clock,
  AlertCircle,
  CheckCircle2,
  Home,
  Navigation,
  Monitor,
  Eye,
  EyeOff
} from 'lucide-react';
import styles from './Settings.module.css';
import { fetchTokenUsage, resetTokenUsage, type TokenUsageStats } from '../../services/api';

interface AIProvider {
  id: string;
  display_name: string;
  model: string;
  api_key_configured: boolean;
  is_default: boolean;
  available?: boolean;
  latency_ms?: number;
  error?: string;
}

export const Settings: React.FC = () => {
  // Get all store functions and values with defaults
  const healthCheckEnabled = useStore((state) => state.healthCheckEnabled ?? true);
  const setHealthCheckEnabled = useStore((state) => state.setHealthCheckEnabled);
  const healthCheckInterval = useStore((state) => state.healthCheckInterval ?? 120);
  const setHealthCheckInterval = useStore((state) => state.setHealthCheckInterval);
  const lastHealthCheck = useStore((state) => state.lastHealthCheck);
  const setLastHealthCheck = useStore((state) => state.setLastHealthCheck);

  // Application settings
  const useDefaultLandingPage = useStore((state) => state.useDefaultLandingPage ?? false);
  const setUseDefaultLandingPage = useStore((state) => state.setUseDefaultLandingPage);
  const defaultLandingPage = useStore((state) => state.defaultLandingPage ?? 'upload');
  const setDefaultLandingPage = useStore((state) => state.setDefaultLandingPage);

  // Browser behaviour settings
  const keepBrowserOpenAgent = useStore((state) => state.keepBrowserOpenAgent ?? false);
  const setKeepBrowserOpenAgent = useStore((state) => state.setKeepBrowserOpenAgent);

  // Image Analysis settings
  const imageAnalysisEnabled = useStore((state) => state.imageAnalysisEnabled ?? false);
  const setImageAnalysisEnabled = useStore((state) => state.setImageAnalysisEnabled);
  const [imageAnalysisExpanded, setImageAnalysisExpanded] = useState(false);
  const [visionModel, setVisionModel] = useState<string>('');
  const [visionKeyConfigured, setVisionKeyConfigured] = useState<boolean>(false);
  const [openaiKeyConfigured, setOpenaiKeyConfigured] = useState<boolean>(false);
  const [usageToday, setUsageToday] = useState<number>(0);
  const [usageDate, setUsageDate] = useState<string>('');
  const [visionProvider, setVisionProvider] = useState<string>('groq');
  const [visionModels, setVisionModels] = useState<{ groq: string; openai: string }>({ groq: '', openai: '' });
  const [settingVisionProvider, setSettingVisionProvider] = useState(false);

  // Token usage tracking
  const [tokenStats, setTokenStats] = useState<TokenUsageStats | null>(null);
  const [tokenLoading, setTokenLoading] = useState(false);
  const [tokenExpanded, setTokenExpanded] = useState(false);

  const [aiModelsExpanded, setAiModelsExpanded] = useState(false);
  const [appSettingsExpanded, setAppSettingsExpanded] = useState(false);
  const [intervalConfigExpanded, setIntervalConfigExpanded] = useState(false);
  const [landingPageExpanded, setLandingPageExpanded] = useState(false);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [isChecking, setIsChecking] = useState(false);
  const [customInterval, setCustomInterval] = useState(healthCheckInterval);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Update customInterval when healthCheckInterval changes
  useEffect(() => {
    setCustomInterval(healthCheckInterval);
  }, [healthCheckInterval]);

  const fetchImageAnalysisStatus = () => {
    fetch('/api/v1/image-analysis/status')
      .then(r => r.json())
      .then(data => {
        setVisionModel(data.model || '');
        setVisionKeyConfigured(data.vision_key_configured ?? false);
        setOpenaiKeyConfigured(data.openai_key_configured ?? false);
        setUsageToday(data.usage_today ?? 0);
        setUsageDate(data.usage_date || '');
        setVisionProvider(data.vision_provider || 'groq');
        if (data.models) setVisionModels(data.models);
        // Sync server-side enabled state into store on first load
        if (data.enabled !== imageAnalysisEnabled) {
          setImageAnalysisEnabled(data.enabled);
        }
      })
      .catch(() => { /* ignore */ });
  };

  const handleVisionProviderChange = async (provider: string) => {
    setSettingVisionProvider(true);
    try {
      const res = await fetch('/api/v1/image-analysis/set-vision-provider', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider }),
      });
      if (res.ok) {
        setVisionProvider(provider);
        setVisionModel(provider === 'groq' ? visionModels.groq : visionModels.openai);
      }
    } catch { /* ignore */ } finally {
      setSettingVisionProvider(false);
    }
  };

  // Fetch provider configuration + image analysis status on mount
  useEffect(() => {
    console.log('Settings component mounted');
    fetchProviders();
    fetchImageAnalysisStatus();

    // Poll usage count every 30 seconds so count stays fresh without refresh
    const interval = setInterval(fetchImageAnalysisStatus, 30_000);

    // Poll token usage every 30 seconds
    const fetchTokenStats = () => {
      fetchTokenUsage().then(setTokenStats).catch(() => {});
    };
    fetchTokenStats();
    const tokenInterval = setInterval(fetchTokenStats, 30_000);

    return () => { clearInterval(interval); clearInterval(tokenInterval); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchProviders = async () => {
    try {
      setLoading(true);
      setError(null);
      console.log('Fetching providers from /api/v1/llm-providers...');

      const response = await fetch('/api/v1/llm-providers');

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      console.log('Providers fetched:', data);

      setProviders(data.providers || []);
    } catch (error) {
      console.error('Failed to fetch providers:', error);
      setError(error instanceof Error ? error.message : 'Failed to fetch providers');
    } finally {
      setLoading(false);
    }
  };

  const validateProviders = async () => {
    setIsChecking(true);
    setError(null);
    try {
      console.log('Validating providers...');
      const response = await fetch('/api/v1/ai-providers/validate', {
        method: 'POST'
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      console.log('Validation results:', data);

      // Update providers with availability status
      setProviders(prev => prev.map(p => ({
        ...p,
        available: data[p.id]?.available,
        latency_ms: data[p.id]?.latency_ms,
        error: data[p.id]?.error
      })));

      if (setLastHealthCheck) {
        setLastHealthCheck(new Date());
      }

      setSuccessMessage('Health check completed successfully');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (error) {
      console.error('Health check failed:', error);
      setError(error instanceof Error ? error.message : 'Health check failed');
    } finally {
      setIsChecking(false);
    }
  };

  const handleIntervalSave = () => {
    if (setHealthCheckInterval) {
      setHealthCheckInterval(customInterval);
      setSuccessMessage(`Check interval updated to ${customInterval} minutes`);
      setTimeout(() => setSuccessMessage(null), 3000);
    }
  };

  const getProviderStatusIcon = (provider: AIProvider) => {
    if (provider.available === true) {
      return <CheckCircle2 size={20} className={styles.statusIconSuccess} />;
    } else if (provider.available === false) {
      return <AlertCircle size={20} className={styles.statusIconError} />;
    }
    return <Activity size={20} className={styles.statusIconUnknown} />;
  };

  const getProviderStatusText = (provider: AIProvider) => {
    if (provider.available === true) return 'Available';
    if (provider.available === false) return 'Unavailable';
    return 'Not Checked';
  };

  const getProviderStatusClass = (provider: AIProvider) => {
    if (provider.available === true) return styles.statusSuccess;
    if (provider.available === false) return styles.statusError;
    return styles.statusUnknown;
  };

  return (
    <div className={styles.container}>
      {/* Header Section */}
      <div className={styles.header}>
        <div className={styles.titleSection}>
          <SettingsIcon size={32} className={styles.icon} />
          <div>
            <h1>Settings</h1>
            <p>Manage application configuration and monitor AI providers</p>
          </div>
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className={styles.messageError}>
          <AlertCircle size={20} />
          <span>{error}</span>
          <button className={styles.messageDismiss} onClick={() => setError(null)}>
            <X size={16} />
          </button>
        </div>
      )}

      {successMessage && (
        <div className={styles.messageSuccess}>
          <CheckCircle2 size={20} />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className={styles.loadingContainer}>
          <RefreshCw className={styles.loadingSpinner} size={48} />
          <p className={styles.loadingText}>Loading configuration...</p>
        </div>
      )}

      {/* AI Models Section */}
      {!loading && (
        <div className={styles.section} data-section="ai">
          <div
            className={styles.sectionHeader}
            onClick={() => setAiModelsExpanded(!aiModelsExpanded)}
          >
            <div className={styles.sectionHeaderLeft}>
              <div className={styles.expandIcon}>
                {aiModelsExpanded ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
              </div>
              <Zap size={20} className={styles.sectionIcon} />
              <span className={styles.sectionTitle}>AI Model Providers</span>
              <span className={styles.providerCount}>{providers.length}</span>
            </div>
          </div>

          {aiModelsExpanded && (
            <div className={styles.sectionContent}>
              {/* Health Check Controls */}
              <div className={styles.controlPanel}>
                <div className={styles.controlPanelHeader}>
                  <Activity size={18} />
                  <h3>Health Check Configuration</h3>
                </div>

                <div className={styles.controlGrid}>
                  {/* Automatic Health Checks Toggle */}
                  <div className={styles.controlItem}>
                    <label className={styles.toggleLabel}>
                      <input
                        type="checkbox"
                        checked={healthCheckEnabled}
                        onChange={(e) => setHealthCheckEnabled && setHealthCheckEnabled(e.target.checked)}
                        className={styles.toggleInput}
                      />
                      <span className={styles.toggleSwitch}></span>
                      <span className={styles.toggleText}>
                        <strong>Automatic Health Checks</strong>
                        <small>Periodically validate AI provider availability</small>
                      </span>
                    </label>
                  </div>

                  {/* Check Interval - Expandable Section */}
                  <div className={styles.expandableSection}>
                    <div
                      className={styles.expandableHeader}
                      onClick={() => setIntervalConfigExpanded(!intervalConfigExpanded)}
                    >
                      <div className={styles.expandableTitle}>
                        {intervalConfigExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        <Clock size={16} />
                        <span>Check Interval</span>
                      </div>
                      <span className={styles.currentValue}>{customInterval} minutes</span>
                    </div>

                    {intervalConfigExpanded && (
                      <div className={styles.expandableContent}>
                        <div className={styles.inputGroup}>
                          <input
                            type="number"
                            min="5"
                            max="1440"
                            value={customInterval}
                            onChange={(e) => setCustomInterval(Number(e.target.value))}
                            disabled={!healthCheckEnabled}
                            className={styles.numberInput}
                          />
                          <span className={styles.inputUnit}>minutes</span>
                          <button
                            onClick={handleIntervalSave}
                            disabled={!healthCheckEnabled}
                            className={styles.saveButton}
                          >
                            Save
                          </button>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Run Health Check Button */}
                  <div className={styles.controlItem}>
                    <button
                      className={styles.checkButton}
                      onClick={validateProviders}
                      disabled={isChecking}
                    >
                      <RefreshCw className={isChecking ? styles.spinning : ''} size={18} />
                      <span>{isChecking ? 'Checking...' : 'Run Health Check'}</span>
                    </button>
                    {lastHealthCheck && (
                      <div className={styles.lastCheckInfo}>
                        <Clock size={14} />
                        <span>Last check: {new Date(lastHealthCheck).toLocaleString()}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Provider Cards */}
              {providers.length === 0 ? (
                <div className={styles.emptyState}>
                  <AlertCircle size={48} />
                  <h3>No Providers Configured</h3>
                  <p>Configure AI providers in your environment settings</p>
                </div>
              ) : (
                <div className={styles.providerGrid}>
                  {providers.map(provider => (
                    <div
                      key={provider.id}
                      className={`${styles.providerCard} ${getProviderStatusClass(provider)}`}
                    >
                      <div className={styles.providerCardHeader}>
                        <div className={styles.providerInfo}>
                          {getProviderStatusIcon(provider)}
                          <div>
                            <h3 className={styles.providerName}>{provider.display_name}</h3>
                            <span className={styles.providerStatus}>
                              {getProviderStatusText(provider)}
                            </span>
                          </div>
                        </div>
                        {provider.is_default && (
                          <div className={styles.defaultBadge}>
                            <Zap size={12} />
                            <span>Default</span>
                          </div>
                        )}
                      </div>

                      <div className={styles.providerDetails}>
                        <div className={styles.detailRow}>
                          <span className={styles.detailLabel}>Model</span>
                          <span className={styles.detailValue}>{provider.model}</span>
                        </div>

                        <div className={styles.detailRow}>
                          <span className={styles.detailLabel}>API Key</span>
                          <span className={styles.detailValue}>
                            {provider.api_key_configured ? (
                              <span className={styles.configured}>
                                <Check size={14} /> Configured
                              </span>
                            ) : (
                              <span className={styles.notConfigured}>
                                <X size={14} /> Not configured
                              </span>
                            )}
                          </span>
                        </div>

                        {provider.available === true && provider.latency_ms && (
                          <div className={styles.detailRow}>
                            <span className={styles.detailLabel}>Response Time</span>
                            <span className={styles.latencyValue}>
                              <Activity size={14} />
                              {provider.latency_ms.toFixed(0)}ms
                            </span>
                          </div>
                        )}

                        {provider.error && (
                          <div className={styles.errorMessage}>
                            <AlertCircle size={14} />
                            <span>{provider.error}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Application Settings Section */}
      {!loading && (
        <div className={styles.section} data-section="app">
          <div
            className={styles.sectionHeader}
            onClick={() => setAppSettingsExpanded(!appSettingsExpanded)}
          >
            <div className={styles.sectionHeaderLeft}>
              <div className={styles.expandIcon}>
                {appSettingsExpanded ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
              </div>
              <SettingsIcon size={20} className={styles.sectionIcon} />
              <span className={styles.sectionTitle}>Application Settings</span>
            </div>
          </div>

          {appSettingsExpanded && (
            <div className={styles.sectionContent}>
              {/* Default Landing Page Section */}
              <div className={styles.nestedSection}>
                <div
                  className={styles.nestedSectionHeader}
                  onClick={() => {
                    if (useDefaultLandingPage) {
                      setLandingPageExpanded(!landingPageExpanded);
                    }
                  }}
                  style={{ cursor: useDefaultLandingPage ? 'pointer' : 'default' }}
                >
                  <div className={styles.nestedSectionLeft}>
                    {useDefaultLandingPage && (
                      <div className={styles.expandIcon}>
                        {landingPageExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                      </div>
                    )}
                    <Home size={18} className={styles.nestedSectionIcon} />
                    <span className={styles.nestedSectionTitle}>Default Landing Page</span>
                  </div>

                  {/* Toggle on the right side */}
                  <label className={styles.inlineToggleLabel} onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={useDefaultLandingPage}
                      onChange={(e) => {
                        setUseDefaultLandingPage && setUseDefaultLandingPage(e.target.checked);
                        // If turning ON, expand immediately
                        if (e.target.checked) {
                          setLandingPageExpanded(true);
                        } else {
                          // If turning OFF, collapse
                          setLandingPageExpanded(false);
                        }
                      }}
                      className={styles.toggleInput}
                    />
                    <span className={styles.toggleSwitch}></span>
                  </label>
                </div>

                {/* Dropdown appears only when toggle is ON AND section is expanded */}
                {useDefaultLandingPage && landingPageExpanded && (
                  <div className={styles.nestedSectionContent}>
                    <div className={styles.dropdownGroup}>
                      <label className={styles.dropdownLabel}>
                        Select Landing Page
                      </label>
                      <select
                        value={defaultLandingPage}
                        onChange={(e) => setDefaultLandingPage && setDefaultLandingPage(e.target.value as 'upload' | 'loadtest')}
                        className={styles.dropdown}
                      >
                        <option value="upload">Functional Test</option>
                        <option value="loadtest">Load Test</option>
                      </select>
                      <p className={styles.dropdownHint}>
                        This page will open automatically when you launch the application
                      </p>
                    </div>
                  </div>
                )}
              </div>

              {/* Browser Behaviour Section */}
              <div className={styles.nestedSection}>
                <div className={styles.nestedSectionHeader} style={{ cursor: 'default' }}>
                  <div className={styles.nestedSectionLeft}>
                    <Monitor size={18} className={styles.nestedSectionIcon} />
                    <div>
                      <span className={styles.nestedSectionTitle}>Functional Test Agent — Browser</span>
                      <p style={{ margin: '2px 0 0', fontSize: '0.78rem', color: '#6b7280' }}>
                        {keepBrowserOpenAgent
                          ? 'Browser stays open across all test cases (current session)'
                          : 'Browser closes and reopens between each test case'}
                      </p>
                    </div>
                  </div>
                  <label className={styles.inlineToggleLabel} onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={keepBrowserOpenAgent}
                      onChange={(e) => setKeepBrowserOpenAgent(e.target.checked)}
                      className={styles.toggleInput}
                    />
                    <span className={styles.toggleSwitch}></span>
                  </label>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Image Analysis Section */}
      {!loading && (
        <div className={styles.section} data-section="vision">
          <div
            className={styles.sectionHeader}
            onClick={() => setImageAnalysisExpanded(!imageAnalysisExpanded)}
          >
            <div className={styles.sectionHeaderLeft}>
              <div className={styles.expandIcon}>
                {imageAnalysisExpanded ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
              </div>
              <Eye size={20} className={styles.sectionIcon} />
              <span className={styles.sectionTitle}>Image Analysis (Vision)</span>
              {/* Active / Inactive badge */}
              <span
                style={{
                  marginLeft: 10,
                  padding: '2px 10px',
                  borderRadius: 20,
                  fontSize: '0.72rem',
                  fontWeight: 600,
                  background: imageAnalysisEnabled ? '#dcfce7' : '#f3f4f6',
                  color: imageAnalysisEnabled ? '#15803d' : '#6b7280',
                  border: `1px solid ${imageAnalysisEnabled ? '#86efac' : '#d1d5db'}`,
                }}
              >
                {imageAnalysisEnabled ? 'Active' : 'Inactive'}
              </span>
            </div>
          </div>

          {imageAnalysisExpanded && (
            <div className={styles.sectionContent}>
              <div className={styles.nestedSection}>
                <div className={styles.nestedSectionHeader} style={{ cursor: 'default' }}>
                  <div className={styles.nestedSectionLeft}>
                    {imageAnalysisEnabled
                      ? <Eye size={18} className={styles.nestedSectionIcon} style={{ color: '#15803d' }} />
                      : <EyeOff size={18} className={styles.nestedSectionIcon} />
                    }
                    <div>
                      <span className={styles.nestedSectionTitle}>Vision-Assisted Selector Fallback</span>
                      <p style={{ margin: '2px 0 0', fontSize: '0.78rem', color: '#6b7280' }}>
                        When enabled, if an element cannot be found by DOM selectors during recording,
                        a screenshot is sent to the vision model for analysis.
                      </p>
                      {imageAnalysisEnabled && !(visionProvider === 'groq' ? visionKeyConfigured : openaiKeyConfigured) && (
                        <p style={{ margin: '4px 0 0', fontSize: '0.72rem', color: '#dc2626', fontWeight: 600 }}>
                          Warning: Vision API key is not configured — image analysis will not work.
                        </p>
                      )}
                    </div>
                  </div>
                  <label className={styles.inlineToggleLabel} onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={imageAnalysisEnabled}
                      onChange={(e) => setImageAnalysisEnabled(e.target.checked)}
                      className={styles.toggleInput}
                    />
                    <span className={styles.toggleSwitch}></span>
                  </label>
                </div>
              </div>

              {/* Vision Model Selection */}
              <div style={{ margin: '8px 0 0' }}>
                <div style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151', marginBottom: 8 }}>
                  Vision Model
                </div>
                <div style={{ display: 'flex', gap: 10 }}>
                  {/* Groq card */}
                  <label
                    style={{
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 4,
                      padding: '10px 14px',
                      borderRadius: 8,
                      border: `2px solid ${visionProvider === 'groq' ? '#3b82f6' : '#e2e8f0'}`,
                      background: visionProvider === 'groq' ? '#eff6ff' : '#f8fafc',
                      cursor: settingVisionProvider ? 'wait' : 'pointer',
                      transition: 'border-color 0.15s, background 0.15s',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <input
                        type="radio"
                        name="visionProvider"
                        value="groq"
                        checked={visionProvider === 'groq'}
                        disabled={settingVisionProvider}
                        onChange={() => handleVisionProviderChange('groq')}
                        style={{ accentColor: '#3b82f6' }}
                      />
                      <span style={{ fontWeight: 600, fontSize: '0.82rem', color: '#1e293b' }}>Groq</span>
                      <span style={{
                        marginLeft: 'auto',
                        fontSize: '0.68rem',
                        padding: '1px 7px',
                        borderRadius: 10,
                        background: visionKeyConfigured ? '#dcfce7' : '#fee2e2',
                        color: visionKeyConfigured ? '#15803d' : '#dc2626',
                        fontWeight: 600,
                      }}>
                        {visionKeyConfigured ? 'Key OK' : 'No key'}
                      </span>
                    </div>
                    <span style={{ fontSize: '0.72rem', color: '#6b7280', paddingLeft: 20 }}>
                      {visionModels.groq || 'llama-4-scout-17b'}
                    </span>
                  </label>

                  {/* OpenAI card */}
                  <label
                    style={{
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 4,
                      padding: '10px 14px',
                      borderRadius: 8,
                      border: `2px solid ${visionProvider === 'openai' ? '#3b82f6' : '#e2e8f0'}`,
                      background: visionProvider === 'openai' ? '#eff6ff' : '#f8fafc',
                      cursor: settingVisionProvider ? 'wait' : 'pointer',
                      transition: 'border-color 0.15s, background 0.15s',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <input
                        type="radio"
                        name="visionProvider"
                        value="openai"
                        checked={visionProvider === 'openai'}
                        disabled={settingVisionProvider}
                        onChange={() => handleVisionProviderChange('openai')}
                        style={{ accentColor: '#3b82f6' }}
                      />
                      <span style={{ fontWeight: 600, fontSize: '0.82rem', color: '#1e293b' }}>OpenAI</span>
                      <span style={{
                        marginLeft: 'auto',
                        fontSize: '0.68rem',
                        padding: '1px 7px',
                        borderRadius: 10,
                        background: openaiKeyConfigured ? '#dcfce7' : '#fee2e2',
                        color: openaiKeyConfigured ? '#15803d' : '#dc2626',
                        fontWeight: 600,
                      }}>
                        {openaiKeyConfigured ? 'Key OK' : 'No key'}
                      </span>
                    </div>
                    <span style={{ fontSize: '0.72rem', color: '#6b7280', paddingLeft: 20 }}>
                      {visionModels.openai || 'gpt-4o-mini'}
                    </span>
                  </label>
                </div>
              </div>

              {/* Daily usage counter — always visible when section is expanded */}
              <div style={{
                margin: '8px 0 0',
                padding: '10px 16px',
                borderRadius: 8,
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
              }}>
                <Activity size={16} style={{ color: '#6b7280', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <span style={{ fontSize: '0.78rem', color: '#6b7280' }}>Vision model calls today</span>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 2 }}>
                    <span style={{
                      fontSize: '1.5rem',
                      fontWeight: 700,
                      color: usageToday === 0 ? '#94a3b8' : usageToday > 20 ? '#dc2626' : '#0f172a',
                      lineHeight: 1,
                    }}>
                      {usageToday}
                    </span>
                    <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                      {usageDate ? `on ${usageDate}` : ''}
                      {' · resets at midnight'}
                    </span>
                  </div>
                </div>
                <button
                  onClick={fetchImageAnalysisStatus}
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: '#94a3b8', padding: 4, borderRadius: 4,
                  }}
                  title="Refresh count"
                >
                  <RefreshCw size={14} />
                </button>
              </div>

              {imageAnalysisEnabled && (
                <div style={{
                  margin: '8px 0 0',
                  padding: '10px 14px',
                  borderRadius: 8,
                  background: '#fef9c3',
                  border: '1px solid #fde047',
                  fontSize: '0.8rem',
                  color: '#713f12',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 8,
                }}>
                  <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 1, color: '#b45309' }} />
                  <span>
                    <strong>Token usage notice:</strong> Image analysis sends screenshots to the {visionProvider === 'openai' ? 'OpenAI' : 'Groq'} vision model ({visionModel || (visionProvider === 'openai' ? 'gpt-4o-mini' : 'llama-4-scout-17b')}).
                    Each fallback invocation consumes tokens. Use this feature when DOM-based selectors consistently fail.
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Token Usage Section */}
      {!loading && (
        <div className={styles.section} data-section="token">
          <div
            className={styles.sectionHeader}
            onClick={() => setTokenExpanded(!tokenExpanded)}
          >
            <div className={styles.sectionHeaderLeft}>
              <div className={styles.expandIcon}>
                {tokenExpanded ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
              </div>
              <Activity size={20} className={styles.sectionIcon} />
              <span className={styles.sectionTitle}>Token Usage & Cost</span>
              {tokenStats && tokenStats.total_calls > 0 && (
                <span style={{
                  marginLeft: 10, padding: '2px 10px', borderRadius: 20,
                  fontSize: '0.72rem', fontWeight: 600,
                  background: '#dbeafe', color: '#1d4ed8',
                }}>
                  {tokenStats.total_calls} calls · ${tokenStats.total_cost_usd.toFixed(6)}
                </span>
              )}
            </div>
          </div>

          {tokenExpanded && (
            <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* Stat chips */}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {[
                  { label: 'Calls', value: tokenStats?.total_calls ?? 0 },
                  { label: 'Input Tokens', value: (tokenStats?.total_input_tokens ?? 0).toLocaleString() },
                  { label: 'Output Tokens', value: (tokenStats?.total_output_tokens ?? 0).toLocaleString() },
                  { label: 'Cost ($)', value: `$${(tokenStats?.total_cost_usd ?? 0).toFixed(6)}` },
                ].map(chip => (
                  <div key={chip.label} style={{
                    padding: '8px 14px', borderRadius: 8, background: '#f1f5f9',
                    border: '1px solid #e2e8f0', textAlign: 'center', minWidth: 100,
                  }}>
                    <div style={{ fontSize: '0.7rem', color: '#6b7280', marginBottom: 2 }}>{chip.label}</div>
                    <div style={{ fontSize: '1rem', fontWeight: 700, color: '#0f172a' }}>{chip.value}</div>
                  </div>
                ))}
              </div>

              {/* Per-provider table */}
              {tokenStats && Object.keys(tokenStats.by_provider).length > 0 && (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead>
                      <tr style={{ background: '#f8fafc' }}>
                        {['Provider', 'Calls', 'Input', 'Output', 'Total', 'Cost'].map(h => (
                          <th key={h} style={{ padding: '6px 10px', textAlign: 'left', borderBottom: '1px solid #e2e8f0', color: '#6b7280', fontWeight: 600 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(tokenStats.by_provider).map(([prov, s]) => (
                        <tr key={prov} style={{ borderBottom: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '6px 10px', fontWeight: 600 }}>{prov}</td>
                          <td style={{ padding: '6px 10px' }}>{s.calls}</td>
                          <td style={{ padding: '6px 10px' }}>{s.input_tokens.toLocaleString()}</td>
                          <td style={{ padding: '6px 10px' }}>{s.output_tokens.toLocaleString()}</td>
                          <td style={{ padding: '6px 10px' }}>{s.total_tokens.toLocaleString()}</td>
                          <td style={{ padding: '6px 10px' }}>${s.cost_usd.toFixed(6)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Recent calls table */}
              {tokenStats && tokenStats.recent_calls.length > 0 && (
                <div style={{ overflowX: 'auto' }}>
                  <div style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151', marginBottom: 6 }}>Recent Calls</div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}>
                    <thead>
                      <tr style={{ background: '#f8fafc' }}>
                        {['Time', 'Agent', 'Provider', 'In', 'Out', 'Cost'].map(h => (
                          <th key={h} style={{ padding: '5px 8px', textAlign: 'left', borderBottom: '1px solid #e2e8f0', color: '#6b7280', fontWeight: 600 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {tokenStats.recent_calls.map((r, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '5px 8px', color: '#6b7280' }}>{new Date(r.timestamp).toLocaleTimeString()}</td>
                          <td style={{ padding: '5px 8px' }}>{r.agent}</td>
                          <td style={{ padding: '5px 8px' }}>{r.provider}</td>
                          <td style={{ padding: '5px 8px' }}>{r.input_tokens.toLocaleString()}</td>
                          <td style={{ padding: '5px 8px' }}>{r.output_tokens.toLocaleString()}</td>
                          <td style={{ padding: '5px 8px' }}>${r.cost_usd.toFixed(6)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Action buttons */}
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => { setTokenLoading(true); fetchTokenUsage().then(setTokenStats).catch(() => {}).finally(() => setTokenLoading(false)); }}
                  disabled={tokenLoading}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '6px 14px', borderRadius: 6, border: '1px solid #e2e8f0',
                    background: '#f8fafc', cursor: tokenLoading ? 'not-allowed' : 'pointer',
                    fontSize: '0.8rem', color: '#374151',
                  }}
                >
                  <RefreshCw size={13} /> Refresh
                </button>
                <button
                  onClick={() => { resetTokenUsage().then(() => fetchTokenUsage().then(setTokenStats)).catch(() => {}); }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '6px 14px', borderRadius: 6, border: '1px solid #fca5a5',
                    background: '#fef2f2', cursor: 'pointer', fontSize: '0.8rem', color: '#dc2626',
                  }}
                >
                  <X size={13} /> Reset
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
