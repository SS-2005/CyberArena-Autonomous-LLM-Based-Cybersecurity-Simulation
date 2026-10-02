import React, { useEffect, useState } from 'react';
import { Navbar } from './components/Navbar';
import { VMCard } from './components/VMCard';
import { CommandTerminal } from './components/CommandTerminal';
import { SnapshotModal } from './components/SnapshotModal';
import { AgentPanel } from './components/AgentPanel';
import { ExperimentDashboard } from './components/ExperimentDashboard';
import { VMInfo, SystemConfigResponse } from './types/vm';
import { api } from './api/client';
import { 
  Server, 
  ShieldCheck, 
  AlertCircle, 
  CheckCircle, 
  X, 
  Network,
  Bot,
  Layers
} from 'lucide-react';

export const App: React.FC = () => {
  const [config, setConfig] = useState<SystemConfigResponse | null>(null);
  const [vms, setVms] = useState<VMInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'vms' | 'agents' | 'experiments'>('experiments');

  // Active terminal VM
  const [activeTerminalVM, setActiveTerminalVM] = useState<VMInfo | null>(null);

  // Snapshot modal state
  const [snapshotModal, setSnapshotModal] = useState<{
    isOpen: boolean;
    vm: VMInfo | null;
    mode: 'take' | 'restore';
  }>({
    isOpen: false,
    vm: null,
    mode: 'take',
  });

  // Toast / notification
  const [toast, setToast] = useState<{
    message: string;
    isError: boolean;
  } | null>(null);

  const showToast = (message: string, isError = false) => {
    setToast({ message, isError });
    setTimeout(() => {
      setToast(null);
    }, 6000);
  };

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [sysConfig, vmList] = await Promise.all([
        api.getConfig(),
        api.listVMs(),
      ]);
      setConfig(sysConfig);
      setVms(vmList);

      // Keep active terminal VM updated if open
      if (activeTerminalVM) {
        const updated = vmList.find((v) => v.vm_id === activeTerminalVM.vm_id);
        if (updated) {
          setActiveTerminalVM(updated);
        }
      }
    } catch (err: any) {
      setError(err.message || 'Failed to connect to CyberArena Backend API');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Navbar
        maxVM={config?.max_vm ?? 2}
        configuredCount={vms.length}
        onRefresh={loadData}
        isLoading={isLoading}
      />

      {/* Toast Notification Banner */}
      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: '24px',
            right: '24px',
            zIndex: 60,
            backgroundColor: toast.isError ? '#4c0519' : '#064e3b',
            border: `1px solid ${toast.isError ? '#e11d48' : '#059669'}`,
            color: toast.isError ? '#fecdd3' : '#a7f3d0',
            padding: '12px 18px',
            borderRadius: '8px',
            boxShadow: '0 10px 30px rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            maxWidth: '420px',
          }}
        >
          {toast.isError ? <AlertCircle size={18} /> : <CheckCircle size={18} />}
          <span style={{ fontSize: '0.85rem', flex: 1 }}>{toast.message}</span>
          <button
            onClick={() => setToast(null)}
            style={{
              background: 'none',
              border: 'none',
              color: 'inherit',
              cursor: 'pointer',
              padding: '2px',
            }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Main Content Area */}
      <main style={{ maxWidth: '1280px', margin: '0 auto', padding: '24px', width: '100%', flex: 1 }}>
        {/* Lab Architecture & Isolation Info Banner */}
        <section
          style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '18px 24px',
            marginBottom: '24px',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: '20px',
          }}
        >
          <div style={{ display: 'flex', gap: '12px' }}>
            <div
              style={{
                padding: '10px',
                borderRadius: '8px',
                backgroundColor: 'rgba(6, 182, 212, 0.1)',
                color: 'var(--accent-cyan)',
                height: 'fit-content',
              }}
            >
              <ShieldCheck size={24} />
            </div>
            <div>
              <h2 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#ffffff', marginBottom: '4px' }}>
                Strict Execution Isolation
              </h2>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                All agent actions and commands execute strictly within assigned virtual machines over SSH.
                The host Windows operating system is strictly protected from becoming an execution target.
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '12px' }}>
            <div
              style={{
                padding: '10px',
                borderRadius: '8px',
                backgroundColor: 'rgba(16, 185, 129, 0.1)',
                color: 'var(--accent-emerald)',
                height: 'fit-content',
              }}
            >
              <Network size={24} />
            </div>
            <div>
              <h2 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#ffffff', marginBottom: '4px' }}>
                Isolated Host-Only Network
              </h2>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                Laboratory VMs communicate across a private host-only subnet (192.168.32.x).
                Public networks and external servers are not permitted targets.
              </p>
            </div>
          </div>
        </section>

        {/* Tab Navigation */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            borderBottom: '1px solid var(--border-color)',
            paddingBottom: '16px',
            marginBottom: '24px',
          }}
        >
          <button
            onClick={() => setActiveTab('vms')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 18px',
              borderRadius: '8px',
              fontSize: '0.82rem',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s',
              backgroundColor: activeTab === 'vms' ? 'rgba(6, 182, 212, 0.15)' : 'transparent',
              border: `1px solid ${activeTab === 'vms' ? 'var(--accent-cyan)' : 'transparent'}`,
              color: activeTab === 'vms' ? 'var(--accent-cyan)' : 'var(--text-muted)',
            }}
          >
            <Server size={16} />
            Virtual Machines (Phase 1)
          </button>
          <button
            onClick={() => setActiveTab('agents')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 18px',
              borderRadius: '8px',
              fontSize: '0.82rem',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s',
              backgroundColor: activeTab === 'agents' ? 'rgba(99, 102, 241, 0.15)' : 'transparent',
              border: `1px solid ${activeTab === 'agents' ? '#6366f1' : 'transparent'}`,
              color: activeTab === 'agents' ? '#a5b4fc' : 'var(--text-muted)',
            }}
          >
            <Bot size={16} />
            Autonomous Agents & LLM (Phase 2)
          </button>
          <button
            onClick={() => setActiveTab('experiments')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 18px',
              borderRadius: '8px',
              fontSize: '0.82rem',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s',
              backgroundColor: activeTab === 'experiments' ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
              border: `1px solid ${activeTab === 'experiments' ? '#38bdf8' : 'transparent'}`,
              color: activeTab === 'experiments' ? '#38bdf8' : 'var(--text-muted)',
            }}
          >
            <Layers size={16} />
            Multi-Agent Experiments (Phase 3)
          </button>
        </div>

        {activeTab === 'vms' ? (
          <div>
            {/* Section Heading */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#ffffff' }}>
                  Configured Virtual Machines
                </h2>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Registry-driven nodes mapped to local VirtualBox instances
                </p>
              </div>
            </div>

            {/* Loading State */}
            {isLoading && vms.length === 0 && (
              <div
                style={{
                  padding: '60px 20px',
                  textAlign: 'center',
                  backgroundColor: 'var(--bg-card)',
                  borderRadius: '12px',
                  border: '1px solid var(--border-color)',
                }}
              >
                <div
                  className="animate-spin"
                  style={{
                    width: '32px',
                    height: '32px',
                    border: '3px solid var(--border-color)',
                    borderTopColor: 'var(--accent-cyan)',
                    borderRadius: '50%',
                    margin: '0 auto 16px auto',
                  }}
                />
                <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                  Querying hypervisor and loading VM registry...
                </p>
              </div>
            )}

            {/* Error State */}
            {error && (
              <div
                style={{
                  padding: '24px',
                  textAlign: 'center',
                  backgroundColor: 'rgba(244, 63, 94, 0.1)',
                  borderRadius: '12px',
                  border: '1px solid rgba(244, 63, 94, 0.3)',
                  marginBottom: '24px',
                }}
              >
                <AlertCircle size={32} color="#fb7185" style={{ margin: '0 auto 12px auto' }} />
                <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#fb7185', marginBottom: '6px' }}>
                  Backend Connection Error
                </h3>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
                  {error}
                </p>
                <button
                  onClick={loadData}
                  style={{
                    padding: '8px 20px',
                    borderRadius: '8px',
                    backgroundColor: 'var(--bg-card)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-main)',
                    fontSize: '0.85rem',
                    cursor: 'pointer',
                  }}
                >
                  Retry Connection
                </button>
              </div>
            )}

            {/* Empty State */}
            {!isLoading && !error && vms.length === 0 && (
              <div
                style={{
                  padding: '60px 20px',
                  textAlign: 'center',
                  backgroundColor: 'var(--bg-card)',
                  borderRadius: '12px',
                  border: '1px solid var(--border-color)',
                }}
              >
                <Server size={40} color="var(--text-dim)" style={{ margin: '0 auto 16px auto' }} />
                <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '8px' }}>
                  No Virtual Machines Configured
                </h3>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', maxWidth: '480px', margin: '0 auto' }}>
                  No lab VMs were found in <code style={{ color: 'var(--accent-cyan)' }}>configs/vms.json</code>.
                  Configure your VirtualBox VMs in the registry to begin operations.
                </p>
              </div>
            )}

            {/* Dynamic VM Cards Grid */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
                gap: '20px',
              }}
            >
              {vms.map((vm) => (
                <VMCard
                  key={vm.vm_id}
                  vm={vm}
                  onRefresh={loadData}
                  onOpenTerminal={(selected) => setActiveTerminalVM(selected)}
                  onOpenSnapshot={(selected, mode) =>
                    setSnapshotModal({ isOpen: true, vm: selected, mode })
                  }
                  onShowMessage={showToast}
                />
              ))}
            </div>

            {/* Guest Command Terminal Drawer */}
            {activeTerminalVM && (
              <CommandTerminal
                vm={activeTerminalVM}
                onClose={() => setActiveTerminalVM(null)}
              />
            )}
          </div>
        ) : activeTab === 'agents' ? (
          <AgentPanel vms={vms} />
        ) : (
          <ExperimentDashboard vms={vms} maxVm={config?.max_vm ?? 2} />
        )}
      </main>

      {/* Snapshot Modal */}
      {snapshotModal.isOpen && snapshotModal.vm && (
        <SnapshotModal
          vm={snapshotModal.vm}
          mode={snapshotModal.mode}
          onClose={() => setSnapshotModal({ isOpen: false, vm: null, mode: 'take' })}
          onSuccess={(msg) => {
            showToast(msg, false);
            loadData();
          }}
        />
      )}

      {/* Footer */}
      <footer
        style={{
          borderTop: '1px solid var(--border-color)',
          padding: '16px 24px',
          textAlign: 'center',
          fontSize: '0.75rem',
          color: 'var(--text-dim)',
          backgroundColor: '#0a0e17',
        }}
      >
        CYBERARENA &bull; Autonomous AI Agent Experimentation Platform &bull; Phase 1 + Phase 2 + Phase 3 Verified
      </footer>
    </div>
  );
};
