import asyncio
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, AsyncIterator, Any
from fastapi import WebSocket

from backend.agents.agent import Agent
from backend.agents.events import event_broadcaster
from backend.db.repository import ExperimentRepository
from backend.schemas.agent import AgentEvent, AgentStatus
from backend.schemas.experiment import (
    ExperimentStatus,
    ExperimentEventType,
    ExperimentCreateRequest,
    ExperimentDetail,
    ExperimentSummary,
    ExperimentAgentState,
    ExperimentEvent,
    ExperimentOperationResponse,
)
from backend.services.llm_service import LLMService
from backend.services.vm_service import VMService
from backend.tools.registry import ToolRegistry, default_tool_registry
from backend.utils.logger import logger


class ExperimentEventBroadcaster:
    """
    Real-time pub/sub event broadcaster supporting both WebSockets and Server-Sent Events (SSE).
    Thread-safe to dispatch events from background executor threads to async web clients.
    Uses dedicated per-client FIFO asyncio.Queues for WebSockets to guarantee zero dropped events
    and prevent concurrent ASGI send conflicts.
    """

    def __init__(self, repository: Optional[ExperimentRepository] = None):
        self.repository = repository
        self._sse_subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._ws_queues: Dict[str, List[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def register_ws_queue(self, experiment_id: str) -> asyncio.Queue:
        """Register a new FIFO queue for a connected WebSocket client."""
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            if experiment_id not in self._ws_queues:
                self._ws_queues[experiment_id] = []
            self._ws_queues[experiment_id].append(q)
        return q

    def unregister_ws_queue(self, experiment_id: str, q: asyncio.Queue) -> None:
        """Unregister and clean up a WebSocket client queue."""
        with self._lock:
            if experiment_id in self._ws_queues and q in self._ws_queues[experiment_id]:
                self._ws_queues[experiment_id].remove(q)
                if not self._ws_queues[experiment_id]:
                    self._ws_queues.pop(experiment_id, None)

    def publish(self, event: ExperimentEvent) -> None:
        """Publish an experiment event to all WebSocket and SSE listeners and record to DB."""
        # 1. Persist to SQLite repository
        if self.repository:
            try:
                self.repository.add_event(event)
            except Exception as e:
                logger.debug(f"Failed to record event in SQLite: {e}")

        # 2. Collect subscriber queues under lock
        with self._lock:
            sse_queues = list(self._sse_subscribers.get(event.experiment_id, []))
            ws_queues = list(self._ws_queues.get(event.experiment_id, []))

        # 3. Dispatch to SSE queues
        for q in sse_queues:
            try:
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(q.put_nowait, event)
                else:
                    q.put_nowait(event)
            except Exception as e:
                logger.debug(f"Failed to dispatch event to SSE queue: {e}")

        # 4. Dispatch to WebSocket queues safely without blocking or dropping
        if ws_queues:
            payload = json.dumps(event.model_dump())
            for wq in ws_queues:
                try:
                    if self._loop and self._loop.is_running():
                        self._loop.call_soon_threadsafe(wq.put_nowait, payload)
                    else:
                        wq.put_nowait(payload)
                except Exception as e:
                    logger.debug(f"Failed to dispatch event to WS queue: {e}")

    async def subscribe_sse(self, experiment_id: str) -> AsyncIterator[ExperimentEvent]:
        """Subscribe to real-time events for an experiment via SSE."""
        q: asyncio.Queue = asyncio.Queue()
        self._loop = asyncio.get_running_loop()

        with self._lock:
            if experiment_id not in self._sse_subscribers:
                self._sse_subscribers[experiment_id] = []
            self._sse_subscribers[experiment_id].append(q)

        # Replay past lifecycle events from repository if available (exclude ephemeral streaming chunks)
        if self.repository:
            try:
                past_events = [
                    pe for pe in self.repository.get_events(experiment_id, limit=200)
                    if pe.event_type not in ("llm_chunk", "agent_tool_output_chunk")
                ]
                for pe in past_events:
                    yield pe
                    await asyncio.sleep(0.001)
            except Exception as e:
                logger.debug(f"Error fetching past events for SSE replay: {e}")

        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    if event is None:
                        break
                    yield event
                except asyncio.TimeoutError:
                    # Keepalive comment
                    yield ExperimentEvent(
                        experiment_id=experiment_id,
                        event_type="ping",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
        finally:
            with self._lock:
                if experiment_id in self._sse_subscribers and q in self._sse_subscribers[experiment_id]:
                    self._sse_subscribers[experiment_id].remove(q)
                    if not self._sse_subscribers[experiment_id]:
                        self._sse_subscribers.pop(experiment_id, None)


class ExperimentService:
    """
    Phase 3 Orchestrator:
    - Dynamic Multi-Agent Experiment Builder (1 -> max_vm agents)
    - Concurrent Agent Execution using async/task-based orchestration
    - Independent state, memory, and failure isolation
    - WebSocket and SSE real-time telemetry streaming
    - SQLite persistence via ExperimentRepository
    """

    def __init__(
        self,
        llm_service: LLMService,
        vm_service: VMService,
        tool_registry: Optional[ToolRegistry] = None,
        repository: Optional[ExperimentRepository] = None,
    ):
        self.llm_service = llm_service
        self.vm_service = vm_service
        self.tool_registry = tool_registry or default_tool_registry
        self.repository = repository or ExperimentRepository()
        self.broadcaster = ExperimentEventBroadcaster(repository=self.repository)

        # Active in-memory experiment runtimes: experiment_id -> dict of agents
        self._active_agents: Dict[str, Dict[str, Agent]] = {}
        self._active_tasks: Dict[str, asyncio.Task] = {}
        # Concurrency control for local LLM inference safety - allow true concurrent execution
        self._parallelism = max(self.llm_service.registry_config.llm_parallelism, 4)
        self._inference_lock = threading.Semaphore(self._parallelism)

    def create_experiment(self, req: ExperimentCreateRequest) -> ExperimentDetail:
        """
        Dynamically validate and create a new multi-agent experiment.
        Enforces 1 -> max_vm agents, unique VMs per agent, and registry validation.
        """
        sys_config = self.vm_service.get_system_config()
        max_vm = sys_config.max_vm
        configured_vm_ids = [v.vm_id for v in sys_config.vms]

        # 1. Enforce agent count bounds (1 to dynamic max_vm)
        agent_count = len(req.agents)
        if agent_count < 1:
            raise ValueError("An experiment must contain at least 1 agent.")
        if agent_count > max_vm:
            raise ValueError(
                f"Requested {agent_count} agents, but system resource configuration allows a maximum of {max_vm} VMs/agents."
            )

        # 2. Enforce unique VM assignment
        assigned_vms = [a.vm_id for a in req.agents]
        if len(assigned_vms) != len(set(assigned_vms)):
            raise ValueError(
                f"Each agent in an experiment must be assigned to a unique VM. Duplicates found in: {assigned_vms}"
            )

        # 3. Validate VM existence
        for vm_id in assigned_vms:
            if vm_id not in configured_vm_ids:
                raise ValueError(
                    f"Assigned VM '{vm_id}' is not configured in the laboratory VM registry ({configured_vm_ids})."
                )

        # 4. Validate models and tools
        agents_data: List[Dict[str, Any]] = []
        for idx, a in enumerate(req.agents):
            model_cfg = self.llm_service.resolve_model(a.model_id)
            tools = a.tools or self.tool_registry.list_tool_names()
            for t in tools:
                if not self.tool_registry.get(t):
                    raise ValueError(f"Agent {idx+1}: Tool '{t}' is not recognized in ToolRegistry.")

            agent_id = f"agent-{idx + 1}"
            agents_data.append(
                {
                    "agent_id": agent_id,
                    "role": a.role,
                    "vm_id": a.vm_id,
                    "model_id": model_cfg.model_id,
                    "tools": tools,
                    "iteration_limit": a.iteration_limit or self.llm_service.registry_config.default_iteration_limit,
                    "command_timeout": a.command_timeout or self.llm_service.registry_config.default_timeout,
                }
            )

        # 5. Generate experiment ID and persist to SQLite
        exp_id = f"exp-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        detail = self.repository.create_experiment(
            experiment_id=exp_id,
            name=req.name,
            description=req.description,
            agents=agents_data,
            raw_config=req.model_dump(),
        )

        logger.info(
            f"Created Experiment '{exp_id}' ('{req.name}') with {len(agents_data)} agents on VMs: {assigned_vms}"
        )

        # 6. Publish creation event
        self.broadcaster.publish(
            ExperimentEvent(
                experiment_id=exp_id,
                event_type=ExperimentEventType.EXPERIMENT_CREATED,
                iteration=0,
                timestamp=detail.created_at,
                content=f"Experiment '{detail.name}' created with {len(agents_data)} configured agents.",
                status=ExperimentStatus.CREATED.value,
                data={
                    "name": detail.name,
                    "agent_count": len(agents_data),
                    "vms": assigned_vms,
                },
            )
        )

        return detail

    def get_experiment(self, experiment_id: str) -> ExperimentDetail:
        """Fetch experiment details, merging live memory states if currently executing."""
        exp = self.repository.get_experiment(experiment_id)
        if not exp:
            raise ValueError(f"Experiment '{experiment_id}' not found.")

        # If running in memory, sync live statuses
        if experiment_id in self._active_agents:
            live_agents = self._active_agents[experiment_id]
            updated_agents: List[ExperimentAgentState] = []
            for a_state in exp.agents:
                if a_state.agent_id in live_agents:
                    live_agent = live_agents[a_state.agent_id]
                    a_state.status = live_agent.status.value if hasattr(live_agent.status, "value") else str(live_agent.status)
                    a_state.current_iteration = live_agent.current_iteration
                    a_state.history = live_agent.history
                    a_state.error_message = live_agent.error_message
                    a_state.final_conclusion = live_agent.final_conclusion or a_state.final_conclusion
                    a_state.updated_at = live_agent.updated_at
                updated_agents.append(a_state)
            exp.agents = updated_agents

        return exp

    def list_experiments(self) -> List[ExperimentSummary]:
        """List summaries of all experiments."""
        summaries = self.repository.list_experiments()
        # Merge live status for running experiments
        for s in summaries:
            if s.id in self._active_tasks and not self._active_tasks[s.id].done():
                s.status = ExperimentStatus.RUNNING
        return summaries

    async def start_experiment(self, experiment_id: str) -> ExperimentOperationResponse:
        """
        Launch concurrent autonomous execution for all agents in the experiment.
        Uses asyncio.create_task and asyncio.gather for parallel multi-agent operation.
        Provides failure isolation so errors in one agent do not crash others.
        """
        exp = self.get_experiment(experiment_id)
        if exp.status == ExperimentStatus.RUNNING:
            return ExperimentOperationResponse(
                experiment_id=experiment_id,
                operation="start",
                success=False,
                message=f"Experiment '{experiment_id}' is already running.",
                status=exp.status,
            )

        # Validate that all requested agent models are locally installed in Ollama before starting
        installed_models = set(self.llm_service.provider.list_models())
        uninstalled = []
        for a_conf in exp.agents:
            model_cfg = self.llm_service.resolve_model(a_conf.model_id)
            is_inst = model_cfg.model_name in installed_models or any(model_cfg.model_name == m.split(":")[0] for m in installed_models)
            if not is_inst:
                uninstalled.append(f"Agent '{a_conf.agent_id}' requested model '{model_cfg.display_name or model_cfg.model_name}' ({model_cfg.model_name})")

        if uninstalled:
            missing_desc = "; ".join(uninstalled)
            raise ValueError(
                f"Cannot start experiment: One or more selected models are not installed in local Ollama: {missing_desc}. Please install them before running."
            )

        # Update experiment status to running
        self.repository.update_experiment_status(experiment_id, ExperimentStatus.RUNNING)
        self.broadcaster.set_loop(asyncio.get_running_loop())

        # Instantiate independent Agent objects
        agents_map: Dict[str, Agent] = {}
        for a_conf in exp.agents:
            # Event callback: translate agent events to experiment events and persist
            def make_event_callback(ag_id: str, vm_id: str):
                def _cb(agent_event: AgentEvent):
                    exp_event = ExperimentEvent(
                        experiment_id=experiment_id,
                        event_id=agent_event.event_id,
                        agent_id=ag_id,
                        event_type=agent_event.event_type,
                        iteration=agent_event.iteration,
                        timestamp=agent_event.timestamp,
                        tool_name=agent_event.tool_name,
                        content=agent_event.content,
                        status=agent_event.status,
                        error=agent_event.error,
                        summary=agent_event.summary,
                        parameters=agent_event.parameters,
                        output_chunk=agent_event.output_chunk,
                        stream=agent_event.stream,
                        vm_id=agent_event.vm_id or vm_id,
                        conclusion=agent_event.conclusion,
                        data={**agent_event.data, "vm_id": vm_id},
                    )
                    self.broadcaster.publish(exp_event)
                return _cb

            agent_inst = Agent(
                agent_id=a_conf.agent_id,
                role=a_conf.role,
                vm_id=a_conf.vm_id,
                model_id=a_conf.model_id,
                llm_service=self.llm_service,
                vm_provider=self.vm_service.provider,
                tool_registry=self.tool_registry,
                allowed_tools=self.tool_registry.list_tool_names(),
                iteration_limit=a_conf.iteration_limit,
                command_timeout=a_conf.command_timeout,
                event_callback=make_event_callback(a_conf.agent_id, a_conf.vm_id),
                inference_semaphore=self._inference_lock,
            )
            agents_map[a_conf.agent_id] = agent_inst

        self._active_agents[experiment_id] = agents_map

        # Broadcast experiment started
        self.broadcaster.publish(
            ExperimentEvent(
                experiment_id=experiment_id,
                event_type=ExperimentEventType.EXPERIMENT_STARTED,
                timestamp=datetime.now(timezone.utc).isoformat(),
                content=f"Experiment '{exp.name}' started concurrent execution with {len(agents_map)} agents.",
                status=ExperimentStatus.RUNNING.value,
                data={"agent_count": len(agents_map)},
            )
        )

        # Launch the concurrent coordinator task
        task = asyncio.create_task(self._orchestrate_experiment(experiment_id, agents_map))
        self._active_tasks[experiment_id] = task

        return ExperimentOperationResponse(
            experiment_id=experiment_id,
            operation="start",
            success=True,
            message=f"Experiment '{experiment_id}' started with {len(agents_map)} concurrent agents.",
            status=ExperimentStatus.RUNNING,
        )

    async def _orchestrate_experiment(
        self,
        experiment_id: str,
        agents_map: Dict[str, Agent],
    ) -> None:
        """
        Internal worker that executes all agents concurrently with failure isolation.
        """
        loop = asyncio.get_running_loop()
        exp = self.get_experiment(experiment_id)

        async def _run_single_agent(agent: Agent) -> Agent:
            logger.info(f"[{experiment_id}] Starting concurrent worker for agent '{agent.agent_id}' on VM '{agent.vm_id}'")
            try:
                def _run_with_semaphore():
                    return agent.run_all()

                await loop.run_in_executor(None, _run_with_semaphore)
            except Exception as e:
                logger.error(f"[{experiment_id}] Agent '{agent.agent_id}' failed: {e}")
                agent.status = AgentStatus.FAILED
                agent.error_message = str(e)
            finally:
                # Persist final agent state to SQLite
                try:
                    hist_data = [s.model_dump() for s in agent.history]
                    self.repository.update_agent_state(
                        experiment_id=experiment_id,
                        agent_id=agent.agent_id,
                        status=agent.status.value if hasattr(agent.status, "value") else str(agent.status),
                        current_iteration=agent.current_iteration,
                        error_message=agent.error_message,
                        history=hist_data,
                        final_conclusion=agent.final_conclusion,
                    )
                except Exception as db_err:
                    logger.error(f"[{experiment_id}] Failed to save final agent state to DB: {db_err}")

            return agent

        # Launch all agents concurrently with asyncio.gather
        agent_coroutines = [_run_single_agent(a) for a in agents_map.values()]
        results = await asyncio.gather(*agent_coroutines, return_exceptions=True)

        # Analyze outcomes
        completed_at = datetime.now(timezone.utc).isoformat()
        any_stopped = any(a.status == AgentStatus.STOPPED for a in agents_map.values())
        all_failed = all(a.status == AgentStatus.FAILED for a in agents_map.values())

        if any_stopped:
            final_status = ExperimentStatus.STOPPED
            event_type = ExperimentEventType.EXPERIMENT_STOPPED
            msg = f"Experiment '{experiment_id}' stopped by user."
        elif all_failed:
            final_status = ExperimentStatus.FAILED
            event_type = ExperimentEventType.EXPERIMENT_FAILED
            msg = f"All agents in experiment '{experiment_id}' encountered errors."
        else:
            final_status = ExperimentStatus.COMPLETED
            event_type = ExperimentEventType.EXPERIMENT_COMPLETED
            msg = f"Experiment '{experiment_id}' completed execution successfully."

        # Experiment-Level LLM Synthesis across all agents
        experiment_synthesis = ""
        try:
            agents_summary_lines = []
            for a in agents_map.values():
                c = a.final_conclusion or "No conclusion generated."
                steps_cnt = len(a.history)
                succ_cnt = sum(1 for s in a.history if s.success)
                a_stat = a.status.value if hasattr(a.status, 'value') else str(a.status)

                details = [
                    f"Agent: {a.agent_id} | Assigned VM: {a.vm_id} | Status: {a_stat}",
                    f"Role/Objective: {a.role}",
                    f"Iterations: {a.current_iteration}/{a.iteration_limit} (Iteration Limit Reached: {a.iteration_limit_reached})",
                    f"Steps Executed: {steps_cnt} (Successful: {succ_cnt}/{steps_cnt})",
                    f"Conclusion Summary: {c}",
                ]
                if getattr(a, "structured_conclusion", None):
                    sc = a.structured_conclusion
                    if sc.findings:
                        details.append(f"Discovered Findings: {json.dumps(sc.findings)}")
                    if sc.evidence:
                        details.append(f"Observable Evidence: {json.dumps(sc.evidence[:5])}")
                    if sc.errors:
                        details.append(f"Errors Encountered: {json.dumps(sc.errors)}")
                    if sc.unresolved_items:
                        details.append(f"Unresolved Actions: {json.dumps(sc.unresolved_items)}")

                agents_summary_lines.append("\n".join(details))
            agents_summary_text = "\n\n".join(agents_summary_lines)

            exp_prompt = (
                f"You are the CyberArena Experiment Orchestrator reviewing a completed multi-agent experiment.\n"
                f"Experiment Name: '{exp.name}'\n"
                f"Description: {exp.description or 'None'}\n\n"
                f"Agent Execution Summary & Discovered Evidence:\n"
                f"{agents_summary_text}\n\n"
                f"Synthesize an authoritative, structured markdown experiment report with these exact sections:\n"
                f"### Overall Experiment Summary\n"
                f"### Key Findings\n"
                f"### Per-Agent Observations\n"
                f"### Limitations & Security Observations\n\n"
                f"Be factual, concise, and professional. Base findings strictly on the agents' reported conclusions, concrete evidence, and metrics. If an agent reached its iteration limit, clearly treat its findings as partial rather than complete."
            )

            default_model = self.llm_service.registry_config.default_model
            def _gen_exp_synthesis():
                return self.llm_service.generate(
                    model_id=default_model,
                    prompt=exp_prompt,
                    system_prompt="You are an expert security orchestrator producing comprehensive executive experiment reports.",
                    json_format=False,
                    temperature=0.3,
                    timeout=180,
                )

            synthesis_resp = await loop.run_in_executor(None, _gen_exp_synthesis)
            clean_syn = re.sub(r"<think>.*?</think>", "", synthesis_resp.text, flags=re.DOTALL).strip()
            experiment_synthesis = clean_syn or synthesis_resp.text.strip()
        except Exception as syn_err:
            logger.warning(f"[{experiment_id}] Experiment LLM synthesis failed: {syn_err}")
            all_findings = []
            all_errors = []
            for a in agents_map.values():
                sc = getattr(a, "structured_conclusion", None)
                if sc:
                    for f in sc.findings:
                        all_findings.append(f"- **[{a.agent_id}]**: {f}")
                    for err in sc.errors:
                        all_errors.append(f"- **[{a.agent_id}]**: {err}")
                elif a.final_conclusion:
                    all_findings.append(f"- **[{a.agent_id}]**: {a.final_conclusion}")
                if getattr(a, "iteration_limit_reached", False):
                    all_errors.append(f"- **[{a.agent_id}]**: Stopped because iteration limit ({a.iteration_limit}) was reached.")

            experiment_synthesis = (
                f"### Overall Experiment Summary\n"
                f"Deterministic Executive Report: Multi-agent experiment '{exp.name}' concluded with {len(agents_map)} participating agents across assigned nodes. "
                f"(LLM report synthesis fallback engaged: {syn_err})\n\n"
                f"### Key Findings\n" +
                ("\n".join(all_findings) if all_findings else "- No specific findings reported.") +
                f"\n\n### Per-Agent Observations\n" +
                "\n".join([f"- **{a.agent_id}** ({a.vm_id}): Status: {a.status.value}. Summary: {a.final_conclusion or 'Completed'}" for a in agents_map.values()]) +
                f"\n\n### Limitations & Security Observations\n" +
                ("\n".join(all_errors) if all_errors else "- All agent cycles executed within security parameters with no reported exceptions.")
            )

        # Update experiment conclusion in SQLite
        self.repository.update_experiment_conclusion(experiment_id, experiment_synthesis)

        # Broadcast experiment summary updated event
        self.broadcaster.publish(
            ExperimentEvent(
                experiment_id=experiment_id,
                event_type=ExperimentEventType.EXPERIMENT_SUMMARY_UPDATED,
                timestamp=datetime.now(timezone.utc).isoformat(),
                content=experiment_synthesis,
                conclusion=experiment_synthesis,
                status=final_status.value,
                data={"conclusion": experiment_synthesis},
            )
        )

        # Update experiment status in repository
        self.repository.update_experiment_status(
            experiment_id=experiment_id,
            status=final_status,
            completed_at=completed_at,
        )

        # Broadcast completion event
        self.broadcaster.publish(
            ExperimentEvent(
                experiment_id=experiment_id,
                event_type=event_type,
                timestamp=completed_at,
                content=msg,
                conclusion=experiment_synthesis,
                status=final_status.value,
                data={
                    "completed_at": completed_at,
                    "final_conclusion": experiment_synthesis,
                    "agents": {
                        a.agent_id: {
                            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
                            "iterations": a.current_iteration,
                            "steps": len(a.history),
                            "conclusion": a.final_conclusion,
                        }
                        for a in agents_map.values()
                    },
                },
            )
        )

        logger.info(f"[{experiment_id}] Final experiment status: {final_status.value}")
        self._active_tasks.pop(experiment_id, None)

    def stop_experiment(self, experiment_id: str) -> ExperimentOperationResponse:
        """Cleanly request all running agents in the experiment to halt execution."""
        if experiment_id not in self._active_agents:
            # Check DB status
            exp = self.repository.get_experiment(experiment_id)
            if not exp:
                raise ValueError(f"Experiment '{experiment_id}' not found.")
            return ExperimentOperationResponse(
                experiment_id=experiment_id,
                operation="stop",
                success=True,
                message=f"Experiment '{experiment_id}' is not currently running.",
                status=exp.status,
            )

        agents = self._active_agents[experiment_id]
        for a in agents.values():
            a.request_stop()

        logger.info(f"Stop signal sent to all agents in experiment '{experiment_id}'")

        self.repository.update_experiment_status(experiment_id, ExperimentStatus.STOPPED)

        self.broadcaster.publish(
            ExperimentEvent(
                experiment_id=experiment_id,
                event_type=ExperimentEventType.EXPERIMENT_STOPPED,
                timestamp=datetime.now(timezone.utc).isoformat(),
                content=f"Stop requested for experiment '{experiment_id}'.",
                status=ExperimentStatus.STOPPED.value,
            )
        )

        return ExperimentOperationResponse(
            experiment_id=experiment_id,
            operation="stop",
            success=True,
            message=f"Stop signal transmitted to {len(agents)} agents.",
            status=ExperimentStatus.STOPPED,
        )

    def delete_experiment(self, experiment_id: str) -> ExperimentOperationResponse:
        """Delete experiment records, cascaded agents and events from SQLite."""
        if experiment_id in self._active_agents:
            self.stop_experiment(experiment_id)

        task = self._active_tasks.pop(experiment_id, None)
        if task and not task.done():
            task.cancel()

        self._active_agents.pop(experiment_id, None)

        deleted = self.repository.delete_experiment(experiment_id)
        if not deleted:
            raise ValueError(f"Experiment '{experiment_id}' not found.")

        return ExperimentOperationResponse(
            experiment_id=experiment_id,
            operation="delete",
            success=True,
            message=f"Experiment '{experiment_id}' deleted successfully.",
            status=ExperimentStatus.STOPPED,
        )
