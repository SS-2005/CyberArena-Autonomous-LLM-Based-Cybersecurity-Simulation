from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from backend.schemas.agent import AgentStep


class ExperimentStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ExperimentEventType(str, Enum):
    EXPERIMENT_CREATED = "experiment_created"
    EXPERIMENT_STARTED = "experiment_started"
    AGENT_STARTED = "agent_started"
    AGENT_ITERATION_STARTED = "agent_iteration_started"
    AGENT_REASONING_SUMMARY = "agent_reasoning_summary"
    AGENT_ACTION_REQUESTED = "agent_action_requested"
    AGENT_TOOL_OUTPUT_CHUNK = "agent_tool_output_chunk"
    AGENT_ITERATION_COMPLETED = "agent_iteration_completed"
    AGENT_FINAL_CONCLUSION = "agent_final_conclusion"
    LLM_STARTED = "llm_started"
    LLM_CHUNK = "llm_chunk"
    LLM_COMPLETED = "llm_completed"
    TOOL_REQUESTED = "tool_requested"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    OBSERVATION_RECEIVED = "observation_received"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_STOPPED = "agent_stopped"
    AGENT_STATUS_UPDATED = "agent_status_updated"
    AGENT_STATUS_CHANGED = "agent_status_changed"
    EXPERIMENT_SUMMARY_UPDATED = "experiment_summary_updated"
    EXPERIMENT_COMPLETED = "experiment_completed"
    EXPERIMENT_STOPPED = "experiment_stopped"
    EXPERIMENT_FAILED = "experiment_failed"


class ExperimentAgentConfig(BaseModel):
    role: str = Field(..., min_length=1, description="Agent objective or instructions")
    vm_id: str = Field(..., min_length=1, description="Assigned VM ID (must be unique per experiment)")
    model_id: Optional[str] = Field(None, description="Model ID from model registry (defaults to default model)")
    tools: Optional[List[str]] = Field(None, description="Allowed tools for this agent (defaults to all)")
    iteration_limit: Optional[int] = Field(default=10, ge=1, le=100, description="Max iterations")
    command_timeout: Optional[int] = Field(default=180, ge=1, le=600, description="Timeout in seconds per action")


class ExperimentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Experiment display name")
    description: Optional[str] = Field(None, max_length=500, description="Optional experiment description")
    agents: List[ExperimentAgentConfig] = Field(..., min_length=1, description="List of agent configurations")


class ExperimentAgentState(BaseModel):
    agent_id: str
    role: str
    vm_id: str
    model_id: str
    status: str
    current_iteration: int = 0
    iteration_limit: int = 10
    command_timeout: int = 180
    error_message: Optional[str] = None
    final_conclusion: Optional[str] = None
    history: List[AgentStep] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ExperimentSummary(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: ExperimentStatus
    agent_count: int
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None


class ExperimentDetail(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: ExperimentStatus
    agents: List[ExperimentAgentState] = Field(default_factory=list)
    final_conclusion: Optional[str] = None
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    total_events: int = 0


class ExperimentEvent(BaseModel):
    id: Optional[int] = None
    event_id: Optional[str] = None
    experiment_id: str
    agent_id: Optional[str] = None
    event_type: str
    iteration: int = 0
    timestamp: str
    tool_name: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None
    summary: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    output_chunk: Optional[str] = None
    stream: Optional[str] = None
    vm_id: Optional[str] = None
    conclusion: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class ExperimentOperationResponse(BaseModel):
    experiment_id: str
    operation: str
    success: bool
    message: str
    status: ExperimentStatus
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
