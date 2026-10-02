from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    model_id: str = Field(..., description="Unique logical identifier for the model in CyberArena")
    provider: str = Field(default="ollama", description="LLM provider type (e.g. ollama)")
    model_name: str = Field(..., description="Actual model tag in provider engine (e.g. qwen3:4b)")
    display_name: Optional[str] = Field(None, description="Human-friendly display name")
    enabled: bool = Field(default=True, description="Whether the model is enabled for agent selection")
    size: Optional[str] = Field(None, description="Approximate model file size")
    thinking_supported: bool = Field(default=False, description="Whether model supports extended reasoning/thinking")
    think: Optional[bool] = Field(default=None, description="Default thinking behavior for this model")
    temperature: Optional[float] = Field(default=None, description="Configured temperature")
    num_ctx: Optional[int] = Field(default=4096, description="Context window size")
    max_tokens: Optional[int] = Field(default=None, description="Max generation tokens")
    description: Optional[str] = Field(None, description="Model description and resource profile")


class ModelRegistryConfig(BaseModel):
    default_model: str = Field(..., description="Default model_id for new agents")
    llm_parallelism: int = Field(default=4, description="Maximum concurrent local LLM inference tasks")
    default_iteration_limit: int = Field(default=10, description="Default iteration cap per agent execution")
    default_timeout: int = Field(default=180, description="Default generation timeout in seconds")
    models: List[ModelConfig] = Field(default_factory=list, description="Configured model entries")


class ModelStatus(BaseModel):
    model_id: str
    provider: str
    model_name: str
    display_name: Optional[str] = None
    configured: bool
    installed: bool
    available: bool
    size: Optional[str] = None
    thinking_supported: bool = False
    think: Optional[bool] = None
    description: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class LLMHealthResponse(BaseModel):
    status: str
    provider: str
    base_url: str
    installed_models: List[str]
    message: str
    timestamp: str


class LLMTestRequest(BaseModel):
    model_id: Optional[str] = Field(None, description="Target model_id. Defaults to registry default.")
    prompt: str = Field(..., min_length=1, description="Test prompt to send to LLM")


class LLMTestResponse(BaseModel):
    model_id: str
    model_name: str
    response: str
    duration: float
    timestamp: str


class LLMGenerationResponse(BaseModel):
    text: str
    duration: float
    model_name: str
    tokens_generated: Optional[int] = None
    raw: Optional[Dict[str, Any]] = None
