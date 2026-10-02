import asyncio
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.agents.agent import Agent
from backend.schemas.agent import (
    AgentCreateRequest,
    AgentState,
    AgentStep,
    AgentStatus,
    AgentOperationResponse,
    AgentEvent,
    AgentEventType,
)
from backend.agents.events import event_broadcaster
from backend.services.llm_service import LLMService
from backend.services.vm_service import VMService
from backend.tools.registry import ToolRegistry, default_tool_registry
from backend.utils.logger import logger


class AgentService:
    """
    Manages autonomous AI agent instances, lifecycle, and background execution.
    Enforces concurrency controls (e.g. max 1 concurrent LLM inference) for CPU safety.
    """

    def __init__(
        self,
        llm_service: LLMService,
        vm_service: VMService,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        self.llm_service = llm_service
        self.vm_service = vm_service
        self.tool_registry = tool_registry or default_tool_registry
        self._agents: Dict[str, Agent] = {}
        self._active_tasks: Dict[str, asyncio.Task] = {}
        # Concurrency semaphore based on model registry parallelism configuration (default 1)
        self._parallelism = self.llm_service.registry_config.llm_parallelism
        self._inference_lock = threading.Semaphore(self._parallelism)

    def create_agent(self, req: AgentCreateRequest) -> AgentState:
        """Create and register a new autonomous agent."""
        # 1. Verify VM existence in VM registry
        configured_vms = [v.vm_id for v in self.vm_service.list_vms()]
        if req.vm_id not in configured_vms:
            raise ValueError(f"Assigned VM '{req.vm_id}' is not in configured VM registry ({configured_vms}).")

        # 2. Assign agent ID
        agent_id = req.agent_id or f"agent-{len(self._agents) + 1:02d}-{str(uuid.uuid4())[:6]}"
        if agent_id in self._agents:
            raise ValueError(f"Agent with ID '{agent_id}' already exists.")

        # 3. Resolve Model
        model_cfg = self.llm_service.resolve_model(req.model_id)

        # 4. Resolve Tools
        allowed_tools = req.tools or self.tool_registry.list_tool_names()
        for t in allowed_tools:
            if not self.tool_registry.get(t):
                raise ValueError(f"Requested tool '{t}' does not exist in ToolRegistry.")

        # 5. Iteration limit & timeout
        iter_limit = req.iteration_limit or self.llm_service.registry_config.default_iteration_limit
        cmd_timeout = req.command_timeout or self.llm_service.registry_config.default_timeout

        agent = Agent(
            agent_id=agent_id,
            role=req.role,
            vm_id=req.vm_id,
            model_id=model_cfg.model_id,
            llm_service=self.llm_service,
            vm_provider=self.vm_service.provider,
            tool_registry=self.tool_registry,
            allowed_tools=allowed_tools,
            iteration_limit=iter_limit,
            command_timeout=cmd_timeout,
        )

        self._agents[agent_id] = agent
        logger.info(f"Created agent '{agent_id}' assigned to VM '{req.vm_id}' with model '{model_cfg.model_id}'")
        event_broadcaster.publish(
            AgentEvent(
                agent_id=agent_id,
                event_type=AgentEventType.AGENT_CREATED,
                iteration=0,
                timestamp=agent.created_at,
                content=f"Agent '{agent_id}' created with objective: {agent.role}",
                status="idle",
                data={"role": agent.role, "vm_id": agent.vm_id, "model_id": agent.model_id},
            )
        )
        return agent.get_state()


    def get_agent(self, agent_id: str) -> Agent:
        """Retrieve agent instance or raise ValueError."""
        if agent_id not in self._agents:
            raise ValueError(f"Agent '{agent_id}' not found.")
        return self._agents[agent_id]

    def get_agent_state(self, agent_id: str) -> AgentState:
        """Retrieve serializable agent state."""
        return self.get_agent(agent_id).get_state()

    def list_agents(self) -> List[AgentState]:
        """List state of all registered agents."""
        return [a.get_state() for a in self._agents.values()]

    def get_agent_history(self, agent_id: str) -> List[AgentStep]:
        """Return execution history for a given agent."""
        return self.get_agent(agent_id).history

    def start_agent_sync(self, agent_id: str) -> AgentState:
        """Run agent to completion synchronously (useful for integration tests & scripts)."""
        agent = self.get_agent(agent_id)
        if agent.status == AgentStatus.RUNNING:
            raise ValueError(f"Agent '{agent_id}' is already running.")

        with self._inference_lock:
            state = agent.run_all()
        return state

    async def start_agent_async(self, agent_id: str) -> AgentOperationResponse:
        """Launch autonomous execution of the agent as a background task."""
        agent = self.get_agent(agent_id)
        if agent.status == AgentStatus.RUNNING:
            return AgentOperationResponse(
                agent_id=agent_id,
                operation="start",
                success=False,
                message=f"Agent '{agent_id}' is already running.",
                status=agent.status,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        agent.status = AgentStatus.RUNNING

        async def _run_worker():
            loop = asyncio.get_running_loop()
            try:
                # Run the blocking loop in executor with inference semaphore
                def _guarded_run():
                    with self._inference_lock:
                        return agent.run_all()

                await loop.run_in_executor(None, _guarded_run)
            except Exception as e:
                logger.error(f"Error in background agent execution for '{agent_id}': {e}")
                agent.status = AgentStatus.FAILED
                agent.error_message = str(e)
            finally:
                self._active_tasks.pop(agent_id, None)

        task = asyncio.create_task(_run_worker())
        self._active_tasks[agent_id] = task

        return AgentOperationResponse(
            agent_id=agent_id,
            operation="start",
            success=True,
            message=f"Agent '{agent_id}' started autonomous loop in background.",
            status=AgentStatus.RUNNING,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def stop_agent(self, agent_id: str) -> AgentOperationResponse:
        """Request agent to cleanly halt execution."""
        agent = self.get_agent(agent_id)
        agent.request_stop()
        logger.info(f"Stop signal sent to agent '{agent_id}'.")

        return AgentOperationResponse(
            agent_id=agent_id,
            operation="stop",
            success=True,
            message=f"Stop signal sent to agent '{agent_id}'.",
            status=agent.status,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def delete_agent(self, agent_id: str) -> AgentOperationResponse:
        """
        Delete an agent's runtime state and history.
        Does NOT touch the VirtualBox VM, snapshots, or VM files.
        """
        if agent_id not in self._agents:
            raise ValueError(f"Agent '{agent_id}' not found.")

        agent = self._agents[agent_id]
        # Cleanly stop running agent before deletion
        if agent.status == AgentStatus.RUNNING:
            agent.request_stop()

        # Cancel background task if active
        task = self._active_tasks.pop(agent_id, None)
        if task and not task.done():
            task.cancel()

        # Remove from agents dictionary
        del self._agents[agent_id]

        # Purge event broadcaster history and subscribers
        event_broadcaster.clear_agent(agent_id)

        logger.info(f"Agent '{agent_id}' runtime state deleted successfully.")
        return AgentOperationResponse(
            agent_id=agent_id,
            operation="delete",
            success=True,
            message=f"Agent '{agent_id}' runtime deleted successfully.",
            status=AgentStatus.STOPPED,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

