from typing import Dict, List, Optional, Any, Callable
from backend.tools.base import BaseTool, ToolExecutionResult
from backend.tools.builtin import (
    ExecuteCommandTool,
    ReadFileTool,
    WriteFileTool,
    ListDirectoryTool,
    ProcessInfoTool,
    ServiceStatusTool,
    NetworkInfoTool,
    SystemInfoTool,
    MemoryInfoTool,
    DiskUsageTool,
    ListeningPortsTool,
    UptimeTool,
)
from backend.tools.privileged import (
    InstallPackageTool,
    RestartServiceTool,
    ModifySystemConfigTool,
    CreateUserTool,
)
from backend.virtualization.base import VMProvider
from backend.utils.logger import logger


class ToolRegistry:
    """
    Central registry for agent tools.
    Manages tool discovery, schema generation for LLM system prompts, and execution dispatching.
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        defaults = [
            ExecuteCommandTool(),
            ReadFileTool(),
            WriteFileTool(),
            ListDirectoryTool(),
            ProcessInfoTool(),
            ServiceStatusTool(),
            NetworkInfoTool(),
            SystemInfoTool(),
            MemoryInfoTool(),
            DiskUsageTool(),
            ListeningPortsTool(),
            UptimeTool(),
            InstallPackageTool(),
            RestartServiceTool(),
            ModifySystemConfigTool(),
            CreateUserTool(),
        ]
        for tool in defaults:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        return list(self._tools.values())

    def list_tool_names(self) -> List[str]:
        return list(self._tools.keys())

    def get_tool_schemas(self, allowed_tools: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Return JSON-serializable schemas for allowed tools to feed to the LLM."""
        schemas = []
        for name, tool in self._tools.items():
            if allowed_tools is None or name in allowed_tools:
                schemas.append({
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                })
        return schemas

    def execute(
        self,
        tool_name: str,
        vm_provider: VMProvider,
        vm_id: str,
        parameters: Dict[str, Any],
        output_callback: Optional[Callable[[str, str], None]] = None,
    ) -> ToolExecutionResult:
        """Dispatch tool execution strictly to assigned VM via vm_provider."""
        tool = self.get(tool_name)
        if not tool:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Tool '{tool_name}' is not recognized by CyberArena ToolRegistry.",
            )

        # Strip reserved/untrusted parameters to prevent parameter collisions or target spoofing
        safe_params = {k: v for k, v in parameters.items() if k not in ("vm_id", "vm_provider")}
        if output_callback is not None:
            safe_params["output_callback"] = output_callback

        try:
            return tool.execute(vm_provider, vm_id, **safe_params)
        except Exception as e:
            logger.error(f"Unhandled error executing tool '{tool_name}' on VM '{vm_id}': {e}")
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Error executing tool '{tool_name}': {e}",
            )


# Global default registry instance
default_tool_registry = ToolRegistry()
