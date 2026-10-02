import React, { useState, useEffect, useRef, useMemo } from 'react';
import { api } from '../api/client';
import {
  ExperimentDetail,
  ExperimentSummary,
  ExperimentCreateRequest,
  ExperimentAgentConfig,
  ExperimentEvent,
} from '../types/experiment';
import { VMInfo } from '../types/vm';
import { ModelStatus } from '../types/llm';
import {
  Play,
  Square,
  RefreshCw,
  Trash2,
  Terminal,
  Activity,
  Server,
  Cpu,
  Layers,
  AlertTriangle,
  Sliders,
  CheckCircle2,
  Shield,
  FileText,
  Zap,
  Sparkles,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

interface ExperimentDashboardProps {
  vms: VMInfo[];
  maxVm: number;
}

interface VMTerminalEntry {
  timestamp: string;
  tool: string;
  command?: string;
  output?: string;
  success?: boolean;
  isRunning?: boolean;
  agentId: string;
}

interface AgentLiveState {
  step: number;
  statusText: string;
  reasoning: string;
  toolName?: string;
  toolCommand?: string;
  toolOutput?: string;
  isStreaming: boolean;
  isGeneratingInsights: boolean;
  isOutputFedBack: boolean;
}

/** Helper component to render structured markdown findings cleanly */
const MarkdownReportViewer: React.FC<{ markdown: string }> = ({ markdown }) => {
  const sections = useMemo(() => {
    const lines = markdown.split('\n');
    const result: { title: string; body: string[]; type: 'summary' | 'findings' | 'observations' | 'limitations' | 'general' }[] = [];
    let currentTitle = 'Executive Overview';
    let currentBody: string[] = [];
    let currentType: 'summary' | 'findings' | 'observations' | 'limitations' | 'general' = 'general';

    const flush = () => {
      if (currentBody.length > 0 || currentTitle !== 'Executive Overview') {
        result.push({ title: currentTitle, body: [...currentBody], type: currentType });
        currentBody = [];
      }
    };

    for (const rawLine of lines) {
      const line = rawLine.trimEnd();
      if (line.startsWith('### ') || line.startsWith('## ')) {
        flush();
        currentTitle = line.replace(/^#+\s*/, '').trim();
        const lower = currentTitle.toLowerCase();
        if (lower.includes('overall') || lower.includes('summary')) {
          currentType = 'summary';
        } else if (lower.includes('key finding') || lower.includes('findings')) {
          currentType = 'findings';
        } else if (lower.includes('per-agent') || lower.includes('agent observation')) {
          currentType = 'observations';
        } else if (lower.includes('limitation') || lower.includes('security')) {
          currentType = 'limitations';
        } else {
          currentType = 'general';
        }
      } else {
        currentBody.push(line);
      }
    }
    flush();
    return result;
  }, [markdown]);

  const getSectionBadgeStyle = (type: string) => {
    switch (type) {
      case 'summary':
        return { bg: 'rgba(56, 189, 248, 0.15)', border: '#38bdf8', color: '#38bdf8', icon: <FileText size={14} /> };
      case 'findings':
        return { bg: 'rgba(52, 211, 153, 0.15)', border: '#34d399', color: '#34d399', icon: <CheckCircle2 size={14} /> };
      case 'observations':
        return { bg: 'rgba(167, 139, 250, 0.15)', border: '#a78bfa', color: '#a78bfa', icon: <Cpu size={14} /> };
      case 'limitations':
        return { bg: 'rgba(251, 191, 36, 0.15)', border: '#fbbf24', color: '#fbbf24', icon: <Shield size={14} /> };
      default:
        return { bg: 'rgba(148, 163, 184, 0.15)', border: '#94a3b8', color: '#94a3b8', icon: <Zap size={14} /> };
    }
  };

  const renderFormattedLine = (line: string, idx: number) => {
    if (!line.trim()) return <div key={idx} style={{ height: '6px' }} />;

    const isBullet = line.trim().startsWith('- ') || line.trim().startsWith('* ');
    const cleanLine = isBullet ? line.trim().substring(2) : line;

    const parts = cleanLine.split(/(\*\*.*?\*\*)/g);
    const content = parts.map((part, pIdx) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={pIdx} style={{ color: '#ffffff', fontWeight: 600 }}>{part.slice(2, -2)}</strong>;
      }
      return part;
    });

    if (isBullet) {
      return (
        <li key={idx} style={{ marginBottom: '6px', color: '#cbd5e1', lineHeight: '1.5' }}>
          {content}
        </li>
      );
    }
    return (
      <p key={idx} style={{ margin: '4px 0', color: '#cbd5e1', lineHeight: '1.5' }}>
        {content}
      </p>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {sections.map((sec, sIdx) => {
        const style = getSectionBadgeStyle(sec.type);
        const hasBullets = sec.body.some((l) => l.trim().startsWith('- ') || l.trim().startsWith('* '));

        return (
          <div
            key={sIdx}
            style={{
              backgroundColor: '#090d16',
              border: `1px solid ${style.border}33`,
              borderLeft: `3px solid ${style.border}`,
              borderRadius: '8px',
              padding: '14px 16px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <span style={{ color: style.color }}>{style.icon}</span>
              <h5 style={{ fontSize: '0.88rem', fontWeight: 700, color: '#ffffff', margin: 0 }}>
                {sec.title}
              </h5>
            </div>
            {hasBullets ? (
              <ul style={{ margin: '4px 0 0 0', paddingLeft: '20px', fontSize: '0.8rem' }}>
                {sec.body.map((l, lIdx) => renderFormattedLine(l, lIdx))}
              </ul>
            ) : (
              <div style={{ fontSize: '0.8rem' }}>
                {sec.body.map((l, lIdx) => renderFormattedLine(l, lIdx))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export const ExperimentDashboard: React.FC<ExperimentDashboardProps> = ({ vms, maxVm }) => {
  // Metadata
  const [models, setModels] = useState<ModelStatus[]>([]);
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Active Selected Experiment
  const [selectedExpId, setSelectedExpId] = useState<string | null>(null);
  const [selectedExpDetail, setSelectedExpDetail] = useState<ExperimentDetail | null>(null);
  const [isExpActionLoading, setIsExpActionLoading] = useState(false);

  // Real-time Per-Agent Live Execution State
  const [agentLiveStates, setAgentLiveStates] = useState<Record<string, AgentLiveState>>({});
  const [expandedPastSteps, setExpandedPastSteps] = useState<Record<string, boolean>>({});

  // VM Console Terminals
  const [activeVmTerminalTab, setActiveVmTerminalTab] = useState<string>('vm-01');
  const [vmTerminalLogs, setVmTerminalLogs] = useState<Record<string, VMTerminalEntry[]>>({});

  // Builder Form State
  const [showBuilder, setShowBuilder] = useState(false);
  const [expName, setExpName] = useState('Cyber Range Concurrent Simulation');
  const [expDescription, setExpDescription] = useState('Autonomous multi-agent penetration and defensive audit on isolated subnet');
  const [agentCount, setAgentCount] = useState<number>(Math.min(2, Math.max(1, vms.length || 2)));
  const [builderAgents, setBuilderAgents] = useState<ExperimentAgentConfig[]>([
    {
      role: 'Autonomous Offensive Reconnaissance: Discover active hosts on 192.168.32.0/24, inspect open ports and running services, and report findings.',
      vm_id: vms[0]?.vm_id || 'vm-01',
      model_id: '',
      iteration_limit: 5,
      command_timeout: 180,
    },
    {
      role: 'Autonomous Defensive Security Monitor: Inspect local listening ports, active network connections, examine process tree, and verify system integrity.',
      vm_id: vms[1]?.vm_id || 'vm-02',
      model_id: '',
      iteration_limit: 5,
      command_timeout: 180,
    },
  ]);

  // Terminal scroll refs
  const terminalEndRef = useRef<HTMLDivElement | null>(null);
  const reconnectTimeoutRef = useRef<any>(null);
  const isUnmountingRef = useRef<boolean>(false);
  const selectedExpIdRef = useRef<string | null>(selectedExpId);

  useEffect(() => {
    selectedExpIdRef.current = selectedExpId;
  }, [selectedExpId]);

  // Load models and experiments list
  const loadGlobalData = async () => {
    try {
      const [modelList, expList] = await Promise.all([
        api.listModels().catch(() => []),
        api.listExperiments().catch(() => []),
      ]);
      setModels(modelList);
      setExperiments(expList);

      // Auto-select latest experiment if none selected
      if (!selectedExpId && expList.length > 0) {
        setSelectedExpId(expList[0].id);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load experiments');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadGlobalData();
  }, []);

  // Compute Assigned VMs for the current experiment dynamically
  const assignedVms = useMemo(() => {
    if (!selectedExpDetail || !selectedExpDetail.agents) return [];
    const uniqueVmIds = Array.from(new Set(selectedExpDetail.agents.map((a) => a.vm_id)));
    return uniqueVmIds.map((vmId) => {
      const vmObj = vms.find((v) => v.vm_id === vmId);
      const agent = selectedExpDetail.agents.find((a) => a.vm_id === vmId);
      return {
        vm_id: vmId,
        virtualbox_vm_name: vmObj?.virtualbox_vm_name || `cyberarena-${vmId}`,
        ssh_host: vmObj?.ssh_host || (vmId === 'vm-01' ? '192.168.32.101' : '192.168.32.102'),
        ssh_port: vmObj?.ssh_port || 22,
        state: vmObj?.state || 'RUNNING',
        agent_id: agent?.agent_id || 'unassigned',
        role: agent?.role || 'No role configured',
      };
    });
  }, [selectedExpDetail, vms]);

  // Ensure activeVmTerminalTab matches an assigned VM
  useEffect(() => {
    if (assignedVms.length > 0) {
      if (!assignedVms.some((v) => v.vm_id === activeVmTerminalTab)) {
        setActiveVmTerminalTab(assignedVms[0].vm_id);
      }
    }
  }, [assignedVms, activeVmTerminalTab]);

  // Update builder agents count
  const handleAgentCountChange = (newCount: number) => {
    const clamped = Math.max(1, Math.min(newCount, maxVm));
    setAgentCount(clamped);

    setBuilderAgents((prev) => {
      const next = [...prev];
      while (next.length < clamped) {
        const nextIdx = next.length;
        const usedVms = next.map((a) => a.vm_id);
        const availableVm = vms.find((v) => !usedVms.includes(v.vm_id))?.vm_id || vms[0]?.vm_id || `vm-${nextIdx + 1}`;
        next.push({
          role: nextIdx === 0
            ? 'Autonomous Offensive Reconnaissance: Discover active hosts, inspect open ports and report findings.'
            : 'Autonomous Defensive Security Monitor: Inspect listening sockets, active connections, and running processes.',
          vm_id: availableVm,
          model_id: models[0]?.model_id || '',
          iteration_limit: 5,
          command_timeout: 180,
        });
      }
      return next.slice(0, clamped);
    });
  };

  // Fetch selected experiment detail
  const fetchExperimentDetail = async (expId: string) => {
    try {
      const detail = await api.getExperiment(expId);
      if (selectedExpIdRef.current !== expId) return;
      setSelectedExpDetail(detail);

      // Populate VM terminal logs from past history if any
      const initLogs: Record<string, VMTerminalEntry[]> = {};
      detail.agents.forEach((agent) => {
        if (!initLogs[agent.vm_id]) initLogs[agent.vm_id] = [];
        agent.history.forEach((step) => {
          const cmdStr = (step.action.parameters && typeof step.action.parameters.command === 'string')
            ? step.action.parameters.command
            : JSON.stringify(step.action.parameters || {});
          initLogs[agent.vm_id].push({
            timestamp: step.timestamp,
            tool: step.action.tool,
            command: cmdStr,
            output: step.observation,
            success: step.success,
            isRunning: false,
            agentId: agent.agent_id,
          });
        });
      });
      setVmTerminalLogs(initLogs);
    } catch (err: any) {
      if (selectedExpIdRef.current === expId) {
        setError(`Failed to fetch experiment ${expId}: ${err.message}`);
      }
    }
  };

  useEffect(() => {
    if (!selectedExpId) {
      setSelectedExpDetail(null);
      setAgentLiveStates({});
      setVmTerminalLogs({});
      return;
    }

    // Immediately clear live state and terminal logs from previous experiment to guarantee strict isolation
    setAgentLiveStates({});
    setVmTerminalLogs({});

    fetchExperimentDetail(selectedExpId);
  }, [selectedExpId]);

  // Real-time Event Subscription (Strictly Real-Time Telemetry)
  useEffect(() => {
    if (!selectedExpId) return;

    isUnmountingRef.current = false;
    let activeCloseFn: (() => void) | null = null;

    const handleEvent = (event: ExperimentEvent) => {
      // Strict experiment isolation: discard any event not belonging to the currently selected experiment
      if (event.experiment_id && event.experiment_id !== selectedExpIdRef.current) {
        return;
      }

      const agentId = event.agent_id;

      // 1. Live Agent Step & Reasoning Management
      if (agentId) {
        if (event.event_type === 'agent_iteration_started') {
          setAgentLiveStates((prev) => ({
            ...prev,
            [agentId]: {
              step: event.iteration || (prev[agentId]?.step ? prev[agentId].step + 1 : 1),
              statusText: 'LLM Reasoning & Generation...',
              reasoning: '',
              toolName: undefined,
              toolCommand: undefined,
              toolOutput: undefined,
              isStreaming: true,
              isGeneratingInsights: false,
              isOutputFedBack: false,
            },
          }));
        } else if (event.event_type === 'llm_chunk') {
          const chunk = event.content || '';
          const accumulated = (event.data && typeof event.data.accumulated === 'string')
            ? event.data.accumulated
            : null;
          setAgentLiveStates((prev) => {
            const curr = prev[agentId] || {
              step: 1,
              statusText: 'LLM Reasoning & Generation...',
              reasoning: '',
              isStreaming: true,
              isGeneratingInsights: false,
              isOutputFedBack: false,
            };
            return {
              ...prev,
              [agentId]: {
                ...curr,
                reasoning: accumulated !== null ? accumulated : (curr.reasoning + chunk),
                isStreaming: true,
              },
            };
          });
        } else if (event.event_type === 'llm_completed') {
          setAgentLiveStates((prev) => {
            const curr = prev[agentId];
            if (!curr) return prev;
            return {
              ...prev,
              [agentId]: {
                ...curr,
                reasoning: event.thinking || event.content || curr.reasoning,
                statusText: 'Tool Requested by LLM',
                isStreaming: false,
              },
            };
          });
        } else if (event.event_type === 'agent_action_requested' || event.event_type === 'tool_started') {
          const tool = event.tool_name || 'execute_command';
          const cmd = event.parameters?.command || event.data?.parameters?.command || event.summary || '';
          setAgentLiveStates((prev) => {
            const curr = prev[agentId] || {
              step: 1,
              statusText: 'Executing Tool...',
              reasoning: '',
              isStreaming: false,
              isGeneratingInsights: false,
              isOutputFedBack: false,
            };
            return {
              ...prev,
              [agentId]: {
                ...curr,
                toolName: tool,
                toolCommand: typeof cmd === 'string' ? cmd : JSON.stringify(cmd),
                statusText: `Executing Tool: ${tool}`,
                isOutputFedBack: false,
              },
            };
          });
        } else if (event.event_type === 'agent_tool_output_chunk') {
          const chunk = event.output_chunk || event.data?.output_chunk || event.content || '';
          setAgentLiveStates((prev) => {
            const curr = prev[agentId];
            if (!curr) return prev;
            return {
              ...prev,
              [agentId]: {
                ...curr,
                toolOutput: (curr.toolOutput || '') + chunk,
                statusText: 'Receiving Tool Output...',
              },
            };
          });
        } else if (event.event_type === 'tool_completed' || event.event_type === 'agent_observation_received') {
          const out = event.content || event.data?.output || '';
          setAgentLiveStates((prev) => {
            const curr = prev[agentId];
            if (!curr) return prev;
            return {
              ...prev,
              [agentId]: {
                ...curr,
                toolOutput: out || curr.toolOutput || '',
                statusText: 'Output received and fed back to LLM for next step',
                isStreaming: false,
                isOutputFedBack: true,
              },
            };
          });
        } else if (
          event.event_type === 'agent_status_changed' &&
          (event.content?.toLowerCase().includes('insight') || (event as any).status === 'generating_insights')
        ) {
          setAgentLiveStates((prev) => ({
            ...prev,
            [agentId]: {
              step: prev[agentId]?.step || 1,
              statusText: 'iteration complete generating insights',
              reasoning: '',
              isStreaming: true,
              isGeneratingInsights: true,
              isOutputFedBack: false,
            },
          }));
        } else if (event.event_type === 'agent_final_conclusion') {
          setAgentLiveStates((prev) => {
            const curr = prev[agentId];
            return {
              ...prev,
              [agentId]: {
                step: curr?.step || 1,
                statusText: 'Execution Complete - Insights Synthesized',
                reasoning: event.conclusion || event.content || curr?.reasoning || '',
                isStreaming: false,
                isGeneratingInsights: false,
                isOutputFedBack: false,
              },
            };
          });
        }
      }

      // 2. VM Terminal Logs Streaming
      if (event.event_type === 'agent_tool_output_chunk') {
        const vmId = event.vm_id || event.data?.vm_id || selectedExpDetail?.agents.find((a) => a.agent_id === event.agent_id)?.vm_id;
        const chunk = event.output_chunk || event.data?.output_chunk || event.content || '';
        if (vmId && chunk) {
          setVmTerminalLogs((prev) => {
            const logs = prev[vmId] ? [...prev[vmId]] : [];
            if (logs.length > 0 && logs[logs.length - 1].isRunning) {
              const last = { ...logs[logs.length - 1] };
              last.output = (last.output || '') + chunk;
              logs[logs.length - 1] = last;
            } else {
              logs.push({
                timestamp: event.timestamp || new Date().toISOString(),
                tool: event.tool_name || 'execute_command',
                command: 'streaming...',
                output: chunk,
                isRunning: true,
                agentId: event.agent_id || 'agent',
              });
            }
            return { ...prev, [vmId]: logs };
          });
        }
      }

      // Tool starting or action requested in terminal
      if (event.event_type === 'agent_action_requested' || event.event_type === 'tool_started') {
        const vmId = event.vm_id || event.data?.vm_id || selectedExpDetail?.agents.find((a) => a.agent_id === event.agent_id)?.vm_id;
        if (vmId) {
          const cmdStr = (event.parameters && typeof event.parameters.command === 'string')
            ? event.parameters.command
            : (event.data?.parameters && typeof event.data.parameters.command === 'string')
            ? event.data.parameters.command
            : (event.summary || event.tool_name || 'Executing...');

          setVmTerminalLogs((prev) => {
            const logs = prev[vmId] ? [...prev[vmId]] : [];
            if (logs.length > 0 && logs[logs.length - 1].isRunning && logs[logs.length - 1].command === cmdStr) {
              return prev;
            }
            logs.push({
              timestamp: event.timestamp || new Date().toISOString(),
              tool: event.tool_name || 'tool',
              command: cmdStr,
              output: '',
              isRunning: true,
              agentId: event.agent_id || 'agent',
            });
            return { ...prev, [vmId]: logs };
          });
        }
      }

      // Tool completion or failure in terminal
      if (event.event_type === 'tool_completed' || event.event_type === 'tool_failed') {
        const vmId = event.vm_id || event.data?.vm_id || selectedExpDetail?.agents.find((a) => a.agent_id === event.agent_id)?.vm_id;
        if (vmId) {
          const outputText = event.content || event.data?.output || event.error || '';
          const cmdStr = (event.parameters && typeof event.parameters.command === 'string')
            ? event.parameters.command
            : (event.data?.parameters && typeof event.data.parameters.command === 'string')
            ? event.data.parameters.command
            : undefined;

          setVmTerminalLogs((prev) => {
            const logs = prev[vmId] ? [...prev[vmId]] : [];
            if (logs.length > 0 && logs[logs.length - 1].isRunning) {
              const last = { ...logs[logs.length - 1] };
              last.isRunning = false;
              last.success = event.event_type === 'tool_completed';
              if (outputText && (!last.output || outputText.length > last.output.length)) {
                last.output = outputText;
              }
              if (cmdStr && (last.command === 'streaming...' || !last.command)) {
                last.command = cmdStr;
              }
              logs[logs.length - 1] = last;
            } else {
              logs.push({
                timestamp: event.timestamp,
                tool: event.tool_name || 'tool',
                command: cmdStr || event.summary || '',
                output: outputText,
                success: event.event_type === 'tool_completed',
                isRunning: false,
                agentId: event.agent_id || 'unknown',
              });
            }
            return { ...prev, [vmId]: logs };
          });
        }
      }

      // 3. Update Agent State in-place
      setSelectedExpDetail((prev) => {
        if (!prev) return prev;
        const updatedAgents = prev.agents.map((ag) => {
          if (ag.agent_id === event.agent_id) {
            const copy = { ...ag };
            if (event.event_type === 'agent_iteration_started') {
              copy.current_iteration = event.iteration;
              copy.status = 'running';
            } else if (event.event_type === 'agent_iteration_completed') {
              copy.current_iteration = event.iteration;
              const stepRec = event.data?.step_record;
              if (stepRec) {
                const hist = copy.history ? [...copy.history] : [];
                const existingIdx = hist.findIndex((s: any) => s.step_number === stepRec.step_number);
                if (existingIdx >= 0) {
                  hist[existingIdx] = stepRec;
                } else {
                  hist.push(stepRec);
                }
                copy.history = hist;
              }
            } else if (event.event_type === 'agent_final_conclusion') {
              copy.final_conclusion = event.conclusion || event.content || copy.final_conclusion;
              copy.status = 'completed';
            } else if (event.event_type === 'agent_completed') {
              copy.status = 'completed';
            } else if (event.event_type === 'agent_failed') {
              copy.status = 'failed';
              copy.error_message = event.error || copy.error_message;
            }
            return copy;
          }
          return ag;
        });

        let expConclusion = prev.final_conclusion;
        if (event.event_type === 'experiment_summary_updated' || event.event_type === 'experiment_completed') {
          expConclusion = event.conclusion || (event.data?.final_conclusion) || expConclusion;
        }

        return {
          ...prev,
          agents: updatedAgents,
          final_conclusion: expConclusion,
          status: event.event_type === 'experiment_completed' ? 'completed' : event.event_type === 'experiment_stopped' ? 'stopped' : prev.status,
        };
      });

      // Lifecycle updates
      if (
        event.event_type === 'experiment_started' ||
        event.event_type === 'experiment_completed' ||
        event.event_type === 'experiment_stopped' ||
        event.event_type === 'experiment_summary_updated'
      ) {
        fetchExperimentDetail(selectedExpId);
        api.listExperiments().then(setExperiments).catch(() => {});
      }
    };

    const setupConnection = () => {
      if (activeCloseFn) {
        try { activeCloseFn(); } catch {}
        activeCloseFn = null;
      }
      try {
        const wsClient = api.connectExperimentWS(
          selectedExpId,
          handleEvent,
          () => {},
          () => {
            if (!isUnmountingRef.current && selectedExpIdRef.current === selectedExpId) {
              reconnectTimeoutRef.current = setTimeout(setupConnection, 3000);
            }
          },
          () => {}
        );
        activeCloseFn = wsClient.close;
      } catch {
        const sseCleanup = api.subscribeExperimentSSE(selectedExpId, handleEvent, () => {});
        activeCloseFn = sseCleanup;
      }
    };

    setupConnection();

    return () => {
      isUnmountingRef.current = true;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (activeCloseFn) activeCloseFn();
    };
  }, [selectedExpId]);

  // Terminal scroll auto-scroll
  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [vmTerminalLogs, activeVmTerminalTab]);

  // Create Experiment Submit
  const handleCreateExperiment = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsExpActionLoading(true);
    setError(null);

    const usedVms = builderAgents.map((a) => a.vm_id);
    if (new Set(usedVms).size !== usedVms.length) {
      setError('Each agent must be assigned to a different VM. Please select unique VMs.');
      setIsExpActionLoading(false);
      return;
    }

    try {
      const payload: ExperimentCreateRequest = {
        name: expName.trim(),
        description: expDescription.trim() || undefined,
        agents: builderAgents.map((a) => ({
          ...a,
          model_id: a.model_id || undefined,
        })),
      };

      const created = await api.createExperiment(payload);
      setAgentLiveStates({});
      setVmTerminalLogs({});
      setSelectedExpId(created.id);
      setSelectedExpDetail(created);
      setShowBuilder(false);
      await loadGlobalData();
    } catch (err: any) {
      setError(err.message || 'Failed to create experiment');
    } finally {
      setIsExpActionLoading(false);
    }
  };

  // Start Experiment
  const handleStartExperiment = async () => {
    if (!selectedExpId) return;
    setIsExpActionLoading(true);
    setError(null);
    try {
      setAgentLiveStates({});
      setVmTerminalLogs({});
      await api.startExperiment(selectedExpId);
      await fetchExperimentDetail(selectedExpId);
      await loadGlobalData();
    } catch (err: any) {
      setError(err.message || 'Failed to start experiment');
    } finally {
      setIsExpActionLoading(false);
    }
  };

  // Stop Experiment
  const handleStopExperiment = async () => {
    if (!selectedExpId) return;
    setIsExpActionLoading(true);
    setError(null);
    try {
      await api.stopExperiment(selectedExpId);
      await fetchExperimentDetail(selectedExpId);
      await loadGlobalData();
    } catch (err: any) {
      setError(err.message || 'Failed to stop experiment');
    } finally {
      setIsExpActionLoading(false);
    }
  };

  // Delete Experiment
  const handleDeleteExperiment = async (expId: string) => {
    if (!confirm('Are you sure you want to delete this experiment and all associated agent logs?')) return;
    setIsExpActionLoading(true);
    try {
      await api.deleteExperiment(expId);
      if (selectedExpId === expId) {
        setSelectedExpId(null);
        setSelectedExpDetail(null);
      }
      await loadGlobalData();
    } catch (err: any) {
      setError(err.message || 'Failed to delete experiment');
    } finally {
      setIsExpActionLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'running':
        return '#38bdf8';
      case 'completed':
        return '#34d399';
      case 'stopped':
        return '#fbbf24';
      case 'failed':
        return '#ef4444';
      default:
        return '#94a3b8';
    }
  };

  const currentActiveVm = assignedVms.find((v) => v.vm_id === activeVmTerminalTab);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* 1. Header Toolbar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '12px',
          padding: '16px 20px',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              padding: '10px',
              borderRadius: '8px',
              backgroundColor: 'rgba(56, 189, 248, 0.12)',
              color: '#38bdf8',
            }}
          >
            <Shield size={24} />
          </div>
          <div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#ffffff', margin: 0 }}>
              Multi-Agent Security Range (Phase 3)
            </h2>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0 }}>
              Real-time autonomous ReAct execution across isolated Ubuntu VMs.
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={() => setShowBuilder(!showBuilder)}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              backgroundColor: showBuilder ? '#1e293b' : '#38bdf8',
              color: showBuilder ? '#ffffff' : '#0f172a',
              border: 'none',
              fontWeight: 600,
              fontSize: '0.85rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <Sliders size={16} />
            {showBuilder ? 'Close Scenario Builder' : 'New Scenario Builder'}
          </button>

          <button
            onClick={loadGlobalData}
            disabled={isLoading}
            style={{
              padding: '8px 12px',
              borderRadius: '8px',
              backgroundColor: '#1e293b',
              color: '#ffffff',
              border: '1px solid var(--border-color)',
              cursor: isLoading ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
            title="Refresh list"
          >
            <RefreshCw size={15} className={isLoading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {error && (
        <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.15)', border: '1px solid #ef4444', borderRadius: '8px', padding: '12px 16px', color: '#fca5a5', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <AlertTriangle size={18} />
          <span style={{ fontSize: '0.85rem', flex: 1 }}>{error}</span>
          <button onClick={() => setError(null)} style={{ background: 'none', border: 'none', color: '#fca5a5', cursor: 'pointer' }}>&times;</button>
        </div>
      )}

      {/* Scenario Builder Modal / Form */}
      {showBuilder && (
        <div
          style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '24px',
            boxShadow: '0 8px 30px rgba(0,0,0,0.4)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <div>
              <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#ffffff', margin: 0 }}>
                Configure Multi-Agent Scenario
              </h3>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0 }}>
                Assign autonomous agents to isolated laboratory VMs with custom cyber objectives.
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                Agents Count:
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {[1, 2].map((num) => (
                  <button
                    key={num}
                    type="button"
                    onClick={() => handleAgentCountChange(num)}
                    style={{
                      padding: '4px 12px',
                      borderRadius: '6px',
                      backgroundColor: agentCount === num ? '#38bdf8' : '#1e293b',
                      color: agentCount === num ? '#0f172a' : '#ffffff',
                      border: 'none',
                      fontWeight: 700,
                      fontSize: '0.8rem',
                      cursor: 'pointer',
                    }}
                  >
                    {num} Agent{num > 1 ? 's' : ''}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <form onSubmit={handleCreateExperiment} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Experiment Title
                </label>
                <input
                  type="text"
                  value={expName}
                  onChange={(e) => setExpName(e.target.value)}
                  required
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    backgroundColor: '#090d16',
                    border: '1px solid var(--border-color)',
                    color: '#ffffff',
                    fontSize: '0.85rem',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Description / Scenario Objective
                </label>
                <input
                  type="text"
                  value={expDescription}
                  onChange={(e) => setExpDescription(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    backgroundColor: '#090d16',
                    border: '1px solid var(--border-color)',
                    color: '#ffffff',
                    fontSize: '0.85rem',
                  }}
                />
              </div>
            </div>

            {/* Dynamic Agent Cards Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fit, minmax(340px, 1fr))`, gap: '16px' }}>
              {builderAgents.map((ag, idx) => (
                <div
                  key={idx}
                  style={{
                    backgroundColor: '#0a0f1d',
                    border: '1px solid #1e293b',
                    borderRadius: '10px',
                    padding: '16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '12px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #1e293b', paddingBottom: '8px' }}>
                    <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Cpu size={14} /> Agent {idx + 1}
                    </span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', backgroundColor: '#1e293b', padding: '2px 8px', borderRadius: '4px' }}>
                      Isolated Runtime
                    </span>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                      Assigned Laboratory VM (Target Node)
                    </label>
                    <select
                      value={ag.vm_id}
                      onChange={(e) => {
                        const val = e.target.value;
                        setBuilderAgents((prev) => {
                          const copy = [...prev];
                          copy[idx] = { ...copy[idx], vm_id: val };
                          return copy;
                        });
                      }}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: '6px',
                        backgroundColor: '#090d16',
                        border: '1px solid var(--border-color)',
                        color: '#ffffff',
                        fontSize: '0.8rem',
                      }}
                    >
                      {vms.map((v) => (
                        <option key={v.vm_id} value={v.vm_id}>
                          {v.vm_id} ({v.ssh_host}) - {v.virtualbox_vm_name}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                      Local LLM Inference Engine
                    </label>
                    <select
                      value={ag.model_id}
                      onChange={(e) => {
                        const val = e.target.value;
                        setBuilderAgents((prev) => {
                          const copy = [...prev];
                          copy[idx] = { ...copy[idx], model_id: val };
                          return copy;
                        });
                      }}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: '6px',
                        backgroundColor: '#090d16',
                        border: '1px solid var(--border-color)',
                        color: '#ffffff',
                        fontSize: '0.8rem',
                      }}
                    >
                      <option value="">Default Model ({models[0]?.display_name || models[0]?.model_name || 'qwen2.5:1.5b'})</option>
                      {models.map((m) => (
                        <option key={m.model_id} value={m.model_id} disabled={!m.installed}>
                          {m.installed ? '✓' : '✗'} {m.display_name || m.model_name} {m.size ? `(${m.size})` : ''} {m.thinking_supported ? '[CoT]' : '[Direct]'} {!m.installed ? '- Not Installed' : ''}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                      Objective / Prompt
                    </label>
                    <textarea
                      value={ag.role}
                      rows={3}
                      onChange={(e) => {
                        const val = e.target.value;
                        setBuilderAgents((prev) => {
                          const copy = [...prev];
                          copy[idx] = { ...copy[idx], role: val };
                          return copy;
                        });
                      }}
                      required
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: '6px',
                        backgroundColor: '#090d16',
                        border: '1px solid var(--border-color)',
                        color: '#ffffff',
                        fontSize: '0.8rem',
                        resize: 'vertical',
                      }}
                    />
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: '2px' }}>
                        Iteration Limit
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={20}
                        value={ag.iteration_limit || 5}
                        onChange={(e) => {
                          const val = parseInt(e.target.value) || 5;
                          setBuilderAgents((prev) => {
                            const copy = [...prev];
                            copy[idx] = { ...copy[idx], iteration_limit: val };
                            return copy;
                          });
                        }}
                        style={{
                          width: '100%',
                          padding: '6px 10px',
                          borderRadius: '6px',
                          backgroundColor: '#090d16',
                          border: '1px solid var(--border-color)',
                          color: '#ffffff',
                          fontSize: '0.8rem',
                        }}
                      />
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: '2px' }}>
                        Command Timeout (s)
                      </label>
                      <input
                        type="number"
                        min={10}
                        max={300}
                        value={ag.command_timeout || 180}
                        onChange={(e) => {
                          const val = parseInt(e.target.value) || 180;
                          setBuilderAgents((prev) => {
                            const copy = [...prev];
                            copy[idx] = { ...copy[idx], command_timeout: val };
                            return copy;
                          });
                        }}
                        style={{
                          width: '100%',
                          padding: '6px 10px',
                          borderRadius: '6px',
                          backgroundColor: '#090d16',
                          border: '1px solid var(--border-color)',
                          color: '#ffffff',
                          fontSize: '0.8rem',
                        }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
              <button
                type="button"
                onClick={() => setShowBuilder(false)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '8px',
                  backgroundColor: '#1e293b',
                  color: '#ffffff',
                  border: 'none',
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isExpActionLoading}
                style={{
                  padding: '8px 20px',
                  borderRadius: '8px',
                  backgroundColor: '#38bdf8',
                  color: '#0f172a',
                  border: 'none',
                  fontWeight: 700,
                  fontSize: '0.85rem',
                  cursor: isExpActionLoading ? 'not-allowed' : 'pointer',
                }}
              >
                {isExpActionLoading ? 'Creating...' : 'Deploy Scenario'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Experiments Selector Bar */}
      <div style={{ display: 'flex', gap: '10px', overflowX: 'auto', paddingBottom: '4px' }}>
        {experiments.map((exp) => (
          <div
            key={exp.id}
            onClick={() => setSelectedExpId(exp.id)}
            style={{
              padding: '10px 14px',
              borderRadius: '8px',
              backgroundColor: selectedExpId === exp.id ? '#1e293b' : 'var(--bg-card)',
              border: `1px solid ${selectedExpId === exp.id ? '#38bdf8' : 'var(--border-color)'}`,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              minWidth: '220px',
              transition: 'all 0.15s ease',
            }}
          >
            <div
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: getStatusColor(exp.status),
              }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#ffffff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {exp.name}
              </div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                {exp.agent_count} agent{exp.agent_count > 1 ? 's' : ''} &bull; {exp.status.toUpperCase()}
              </div>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleDeleteExperiment(exp.id);
              }}
              title="Delete experiment"
              style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', padding: '4px' }}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      {/* Active Selected Experiment Details */}
      {selectedExpDetail ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Experiment Control Bar */}
          <div
            style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '16px 20px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '16px',
            }}
          >
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <h3 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#ffffff', margin: 0 }}>
                  {selectedExpDetail.name}
                </h3>
                <span
                  style={{
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    padding: '3px 10px',
                    borderRadius: '20px',
                    backgroundColor: `${getStatusColor(selectedExpDetail.status)}22`,
                    color: getStatusColor(selectedExpDetail.status),
                    border: `1px solid ${getStatusColor(selectedExpDetail.status)}`,
                  }}
                >
                  {selectedExpDetail.status}
                </span>
              </div>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: '4px 0 0 0' }}>
                ID: <code>{selectedExpDetail.id}</code> &bull; Created: {new Date(selectedExpDetail.created_at).toLocaleTimeString()}
              </p>
            </div>

            {/* Action Buttons */}
            <div style={{ display: 'flex', gap: '10px' }}>
              {selectedExpDetail.status === 'running' ? (
                <button
                  onClick={handleStopExperiment}
                  disabled={isExpActionLoading}
                  style={{
                    padding: '8px 18px',
                    borderRadius: '8px',
                    backgroundColor: '#ef4444',
                    color: '#ffffff',
                    border: 'none',
                    fontWeight: 600,
                    fontSize: '0.85rem',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}
                >
                  <Square size={16} /> Stop Experiment
                </button>
              ) : (
                <button
                  onClick={handleStartExperiment}
                  disabled={isExpActionLoading}
                  style={{
                    padding: '8px 22px',
                    borderRadius: '8px',
                    backgroundColor: '#38bdf8',
                    color: '#0f172a',
                    border: 'none',
                    fontWeight: 700,
                    fontSize: '0.85rem',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}
                >
                  <Play size={16} /> Run Concurrent Experiment
                </button>
              )}
            </div>
          </div>

          {/* ACTIVE AGENTS REAL-TIME EXECUTION PANELS */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(460px, 1fr))', gap: '18px' }}>
            {selectedExpDetail.agents.map((agent) => {
              const live = agentLiveStates[agent.agent_id];
              const isPastExpanded = !!expandedPastSteps[agent.agent_id];
              const isRunning = agent.status === 'running';

              return (
                <div
                  key={agent.agent_id}
                  style={{
                    backgroundColor: 'var(--bg-card)',
                    border: `1px solid ${isRunning ? '#38bdf866' : 'var(--border-color)'}`,
                    borderRadius: '12px',
                    padding: '20px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '14px',
                    boxShadow: isRunning ? '0 0 20px rgba(56, 189, 248, 0.08)' : 'none',
                  }}
                >
                  {/* Agent Header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Cpu size={18} color="#38bdf8" />
                        <h4 style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff', margin: 0 }}>
                          {agent.agent_id}
                        </h4>
                        <span
                          style={{
                            fontSize: '0.68rem',
                            fontWeight: 700,
                            padding: '2px 8px',
                            borderRadius: '4px',
                            backgroundColor: 'rgba(56, 189, 248, 0.15)',
                            color: '#38bdf8',
                            border: '1px solid rgba(56, 189, 248, 0.3)',
                          }}
                        >
                          Target: {agent.vm_id}
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '6px', fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                        <span>Model: <strong style={{ color: '#38bdf8' }}>{models.find((m) => m.model_id === agent.model_id || m.model_name === agent.model_id)?.display_name || agent.model_id}</strong></span>
                        <span
                          style={{
                            fontSize: '0.65rem',
                            padding: '1px 6px',
                            borderRadius: '3px',
                            backgroundColor: 'rgba(56, 189, 248, 0.12)',
                            border: '1px solid rgba(56, 189, 248, 0.3)',
                            color: '#7dd3fc',
                          }}
                        >
                          {models.find((m) => m.model_id === agent.model_id)?.thinking_supported ? '🧠 CoT' : '⚡ Fast Direct'}
                        </span>
                        <span>&bull; Limit: {agent.iteration_limit}</span>
                      </div>
                    </div>

                    <span
                      style={{
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        padding: '3px 10px',
                        borderRadius: '6px',
                        backgroundColor: `${getStatusColor(agent.status)}22`,
                        color: getStatusColor(agent.status),
                        border: `1px solid ${getStatusColor(agent.status)}44`,
                      }}
                    >
                      {agent.status}
                    </span>
                  </div>

                  {/* Objective */}
                  <div style={{ backgroundColor: '#090d16', border: '1px solid #1e293b', borderRadius: '8px', padding: '10px 14px' }}>
                    <span style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: '2px' }}>
                      Objective:
                    </span>
                    <p style={{ fontSize: '0.8rem', color: '#e2e8f0', margin: 0, lineHeight: 1.4 }}>
                      {agent.role}
                    </p>
                  </div>

                  {/* Step Progress Bar */}
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                      <span>Progress</span>
                      <span>
                        Iteration {agent.current_iteration} of {agent.iteration_limit}
                      </span>
                    </div>
                    <div style={{ height: '6px', backgroundColor: '#1e293b', borderRadius: '3px', overflow: 'hidden' }}>
                      <div
                        style={{
                          height: '100%',
                          backgroundColor: '#38bdf8',
                          width: `${Math.min(100, (agent.current_iteration / agent.iteration_limit) * 100)}%`,
                          transition: 'width 0.3s ease',
                        }}
                      />
                    </div>
                  </div>

                  {/* REAL-TIME CURRENT STEP PROCESSING CARD */}
                  {live ? (
                    <div
                      style={{
                        backgroundColor: '#090e1a',
                        border: `1px solid ${live.isGeneratingInsights ? '#a78bfa' : '#38bdf866'}`,
                        borderRadius: '8px',
                        padding: '14px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '10px',
                      }}
                    >
                      {/* Step Status Badge */}
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <Activity size={14} color={live.isGeneratingInsights ? '#a78bfa' : '#38bdf8'} className={live.isStreaming ? 'animate-spin' : ''} />
                          <span
                            style={{
                              fontSize: '0.8rem',
                              fontWeight: 700,
                              color: live.isGeneratingInsights ? '#a78bfa' : '#38bdf8',
                              textTransform: live.isGeneratingInsights ? 'uppercase' : 'none',
                            }}
                          >
                            {live.statusText}
                          </span>
                        </div>
                        <span style={{ fontSize: '0.72rem', color: '#64748b', fontFamily: 'monospace' }}>
                          Step {live.step}
                        </span>
                      </div>

                      {/* 1. Actual Text / Reasoning Generated by LLM */}
                      {live.reasoning && (
                        <div>
                          <span style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>
                            {live.isGeneratingInsights ? 'LLM Synthesized Insights (Streaming):' : 'LLM Reasoning & Thought Generation:'}
                          </span>
                          <pre
                            style={{
                              margin: 0,
                              padding: '10px 12px',
                              backgroundColor: '#050811',
                              border: '1px solid #131d2e',
                              borderRadius: '6px',
                              fontSize: '0.75rem',
                              color: live.isGeneratingInsights ? '#ddd6fe' : '#a5f3fc',
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              maxHeight: '140px',
                              overflowY: 'auto',
                              lineHeight: 1.45,
                              fontFamily: 'monospace',
                            }}
                          >
                            {live.reasoning}
                          </pre>
                        </div>
                      )}

                      {/* 2. Tool Request & Command */}
                      {live.toolName && (
                        <div style={{ backgroundColor: '#0c1322', border: '1px solid #1e293b', borderRadius: '6px', padding: '8px 12px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.74rem', color: '#94a3b8' }}>
                            <span>Tool Request:</span>
                            <code style={{ color: '#38bdf8', fontWeight: 700 }}>{live.toolName}</code>
                          </div>
                          {live.toolCommand && (
                            <div style={{ marginTop: '4px', fontSize: '0.75rem', color: '#ffffff', fontFamily: 'monospace' }}>
                              <span style={{ color: '#34d399' }}>$ </span>{live.toolCommand}
                            </div>
                          )}
                        </div>
                      )}

                      {/* 3. Actual Command Output Received from VM */}
                      {live.toolOutput && (
                        <div>
                          <span style={{ fontSize: '0.7rem', fontWeight: 600, color: '#34d399', display: 'block', marginBottom: '4px' }}>
                            Actual VM Output Received:
                          </span>
                          <pre
                            style={{
                              margin: 0,
                              padding: '10px 12px',
                              backgroundColor: '#050811',
                              border: '1px solid #131d2e',
                              borderRadius: '6px',
                              fontSize: '0.75rem',
                              color: '#cbd5e1',
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              maxHeight: '140px',
                              overflowY: 'auto',
                              lineHeight: 1.4,
                              fontFamily: 'monospace',
                            }}
                          >
                            {live.toolOutput}
                          </pre>
                        </div>
                      )}

                      {/* 4. Feedback to LLM Indicator */}
                      {live.isOutputFedBack && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem', color: '#34d399', backgroundColor: 'rgba(52, 211, 153, 0.08)', padding: '6px 10px', borderRadius: '4px' }}>
                          <CheckCircle2 size={13} />
                          <span>Output fed back into LLM context for next iteration</span>
                        </div>
                      )}
                    </div>
                  ) : isRunning ? (
                    <div style={{ backgroundColor: '#090e1a', border: '1px dashed #38bdf844', borderRadius: '8px', padding: '16px', textAlign: 'center' }}>
                      <Activity size={18} color="#38bdf8" className="animate-spin" style={{ margin: '0 auto 6px auto' }} />
                      <div style={{ fontSize: '0.8rem', color: '#38bdf8', fontWeight: 600 }}>
                        Agent Initializing Reasoning Loop...
                      </div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        Waiting for first inference iteration.
                      </div>
                    </div>
                  ) : null}

                  {/* Individual Agent Final Conclusion Card */}
                  {agent.final_conclusion && (
                    <div style={{ backgroundColor: 'rgba(52, 211, 153, 0.08)', border: '1px solid #34d39966', borderRadius: '8px', padding: '12px 14px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                        <Sparkles size={14} color="#34d399" />
                        <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#34d399' }}>
                          Agent Evidence-Based Conclusion
                        </span>
                      </div>
                      <p style={{ margin: 0, fontSize: '0.78rem', color: '#e2e8f0', lineHeight: 1.45 }}>
                        {agent.final_conclusion}
                      </p>
                    </div>
                  )}

                  {/* Completed Steps History */}
                  {agent.history.length > 0 && (
                    <div>
                      <button
                        onClick={() =>
                          setExpandedPastSteps((prev) => ({
                            ...prev,
                            [agent.agent_id]: !prev[agent.agent_id],
                          }))
                        }
                        style={{
                          width: '100%',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          backgroundColor: '#0c1322',
                          border: '1px solid #1e293b',
                          borderRadius: '6px',
                          padding: '8px 12px',
                          color: '#94a3b8',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        <span>Completed Steps ({agent.history.length})</span>
                        {isPastExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>

                      {isPastExpanded && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '10px', maxHeight: '300px', overflowY: 'auto' }}>
                          {agent.history.map((step) => (
                            <div
                              key={step.step_number}
                              style={{
                                backgroundColor: '#090d16',
                                border: '1px solid #1e293b',
                                borderRadius: '6px',
                                padding: '10px',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '6px',
                              }}
                            >
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#38bdf8', fontFamily: 'monospace' }}>
                                  STEP {step.step_number}
                                </span>
                                <span style={{ fontSize: '0.68rem', color: step.success ? '#34d399' : '#f87171' }}>
                                  {step.success ? '✓ SUCCESS' : '✗ FAILED'} ({step.duration}s)
                                </span>
                              </div>

                              <div style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>
                                {step.action.summary}
                              </div>

                              <div style={{ fontSize: '0.72rem', color: '#38bdf8', fontFamily: 'monospace' }}>
                                Tool: {step.action.tool}({JSON.stringify(step.action.parameters)})
                              </div>

                              <pre
                                style={{
                                  margin: '2px 0 0 0',
                                  padding: '6px 8px',
                                  backgroundColor: '#050811',
                                  borderRadius: '4px',
                                  fontSize: '0.7rem',
                                  color: '#94a3b8',
                                  whiteSpace: 'pre-wrap',
                                  maxHeight: '90px',
                                  overflowY: 'auto',
                                }}
                              >
                                {step.observation}
                              </pre>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* DYNAMIC PER-VM LIVE TERMINAL CONSOLE */}
          <section
            style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
              <div>
                <h4 style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
                  <Terminal size={18} color="#34d399" />
                  Assigned VM Live Terminals
                </h4>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '4px 0 0 0' }}>
                  Real-time command stream executing inside isolated guest environments.
                </p>
              </div>

              {/* Dynamic VM Selector Tabs: Only assigned VMs are displayed */}
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                {assignedVms.map((v) => (
                  <button
                    key={v.vm_id}
                    onClick={() => setActiveVmTerminalTab(v.vm_id)}
                    style={{
                      padding: '8px 14px',
                      borderRadius: '8px',
                      backgroundColor: activeVmTerminalTab === v.vm_id ? 'rgba(52, 211, 153, 0.15)' : '#090d16',
                      border: `1px solid ${activeVmTerminalTab === v.vm_id ? '#34d399' : 'var(--border-color)'}`,
                      color: activeVmTerminalTab === v.vm_id ? '#34d399' : 'var(--text-muted)',
                      fontSize: '0.8rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      transition: 'all 0.2s',
                    }}
                  >
                    <Server size={14} />
                    <span>{v.vm_id}</span>
                    <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>({v.ssh_host})</span>
                    <span style={{ fontSize: '0.68rem', backgroundColor: '#1e293b', padding: '1px 6px', borderRadius: '10px', color: '#cbd5e1' }}>
                      {vmTerminalLogs[v.vm_id]?.length || 0} cmds
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Target VM Details Banner */}
            {currentActiveVm && (
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 14px',
                  backgroundColor: '#0c1322',
                  border: '1px solid #1e293b',
                  borderRadius: '6px',
                  fontSize: '0.78rem',
                  color: '#94a3b8',
                  flexWrap: 'wrap',
                  gap: '8px',
                }}
              >
                <div>
                  Target Node: <strong style={{ color: '#34d399' }}>{currentActiveVm.vm_id}</strong> &bull; VM: <strong style={{ color: '#ffffff' }}>{currentActiveVm.virtualbox_vm_name}</strong> &bull; SSH: <strong style={{ color: '#38bdf8' }}>{currentActiveVm.ssh_host}:{currentActiveVm.ssh_port}</strong>
                </div>
                <div>
                  Assigned Agent: <strong style={{ color: '#fbbf24' }}>{currentActiveVm.agent_id}</strong>
                </div>
              </div>
            )}

            {/* Terminal Window with Live Streaming Chunks */}
            <div
              style={{
                backgroundColor: '#050811',
                border: '1px solid #1e293b',
                borderRadius: '8px',
                padding: '16px',
                fontFamily: 'monospace',
                fontSize: '0.78rem',
                minHeight: '220px',
                maxHeight: '360px',
                overflowY: 'auto',
                color: '#e2e8f0',
              }}
            >
              <div style={{ color: '#64748b', marginBottom: '8px', borderBottom: '1px solid #1e293b', paddingBottom: '6px' }}>
                # CyberArena SSH Console &bull; Target: {activeVmTerminalTab} ({currentActiveVm?.ssh_host}) &bull; Guest Isolation Verified
              </div>

              {(!vmTerminalLogs[activeVmTerminalTab] || vmTerminalLogs[activeVmTerminalTab].length === 0) ? (
                <div style={{ color: '#475569', fontStyle: 'italic', padding: '24px 0', textAlign: 'center' }}>
                  No guest commands executed on {activeVmTerminalTab} yet.
                </div>
              ) : (
                vmTerminalLogs[activeVmTerminalTab].map((log, idx) => (
                  <div key={idx} style={{ marginBottom: '14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#38bdf8' }}>
                      <span style={{ color: '#64748b' }}>[{new Date(log.timestamp).toLocaleTimeString()}]</span>
                      <span style={{ color: '#34d399', fontWeight: 'bold' }}>{log.agentId}@{activeVmTerminalTab}$</span>
                      <span>{log.tool}: {log.command}</span>
                      {log.isRunning && (
                        <span style={{ fontSize: '0.7rem', color: '#fbbf24', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Activity size={12} className="animate-spin" /> executing...
                        </span>
                      )}
                    </div>
                    <pre
                      style={{
                        margin: '4px 0 0 16px',
                        padding: '8px 12px',
                        backgroundColor: '#090d16',
                        borderRadius: '4px',
                        borderLeft: `2px solid ${log.isRunning ? '#fbbf24' : log.success ? '#34d399' : '#f87171'}`,
                        whiteSpace: 'pre-wrap',
                        color: log.isRunning ? '#fde047' : log.success ? '#cbd5e1' : '#fca5a5',
                        fontSize: '0.75rem',
                        overflowX: 'auto',
                      }}
                    >
                      {log.output || (log.isRunning ? '(streaming output...)' : '(No output returned)')}
                    </pre>
                  </div>
                ))
              )}
              <div ref={terminalEndRef} />
            </div>
          </section>

          {/* OVERALL EXPERIMENT EXECUTIVE SYNTHESIS REPORT */}
          {selectedExpDetail.final_conclusion && (
            <section
              style={{
                backgroundColor: 'var(--bg-card)',
                border: '1px solid #38bdf866',
                borderRadius: '12px',
                padding: '20px',
                display: 'flex',
                flexDirection: 'column',
                gap: '14px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #1e293b', paddingBottom: '10px' }}>
                <span style={{ fontSize: '0.9rem', fontWeight: 700, color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Shield size={16} /> Autonomous Range Executive Report
                </span>
                <span style={{ fontSize: '0.7rem', color: '#34d399', backgroundColor: 'rgba(52, 211, 153, 0.15)', padding: '2px 8px', borderRadius: '4px', border: '1px solid #34d399' }}>
                  Verified by Local LLM
                </span>
              </div>
              <MarkdownReportViewer markdown={selectedExpDetail.final_conclusion} />
            </section>
          )}
        </div>
      ) : (
        <div
          style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '40px',
            textAlign: 'center',
          }}
        >
          <Layers size={40} color="#64748b" style={{ margin: '0 auto 12px auto' }} />
          <h3 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#ffffff', marginBottom: '6px' }}>
            No Experiment Selected
          </h3>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', maxWidth: '440px', margin: '0 auto' }}>
            Select an existing experiment above or configure a new multi-agent cyber experiment with the builder.
          </p>
        </div>
      )}
    </div>
  );
};
