import { useState, useEffect, useRef } from 'react';
import { ChevronDown } from 'lucide-react';
import { getLLMProviders } from '../../services/api';
import styles from './ProviderSelect.module.css';

const PROVIDER_LABELS: Record<string, string> = {
  groq: 'Groq (Llama 3.1)',
  openai: 'OpenAI (GPT-4o)',
  anthropic: 'Anthropic (Claude)',
  waymore: 'Waymore AI',
};

const PROVIDER_ORDER = ['groq', 'openai', 'anthropic', 'waymore'];

interface ProviderSelectProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
}

export const ProviderSelect = ({ value, onChange, disabled, className }: ProviderSelectProps) => {
  const [open, setOpen] = useState(false);
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getLLMProviders()
      .then(data => {
        // Build configured map from providers array (each item has api_key_configured)
        const map: Record<string, boolean> = {};
        const providers = data.providers as unknown as Array<{ id: string; api_key_configured: boolean }>;
        if (Array.isArray(providers)) {
          providers.forEach(p => { if (p.id) map[p.id] = p.api_key_configured ?? false; });
        }
        setConfigured(map);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const isConfigured = (id: string) => configured[id] !== false; // default green if unknown
  const hasChecked = Object.keys(configured).length > 0;

  return (
    <div ref={ref} className={`${styles.wrapper} ${className || ''}`}>
      <button
        type="button"
        className={styles.trigger}
        onClick={() => !disabled && setOpen(prev => !prev)}
        disabled={disabled}
        title="Select AI Provider"
      >
        <span
          className={styles.dot}
          style={{
            background: !hasChecked
              ? '#94a3b8'
              : isConfigured(value) ? '#22c55e' : '#ef4444',
            boxShadow: !hasChecked
              ? 'none'
              : isConfigured(value)
                ? '0 0 6px rgba(34,197,94,0.5)'
                : '0 0 6px rgba(239,68,68,0.5)',
          }}
        />
        <span className={styles.label}>{PROVIDER_LABELS[value] || value}</span>
        <ChevronDown size={12} className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`} />
      </button>

      {open && (
        <div className={styles.dropdown}>
          {PROVIDER_ORDER.map(id => {
            const available = !hasChecked ? null : isConfigured(id);
            return (
              <button
                key={id}
                type="button"
                className={`${styles.option} ${id === value ? styles.optionActive : ''}`}
                onClick={() => { onChange(id); setOpen(false); }}
              >
                <span
                  className={styles.dot}
                  style={{
                    background: available === null ? '#94a3b8' : available ? '#22c55e' : '#ef4444',
                    boxShadow: available === null
                      ? 'none'
                      : available
                        ? '0 0 6px rgba(34,197,94,0.5)'
                        : '0 0 6px rgba(239,68,68,0.5)',
                  }}
                />
                <span>{PROVIDER_LABELS[id]}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
