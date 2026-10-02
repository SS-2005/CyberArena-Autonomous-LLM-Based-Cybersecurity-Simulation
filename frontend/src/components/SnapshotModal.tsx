import React, { useState } from 'react';
import { Camera, RotateCcw, AlertTriangle } from 'lucide-react';
import { VMInfo } from '../types/vm';
import { api } from '../api/client';

interface SnapshotModalProps {
  vm: VMInfo;
  mode: 'take' | 'restore';
  onClose: () => void;
  onSuccess: (message: string) => void;
}

export const SnapshotModal: React.FC<SnapshotModalProps> = ({ vm, mode, onClose, onSuccess }) => {
  const [snapshotName, setSnapshotName] = useState(mode === 'take' ? `snap_${Date.now()}` : '');
  const [description, setDescription] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!snapshotName.trim() || isLoading) return;

    setIsLoading(true);
    setError(null);

    try {
      if (mode === 'take') {
        const res = await api.createSnapshot(vm.vm_id, snapshotName.trim(), description.trim() || undefined);
        if (res.success) {
          onSuccess(res.message);
          onClose();
        } else {
          setError(res.message);
        }
      } else {
        const res = await api.restoreSnapshot(vm.vm_id, snapshotName.trim());
        if (res.success) {
          onSuccess(res.message);
          onClose();
        } else {
          setError(res.message);
        }
      }
    } catch (err: any) {
      setError(err.message || 'Operation failed');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(5, 8, 15, 0.8)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 50,
        padding: '16px',
      }}
    >
      <div
        style={{
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '12px',
          width: '100%',
          maxWidth: '460px',
          padding: '24px',
          boxShadow: '0 20px 40px rgba(0,0,0,0.6)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
          <div
            style={{
              padding: '8px',
              borderRadius: '8px',
              backgroundColor: mode === 'take' ? 'rgba(6, 182, 212, 0.1)' : 'rgba(245, 158, 11, 0.1)',
              color: mode === 'take' ? 'var(--accent-cyan)' : 'var(--accent-amber)',
            }}
          >
            {mode === 'take' ? <Camera size={20} /> : <RotateCcw size={20} />}
          </div>
          <div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>
              {mode === 'take' ? 'Create VM Snapshot' : 'Restore VM Snapshot'}
            </h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Target: <span style={{ color: 'var(--accent-cyan)' }}>{vm.vm_id}</span> ({vm.virtualbox_vm_name})
            </p>
          </div>
        </div>

        {mode === 'restore' && (
          <div
            style={{
              padding: '10px 12px',
              borderRadius: '8px',
              backgroundColor: 'rgba(245, 158, 11, 0.1)',
              border: '1px solid rgba(245, 158, 11, 0.3)',
              color: '#fbbf24',
              fontSize: '0.8rem',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <AlertTriangle size={16} />
            <span>Restoring will revert the VM state. If running, the VM will be powered off first.</span>
          </div>
        )}

        {error && (
          <div
            style={{
              padding: '10px 12px',
              borderRadius: '8px',
              backgroundColor: 'rgba(244, 63, 94, 0.1)',
              border: '1px solid rgba(244, 63, 94, 0.3)',
              color: '#fb7185',
              fontSize: '0.85rem',
              marginBottom: '16px',
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '14px' }}>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>
              Snapshot Name
            </label>
            <input
              type="text"
              required
              pattern="^[a-zA-Z0-9_\-]+$"
              title="Letters, numbers, dashes, and underscores only"
              value={snapshotName}
              onChange={(e) => setSnapshotName(e.target.value)}
              placeholder="e.g. baseline_clean_state"
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '8px',
                backgroundColor: 'var(--bg-input)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-main)',
                fontSize: '0.9rem',
                outline: 'none',
              }}
            />
          </div>

          {mode === 'take' && (
            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>
                Description (Optional)
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Pre-experiment clean snapshot..."
                rows={2}
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: '8px',
                  backgroundColor: 'var(--bg-input)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-main)',
                  fontSize: '0.85rem',
                  outline: 'none',
                  resize: 'none',
                }}
              />
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
            <button
              type="button"
              onClick={onClose}
              disabled={isLoading}
              style={{
                padding: '8px 16px',
                borderRadius: '8px',
                backgroundColor: 'transparent',
                border: '1px solid var(--border-color)',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                fontSize: '0.85rem',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading || !snapshotName.trim()}
              style={{
                padding: '8px 18px',
                borderRadius: '8px',
                backgroundColor: mode === 'take' ? 'var(--accent-cyan)' : 'var(--accent-amber)',
                color: '#080d1a',
                border: 'none',
                fontWeight: 600,
                fontSize: '0.85rem',
                cursor: isLoading ? 'not-allowed' : 'pointer',
              }}
            >
              {isLoading ? 'Processing...' : mode === 'take' ? 'Create Snapshot' : 'Restore'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
