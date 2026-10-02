export type AgentStatus =
  | 'idle'
  | 'running'
  | 'paused'
  | 'completed'
  | 'partially_completed'
  | 'blocked'
  | 'failed'
  | 'stopped'
  | 'stopped_iteration_limit'
  | 'cancelled';

export type AgentEventType =
  | 'agent_created'
  | 'agent_started'
  | 'agent_iteration_started'
  | 'agent_reasoning_summary'
  | 'agent_action_requested'
  | 'agent_tool_output_chunk'
  | 'agent_iteration_completed'
  | 'agent_final_conclusion'
  | 'llm_started'
  | 'llm_chunk'
  | 'llm_completed'
  | 'tool_requested'
  | 'tool_started'
  | 'tool_completed'
  | 'tool_failed'
  | 'observation_received'
  | 'agent_stopped'
  | 'agent_completed'
  | 'agent_failed';

export interface AgentEvent {
  event_id?: string | null;
  agent_id: string;
  event_type: AgentEventType;
  iteration: number;
  timestamp: string;
  tool_name?: string | null;
  content?: string | null;
  status?: string | null;
  error?: string | null;
  summary?: string | null;
  parameters?: Record<string, unknown> | null;
  output_chunk?: string | null;
  stream?: string | null;
  vm_id?: string | null;
  conclusion?: string | null;
  data?: Record<string, any>;
}

export interface AgentActionRequest {
  tool: string;
  parameters: Record<string, unknown>;
  summary: string;
}

export interface ExecutionRecord {
  iteration: number;
  timestamp: string;
  action_type: string;
  tool_name: string;
  arguments_safe: Record<string, unknown>;
  result: string;
  stdout?: string | null;
  stderr?: string | null;
  exit_code?: number | null;
  duration: number;
  success: boolean;
  error?: string | null;
  error_type?: string | null;
  observation_summary: string;
}

export interface AgentConclusion {
  status: string;
  summary: string;
  findings: string[];
  evidence: string[];
  errors: string[];
  unresolved_items: string[];
  iteration_limit_reached: boolean;
}

export interface AgentStep {
  step_number: number;
  action: AgentActionRequest;
  observation: string;
  success: boolean;
  duration: number;
  timestamp: string;
  execution_record?: ExecutionRecord | null;
}

export interface AgentState {
  agent_id: string;
  role: string;
  model_id: string;
  vm_id: string;
  allowed_tools: string[];
  status: AgentStatus;
  current_iteration: number;
  iteration_limit: number;
  command_timeout: number;
  final_conclusion?: string | null;
  structured_conclusion?: AgentConclusion | null;
  history: AgentStep[];
  execution_records?: ExecutionRecord[];
  created_at: string;
  updated_at: string;
  error_message?: string | null;
}

export interface AgentCreateRequest {
  agent_id?: string;
  role: string;
  model_id?: string;
  vm_id: string;
  tools?: string[];
  iteration_limit?: number;
  command_timeout?: number;
}

export interface AgentOperationResponse {
  agent_id: string;
  operation: string;
  success: boolean;
  message: string;
  status: AgentStatus;
  timestamp: string;
}

export interface ToolDefinitionSchema {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}
