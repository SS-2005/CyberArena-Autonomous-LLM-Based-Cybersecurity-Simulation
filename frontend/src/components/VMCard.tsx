import React, { useState } from 'react';
import { 
  Play, 
  Square, 
  Terminal, 
  Camera, 
  RotateCcw, 
  Activity, 
  Server, 
  Network, 
  Key, 
  ChevronDown
} from 'lucide-react';
import { VMInfo } from '../types/vm';
import { StatusBadge } from './StatusBadge';
import { api } from '../api/client';

interface VMCardProps {
  vm: VMInfo;
  onRefresh: () => void;
  onOpenTerminal: (vm: VMInfo) => void;
  onOpenSnapshot: (vm: VMInfo, mode: 'take' | 'restore') => void;
  onShowMessage: (msg: string, isError?: boolean) => void;
}

export const VMCard: React.FC<VMCardProps> = ({
  vm,
  onRefresh,
  onOpenTerminal,
  onOpenSnapshot,
  onShowMessage,
}) => {
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [isCheckingHealth, setIsCheckingHealth] = useState(false);
  const [showStopMenu, setShowStopMenu] = useState(false);
  const [healthStatus, setHealthStatus] = useState<string | null>(null);

  const handleStart = async () => {
    setIsStarting(true);
    try {
      const res = await api.startVM(vm.vm_id);
      onShowMessage(res.message, !res.success);
      onRefresh();
    } catch (err: any) {
      onShowMessage(err.message || 'Failed to start VM', true);
    } finally {
      setIsStarting(false);
    }
  };

  const handleStop = async (force = false) => {
    setIsStopping(true);
    setShowStopMenu(false);
    try {
      const res = await api.stopVM(vm.vm_id, force);
      onShowMessage(res.message, !res.success);
      onRefresh();
    } catch (err: any) {
      onShowMessage(err.message || 'Failed to stop VM', true);
    } finally {
      setIsStopping(false);
    }
  };

  const handleHealthCheck = async () => {
    setIsCheckingHealth(true);
    try {
      const res = await api.checkHealth(vm.vm_id);
      const latencyStr = res.latency_ms ? ` (${res.latency_ms}ms)` : '';
      const summary = res.ssh_reachable 
        ? `Healthy: SSH Reachable${latencyStr}` 
        : `Hypervisor: ${res.state} | ${res.message}`;
      setHealthStatus(summary);
      onShowMessage(summary, !res.is_running || !res.ssh_reachable);
    } catch (err: any) {
      const errStr = err.message || 'Health check failed';
      setHealthStatus(errStr);
      onShowMessage(errStr, true);
    } finally {
      setIsCheckingHealth(false);
    }
  };

  return (
    <div
      style={{
        backgroundColor: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '12px',
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        transition: 'transform 0.2s ease, border-color 0.2s ease',
        boxShadow: '0 4px 15px rgba(0, 0, 0, 0.2)',
      }}
    >
      {/* Card Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div
            style={{
              padding: '8px',
              borderRadius: '8px',
              backgroundColor: '#162238',
              color: 'var(--accent-cyan)',
            }}
          >
            <Server size={20} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#ffffff' }}>
                {vm.vm_id}
              </h2>
              <span
                style={{
                  fontSize: '0.7rem',
                  padding: '1px 6px',
                  borderRadius: '4px',
                  backgroundColor: '#1f293d',
                  color: 'var(--text-muted)',
                }}
              >
                {vm.vm_provider}
              </span>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontFamily: 'monospace' }}>
              VBox: {vm.virtualbox_vm_name}
            </div>
          </div>
        </div>

        <StatusBadge state={vm.state} />
      </div>

      {/* Description */}
      {vm.description && (
        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
          {vm.description}
        </p>
      )}

      {/* Network & SSH Telemetry Box */}
      <div
        style={{
          backgroundColor: 'var(--bg-input)',
          border: '1px solid var(--border-color)',
          borderRadius: '8px',
          padding: '12px',
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: '8px',
          fontSize: '0.75rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Network size={14} color="var(--text-dim)" />
          <span style={{ color: 'var(--text-muted)' }}>SSH Target:</span>
          <span style={{ color: 'var(--accent-cyan)', fontFamily: 'monospace' }}>
            {vm.ssh_host}:{vm.ssh_port}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Key size={14} color="var(--text-dim)" />
          <span style={{ color: 'var(--text-muted)' }}>Auth User:</span>
          <span style={{ color: 'var(--text-main)', fontFamily: 'monospace' }}>
            {vm.ssh_username}
          </span>
        </div>
      </div>

      {/* Health status banner if checked */}
      {healthStatus && (
        <div
          style={{
            fontSize: '0.75rem',
            padding: '6px 10px',
            borderRadius: '6px',
            backgroundColor: '#0c1524',
            border: '1px solid #1a2a47',
            color: 'var(--accent-cyan)',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <Activity size={12} />
          <span>{healthStatus}</span>
        </div>
      )}

      {/* Control Actions Toolbar */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '8px',
          marginTop: 'auto',
          paddingTop: '8px',
          borderTop: '1px solid var(--border-color)',
        }}
      >
        {/* Start Button */}
        {vm.state !== 'running' ? (
          <button
            onClick={handleStart}
            disabled={isStarting}
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              padding: '8px 12px',
              borderRadius: '8px',
              backgroundColor: 'var(--accent-emerald)',
              color: '#062d21',
              border: 'none',
              fontWeight: 600,
              fontSize: '0.8rem',
              cursor: isStarting ? 'not-allowed' : 'pointer',
            }}
          >
            <Play size={14} fill="currentColor" />
            <span>{isStarting ? 'Starting...' : 'Start'}</span>
          </button>
        ) : (
          /* Stop Button with dropdown for graceful / force */
          <div style={{ flex: 1, position: 'relative', display: 'flex' }}>
            <button
              onClick={() => handleStop(false)}
              disabled={isStopping}
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                padding: '8px 10px',
                borderRadius: '8px 0 0 8px',
                backgroundColor: 'rgba(244, 63, 94, 0.2)',
                border: '1px solid rgba(244, 63, 94, 0.4)',
                color: '#fb7185',
                fontWeight: 600,
                fontSize: '0.8rem',
                cursor: isStopping ? 'not-allowed' : 'pointer',
              }}
            >
              <Square size={14} fill="currentColor" />
              <span>{isStopping ? 'Stopping...' : 'Stop'}</span>
            </button>
            <button
              onClick={() => setShowStopMenu(!showStopMenu)}
              disabled={isStopping}
              style={{
                padding: '8px 6px',
                borderRadius: '0 8px 8px 0',
                backgroundColor: 'rgba(244, 63, 94, 0.2)',
                border: '1px solid rgba(244, 63, 94, 0.4)',
                borderLeft: 'none',
                color: '#fb7185',
                cursor: 'pointer',
              }}
            >
              <ChevronDown size={14} />
            </button>

            {showStopMenu && (
              <div
                style={{
                  position: 'absolute',
                  top: '100%',
                  right: 0,
                  marginTop: '4px',
                  backgroundColor: '#181f2f',
                  border: '1px solid var(--border-color)',
                  borderRadius: '8px',
                  boxShadow: '0 8px 20px rgba(0,0,0,0.5)',
                  zIndex: 20,
                  minWidth: '160px',
                  overflow: 'hidden',
                }}
              >
                <button
                  onClick={() => handleStop(false)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    textAlign: 'left',
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-main)',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                    display: 'block',
                  }}
                >
                  Graceful ACPI Shutdown
                </button>
                <button
                  onClick={() => handleStop(true)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    textAlign: 'left',
                    background: 'none',
                    border: 'none',
                    color: '#fb7185',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                    display: 'block',
                    borderTop: '1px solid var(--border-color)',
                  }}
                >
                  Force Power Off
                </button>
              </div>
            )}
          </div>
        )}

        {/* Guest Command Terminal Button */}
        <button
          onClick={() => onOpenTerminal(vm)}
          title="Open Guest Command Terminal"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '8px 12px',
            borderRadius: '8px',
            backgroundColor: '#162238',
            border: '1px solid #1f3454',
            color: 'var(--accent-cyan)',
            fontWeight: 500,
            fontSize: '0.8rem',
            cursor: 'pointer',
          }}
        >
          <Terminal size={14} />
          <span>Execute</span>
        </button>

        {/* Snapshot Menu */}
        <button
          onClick={() => onOpenSnapshot(vm, 'take')}
          title="Create Snapshot"
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '8px 10px',
            borderRadius: '8px',
            backgroundColor: '#131b2e',
            border: '1px solid var(--border-color)',
            color: 'var(--text-muted)',
            cursor: 'pointer',
          }}
        >
          <Camera size={14} />
        </button>

        {/* Restore Snapshot Menu */}
        <button
          onClick={() => onOpenSnapshot(vm, 'restore')}
          title="Restore Snapshot"
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '8px 10px',
            borderRadius: '8px',
            backgroundColor: '#131b2e',
            border: '1px solid var(--border-color)',
            color: 'var(--text-muted)',
            cursor: 'pointer',
          }}
        >
          <RotateCcw size={14} />
        </button>

        {/* Health Check Button */}
        <button
          onClick={handleHealthCheck}
          disabled={isCheckingHealth}
          title="Check VM Health"
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '8px 10px',
            borderRadius: '8px',
            backgroundColor: '#131b2e',
            border: '1px solid var(--border-color)',
            color: 'var(--text-muted)',
            cursor: isCheckingHealth ? 'not-allowed' : 'pointer',
          }}
        >
          <Activity size={14} className={isCheckingHealth ? 'animate-spin' : ''} />
        </button>
      </div>
    </div>
  );
};
