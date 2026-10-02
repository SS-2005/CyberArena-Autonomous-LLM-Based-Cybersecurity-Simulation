import React, { useState, useEffect, useRef } from 'react';
import { api } from '../api/client';
import { 
  AgentState, 
  ToolDefinitionSchema, 
  AgentCreateRequest, 
  AgentEvent 
} from '../types/agent';
import { ModelStatus, LLMHealthResponse } from '../types/llm';
import { VMInfo } from '../types/vm';
import { 
  Bot, 
  Cpu, 
  Play, 
  Square, 
  Wrench, 
  Terminal, 
  AlertTriangle,
  Sparkles,
  Trash2,
  Activity,
  Layers,
  Zap
} from 'lucide-react';


interface AgentPanelProps {
  vms: VMInfo[];
}

export const AgentPanel: React.FC<AgentPanelProps> = ({ vms }) => {
  // Global & Multi-Agent Data
  const [agents, setAgents] = useState<AgentState[]>([]);
  const [models, setModels] = useState<ModelStatus[]>([]);
  const [llmHealth, setLlmHealth] = useState<LLMHealthResponse | null>(null);
  const [tools, setTools] = useState<ToolDefinitionSchema[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isActionLoading, setIsActionLoading] = useState(false);

  // Authoritative Selected Agent State
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const selectedAgentIdRef = useRef<string | null>(null);
  selectedAgentIdRef.current = selectedAgentId;

  // Selected Agent Detail & Independent Live Events
  const [selectedAgentState, setSelectedAgentState] = useState<AgentState | null>(null);
  const [liveEvents, setLiveEvents] = useState<AgentEvent[]>([]);
  const [activeStreamingThought, setActiveStreamingThought] = useState<string>('');
  const [currentExecutingPhase, setCurrentExecutingPhase] = useState<string | null>(null);
  const [isStreamConnected, setIsStreamConnected] = useState(false);

  // Delete Confirmation Modal
  const [agentToDelete, setAgentToDelete] = useState<string | null>(null);

  // Prompt / Create Agent Form
  const [roleInput, setRoleInput] = useState(
    'Report the hostname and current user of the assigned VM.'
  );
  const [selectedVm, setSelectedVm] = useState(vms[0]?.vm_id || 'vm-01');
  const [selectedModel, setSelectedModel] = useState('');
  const [iterLimit, setIterLimit] = useState(5);

  // Local Model Streaming Test
  const [selectedTestModel, setSelectedTestModel] = useState<string>('');
  const [testPromptInput, setTestPromptInput] = useState(
    'Explain what an isolated VM sandbox is in one sentence.'
  );
  const [testResult, setTestResult] = useState<{
    text: string;
    duration: number;
    isStreaming: boolean;
    isError: boolean;
  } | null>(null);
  const testAbortControllerRef = useRef<AbortController | null>(null);

  const PRESETS = [
    {
      title: 'VM Identity & User',
      prompt: 'Report the hostname and current user of the assigned VM.',
    },
    {
      title: 'OS & Memory Audit',
      prompt: 'Report the operating system and available memory of the assigned VM.',
    },
    {
      title: 'Network & Port Audit',
      prompt: 'Inspect active network interfaces, IP addresses, listening ports, and routing tables on the VM.',
    },
    {
      title: 'Process & Services Audit',
      prompt: 'Identify top memory-consuming processes and check if the ssh service is active.',
    },
  ];

  // 1. Fetch Global Metadata & Agents List
  const fetchGlobalData = async () => {
    try {
      const [h, m, t, a] = await Promise.all([
        api.getLLMHealth().catch(() => null),
        api.listModels().catch(() => []),
        api.listTools().catch(() => []),
        api.listAgents().catch(() => []),
      ]);

      if (h) setLlmHealth(h);
      setModels(m);
      setTools(t);
      setAgents(a);
      setError(null);

      // Auto-select ready model if not yet set
      if (m.length > 0 && !selectedModel) {
        const available = m.find((x) => x.available);
        if (available) setSelectedModel(available.model_id);
        else setSelectedModel(m[0].model_id);
      }
      if (m.length > 0 && !selectedTestModel) {
        const available = m.find((x) => x.available);
        if (available) setSelectedTestModel(available.model_id);
        else setSelectedTestModel(m[0].model_id);
      }

      // If no agent is selected yet, select the first agent safely
      if (a.length > 0 && !selectedAgentIdRef.current) {
        setSelectedAgentId(a[0].agent_id);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load Agent & LLM environment');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchGlobalData();
    const interval = setInterval(fetchGlobalData, 4000);
    return () => clearInterval(interval);
  }, []);

  // 2. Authoritative Subscription to Selected Agent's SSE Stream & State
  useEffect(() => {
    if (!selectedAgentId) {
      setSelectedAgentState(null);
      setLiveEvents([]);
      setActiveStreamingThought('');
      setCurrentExecutingPhase(null);
      return;
    }

    let isMounted = true;
    setLiveEvents([]);
    setActiveStreamingThought('');
    setCurrentExecutingPhase(null);

    // Fetch initial agent state and history
    api.getAgent(selectedAgentId)
      .then((state) => {
        if (isMounted) {
          setSelectedAgentState(state);
        }
      })
      .catch((err) => {
        console.warn(`Failed to fetch state for agent ${selectedAgentId}:`, err);
      });

    // Subscribe to SSE Real-time Events for the authoritative selectedAgentId
    const unsubscribe = api.subscribeAgentEvents(
      selectedAgentId,
      (evt: AgentEvent) => {
        if (!isMounted) return;
        // Strict isolation: verify event belongs to currently selected agent
        if (evt.agent_id !== selectedAgentId) return;

        setIsStreamConnected(true);

        setLiveEvents((prev) => {
          // Avoid duplicate events
          const exists = prev.some(
            (e) => e.timestamp === evt.timestamp && e.event_type === evt.event_type && e.iteration === evt.iteration
          );
          if (exists) return prev;
          return [...prev, evt];
        });

        // Handle Real-time Streamed Thoughts & Lifecycle Phasing
        switch (evt.event_type) {
          case 'agent_started':
            setCurrentExecutingPhase('Agent Initializing Execution...');
            setSelectedAgentState((prev) => prev ? { ...prev, status: 'running' } : null);
            break;

          case 'agent_iteration_started':
            setCurrentExecutingPhase(`Iteration ${evt.iteration} Running`);
            setActiveStreamingThought('');
            break;

          case 'llm_started':
            setCurrentExecutingPhase(`LLM Reasoning & Tool Planning...`);
            setActiveStreamingThought('');
            break;

          case 'llm_chunk':
            // Stream tokens/thoughts in real-time
            if (evt.content) {
              setActiveStreamingThought((prev) => prev + evt.content);
            }
            break;

          case 'llm_completed':
            // LLM generation finished: clear active thought stream to hide raw tokens
            setActiveStreamingThought('');
            setCurrentExecutingPhase('Action Plan Ready');
            break;

          case 'tool_requested':
            setCurrentExecutingPhase(`Tool Requested: ${evt.tool_name || 'action'}`);
            break;

          case 'tool_started':
            setCurrentExecutingPhase(`Executing Tool: ${evt.tool_name || 'action'} on VM...`);
            break;

          case 'tool_completed':
          case 'tool_failed':
          case 'observation_received':
            setCurrentExecutingPhase(null);
            setActiveStreamingThought('');
            // Refresh agent full state & history to update timeline
            api.getAgent(selectedAgentId).then((updated) => {
              if (isMounted) setSelectedAgentState(updated);
            }).catch(() => {});
            break;

          case 'agent_completed':
            setCurrentExecutingPhase(null);
            setActiveStreamingThought('');
            setSelectedAgentState((prev) => prev ? { ...prev, status: 'completed' } : null);
            fetchGlobalData();
            break;

          case 'agent_stopped':
            setCurrentExecutingPhase(null);
            setActiveStreamingThought('');
            setSelectedAgentState((prev) => prev ? { ...prev, status: 'stopped' } : null);
            fetchGlobalData();
            break;

          case 'agent_failed':
            setCurrentExecutingPhase(null);
            setActiveStreamingThought('');
            setSelectedAgentState((prev) => prev ? { ...prev, status: 'failed' } : null);
            fetchGlobalData();
            break;
        }
      },
      () => {
        if (isMounted) setIsStreamConnected(false);
      }
    );

    return () => {
      isMounted = false;
      unsubscribe();
    };
  }, [selectedAgentId]);

  // 3. User Actions: Create Agent
  const handleCreateAgent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!roleInput.trim()) return;
    setIsActionLoading(true);
    setError(null);
    try {
      const req: AgentCreateRequest = {
        role: roleInput.trim(),
        vm_id: selectedVm,
        model_id: selectedModel || undefined,
        iteration_limit: iterLimit,
      };
      const created = await api.createAgent(req);
      await fetchGlobalData();
      // Explicitly switch to the newly created agent
      setSelectedAgentId(created.agent_id);
    } catch (err: any) {
      setError(err.message || 'Failed to create agent');
    } finally {
      setIsActionLoading(false);
    }
  };

  // 4. User Actions: Start Agent Run
  const handleStartAgent = async (id: string) => {
    setIsActionLoading(true);
    setError(null);
    try {
      await api.startAgent(id);
      setSelectedAgentState((prev) => prev ? { ...prev, status: 'running' } : null);
      setAgents((prev) =>
        prev.map((a) => (a.agent_id === id ? { ...a, status: 'running' } : a))
      );
    } catch (err: any) {
      setError(err.message || 'Failed to start agent');
    } finally {
      setIsActionLoading(false);
    }
  };

  // 5. User Actions: Stop Agent
  const handleStopAgent = async (id: string) => {
    setIsActionLoading(true);
    try {
      await api.stopAgent(id);
      setSelectedAgentState((prev) => prev ? { ...prev, status: 'stopped' } : null);
      setAgents((prev) =>
        prev.map((a) => (a.agent_id === id ? { ...a, status: 'stopped' } : a))
      );
    } catch (err: any) {
      setError(err.message || 'Failed to stop agent');
    } finally {
      setIsActionLoading(false);
    }
  };

  // 6. User Actions: Delete Agent
  const handleDeleteAgent = async (id: string) => {
    setIsActionLoading(true);
    setError(null);
    try {
      await api.deleteAgent(id);
      setAgentToDelete(null);
      const remaining = agents.filter((a) => a.agent_id !== id);
      setAgents(remaining);

      // If deleted agent was selected, safely select another remaining agent
      if (selectedAgentId === id) {
        if (remaining.length > 0) {
          setSelectedAgentId(remaining[0].agent_id);
        } else {
          setSelectedAgentId(null);
          setSelectedAgentState(null);
        }
      }
    } catch (err: any) {
      setError(err.message || 'Failed to delete agent');
    } finally {
      setIsActionLoading(false);
    }
  };

  // 7. Interactive Stream Test Local Model
  const handleStreamTestModel = async () => {
    if (!testPromptInput.trim()) return;

    if (testAbortControllerRef.current) {
      testAbortControllerRef.current.abort();
    }
    const controller = new AbortController();
    testAbortControllerRef.current = controller;

    setTestResult({
      text: '',
      duration: 0,
      isStreaming: true,
      isError: false,
    });

    try {
      const modelToUse = selectedTestModel || selectedModel || undefined;
      const res = await api.streamLLMTest(
        testPromptInput.trim(),
        modelToUse,
        (chunk) => {
          setTestResult((prev) => prev ? { ...prev, text: prev.text + chunk } : null);
        },
        controller.signal
      );
      // Clean hidden reasoning thoughts once generation completes to show clean generated output
      const cleanText = res.text.replace(/<think>[\s\S]*?<\/think>/gi, '').trim() || res.text;
      setTestResult({
        text: cleanText,
        duration: res.duration,
        isStreaming: false,
        isError: false,
      });

    } catch (err: any) {
      if (err.name === 'AbortError') {
        setTestResult((prev) => prev ? { ...prev, isStreaming: false } : null);
      } else {
        setTestResult({
          text: err.message || 'LLM streaming test failed',
          duration: 0,
          isStreaming: false,
          isError: true,
        });
      }
    } finally {
      testAbortControllerRef.current = null;
    }
  };

  const handleCancelTestStream = () => {
    if (testAbortControllerRef.current) {
      testAbortControllerRef.current.abort();
      testAbortControllerRef.current = null;
    }
  };

  // Render Helpers
  const activeAgent = selectedAgentState || agents.find((a) => a.agent_id === selectedAgentId);

  const getAgentStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'var(--accent-cyan)';
      case 'completed': return 'var(--accent-emerald)';
      case 'partially_completed': return 'var(--accent-amber)';
      case 'stopped_iteration_limit': return '#f97316';
      case 'failed': return 'var(--accent-rose)';
      case 'blocked': return '#ef4444';
      case 'cancelled':
      case 'stopped': return '#fbbf24';
      default: return 'var(--text-dim)';
    }
  };

  const formatAgentStatus = (status: string) => {
    if (status === 'stopped_iteration_limit') return 'STOPPED - ITERATION LIMIT';
    if (status === 'partially_completed') return 'PARTIALLY COMPLETED';
    return status.replace(/_/g, ' ').toUpperCase();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* 1. TOP TELEMETRY BAR: LOCAL OLLAMA INFERENCE & LIVE HEALTH */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px',
          padding: '16px 22px',
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '12px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            style={{
              padding: '10px',
              borderRadius: '8px',
              backgroundColor:
                llmHealth?.status === 'healthy' ? 'rgba(16, 185, 129, 0.12)' : 'rgba(244, 63, 94, 0.12)',
              color: llmHealth?.status === 'healthy' ? 'var(--accent-emerald)' : 'var(--accent-rose)',
            }}
          >
            <Cpu size={22} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h2 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#ffffff' }}>
                Local Inference Engine (Ollama)
              </h2>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '2px 8px',
                  borderRadius: '12px',
                  fontSize: '0.7rem',
                  fontWeight: 600,
                  backgroundColor:
                    llmHealth?.status === 'healthy' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(244, 63, 94, 0.2)',
                  color: llmHealth?.status === 'healthy' ? 'var(--accent-emerald)' : 'var(--accent-rose)',
                  textTransform: 'uppercase',
                }}
              >
                <span
                  style={{
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    backgroundColor:
                      llmHealth?.status === 'healthy' ? 'var(--accent-emerald)' : 'var(--accent-rose)',
                  }}
                />
                {llmHealth?.status || 'Detecting...'}
              </span>
            </div>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '2px' }}>
              {llmHealth?.message || 'Connecting to 127.0.0.1:11434...'}
            </p>
          </div>
        </div>

        {/* Interactive Stream Test Input & Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: '1', maxWidth: '780px' }}>
          <select
            value={selectedTestModel}
            onChange={(e) => setSelectedTestModel(e.target.value)}
            disabled={testResult?.isStreaming}
            title="Select local model for prompt testing"
            style={{
              backgroundColor: 'var(--bg-input)',
              border: '1px solid var(--border-color)',
              borderRadius: '8px',
              color: 'var(--text-main)',
              padding: '8px 10px',
              fontSize: '0.78rem',
              outline: 'none',
              cursor: 'pointer',
              minWidth: '150px',
              maxWidth: '180px',
            }}
          >
            {models.length === 0 ? (
              <option value="">Default Model</option>
            ) : (
              models.map((m) => (
                <option key={m.model_id} value={m.model_id} disabled={!m.available}>
                  {m.display_name || m.model_name || m.model_id} {!m.available ? '(unavailable)' : ''}
                </option>
              ))
            )}
          </select>
          <input
            type="text"
            value={testPromptInput}
            onChange={(e) => setTestPromptInput(e.target.value)}
            placeholder="Type prompt to test local Ollama inference..."
            disabled={testResult?.isStreaming}
            style={{
              flex: 1,
              backgroundColor: 'var(--bg-input)',
              border: '1px solid var(--border-color)',
              borderRadius: '8px',
              color: 'var(--text-main)',
              padding: '8px 12px',
              fontSize: '0.78rem',
              outline: 'none',
              fontFamily: 'inherit',
            }}
          />
          {testResult?.isStreaming ? (
            <button
              onClick={handleCancelTestStream}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                borderRadius: '8px',
                backgroundColor: 'rgba(244, 63, 94, 0.15)',
                border: '1px solid rgba(244, 63, 94, 0.4)',
                color: 'var(--accent-rose)',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              <Square size={13} />
              Stop Test
            </button>
          ) : (
            <button
              onClick={handleStreamTestModel}
              disabled={isLoading || !testPromptInput.trim()}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 16px',
                borderRadius: '8px',
                backgroundColor: 'rgba(6, 182, 212, 0.12)',
                border: '1px solid rgba(6, 182, 212, 0.35)',
                color: 'var(--accent-cyan)',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                transition: 'all 0.15s ease',
              }}
            >
              <Sparkles size={14} />
              Stream Test Prompt
            </button>
          )}
        </div>
      </div>

      {/* Stream Test Real-time Output Banner */}
      {testResult && (
        <div
          style={{
            backgroundColor: testResult.isError ? 'rgba(244, 63, 94, 0.1)' : 'var(--bg-input)',
            border: `1px solid ${testResult.isError ? 'rgba(244, 63, 94, 0.3)' : 'var(--border-color)'}`,
            borderRadius: '8px',
            padding: '12px 18px',
            fontSize: '0.8rem',
            color: testResult.isError ? 'var(--accent-rose)' : 'var(--text-main)',
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-dim)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>{testResult.isStreaming ? '● Local Ollama Generating Stream...' : 'Streamed Inference Result'}</span>
              {selectedTestModel && (
                <span style={{ color: 'var(--accent-cyan)', textTransform: 'none', fontWeight: 600 }}>
                  [{models.find((m) => m.model_id === selectedTestModel)?.display_name || models.find((m) => m.model_id === selectedTestModel)?.model_name || selectedTestModel}]
                </span>
              )}
            </span>
            {testResult.duration > 0 && (
              <span style={{ fontSize: '0.72rem', color: 'var(--accent-cyan)', fontFamily: 'monospace' }}>
                Latency: {testResult.duration}s
              </span>
            )}
          </div>
          <pre
            style={{
              margin: 0,
              fontFamily: 'monospace',
              fontSize: '0.78rem',
              color: testResult.isError ? 'var(--accent-rose)' : '#93c5fd',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              maxHeight: '120px',
              overflowY: 'auto',
            }}
          >
            {testResult.text || (testResult.isStreaming ? 'Connecting to local model...' : '')}
          </pre>
        </div>
      )}

      {/* Global Error Banner */}
      {error && (
        <div
          style={{
            backgroundColor: 'rgba(244, 63, 94, 0.1)',
            border: '1px solid rgba(244, 63, 94, 0.3)',
            borderRadius: '8px',
            padding: '12px 18px',
            fontSize: '0.82rem',
            color: '#fb7185',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* 2. MAIN WORKSPACE GRID */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(320px, 380px) 1fr',
          gap: '24px',
          alignItems: 'start',
        }}
      >
        {/* LEFT COLUMN: CONFIGURE AGENT & TOOLS */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Create Agent Card */}
          <div
            style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '22px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '18px' }}>
              <div
                style={{
                  padding: '8px',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(6, 182, 212, 0.12)',
                  color: 'var(--accent-cyan)',
                }}
              >
                <Bot size={18} />
              </div>
              <div>
                <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#ffffff' }}>
                  Spawn Autonomous Agent
                </h3>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                  Generic ReAct agent bound to assigned VM
                </p>
              </div>
            </div>

            <form onSubmit={handleCreateAgent} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {/* Presets */}
              <div>
                <label style={{ display: 'block', fontSize: '0.72rem', fontWeight: 500, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Quick Objective Presets
                </label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {PRESETS.map((p, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => setRoleInput(p.prompt)}
                      style={{
                        padding: '4px 10px',
                        borderRadius: '6px',
                        backgroundColor: 'var(--bg-input)',
                        border: '1px solid var(--border-color)',
                        color: 'var(--text-main)',
                        fontSize: '0.7rem',
                        cursor: 'pointer',
                        transition: 'all 0.15s',
                      }}
                    >
                      {p.title}
                    </button>
                  ))}
                </div>
              </div>

              {/* Role Textarea */}
              <div>
                <label style={{ display: 'block', fontSize: '0.72rem', fontWeight: 500, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Agent Objective / Instruction
                </label>
                <textarea
                  value={roleInput}
                  onChange={(e) => setRoleInput(e.target.value)}
                  rows={3}
                  required
                  placeholder="Enter objective for the agent..."
                  style={{
                    width: '100%',
                    backgroundColor: 'var(--bg-input)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '8px',
                    color: 'var(--text-main)',
                    padding: '10px 12px',
                    fontSize: '0.8rem',
                    outline: 'none',
                    resize: 'vertical',
                    fontFamily: 'inherit',
                  }}
                />
              </div>

              {/* VM Selector */}
              <div>
                <label style={{ display: 'block', fontSize: '0.72rem', fontWeight: 500, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Target Assigned Virtual Machine
                </label>
                <select
                  value={selectedVm}
                  onChange={(e) => setSelectedVm(e.target.value)}
                  style={{
                    width: '100%',
                    backgroundColor: 'var(--bg-input)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '8px',
                    color: 'var(--text-main)',
                    padding: '8px 12px',
                    fontSize: '0.8rem',
                    outline: 'none',
                    cursor: 'pointer',
                  }}
                >
                  {vms.map((v) => (
                    <option key={v.vm_id} value={v.vm_id}>
                      {v.vm_id} ({v.virtualbox_vm_name} - {v.ssh_host})
                    </option>
                  ))}
                </select>
              </div>

              {/* Model Selector */}
              <div>
                <label style={{ display: 'block', fontSize: '0.72rem', fontWeight: 500, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Inference Model
                </label>
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  style={{
                    width: '100%',
                    backgroundColor: 'var(--bg-input)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '8px',
                    color: 'var(--text-main)',
                    padding: '8px 12px',
                    fontSize: '0.8rem',
                    outline: 'none',
                    cursor: 'pointer',
                  }}
                >
                  {models.map((m) => (
                    <option key={m.model_id} value={m.model_id} disabled={!m.available}>
                      {m.display_name || m.model_name} {m.size ? `(${m.size})` : ''} {m.thinking_supported ? '[CoT]' : '[Direct]'} {m.available ? '✓ Ready' : '✗ Unavailable'}
                    </option>
                  ))}
                </select>
              </div>

              {/* Iteration Limit */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <label style={{ fontSize: '0.72rem', fontWeight: 500, color: 'var(--text-muted)' }}>
                    Iteration Limit
                  </label>
                  <span style={{ fontSize: '0.72rem', color: 'var(--accent-cyan)', fontWeight: 600 }}>
                    {iterLimit} steps
                  </span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={20}
                  value={iterLimit}
                  onChange={(e) => setIterLimit(parseInt(e.target.value, 10))}
                  style={{ width: '100%', accentColor: 'var(--accent-cyan)' }}
                />
              </div>

              <button
                type="submit"
                disabled={isActionLoading}
                style={{
                  marginTop: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  padding: '10px 16px',
                  borderRadius: '8px',
                  backgroundColor: 'var(--accent-cyan)',
                  border: 'none',
                  color: '#000000',
                  fontSize: '0.82rem',
                  fontWeight: 700,
                  cursor: isActionLoading ? 'not-allowed' : 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                <Bot size={16} />
                {isActionLoading ? 'Creating Agent...' : 'Spawn Autonomous Agent'}
              </button>
            </form>
          </div>

          {/* Assigned Tools Card */}
          <div
            style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '20px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }}>
              <Wrench size={16} color="var(--accent-cyan)" />
              <h4 style={{ fontSize: '0.85rem', fontWeight: 600, color: '#ffffff' }}>
                Assigned Guest Tools ({tools.length})
              </h4>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {tools.map((t) => (
                <div
                  key={t.name}
                  style={{
                    backgroundColor: 'var(--bg-input)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '8px',
                    padding: '8px 12px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <code style={{ fontSize: '0.78rem', color: 'var(--accent-cyan)', fontWeight: 600 }}>
                      {t.name}
                    </code>
                    <span style={{ fontSize: '0.65rem', color: 'var(--text-dim)', textTransform: 'uppercase' }}>
                      VM Tool
                    </span>
                  </div>
                  <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '3px' }}>
                    {t.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: INDEPENDENT MULTI-AGENT WORKSPACE & LIVE TIMELINE */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Agent Navigation List / Tabs */}
          <div
            style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '14px 18px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '12px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Layers size={16} color="var(--accent-cyan)" />
              <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#ffffff' }}>
                Active Agents ({agents.length}):
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflowX: 'auto', flex: 1 }}>
              {agents.length === 0 ? (
                <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                  No agents spawned yet. Use the panel on the left to spawn an agent.
                </span>
              ) : (
                agents.map((a) => {
                  const isSelected = selectedAgentId === a.agent_id;
                  return (
                    <button
                      key={a.agent_id}
                      onClick={() => setSelectedAgentId(a.agent_id)}
                      style={{
                        padding: '6px 12px',
                        borderRadius: '8px',
                        backgroundColor: isSelected ? '#1e293b' : 'var(--bg-input)',
                        border: `1px solid ${isSelected ? 'var(--accent-cyan)' : 'var(--border-color)'}`,
                        color: isSelected ? '#ffffff' : 'var(--text-muted)',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        whiteSpace: 'nowrap',
                        transition: 'all 0.15s ease',
                      }}
                    >
                      <Bot size={13} />
                      <span>{a.agent_id}</span>
                      <span
                        style={{
                          width: '6px',
                          height: '6px',
                          borderRadius: '50%',
                          backgroundColor:
                            a.status === 'running'
                              ? 'var(--accent-amber)'
                              : a.status === 'completed'
                              ? 'var(--accent-emerald)'
                              : 'var(--text-dim)',
                        }}
                      />
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {activeAgent ? (
            <div
              style={{
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border-color)',
                borderRadius: '12px',
                padding: '24px',
                display: 'flex',
                flexDirection: 'column',
                gap: '20px',
              }}
            >
              {/* Agent Active Header */}
              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '14px',
                  borderBottom: '1px solid var(--border-color)',
                  paddingBottom: '16px',
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#ffffff' }}>
                      {activeAgent.agent_id}
                    </h3>
                    <span
                      style={{
                        padding: '3px 10px',
                        borderRadius: '20px',
                        fontSize: '0.7rem',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                        backgroundColor: `${getAgentStatusColor(activeAgent.status)}22`,
                        border: `1px solid ${getAgentStatusColor(activeAgent.status)}66`,
                        color: getAgentStatusColor(activeAgent.status),
                      }}
                    >
                      ● {formatAgentStatus(activeAgent.status)}
                    </span>
                    {isStreamConnected && activeAgent.status === 'running' && (
                      <span style={{ fontSize: '0.68rem', color: 'var(--accent-cyan)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Activity size={12} className="animate-pulse" />
                        Live Stream Connected
                      </span>
                    )}
                  </div>

                  <div style={{ display: 'flex', gap: '14px', fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                    <span>
                      Assigned VM:{' '}
                      <strong style={{ color: 'var(--accent-cyan)', fontFamily: 'monospace' }}>
                        {activeAgent.vm_id}
                      </strong>
                    </span>
                    <span>
                      Model:{' '}
                      <strong style={{ color: '#c7d2fe', fontFamily: 'monospace' }}>
                        {activeAgent.model_id}
                      </strong>
                    </span>
                  </div>
                </div>

                {/* Control Action Buttons */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {activeAgent.status === 'running' ? (
                    <button
                      onClick={() => handleStopAgent(activeAgent.agent_id)}
                      disabled={isActionLoading}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '8px 16px',
                        borderRadius: '8px',
                        backgroundColor: '#4c0519',
                        border: '1px solid #e11d48',
                        color: '#fecdd3',
                        fontSize: '0.78rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      <Square size={13} />
                      Stop Execution
                    </button>
                  ) : (
                    <button
                      onClick={() => handleStartAgent(activeAgent.agent_id)}
                      disabled={isActionLoading || activeAgent.status === 'completed' || activeAgent.status === 'stopped_iteration_limit'}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '8px 18px',
                        borderRadius: '8px',
                        backgroundColor: (activeAgent.status === 'completed' || activeAgent.status === 'stopped_iteration_limit') ? '#1e293b' : '#1e1b4b',
                        border: `1px solid ${(activeAgent.status === 'completed' || activeAgent.status === 'stopped_iteration_limit') ? '#334155' : '#4338ca'}`,
                        color: (activeAgent.status === 'completed' || activeAgent.status === 'stopped_iteration_limit') ? 'var(--text-dim)' : '#c7d2fe',
                        fontSize: '0.78rem',
                        fontWeight: 600,
                        cursor: (activeAgent.status === 'completed' || activeAgent.status === 'stopped_iteration_limit') ? 'default' : 'pointer',
                      }}
                    >
                      <Play size={13} />
                      {activeAgent.status === 'completed' ? 'Cycle Completed' : activeAgent.status === 'stopped_iteration_limit' ? 'Iteration Limit Reached' : 'Start Autonomous Run'}
                    </button>
                  )}

                  {/* Delete Agent Button */}
                  <button
                    onClick={() => setAgentToDelete(activeAgent.agent_id)}
                    disabled={isActionLoading}
                    title="Delete Agent"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      padding: '8px 12px',
                      borderRadius: '8px',
                      backgroundColor: 'rgba(244, 63, 94, 0.1)',
                      border: '1px solid rgba(244, 63, 94, 0.3)',
                      color: 'var(--accent-rose)',
                      fontSize: '0.78rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    <Trash2 size={14} />
                    Delete
                  </button>
                </div>
              </div>

              {/* Objective Banner */}
              <div
                style={{
                  backgroundColor: 'var(--bg-input)',
                  border: '1px solid var(--border-color)',
                  borderRadius: '8px',
                  padding: '12px 16px',
                }}
              >
                <span
                  style={{
                    fontSize: '0.68rem',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    color: 'var(--text-dim)',
                    letterSpacing: '0.05em',
                    display: 'block',
                    marginBottom: '4px',
                  }}
                >
                  Assigned Objective
                </span>
                <p style={{ fontSize: '0.82rem', color: 'var(--text-main)', lineHeight: 1.4 }}>
                  {activeAgent.role}
                </p>
              </div>

              {/* Telemetry Progress */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  fontSize: '0.74rem',
                  color: 'var(--text-muted)',
                }}
              >
                <span>
                  Iteration Progress: <strong>{activeAgent.current_iteration}</strong> of{' '}
                  <strong>{activeAgent.iteration_limit}</strong>
                </span>
                {activeAgent.error_message && (
                  <span style={{ color: 'var(--accent-amber)' }}>{activeAgent.error_message}</span>
                )}
              </div>

              {/* Final Agent Conclusion Card */}
              {(activeAgent.final_conclusion || (activeAgent.status !== 'running' && activeAgent.status !== 'idle')) && (
                <div
                  style={{
                    backgroundColor: '#090d16',
                    border: '1px solid rgba(56, 189, 248, 0.4)',
                    borderRadius: '8px',
                    padding: '16px 18px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span
                      style={{
                        fontSize: '0.75rem',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        color: 'var(--accent-cyan)',
                        letterSpacing: '0.05em',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                      }}
                    >
                      <Sparkles size={14} /> Agent Conclusion
                    </span>
                    <span
                      style={{
                        fontSize: '0.68rem',
                        fontWeight: 600,
                        padding: '2px 8px',
                        borderRadius: '4px',
                        backgroundColor: `${getAgentStatusColor(activeAgent.status)}22`,
                        color: getAgentStatusColor(activeAgent.status),
                        border: `1px solid ${getAgentStatusColor(activeAgent.status)}44`,
                      }}
                    >
                      {formatAgentStatus(activeAgent.status)}
                    </span>
                  </div>

                  <p style={{ fontSize: '0.82rem', color: '#e2e8f0', lineHeight: 1.5, margin: 0 }}>
                    {activeAgent.final_conclusion || 'Execution finished. No final conclusion summary recorded.'}
                  </p>

                  {/* Structured Findings & Evidence if present */}
                  {activeAgent.structured_conclusion && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '4px' }}>
                      {activeAgent.structured_conclusion.findings && activeAgent.structured_conclusion.findings.length > 0 && (
                        <div>
                          <span style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--accent-emerald)', display: 'block', marginBottom: '4px' }}>
                            Key Findings:
                          </span>
                          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.75rem', color: '#cbd5e1' }}>
                            {activeAgent.structured_conclusion.findings.map((f, i) => (
                              <li key={i}>{f}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {activeAgent.structured_conclusion.errors && activeAgent.structured_conclusion.errors.length > 0 && (
                        <div>
                          <span style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--accent-rose)', display: 'block', marginBottom: '4px' }}>
                            Errors Encountered:
                          </span>
                          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.75rem', color: '#fca5a5' }}>
                            {activeAgent.structured_conclusion.errors.map((err, i) => (
                              <li key={i}>{err}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {activeAgent.structured_conclusion.unresolved_items && activeAgent.structured_conclusion.unresolved_items.length > 0 && (
                        <div>
                          <span style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--accent-amber)', display: 'block', marginBottom: '4px' }}>
                            Unresolved Items:
                          </span>
                          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.75rem', color: '#fef08a' }}>
                            {activeAgent.structured_conclusion.unresolved_items.map((u, i) => (
                              <li key={i}>{u}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* LIVE ACTIVE EXECUTION / STREAMING CARD */}
              {(currentExecutingPhase || activeStreamingThought || activeAgent.status === 'running') && (
                <div
                  style={{
                    backgroundColor: 'rgba(6, 182, 212, 0.05)',
                    border: '1px solid rgba(6, 182, 212, 0.3)',
                    borderRadius: '8px',
                    padding: '14px 16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Zap size={15} color="var(--accent-cyan)" />
                      <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--accent-cyan)' }}>
                        {currentExecutingPhase || 'Agent In Progress...'}
                      </span>
                    </div>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)', fontFamily: 'monospace' }}>
                      Iteration {activeAgent.current_iteration + 1}
                    </span>
                  </div>

                  {/* Streamed Hidden Reasoning / Tokens Box (Only while executing) */}
                  {activeStreamingThought && (
                    <div>
                      <span
                        style={{
                          fontSize: '0.68rem',
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          color: 'var(--text-dim)',
                          display: 'block',
                          marginBottom: '4px',
                        }}
                      >
                        Model Reasoning & Generation (Streaming)...
                      </span>
                      <pre
                        style={{
                          backgroundColor: '#050811',
                          border: '1px solid #131d2e',
                          borderRadius: '6px',
                          padding: '10px 12px',
                          fontSize: '0.74rem',
                          color: '#a5f3fc',
                          overflowX: 'auto',
                          maxHeight: '140px',
                          lineHeight: 1.45,
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                        }}
                      >
                        {activeStreamingThought}
                      </pre>
                    </div>
                  )}
                </div>
              )}

              {/* Execution Steps Timeline */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                  <h4 style={{ fontSize: '0.85rem', fontWeight: 600, color: '#ffffff' }}>
                    Activity Timeline ({activeAgent.history.length} completed cycles)
                  </h4>
                  {liveEvents.length > 0 && (
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                      {liveEvents.length} telemetry events logged
                    </span>
                  )}
                </div>

                {activeAgent.history.length === 0 ? (
                  <div
                    style={{
                      padding: '40px 20px',
                      textAlign: 'center',
                      backgroundColor: 'var(--bg-input)',
                      border: '1px dashed var(--border-color)',
                      borderRadius: '8px',
                      color: 'var(--text-dim)',
                      fontSize: '0.82rem',
                    }}
                  >
                    <Terminal size={28} color="var(--text-dim)" style={{ margin: '0 auto 10px auto' }} />
                    <p>Agent is initialized and waiting for instructions.</p>
                    <p style={{ fontSize: '0.72rem', marginTop: '4px' }}>
                      Click "Start Autonomous Run" above to begin the autonomous reasoning loop.
                    </p>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxHeight: '520px', overflowY: 'auto' }}>
                    {activeAgent.history.map((step) => (
                      <div
                        key={step.step_number}
                        style={{
                          backgroundColor: 'var(--bg-input)',
                          border: `1px solid ${step.success ? 'var(--border-color)' : 'rgba(244, 63, 94, 0.4)'}`,
                          borderRadius: '8px',
                          padding: '14px',
                        }}
                      >
                        {/* Step Header */}
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            marginBottom: '8px',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span
                              style={{
                                padding: '2px 8px',
                                borderRadius: '4px',
                                backgroundColor: '#1e293b',
                                color: 'var(--accent-cyan)',
                                fontSize: '0.72rem',
                                fontWeight: 700,
                                fontFamily: 'monospace',
                              }}
                            >
                              STEP {step.step_number}
                            </span>
                            <span
                              style={{
                                padding: '2px 8px',
                                borderRadius: '4px',
                                backgroundColor: step.success ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)',
                                color: step.success ? 'var(--accent-emerald)' : 'var(--accent-rose)',
                                fontSize: '0.68rem',
                                fontWeight: 700,
                              }}
                            >
                              {step.success ? 'SUCCESS' : 'FAILED'}
                            </span>
                          </div>
                          <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)', fontFamily: 'monospace' }}>
                            {step.duration}s
                          </span>
                        </div>

                        {/* Action Summary & Tool */}
                        <div style={{ marginBottom: '10px' }}>
                          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#ffffff', marginBottom: '4px' }}>
                            {step.action.summary}
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.72rem' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Tool Invoked:</span>
                            <code style={{ color: 'var(--accent-cyan)' }}>
                              {step.action.tool}({JSON.stringify(step.action.parameters)})
                            </code>
                          </div>
                        </div>

                        {/* Guest Observation Output Console */}
                        <div>
                          <span
                            style={{
                              fontSize: '0.68rem',
                              fontWeight: 700,
                              textTransform: 'uppercase',
                              color: 'var(--text-dim)',
                              letterSpacing: '0.05em',
                              display: 'block',
                              marginBottom: '4px',
                            }}
                          >
                            Observable Tool Output
                          </span>
                          <pre
                            style={{
                              backgroundColor: '#050811',
                              border: '1px solid #131d2e',
                              borderRadius: '6px',
                              padding: '10px 12px',
                              fontSize: '0.75rem',
                              color: '#93c5fd',
                              overflowX: 'auto',
                              maxHeight: '180px',
                              lineHeight: 1.45,
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-all',
                            }}
                          >
                            {step.observation}
                          </pre>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div
              style={{
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border-color)',
                borderRadius: '12px',
                padding: '60px 20px',
                textAlign: 'center',
                color: 'var(--text-muted)',
              }}
            >
              <Bot size={40} color="var(--text-dim)" style={{ margin: '0 auto 12px auto' }} />
              <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#ffffff', marginBottom: '6px' }}>
                No Active Agent Selected
              </h3>
              <p style={{ fontSize: '0.8rem', maxWidth: '380px', margin: '0 auto' }}>
                Configure and spawn an agent from the left panel to begin autonomous operations.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* 3. CONFIRMATION MODAL FOR AGENT DELETION */}
      {agentToDelete && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '24px',
              maxWidth: '440px',
              width: '90%',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div
                style={{
                  padding: '8px',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(244, 63, 94, 0.15)',
                  color: 'var(--accent-rose)',
                }}
              >
                <Trash2 size={18} />
              </div>
              <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#ffffff' }}>
                Delete Agent Runtime?
              </h3>
            </div>

            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
              Are you sure you want to delete <strong>{agentToDelete}</strong>? Its execution history and telemetry
              will be permanently removed.
            </p>
            <p style={{ fontSize: '0.75rem', color: 'var(--accent-cyan)' }}>
              Note: The assigned VM, its snapshots, and guest files will NOT be affected.
            </p>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '6px' }}>
              <button
                onClick={() => setAgentToDelete(null)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '8px',
                  backgroundColor: 'var(--bg-input)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-main)',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => handleDeleteAgent(agentToDelete)}
                disabled={isActionLoading}
                style={{
                  padding: '8px 16px',
                  borderRadius: '8px',
                  backgroundColor: '#e11d48',
                  border: 'none',
                  color: '#ffffff',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  cursor: isActionLoading ? 'not-allowed' : 'pointer',
                }}
              >
                {isActionLoading ? 'Deleting...' : 'Confirm Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
