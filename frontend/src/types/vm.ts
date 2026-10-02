export type VMState = 
  | 'running' 
  | 'stopped' 
  | 'paused' 
  | 'saved' 
  | 'starting' 
  | 'stopping' 
  | 'error' 
  | 'unknown';

export interface VMInfo {
  vm_id: string;
  vm_provider: string;
  virtualbox_vm_name: string;
  state: VMState;
  ssh_host: string;
  ssh_port: number;
  ssh_username: string;
  ssh_auth_method: string;
  description?: string;
  is_healthy?: boolean;
  last_checked?: string;
}

export interface SystemConfigResponse {
  max_vm: number;
  configured_vm_count: number;
  default_provider: string;
  vms: VMInfo[];
}

export interface CommandExecutionResult {
  vm_id: string;
  command: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  duration: number;
  timestamp: string;
}

export interface VMOperationResult {
  vm_id: string;
  operation: string;
  success: boolean;
  message: string;
  timestamp: string;
  details?: Record<string, unknown>;
}

export interface HealthCheckResult {
  vm_id: string;
  state: VMState;
  is_running: boolean;
  ssh_reachable: boolean;
  latency_ms?: number | null;
  message: string;
  timestamp: string;
}
