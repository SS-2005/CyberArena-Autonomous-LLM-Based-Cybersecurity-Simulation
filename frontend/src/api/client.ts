import { 
  SystemConfigResponse, 
  VMInfo, 
  VMOperationResult, 
  CommandExecutionResult, 
  HealthCheckResult 
} from '../types/vm';

import {
  ModelStatus,
  LLMHealthResponse,
  LLMTestResponse,
} from '../types/llm';

import {
  AgentState,
  AgentCreateRequest,
  AgentOperationResponse,
  AgentStep,
  AgentEvent,
  ToolDefinitionSchema,
} from '../types/agent';

import {
  ExperimentCreateRequest,
  ExperimentDetail,
  ExperimentSummary,
  ExperimentOperationResponse,
  ExperimentEvent,
} from '../types/experiment';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

async function handleResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || '';

  if (!response.ok) {
    let errorDetail = `Request failed with status ${response.status}`;
    if (contentType.includes('application/json')) {
      try {
        const errorJson = await response.json();
        if (errorJson.detail) {
          errorDetail = typeof errorJson.detail === 'string' ? errorJson.detail : JSON.stringify(errorJson.detail);
        }
      } catch {
        // fallback
      }
    } else {
      const text = await response.text();
      if (text.includes('<!DOCTYPE') || text.includes('<html')) {
        errorDetail = `Endpoint not found or proxy misconfigured (HTTP ${response.status})`;
      } else if (text) {
        errorDetail = `HTTP ${response.status}: ${text.slice(0, 150)}`;
      }
    }
    throw new Error(errorDetail);
  }

  // Ensure successful response is actually JSON and not an HTML SPA fallback
  const text = await response.text();
  if (text.trim().startsWith('<') || text.includes('<!DOCTYPE') || text.includes('<html')) {
    throw new Error(`API endpoint returned HTML instead of JSON. Check that backend is running and path is proxied.`);
  }

  try {
    return JSON.parse(text) as T;
  } catch (err: any) {
    throw new Error(`Failed to parse JSON from backend: ${err.message}`);
  }
}

