import { AgentStep } from './agent';

export type ExperimentStatus = 'created' | 'running' | 'completed' | 'failed' | 'stopped';

export interface ExperimentAgentConfig {
  role: string;
  vm_id: string;
  model_id?: string;
  tools?: string[];
  iteration_limit?: number;
  command_timeout?: number;
}

export interface ExperimentCreateRequest {
  name: string;
  description?: string;
  agents: ExperimentAgentConfig[];
}

export interface ExperimentAgentState {
  agent_id: string;
  role: string;
  vm_id: string;
  model_id: string;
  status: string;
  current_iteration: number;
  iteration_limit: number;
  command_timeout: number;
  error_message?: string | null;
  final_conclusion?: string | null;
  history: AgentStep[];
  created_at: string;
  updated_at: string;
}

export interface ExperimentSummary {
  id: string;
  name: string;
  description?: string | null;
  status: ExperimentStatus;
  agent_count: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  duration_seconds?: number | null;
}

export interface ExperimentDetail {
  id: string;
  name: string;
  description?: string | null;
  status: ExperimentStatus;
  agents: ExperimentAgentState[];
  final_conclusion?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  error_message?: string | null;
  total_events: number;
}

export interface ExperimentEvent {
  id?: number;
  event_id?: string;
  experiment_id: string;
  agent_id?: string | null;
  event_type: string;
  iteration: number;
  timestamp: string;
  tool_name?: string | null;
  content?: string | null;
  status?: string | null;
  error?: string | null;
  summary?: string | null;
  parameters?: Record<string, any> | null;
  output_chunk?: string | null;
  stream?: string | null;
  vm_id?: string | null;
  conclusion?: string | null;
  thinking?: string | null;
  data: Record<string, any>;
}

export interface ExperimentOperationResponse {
  experiment_id: string;
  operation: string;
  success: boolean;
  message: string;
  status: ExperimentStatus;
  timestamp: string;
}
