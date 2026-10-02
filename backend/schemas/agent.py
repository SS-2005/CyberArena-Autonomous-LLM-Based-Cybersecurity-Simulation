from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    STOPPED = "stopped"
    STOPPED_ITERATION_LIMIT = "stopped_iteration_limit"
    CANCELLED = "cancelled"


class AgentEventType(str, Enum):
    AGENT_CREATED = "agent_created"
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
    AGENT_STOPPED = "agent_stopped"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_STATUS_UPDATED = "agent_status_updated"
    AGENT_STATUS_CHANGED = "agent_status_changed"


class AgentEvent(BaseModel):
    event_id: Optional[str] = None
    agent_id: str
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



class AgentActionRequest(BaseModel):
    tool: str = Field(..., description="Target tool name or 'finish'")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Tool parameter key-value dictionary")
    summary: str = Field(..., description="Brief reasoning or intent for requesting this action")


class ExecutionRecord(BaseModel):
    iteration: int
    timestamp: str
    action_type: str = "tool_execution"
    tool_name: str
    arguments_safe: Dict[str, Any] = Field(default_factory=dict)
    result: str = ""
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    duration: float = 0.0
    success: bool = True
    error: Optional[str] = None
    error_type: Optional[str] = None
    observation_summary: str = ""


class AgentConclusion(BaseModel):
    status: str = Field(..., description="completed | partially_completed | blocked | failed | inconclusive")
    summary: str = Field(..., description="Executive summary of the agent outcome")
    findings: List[str] = Field(default_factory=list, description="Key discovered facts or results")
    evidence: List[str] = Field(default_factory=list, description="Observable outputs/commands supporting findings")
    errors: List[str] = Field(default_factory=list, description="Any command or tool failures encountered")
    unresolved_items: List[str] = Field(default_factory=list, description="Planned actions or questions left incomplete")
    iteration_limit_reached: bool = Field(False, description="Whether max iterations was reached before finishing")


class AgentStep(BaseModel):
    step_number: int
    action: AgentActionRequest
    observation: str
    success: bool
    duration: float
    timestamp: str
    execution_record: Optional[ExecutionRecord] = None


class AgentState(BaseModel):
    agent_id: str
    role: str = Field(..., description="User-provided objective or instruction for the agent")
    model_id: str
    vm_id: str
    allowed_tools: List[str]
    status: AgentStatus
    current_iteration: int
    iteration_limit: int
    command_timeout: int
    final_conclusion: Optional[str] = None
    structured_conclusion: Optional[AgentConclusion] = None
    history: List[AgentStep] = Field(default_factory=list)
    execution_records: List[ExecutionRecord] = Field(default_factory=list)
    created_at: str
    updated_at: str
    error_message: Optional[str] = None


class AgentCreateRequest(BaseModel):
    agent_id: Optional[str] = Field(None, description="Optional custom agent identifier")
    role: str = Field(..., min_length=1, description="Objective or instruction for the agent")
    model_id: Optional[str] = Field(None, description="Target model_id. Defaults to registry default.")
    vm_id: str = Field(..., min_length=1, description="Assigned VM ID (must be configured in VM registry)")
    tools: Optional[List[str]] = Field(None, description="List of allowed tool names (defaults to all available)")
    iteration_limit: Optional[int] = Field(None, ge=1, le=100, description="Maximum autonomous iterations")
    command_timeout: Optional[int] = Field(None, ge=1, le=300, description="Per-action execution timeout in seconds")


class AgentOperationResponse(BaseModel):
    agent_id: str
    operation: str
    success: bool
    message: str
    status: AgentStatus
    timestamp: str


class ToolDefinitionSchema(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