export const api = {
  // === Virtual Machines ===
  async getConfig(): Promise<SystemConfigResponse> {
    const res = await fetch(`${BASE_URL}/config`);
    return handleResponse<SystemConfigResponse>(res);
  },

  async listVMs(): Promise<VMInfo[]> {
    const res = await fetch(`${BASE_URL}/vms`);
    return handleResponse<VMInfo[]>(res);
  },

  async getVM(vm_id: string): Promise<VMInfo> {
    const res = await fetch(`${BASE_URL}/vms/${encodeURIComponent(vm_id)}`);
    return handleResponse<VMInfo>(res);
  },

  async startVM(vm_id: string): Promise<VMOperationResult> {
    const res = await fetch(`${BASE_URL}/vms/${encodeURIComponent(vm_id)}/start`, {
      method: 'POST',
    });
    return handleResponse<VMOperationResult>(res);
  },

  async stopVM(vm_id: string, force = false): Promise<VMOperationResult> {
    const url = `${BASE_URL}/vms/${encodeURIComponent(vm_id)}/stop${force ? '?force=true' : ''}`;
    const res = await fetch(url, {
      method: 'POST',
    });
    return handleResponse<VMOperationResult>(res);
  },

  async createSnapshot(vm_id: string, snapshotName: string, description?: string): Promise<VMOperationResult> {
    const res = await fetch(`${BASE_URL}/vms/${encodeURIComponent(vm_id)}/snapshot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        snapshot_name: snapshotName,
        description: description || undefined,
      }),
    });
    return handleResponse<VMOperationResult>(res);
  },

  async restoreSnapshot(vm_id: string, snapshotName: string): Promise<VMOperationResult> {
    const res = await fetch(`${BASE_URL}/vms/${encodeURIComponent(vm_id)}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        snapshot_name: snapshotName,
      }),
    });
    return handleResponse<VMOperationResult>(res);
  },

  async executeCommand(vm_id: string, command: string, timeout = 30): Promise<CommandExecutionResult> {
    const res = await fetch(`${BASE_URL}/vms/${encodeURIComponent(vm_id)}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        command,
        timeout,
      }),
    });
    return handleResponse<CommandExecutionResult>(res);
  },

  async checkHealth(vm_id: string): Promise<HealthCheckResult> {
    const res = await fetch(`${BASE_URL}/vms/${encodeURIComponent(vm_id)}/health`);
    return handleResponse<HealthCheckResult>(res);
  },

  // === LLM Gateway ===
  async getLLMHealth(): Promise<LLMHealthResponse> {
    const res = await fetch(`${BASE_URL}/llm/health`);
    return handleResponse<LLMHealthResponse>(res);
  },

  async listModels(): Promise<ModelStatus[]> {
    const res = await fetch(`${BASE_URL}/llm/models`);
    return handleResponse<ModelStatus[]>(res);
  },

  async testModel(prompt: string, model_id?: string): Promise<LLMTestResponse> {
    const res = await fetch(`${BASE_URL}/llm/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        model_id: model_id || undefined,
      }),
    });
    return handleResponse<LLMTestResponse>(res);
  },

  // === Autonomous Agents ===
  async listTools(): Promise<ToolDefinitionSchema[]> {
    const res = await fetch(`${BASE_URL}/agents/tools`);
    return handleResponse<ToolDefinitionSchema[]>(res);
  },

  async listAgents(): Promise<AgentState[]> {
    const res = await fetch(`${BASE_URL}/agents`);
    return handleResponse<AgentState[]>(res);
  },

  async getAgent(agent_id: string): Promise<AgentState> {
    const res = await fetch(`${BASE_URL}/agents/${encodeURIComponent(agent_id)}`);
    return handleResponse<AgentState>(res);
  },

  async createAgent(req: AgentCreateRequest): Promise<AgentState> {
    const res = await fetch(`${BASE_URL}/agents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    return handleResponse<AgentState>(res);
  },

  async startAgent(agent_id: string): Promise<AgentOperationResponse> {
    const res = await fetch(`${BASE_URL}/agents/${encodeURIComponent(agent_id)}/start`, {
      method: 'POST',
    });
    return handleResponse<AgentOperationResponse>(res);
  },

  async stopAgent(agent_id: string): Promise<AgentOperationResponse> {
    const res = await fetch(`${BASE_URL}/agents/${encodeURIComponent(agent_id)}/stop`, {
      method: 'POST',
    });
    return handleResponse<AgentOperationResponse>(res);
  },

  async getAgentHistory(agent_id: string): Promise<AgentStep[]> {
    const res = await fetch(`${BASE_URL}/agents/${encodeURIComponent(agent_id)}/history`);
    return handleResponse<AgentStep[]>(res);
  },

  async deleteAgent(agent_id: string): Promise<AgentOperationResponse> {
    const res = await fetch(`${BASE_URL}/agents/${encodeURIComponent(agent_id)}`, {
      method: 'DELETE',
    });
    return handleResponse<AgentOperationResponse>(res);
  },

  subscribeAgentEvents(
    agent_id: string,
    onEvent: (event: AgentEvent) => void,
    onError?: (err: any) => void
  ): () => void {
    const url = `${BASE_URL}/agents/${encodeURIComponent(agent_id)}/events`;
    const es = new EventSource(url);

    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data) as AgentEvent;
        onEvent(parsed);
      } catch (err) {
        console.warn('Failed to parse SSE agent event:', err);
      }
    };

    es.onerror = (e) => {
      if (onError) onError(e);
    };

    return () => {
      es.close();
    };
  },

  async streamLLMTest(
    prompt: string,
    model_id?: string,
    onChunk?: (chunk: string) => void,
    signal?: AbortSignal
  ): Promise<{ text: string; duration: number }> {
    const startTime = Date.now();
    const res = await fetch(`${BASE_URL}/llm/test/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, model_id: model_id || undefined }),
      signal,
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`LLM stream failed (${res.status}): ${errText}`);
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error('Response stream body not readable');

    const decoder = new TextDecoder('utf-8');
    let accumulated = '';
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith('data:')) {
          const jsonStr = trimmed.slice(5).trim();
          if (jsonStr) {
            try {
              const data = JSON.parse(jsonStr);
              if (data.chunk) {
                accumulated += data.chunk;
                if (onChunk) onChunk(data.chunk);
              }
              if (data.error) {
                throw new Error(data.error);
              }
            } catch (err: any) {
              if (err.message && !err.message.includes('JSON')) throw err;
            }
          }
        }
      }
    }

    const duration = Math.round((Date.now() - startTime) / 100) / 10;
    return { text: accumulated, duration };
  },

  // === Phase 3: Multi-Agent Experiments ===
  async createExperiment(req: ExperimentCreateRequest): Promise<ExperimentDetail> {
    const res = await fetch(`${BASE_URL}/experiments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    return handleResponse<ExperimentDetail>(res);
  },

  async listExperiments(): Promise<ExperimentSummary[]> {
    const res = await fetch(`${BASE_URL}/experiments`);
    return handleResponse<ExperimentSummary[]>(res);
  },

  async getExperiment(experiment_id: string): Promise<ExperimentDetail> {
    const res = await fetch(`${BASE_URL}/experiments/${encodeURIComponent(experiment_id)}`);
    return handleResponse<ExperimentDetail>(res);
  },

  async startExperiment(experiment_id: string): Promise<ExperimentOperationResponse> {
    const res = await fetch(`${BASE_URL}/experiments/${encodeURIComponent(experiment_id)}/start`, {
      method: 'POST',
    });
    return handleResponse<ExperimentOperationResponse>(res);
  },

  async stopExperiment(experiment_id: string): Promise<ExperimentOperationResponse> {
    const res = await fetch(`${BASE_URL}/experiments/${encodeURIComponent(experiment_id)}/stop`, {
      method: 'POST',
    });
    return handleResponse<ExperimentOperationResponse>(res);
  },

  async deleteExperiment(experiment_id: string): Promise<ExperimentOperationResponse> {
    const res = await fetch(`${BASE_URL}/experiments/${encodeURIComponent(experiment_id)}`, {
      method: 'DELETE',
    });
    return handleResponse<ExperimentOperationResponse>(res);
  },

  async getExperimentEventsHistory(experiment_id: string, limit = 500): Promise<ExperimentEvent[]> {
    const res = await fetch(`${BASE_URL}/experiments/${encodeURIComponent(experiment_id)}/events/history?limit=${limit}`);
    return handleResponse<ExperimentEvent[]>(res);
  },

  subscribeExperimentSSE(
    experiment_id: string,
    onEvent: (event: ExperimentEvent) => void,
    onError?: (err: any) => void
  ): () => void {
    const url = `${BASE_URL}/experiments/${encodeURIComponent(experiment_id)}/events`;
    const es = new EventSource(url);

    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data) as ExperimentEvent;
        onEvent(parsed);
      } catch (err) {
        console.warn('Failed to parse SSE experiment event:', err);
      }
    };

    es.onerror = (e) => {
      if (onError) onError(e);
    };

    return () => {
      es.close();
    };
  },

  connectExperimentWS(
    experiment_id: string,
    onEvent: (event: ExperimentEvent) => void,
    onOpen?: () => void,
    onClose?: () => void,
    onError?: (err: any) => void
  ): { ws: WebSocket; close: () => void } {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/experiments/${encodeURIComponent(experiment_id)}`;

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      if (onOpen) onOpen();
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'pong') return;
        if (data.experiment_id && data.event_type) {
          onEvent(data as ExperimentEvent);
        }
      } catch (err) {
        console.warn('Failed to parse WS experiment message:', err);
      }
    };

    ws.onerror = (e) => {
      if (onError) onError(e);
    };

    ws.onclose = () => {
      if (onClose) onClose();
    };

    // Keepalive ping interval
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        try {
          ws.send('ping');
        } catch {}
      }
    }, 15000);

    return {
      ws,
      close: () => {
        clearInterval(pingInterval);
        try {
          ws.close();
        } catch {}
      },
    };
  },
};

