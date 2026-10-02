from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from backend.virtualization.base import VMProvider
from backend.schemas.agent import ToolDefinitionSchema


class ToolExecutionResult(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    """
    Abstract Base Class for agent tools in CyberArena.
    Every tool must target an assigned VM through the VMProvider interface.
    No tool may ever execute commands against the host environment.
    """

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    @abstractmethod
    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        """Execute the tool against the specified VM via VMProvider."""
        pass

    def to_schema(self) -> ToolDefinitionSchema:
        return ToolDefinitionSchema(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )
