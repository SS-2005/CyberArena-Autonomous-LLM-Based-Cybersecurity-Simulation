import React, { useState } from 'react';
import { Terminal, Play, Clock, CheckCircle2, AlertCircle, ShieldAlert, Sparkles } from 'lucide-react';
import { VMInfo, CommandExecutionResult } from '../types/vm';
import { api } from '../api/client';

interface CommandTerminalProps {
  vm: VMInfo;
  onClose?: () => void;
}

const PRESET_COMMANDS = [
  'uname -a',
  'id',
  'ip -brief address',
  'uptime',
  'cat /etc/os-release | grep PRETTY_NAME',
  'free -m',
];

export const CommandTerminal: React.FC<CommandTerminalProps> = ({ vm, onClose }) => {
  const [command, setCommand] = useState('uname -a');
  const [timeoutSec, setTimeoutSec] = useState(30);
  const [isExecuting, setIsExecuting] = useState(false);
  const [result, setResult] = useState<CommandExecutionResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleExecute = async (cmdToRun?: string) => {
    const cmd = cmdToRun || command;
    if (!cmd.trim() || isExecuting) return;

    setIsExecuting(true);
    setErrorMsg(null);

    try {
      const res = await api.executeCommand(vm.vm_id, cmd, timeoutSec);
      setResult(res);
    } catch (err: any) {
      setErrorMsg(err.message || 'Execution failed');
    } finally {
      setIsExecuting(false);
    }
  };

  return (
    <div
      style={{
        backgroundColor: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '12px',
        overflow: 'hidden',
        boxShadow: '0 10px 25px rgba(0, 0, 0, 0.4)',
        marginTop: '20px',
      }}
    >
      {/* Terminal Header */}
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: '#0d131f',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div
            style={{
              padding: '6px',
              borderRadius: '6px',
              backgroundColor: 'rgba(6, 182, 212, 0.1)',
              color: 'var(--accent-cyan)',
            }}
          >
            <Terminal size={18} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>Guest Execution Terminal</span>
              <span
                style={{
                  fontSize: '0.75rem',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  backgroundColor: '#1e293b',
                  color: 'var(--accent-cyan)',
                  fontFamily: 'monospace',
                }}
              >
                {vm.vm_id} ({vm.ssh_username}@{vm.ssh_host}:{vm.ssh_port})
              </span>
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <ShieldAlert size={12} color="var(--accent-cyan)" />
              Isolated Paramiko SSH Execution &bull; Host Windows OS is strictly isolated
            </div>
          </div>
        </div>

        {onClose && (
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-muted)',
              fontSize: '1.25rem',
              cursor: 'pointer',
              padding: '4px 8px',
            }}
          >
            &times;
          </button>
        )}
      </div>

      <div style={{ padding: '16px' }}>
        {/* Quick presets */}
        <div style={{ marginBottom: '12px' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Sparkles size={12} color="var(--accent-cyan)" /> Quick Presets:
          </div>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {PRESET_COMMANDS.map((preset) => (
              <button
                key={preset}
                disabled={isExecuting || vm.state !== 'running'}
                onClick={() => {
                  setCommand(preset);
                  handleExecute(preset);
                }}
                style={{
                  padding: '4px 10px',
                  borderRadius: '6px',
                  backgroundColor: '#131b2e',
                  border: '1px solid #1e293d',
                  color: 'var(--accent-cyan)',
                  fontSize: '0.75rem',
                  fontFamily: 'monospace',
                  cursor: isExecuting || vm.state !== 'running' ? 'not-allowed' : 'pointer',
                  opacity: vm.state !== 'running' ? 0.5 : 1,
                  transition: 'all 0.15s ease',
                }}
              >
                {preset}
              </button>
            ))}
          </div>
        </div>

        {/* Command Input Bar */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleExecute();
          }}
          style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}
        >
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              backgroundColor: 'var(--bg-input)',
              border: '1px solid var(--border-color)',
              borderRadius: '8px',
              padding: '0 12px',
            }}
          >
            <span style={{ color: 'var(--accent-cyan)', fontFamily: 'monospace', marginRight: '8px', userSelect: 'none' }}>
              $
            </span>
            <input
              type="text"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              disabled={isExecuting || vm.state !== 'running'}
              placeholder={vm.state === 'running' ? 'Enter shell command to execute in guest VM...' : 'VM is stopped. Start VM first.'}
              style={{
                width: '100%',
                background: 'none',
                border: 'none',
                outline: 'none',
                color: 'var(--text-main)',
                fontFamily: 'monospace',
                fontSize: '0.9rem',
                padding: '10px 0',
              }}
            />
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              backgroundColor: 'var(--bg-input)',
              border: '1px solid var(--border-color)',
              borderRadius: '8px',
              padding: '0 8px',
              fontSize: '0.75rem',
              color: 'var(--text-muted)',
            }}
            title="Timeout in seconds"
          >
            <Clock size={12} />
            <input
              type="number"
              min={1}
              max={300}
              value={timeoutSec}
              onChange={(e) => setTimeoutSec(Number(e.target.value))}
              disabled={isExecuting}
              style={{
                width: '45px',
                background: 'none',
                border: 'none',
                color: 'var(--text-main)',
                fontSize: '0.8rem',
                outline: 'none',
                textAlign: 'center',
              }}
            />
            <span>s</span>
          </div>

          <button
            type="submit"
            disabled={isExecuting || !command.trim() || vm.state !== 'running'}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '0 16px',
              borderRadius: '8px',
              backgroundColor: isExecuting || vm.state !== 'running' ? '#1e293b' : 'var(--accent-cyan)',
              color: isExecuting || vm.state !== 'running' ? '#64748b' : '#080d1a',
              border: 'none',
              fontWeight: 600,
              fontSize: '0.85rem',
              cursor: isExecuting || vm.state !== 'running' ? 'not-allowed' : 'pointer',
              transition: 'background 0.2s',
            }}
          >
            <Play size={14} fill={isExecuting || vm.state !== 'running' ? 'none' : 'currentColor'} />
            {isExecuting ? 'Running...' : 'Execute'}
          </button>
        </form>

        {/* Warning if VM is not running */}
        {vm.state !== 'running' && (
          <div
            style={{
              padding: '10px 14px',
              borderRadius: '8px',
              backgroundColor: 'rgba(245, 158, 11, 0.1)',
              border: '1px solid rgba(245, 158, 11, 0.3)',
              color: '#fbbf24',
              fontSize: '0.8rem',
              marginBottom: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <AlertCircle size={16} />
            Command execution is disabled because the virtual machine is currently {vm.state}. Start the VM to enable SSH command execution.
          </div>
        )}

        {/* Network isolation reminder */}
        {errorMsg && (
          <div
            style={{
              padding: '10px 14px',
              borderRadius: '8px',
              backgroundColor: 'rgba(244, 63, 94, 0.1)',
              border: '1px solid rgba(244, 63, 94, 0.3)',
              color: '#fb7185',
              fontSize: '0.85rem',
              marginBottom: '12px',
            }}
          >
            {errorMsg}
          </div>
        )}

        {/* Command Output Inspector */}
        {result && (
          <div
            style={{
              borderRadius: '8px',
              border: '1px solid var(--border-color)',
              backgroundColor: '#070a12',
              overflow: 'hidden',
            }}
          >
            {/* Meta bar */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '8px 12px',
                borderBottom: '1px solid #172133',
                backgroundColor: '#0a0e1a',
                fontSize: '0.75rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    fontWeight: 600,
                    backgroundColor: result.exit_code === 0 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)',
                    color: result.exit_code === 0 ? '#34d399' : '#fb7185',
                    border: `1px solid ${result.exit_code === 0 ? '#059669' : '#e11d48'}`,
                  }}
                >
                  {result.exit_code === 0 ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                  Exit Code: {result.exit_code}
                </span>
                <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                  {result.command}
                </span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: 'var(--text-dim)' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <Clock size={12} /> {result.duration}s
                </span>
                <span>{new Date(result.timestamp).toLocaleTimeString()}</span>
              </div>
            </div>

            {/* Output view */}
            <div style={{ padding: '12px', maxHeight: '320px', overflowY: 'auto' }}>
              {result.stdout && (
                <div style={{ marginBottom: result.stderr ? '8px' : '0' }}>
                  <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', color: 'var(--text-dim)', marginBottom: '4px' }}>
                    Standard Output (stdout):
                  </div>
                  <pre
                    style={{
                      fontFamily: 'monospace',
                      fontSize: '0.85rem',
                      color: '#a7f3d0',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                    }}
                  >
                    {result.stdout}
                  </pre>
                </div>
              )}

              {result.stderr && (
                <div>
                  <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', color: '#f87171', marginBottom: '4px' }}>
                    Standard Error (stderr):
                  </div>
                  <pre
                    style={{
                      fontFamily: 'monospace',
                      fontSize: '0.85rem',
                      color: '#fca5a5',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                    }}
                  >
                    {result.stderr}
                  </pre>
                </div>
              )}

              {!result.stdout && !result.stderr && (
                <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontStyle: 'italic' }}>
                  (No output produced)
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
