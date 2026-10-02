export interface ModelStatus {
  model_id: string;
  provider: string;
  model_name: string;
  display_name?: string;
  configured: boolean;
  installed: boolean;
  available: boolean;
  size?: string;
  thinking_supported?: boolean;
  think?: boolean;
  description?: string;
  details?: Record<string, unknown>;
}

export interface LLMHealthResponse {
  status: string;
  provider: string;
  base_url: string;
  installed_models: string[];
  message: string;
  timestamp: string;
}

export interface LLMTestRequest {
  model_id?: string;
  prompt: string;
}

export interface LLMTestResponse {
  model_id: string;
  model_name: string;
  response: string;
  duration: number;
  timestamp: string;
}
