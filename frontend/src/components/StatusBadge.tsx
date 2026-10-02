import React from 'react';
import { VMState } from '../types/vm';

interface StatusBadgeProps {
  state: VMState;
  showDot?: boolean;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ state, showDot = true }) => {
  const getColors = () => {
    switch (state) {
      case 'running':
        return {
          bg: '#064e3b',
          text: '#34d399',
          border: '#059669',
          dot: '#10b981',
        };
      case 'stopped':
        return {
          bg: '#18181b',
          text: '#a1a1aa',
          border: '#27272a',
          dot: '#71717a',
        };
      case 'paused':
      case 'stopping':
        return {
          bg: '#451a03',
          text: '#fbbf24',
          border: '#b45309',
          dot: '#f59e0b',
        };
      case 'starting':
        return {
          bg: '#083344',
          text: '#38bdf8',
          border: '#0284c7',
          dot: '#0ea5e9',
        };
      case 'error':
        return {
          bg: '#4c0519',
          text: '#fb7185',
          border: '#e11d48',
          dot: '#f43f5e',
        };
      default:
        return {
          bg: '#1e293b',
          text: '#94a3b8',
          border: '#334155',
          dot: '#64748b',
        };
    }
  };

  const style = getColors();

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '3px 10px',
        borderRadius: '9999px',
        fontSize: '0.75rem',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        backgroundColor: style.bg,
        color: style.text,
        border: `1px solid ${style.border}`,
      }}
    >
      {showDot && (
        <span
          style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            backgroundColor: style.dot,
            boxShadow: state === 'running' ? `0 0 8px ${style.dot}` : 'none',
          }}
        />
      )}
      {state}
    </span>
  );
};
