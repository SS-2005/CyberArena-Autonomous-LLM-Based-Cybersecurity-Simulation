import json
import re
import time
import threading
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Callable

from backend.schemas.agent import (
    AgentStatus,
    AgentActionRequest,
    AgentStep,
    AgentState,
    AgentEvent,
    AgentEventType,
    ExecutionRecord,
    AgentConclusion,
)
from backend.agents.events import event_broadcaster
from backend.services.llm_service import LLMService
from backend.virtualization.base import VMProvider
from backend.tools.registry import ToolRegistry, default_tool_registry
from backend.utils.logger import logger


class Agent:
    """
    Generic Autonomous AI Agent for CyberArena.
    Role is dynamically user-defined (no hardcoded attacker/defender logic).
    Follows a ReAct loop: OBSERVE -> THINK / PLAN -> TOOL REQUEST -> VALIDATE -> EXECUTE -> OBSERVE.
    Operates strictly within its assigned VM.
    Supports controlled privileged operations and evidence-based conclusion synthesis.
    """

    def __init__(
        self,
        agent_id: str,
        role: str,
        vm_id: str,
        model_id: str,
        llm_service: LLMService,
        vm_provider: VMProvider,
        tool_registry: Optional[ToolRegistry] = None,
        allowed_tools: Optional[List[str]] = None,
        iteration_limit: int = 10,
        command_timeout: int = 60,
        event_callback: Optional[Callable[[AgentEvent], None]] = None,
        inference_semaphore: Optional[threading.Semaphore] = None,
        think: Optional[bool] = None,
    ):
        self.agent_id = agent_id
        self.role = role
        self.vm_id = vm_id
        self.model_id = model_id
        self.llm_service = llm_service
        self.vm_provider = vm_provider
        self.tool_registry = tool_registry or default_tool_registry
        self.allowed_tools = allowed_tools or self.tool_registry.list_tool_names()
        self.iteration_limit = iteration_limit
        self.command_timeout = command_timeout
        self.event_callback = event_callback
        self.inference_semaphore = inference_semaphore

        if think is not None:
            self.think = think
        else:
            try:
                m_cfg = self.llm_service.resolve_model(self.model_id)
                self.think = m_cfg.think
            except Exception:
                self.think = False

        self.status = AgentStatus.IDLE
        self.current_iteration = 0
        self.final_conclusion: Optional[str] = None
        self.structured_conclusion: Optional[AgentConclusion] = None
        self.history: List[AgentStep] = []
        self.execution_records: List[ExecutionRecord] = []
        self.iteration_limit_reached: bool = False
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.error_message: Optional[str] = None
        self._stop_requested = False

    def _emit_event(
        self,
        event_type: str,
        iteration: int = 0,
        tool_name: Optional[str] = None,
        content: Optional[str] = None,
        status: Optional[str] = None,
        error: Optional[str] = None,
        summary: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        output_chunk: Optional[str] = None,
        stream: Optional[str] = None,
        vm_id: Optional[str] = None,
        conclusion: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit real-time telemetry event to subscribers via event_broadcaster and event_callback."""
        try:
            curr_status = status or (self.status.value if hasattr(self.status, "value") else str(self.status))
            event = AgentEvent(
                agent_id=self.agent_id,
                event_type=event_type,
                iteration=iteration if iteration > 0 else self.current_iteration,
                timestamp=datetime.now(timezone.utc).isoformat(),
                tool_name=tool_name,
                content=content,
                status=curr_status,
                error=error,
                summary=summary,
                parameters=parameters,
                output_chunk=output_chunk,
                stream=stream,
                vm_id=vm_id or self.vm_id,
                conclusion=conclusion,
                data=data or {},
            )
            event_broadcaster.publish(event)
            if self.event_callback:
                try:
                    self.event_callback(event)
                except Exception as cb_err:
                    logger.debug(f"Error executing agent event_callback: {cb_err}")
        except Exception as e:
            logger.debug(f"Error publishing agent event: {e}")

    def request_stop(self) -> None:
        """Signal the agent to stop execution cleanly after the current step."""
        self._stop_requested = True
        self.status = AgentStatus.STOPPED
        self._touch()
        self._emit_event(
            event_type=AgentEventType.AGENT_STOPPED,
            content="Agent stop requested by user.",
            status="stopped",
        )

    def cancel(self) -> None:
        """Cancel the agent run immediately."""
        self._stop_requested = True
        self.status = AgentStatus.CANCELLED
        self._touch()
        self._emit_event(
            event_type=AgentEventType.AGENT_STOPPED,
            content="Agent cancelled.",
            status="cancelled",
        )

    def get_state(self) -> AgentState:
        """Return the current serializable agent state."""
        return AgentState(
            agent_id=self.agent_id,
            role=self.role,
            model_id=self.model_id,
            vm_id=self.vm_id,
            allowed_tools=self.allowed_tools,
            status=self.status,
            current_iteration=self.current_iteration,
            iteration_limit=self.iteration_limit,
            command_timeout=self.command_timeout,
            final_conclusion=self.final_conclusion,
            structured_conclusion=self.structured_conclusion,
            history=self.history,
            execution_records=self.execution_records,
            created_at=self.created_at,
            updated_at=self.updated_at,
            error_message=self.error_message,
        )

    def _touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def _build_system_prompt(self) -> str:
        tool_schemas = self.tool_registry.get_tool_schemas(self.allowed_tools)
        schemas_str = json.dumps(tool_schemas, indent=2)

        return (
            f"You are an autonomous cybersecurity agent in CyberArena assigned to an isolated laboratory VM.\n"
            f"Assigned VM: {self.vm_id}\n"
            f"Objective / Role: {self.role}\n\n"
            f"Available Tools:\n"
            f"{schemas_str}\n"
            f"- Special tool 'finish': When objective is fulfilled or cannot proceed, call tool 'finish' with parameters: {{\"summary\": \"Conclusion and findings\"}}.\n\n"
            f"CRITICAL RULES & SECURITY POLICIES:\n"
            f"1. You only interact with your assigned VM '{self.vm_id}' through the provided tools. Never assume access to host files or public networks.\n"
            f"2. ADMINISTRATIVE PRIVILEGES: You have passwordless sudo permissions on this VM. When performing operations that require administrative rights (such as creating files in /root, modifying system configurations, installing packages, or managing services), use `sudo` (e.g. `sudo touch /root/sahil.txt`) or the dedicated tools. NEVER pipe passwords (e.g. echo ... | sudo -S).\n"
            f"3. PROHIBITED DESTRUCTIVE OPERATIONS: Do NOT attempt operations that can destroy or brick the VM (such as 'rm -rf /', raw disk overwrites, filesystem formatting 'mkfs', fork bombs, or poweroff/shutdown). All standard administrative, inspection, and software installation commands are fully permitted.\n"
            f"4. DEPENDENCY & PACKAGE INSTALLATION: You have full access to install software packages and libraries needed for your task via 'install_package' or 'sudo apt-get install -y <pkg>'.\n"
            f"5. ANTI-REPETITION CONSTRAINT: Do NOT repeat the exact same tool call or command if it previously failed or produced an error. If an action fails, analyze the error message, adapt your parameters or command, try an alternative approach, or call 'finish' with your findings.\n"
            f"6. Every response MUST be a single valid JSON object strictly matching this format:\n"
            f"{{\n"
            f'  "thought": "Direct, concise reasoning (1-2 sentences) on current state and next action",\n'
            f'  "tool": "tool_name_from_available_tools_or_finish",\n'
            f'  "parameters": {{ ... }},\n'
            f'  "summary": "Short user-facing summary of this action"\n'
            f"}}\n"
            f"7. Do not include markdown formatting or backticks outside the JSON object.\n"
            f"8. Keep internal reasoning direct and concise (1-2 sentences) to ensure real-time execution. Output the JSON object immediately.\n"
            f"9. {'CRITICAL: Do NOT generate internal thought chains or <think> tags. Directly start your output with \'{\' and output valid JSON.' if not self.think else 'Extended thinking is enabled. Provide concise reasoning inside the JSON thought property.'}\n"
        )

    def _build_conversation_prompt(self) -> str:
        prompt_lines = [f"Agent Objective: {self.role}"]

        if not self.history:
            prompt_lines.append(
                "Execution has just started. Plan your first step, select a tool, and output your JSON action."
            )
        else:
            prompt_lines.append(f"History of steps taken so far ({len(self.history)} steps):")
            for step in self.history:
                prompt_lines.append(f"--- Step {step.step_number} ---")
                prompt_lines.append(f"Action: Tool='{step.action.tool}', Summary='{step.action.summary}'")
                prompt_lines.append(f"Parameters: {json.dumps(step.action.parameters)}")
                prompt_lines.append(f"Success: {step.success}")
                if step.execution_record:
                    rec = step.execution_record
                    if rec.exit_code is not None:
                        prompt_lines.append(f"Exit Code: {rec.exit_code}")
                    if rec.error_type:
                        prompt_lines.append(f"Error Type: {rec.error_type}")
                    if rec.error:
                        prompt_lines.append(f"Error Message: {rec.error}")
                obs_snippet = step.observation.strip()
                if len(obs_snippet) > 800:
                    obs_snippet = obs_snippet[:800] + "... [truncated]"
                prompt_lines.append(f"Observation:\n{obs_snippet}")

            last_step = self.history[-1]
            if not last_step.success:
                prompt_lines.append(
                    f"\n⚠️ NOTICE: Previous step {last_step.step_number} failed with observation: '{last_step.observation}'.\n"
                    f"CRITICAL: Do NOT execute the exact same failed action again. Adapt your approach, adjust parameters, try an alternative command, or call 'finish'."
                )

            prompt_lines.append(
                f"\nCurrent Iteration: {self.current_iteration + 1} of {self.iteration_limit}.\n"
                f"Analyze previous observations and determine your next action. Output valid JSON."
            )

        return "\n".join(prompt_lines)

    def _parse_llm_action(self, response_text: str) -> AgentActionRequest:
        """Parse and validate JSON response from LLM."""
        raw = response_text.strip()
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            raw = match.group(1).strip()
        else:
            first_brace = raw.find("{")
            last_brace = raw.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                raw = raw[first_brace : last_brace + 1]

        data = json.loads(raw)
        tool_name = str(data.get("tool", "")).strip()
        parameters = data.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        summary = str(data.get("summary") or data.get("thought") or f"Execute {tool_name}").strip()

        if not tool_name:
            raise ValueError("Response missing required 'tool' field.")

        return AgentActionRequest(tool=tool_name, parameters=parameters, summary=summary)

    def step(self) -> AgentStep:
        """Execute a single autonomous cycle."""
        if self._stop_requested:
            if self.status != AgentStatus.CANCELLED:
                self.status = AgentStatus.STOPPED
            self._touch()
            self._emit_event(
                event_type=AgentEventType.AGENT_STOPPED,
                iteration=self.current_iteration,
                content="Agent stopped on user request.",
                status=self.status.value,
            )
            step_record = AgentStep(
                step_number=self.current_iteration,
                action=AgentActionRequest(tool="stop", parameters={}, summary="Stop requested by user"),
                observation="Agent stopped on user request.",
                success=True,
                duration=0.0,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return step_record

        self.current_iteration += 1
        step_num = self.current_iteration
        start_time = time.time()

        self._emit_event(
            event_type=AgentEventType.AGENT_ITERATION_STARTED,
            iteration=step_num,
            content=f"Iteration {step_num} started",
        )

        system_prompt = self._build_system_prompt()
        prompt = self._build_conversation_prompt()

        self._emit_event(
            event_type=AgentEventType.LLM_STARTED,
            iteration=step_num,
            content="LLM generation started...",
            data={"model": self.model_id},
        )

        try:
            accumulated_thinking = ""
            accumulated_response = ""
            token_count = 0
            stream_worked = False

            def _execute_llm_inference():
                nonlocal accumulated_thinking, accumulated_response, token_count, stream_worked
                try:
                    chunks = self.llm_service.generate_stream(
                        model_id=self.model_id,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        json_format=True,
                        temperature=0.4,
                        timeout=self.command_timeout,
                        think=self.think,
                    )
                    for chunk_obj in chunks:
                        if self._stop_requested:
                            break
                        if isinstance(chunk_obj, dict):
                            chunk = chunk_obj.get("chunk", "")
                            chunk_type = chunk_obj.get("type", "response")
                            done = chunk_obj.get("done", False)
                            if chunk:
                                token_count += 1
                                stream_worked = True
                                if chunk_type == "thinking":
                                    accumulated_thinking += chunk
                                else:
                                    accumulated_response += chunk

                                accumulated_full = (
                                    f"Thinking:\n{accumulated_thinking}\n\n{accumulated_response}"
                                    if (accumulated_thinking and accumulated_response)
                                    else (accumulated_thinking or accumulated_response)
                                )

                                self._emit_event(
                                    event_type=AgentEventType.LLM_CHUNK,
                                    iteration=step_num,
                                    content=chunk,
                                    data={
                                        "chunk_type": chunk_type,
                                        "chunk": chunk,
                                        "thinking": accumulated_thinking,
                                        "response": accumulated_response,
                                        "accumulated": accumulated_full,
                                        "tokens": token_count,
                                        "step": step_num,
                                    },
                                )
                            if done:
                                break
                except Exception as stream_err:
                    logger.debug(f"Streaming exception: {stream_err}")

                if not stream_worked or (not accumulated_response and not accumulated_thinking):
                    gen_resp = self.llm_service.generate(
                        model_id=self.model_id,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        json_format=True,
                        temperature=0.4,
                        timeout=self.command_timeout,
                        think=self.think,
                    )
                    accumulated_response = gen_resp.text
                    token_count = gen_resp.tokens_generated or 1
                    self._emit_event(
                        event_type=AgentEventType.LLM_CHUNK,
                        iteration=step_num,
                        content=accumulated_response,
                        data={
                            "chunk_type": "response",
                            "chunk": accumulated_response,
                            "thinking": accumulated_thinking,
                            "response": accumulated_response,
                            "accumulated": accumulated_response,
                            "tokens": token_count,
                            "step": step_num,
                        },
                    )

            if self.inference_semaphore:
                with self.inference_semaphore:
                    _execute_llm_inference()
            else:
                _execute_llm_inference()

            llm_text = accumulated_response or accumulated_thinking
            llm_duration = round(time.time() - start_time, 3)

            self._emit_event(
                event_type=AgentEventType.LLM_COMPLETED,
                iteration=step_num,
                content=llm_text,
                data={
                    "duration": llm_duration,
                    "tokens": token_count,
                    "thinking": accumulated_thinking,
                    "response": accumulated_response,
                    "step": step_num,
                },
            )

        except Exception as e:
            err_msg = f"LLM inference error at iteration {step_num}: {e}"
            logger.error(err_msg)
            duration = round(time.time() - start_time, 3)
            self._emit_event(
                event_type=AgentEventType.AGENT_FAILED,
                iteration=step_num,
                error=err_msg,
                status="failed",
            )
            exec_rec = ExecutionRecord(
                iteration=step_num,
                timestamp=datetime.now(timezone.utc).isoformat(),
                action_type="llm_inference",
                tool_name="llm_generate",
                arguments_safe={},
                result="",
                error=err_msg,
                error_type="llm_inference_failure",
                duration=duration,
                success=False,
                observation_summary=err_msg,
            )
            self.execution_records.append(exec_rec)
            step_record = AgentStep(
                step_number=step_num,
                action=AgentActionRequest(tool="unknown", parameters={}, summary="LLM Inference Failed"),
                observation=err_msg,
                success=False,
                duration=duration,
                timestamp=datetime.now(timezone.utc).isoformat(),
                execution_record=exec_rec,
            )
            self.history.append(step_record)
            self._touch()
            self._emit_event(
                event_type=AgentEventType.AGENT_ITERATION_COMPLETED,
                iteration=step_num,
                content=f"Iteration {step_num} failed",
                data={
                    "success": False,
                    "step": step_num,
                    "step_record": step_record.model_dump(),
                    "agent_id": self.agent_id,
                },
            )
            return step_record

        # Parse LLM action
        try:
            action = self._parse_llm_action(llm_text)
            self._emit_event(
                event_type=AgentEventType.AGENT_REASONING_SUMMARY,
                iteration=step_num,
                content=action.summary,
                summary=action.summary,
                data={"summary": action.summary},
            )
            self._emit_event(
                event_type=AgentEventType.AGENT_ACTION_REQUESTED,
                iteration=step_num,
                tool_name=action.tool,
                content=f"Action requested: {action.tool}",
                summary=action.summary,
                parameters=action.parameters,
                data={"parameters": action.parameters, "summary": action.summary},
            )
            self._emit_event(
                event_type=AgentEventType.TOOL_REQUESTED,
                iteration=step_num,
                tool_name=action.tool,
                content=action.summary,
                summary=action.summary,
                parameters=action.parameters,
                data={"parameters": action.parameters, "summary": action.summary},
            )
        except Exception as e:
            parse_err = f"Failed to parse LLM structured action: {e}. Raw response: {llm_text[:200]}"
            logger.warning(parse_err)
            duration = round(time.time() - start_time, 3)
            self._emit_event(
                event_type=AgentEventType.TOOL_FAILED,
                iteration=step_num,
                tool_name="malformed",
                error=parse_err,
            )
            exec_rec = ExecutionRecord(
                iteration=step_num,
                timestamp=datetime.now(timezone.utc).isoformat(),
                action_type="parse_action",
                tool_name="malformed",
                arguments_safe={},
                result="",
                error=parse_err,
                error_type="malformed_action_json",
                duration=duration,
                success=False,
                observation_summary="Failed to parse valid JSON action from LLM.",
            )
            self.execution_records.append(exec_rec)
            step_record = AgentStep(
                step_number=step_num,
                action=AgentActionRequest(tool="malformed", parameters={}, summary="Parse Failure"),
                observation=f"Action validation error: {parse_err}. Please output valid JSON format.",
                success=False,
                duration=duration,
                timestamp=datetime.now(timezone.utc).isoformat(),
                execution_record=exec_rec,
            )
            self.history.append(step_record)
            self._touch()
            self._emit_event(
                event_type=AgentEventType.AGENT_ITERATION_COMPLETED,
                iteration=step_num,
                content=f"Iteration {step_num} failed (parse error)",
                data={
                    "success": False,
                    "step": step_num,
                    "step_record": step_record.model_dump(),
                    "agent_id": self.agent_id,
                },
            )
            return step_record

        # Check if agent decided to finish
        if action.tool.lower() == "finish":
            duration = round(time.time() - start_time, 3)
            final_summary = action.parameters.get("summary") or action.summary or "Objective completed."
            self._emit_event(
                event_type=AgentEventType.AGENT_COMPLETED,
                iteration=step_num,
                content=final_summary,
                status="completed",
                summary=final_summary,
                data={"summary": final_summary, "total_iterations": step_num},
            )
            exec_rec = ExecutionRecord(
                iteration=step_num,
                timestamp=datetime.now(timezone.utc).isoformat(),
                action_type="finish",
                tool_name="finish",
                arguments_safe={"summary": final_summary},
                result=final_summary,
                duration=duration,
                success=True,
                observation_summary=final_summary,
            )
            self.execution_records.append(exec_rec)
            step_record = AgentStep(
                step_number=step_num,
                action=action,
                observation=f"Goal completed: {final_summary}",
                success=True,
                duration=duration,
                timestamp=datetime.now(timezone.utc).isoformat(),
                execution_record=exec_rec,
            )
            self.history.append(step_record)
            self.status = AgentStatus.COMPLETED
            self._touch()
            self._emit_event(
                event_type=AgentEventType.AGENT_ITERATION_COMPLETED,
                iteration=step_num,
                content=f"Iteration {step_num} completed (goal reached)",
                data={
                    "success": True,
                    "step": step_num,
                    "step_record": step_record.model_dump(),
                    "agent_id": self.agent_id,
                },
            )
            return step_record

        # Validate tool against allowed tools
        if action.tool not in self.allowed_tools:
            duration = round(time.time() - start_time, 3)
            obs = f"Tool '{action.tool}' is not in allowed tools list ({self.allowed_tools}). Choose from allowed tools."
            self._emit_event(
                event_type=AgentEventType.TOOL_FAILED,
                iteration=step_num,
                tool_name=action.tool,
                error=obs,
            )
            self._emit_event(
                event_type=AgentEventType.OBSERVATION_RECEIVED,
                iteration=step_num,
                content=obs,
            )
            exec_rec = ExecutionRecord(
                iteration=step_num,
                timestamp=datetime.now(timezone.utc).isoformat(),
                action_type="tool_execution",
                tool_name=action.tool,
                arguments_safe=action.parameters,
                error=obs,
                error_type="tool_not_allowed",
                duration=duration,
                success=False,
                observation_summary=obs,
            )
            self.execution_records.append(exec_rec)
            step_record = AgentStep(
                step_number=step_num,
                action=action,
                observation=obs,
                success=False,
                duration=duration,
                timestamp=datetime.now(timezone.utc).isoformat(),
                execution_record=exec_rec,
            )
            self.history.append(step_record)
            self._touch()
            self._emit_event(
                event_type=AgentEventType.AGENT_ITERATION_COMPLETED,
                iteration=step_num,
                content=f"Iteration {step_num} completed (invalid tool)",
                data={
                    "success": False,
                    "step": step_num,
                    "step_record": step_record.model_dump(),
                    "agent_id": self.agent_id,
                },
            )
            return step_record

        # Execute tool strictly against assigned VM via tool_registry and vm_provider
        self._emit_event(
            event_type=AgentEventType.TOOL_STARTED,
            iteration=step_num,
            tool_name=action.tool,
            content=f"Executing tool '{action.tool}' in VM '{self.vm_id}'",
            parameters=action.parameters,
            vm_id=self.vm_id,
            data={"parameters": action.parameters, "vm_id": self.vm_id},
        )
        tool_start = time.time()
        try:
            def _tool_output_callback(stream: str, chunk: str):
                self._emit_event(
                    event_type=AgentEventType.AGENT_TOOL_OUTPUT_CHUNK,
                    iteration=step_num,
                    tool_name=action.tool,
                    stream=stream,
                    output_chunk=chunk,
                    content=chunk,
                    data={"stream": stream, "output_chunk": chunk, "tool_name": action.tool, "vm_id": self.vm_id},
                )

            exec_res = self.tool_registry.execute(
                tool_name=action.tool,
                vm_provider=self.vm_provider,
                vm_id=self.vm_id,
                parameters=action.parameters,
                output_callback=_tool_output_callback,
            )
            duration = round(time.time() - start_time, 3)
            tool_duration = round(time.time() - tool_start, 3)

            obs = exec_res.output if exec_res.success else (exec_res.error or exec_res.output or "Tool execution failed")
            meta = exec_res.metadata or {}

            # Build structured ExecutionRecord
            exec_rec = ExecutionRecord(
                iteration=step_num,
                timestamp=datetime.now(timezone.utc).isoformat(),
                action_type="tool_execution",
                tool_name=action.tool,
                arguments_safe=action.parameters,
                result=obs[:1000] if obs else "",
                stdout=meta.get("stdout"),
                stderr=meta.get("stderr"),
                exit_code=meta.get("exit_code"),
                duration=tool_duration,
                success=exec_res.success,
                error=exec_res.error,
                error_type=meta.get("error_type"),
                observation_summary=obs[:200] if obs else "",
            )
            self.execution_records.append(exec_rec)

            if exec_res.success:
                self._emit_event(
                    event_type=AgentEventType.TOOL_COMPLETED,
                    iteration=step_num,
                    tool_name=action.tool,
                    content=obs[:1000] if obs else "",
                    data={"output": obs, "duration": tool_duration, "success": True},
                )
            else:
                self._emit_event(
                    event_type=AgentEventType.TOOL_FAILED,
                    iteration=step_num,
                    tool_name=action.tool,
                    error=obs,
                    data={"output": obs, "duration": tool_duration, "success": False, "error_type": meta.get("error_type")},
                )
            self._emit_event(
                event_type=AgentEventType.OBSERVATION_RECEIVED,
                iteration=step_num,
                content=obs,
            )
            step_record = AgentStep(
                step_number=step_num,
                action=action,
                observation=obs,
                success=exec_res.success,
                duration=duration,
                timestamp=datetime.now(timezone.utc).isoformat(),
                execution_record=exec_rec,
            )
        except Exception as e:
            duration = round(time.time() - start_time, 3)
            tool_duration = round(time.time() - tool_start, 3)
            err_obs = f"Execution error in VM '{self.vm_id}': {e}"
            exec_rec = ExecutionRecord(
                iteration=step_num,
                timestamp=datetime.now(timezone.utc).isoformat(),
                action_type="tool_execution",
                tool_name=action.tool,
                arguments_safe=action.parameters,
                result="",
                error=err_obs,
                error_type="vm_execution_exception",
                duration=tool_duration,
                success=False,
                observation_summary=err_obs[:200],
            )
            self.execution_records.append(exec_rec)
            self._emit_event(
                event_type=AgentEventType.TOOL_FAILED,
                iteration=step_num,
                tool_name=action.tool,
                error=err_obs,
                data={"output": err_obs, "duration": tool_duration, "success": False},
            )
            self._emit_event(
                event_type=AgentEventType.OBSERVATION_RECEIVED,
                iteration=step_num,
                content=err_obs,
            )
            step_record = AgentStep(
                step_number=step_num,
                action=action,
                observation=err_obs,
                success=False,
                duration=duration,
                timestamp=datetime.now(timezone.utc).isoformat(),
                execution_record=exec_rec,
            )

        self.history.append(step_record)
        self._touch()
        self._emit_event(
            event_type=AgentEventType.AGENT_ITERATION_COMPLETED,
            iteration=step_num,
            content=f"Iteration {step_num} completed",
            data={
                "success": step_record.success,
                "step": step_num,
                "step_record": step_record.model_dump(),
                "agent_id": self.agent_id,
            },
        )
        return step_record

    def synthesize_final_conclusion(self) -> str:
        """
        Agent-level LLM evidence-based conclusion synthesis.
        Constructs complete evidence record, notifies LLM if iteration limit was reached,
        and requests structured evaluation. Falls back deterministically if LLM fails (Edge Case P).
        """
        if not self.history:
            conc_str = f"Agent initialized but executed zero actions on VM '{self.vm_id}'."
            self.structured_conclusion = AgentConclusion(
                status="inconclusive",
                summary=conc_str,
                findings=[],
                evidence=[],
                errors=[],
                unresolved_items=["No actions executed."],
                iteration_limit_reached=self.iteration_limit_reached,
            )
            self.final_conclusion = conc_str
            self._emit_event(
                event_type=AgentEventType.AGENT_FINAL_CONCLUSION,
                content=conc_str,
                conclusion=conc_str,
                data={"conclusion": conc_str, "vm_id": self.vm_id, "structured_conclusion": self.structured_conclusion.model_dump()},
            )
            return conc_str

        # Build comprehensive execution history and evidence context
        evidence_lines = []
        all_errors = []
        for rec in self.execution_records:
            status_text = "SUCCESS" if rec.success else f"FAILED (type: {rec.error_type or 'error'})"
            line = f"- Iteration {rec.iteration} | Tool: '{rec.tool_name}' | Status: {status_text}"
            if rec.exit_code is not None:
                line += f" | ExitCode: {rec.exit_code}"
            if rec.arguments_safe:
                line += f" | Args: {json.dumps(rec.arguments_safe)}"
            if rec.stdout:
                line += f" | Stdout: {rec.stdout[:200].strip()}"
            if rec.stderr:
                line += f" | Stderr: {rec.stderr[:200].strip()}"
            if rec.error:
                all_errors.append(rec.error)
            evidence_lines.append(line)

        evidence_block = "\n".join(evidence_lines)

        limit_header = ""
        if self.iteration_limit_reached:
            limit_header = (
                f"EXECUTION LIMIT REACHED\n"
                f"The configured maximum iteration count ({self.iteration_limit}) has been reached.\n"
                f"Agent: {self.agent_id}\n"
                f"VM: {self.vm_id}\n"
                f"Iterations: {self.current_iteration} / {self.iteration_limit}\n"
                f"The agent must not execute additional tools.\n\n"
            )

        prompt = (
            f"{limit_header}"
            f"You are the CyberArena Agent Evaluator synthesizing the final results for Agent '{self.agent_id}'.\n"
            f"Assigned VM: {self.vm_id}\n"
            f"Objective / Role: {self.role}\n"
            f"Iteration Count: {self.current_iteration} / {self.iteration_limit}\n"
            f"Iteration Limit Reached: {self.iteration_limit_reached}\n\n"
            f"Accumulated Tool Execution History & Evidence:\n"
            f"{evidence_block}\n\n"
            f"Synthesize an evidence-based conclusion. You MUST respond with a single JSON object matching this schema:\n"
            f"{{\n"
            f'  "status": "completed | partially_completed | blocked | failed | inconclusive",\n'
            f'  "summary": "Concise factual summary (2-4 sentences) stating what was achieved, key discoveries, and whether the objective was met.",\n'
            f'  "findings": ["Concrete finding 1", "Concrete finding 2"],\n'
            f'  "evidence": ["Direct observation or output snippet supporting the findings"],\n'
            f'  "errors": ["Specific tool errors or command failures encountered"],\n'
            f'  "unresolved_items": ["Actions or checks that could not be finished (especially if iteration limit was reached)"],\n'
            f'  "iteration_limit_reached": {json.dumps(self.iteration_limit_reached)}\n'
            f"}}\n"
            f"Do NOT include markdown fences or text outside the JSON object."
        )

        self._emit_event(
            event_type=AgentEventType.AGENT_STATUS_UPDATED,
            status="generating_insights",
            content="iteration complete generating insights",
            summary="iteration complete generating insights",
            data={"phase": "generating_insights", "vm_id": self.vm_id},
        )

        try:
            def _run_synthesis() -> str:
                accum_conc = ""
                try:
                    chunks = self.llm_service.generate_stream(
                        model_id=self.model_id,
                        prompt=prompt,
                        system_prompt="You are an expert security assessor synthesizing factual evidence-based conclusions.",
                        json_format=True,
                        temperature=0.2,
                        timeout=max(self.command_timeout, 180),
                        think=self.think,
                    )
                    for c_obj in chunks:
                        if isinstance(c_obj, dict):
                            c_text = c_obj.get("chunk", "")
                            if c_text:
                                accum_conc += c_text
                                self._emit_event(
                                    event_type=AgentEventType.LLM_CHUNK,
                                    content=c_text,
                                    data={
                                        "chunk_type": "conclusion_stream",
                                        "chunk": c_text,
                                        "accumulated": accum_conc,
                                    },
                                )
                except Exception as stream_err:
                    logger.debug(f"Conclusion stream fallback: {stream_err}")

                if not accum_conc:
                    gen_res = self.llm_service.generate(
                        model_id=self.model_id,
                        prompt=prompt,
                        system_prompt="You are an expert security assessor synthesizing factual evidence-based conclusions.",
                        json_format=True,
                        temperature=0.2,
                        timeout=max(self.command_timeout, 180),
                        think=self.think,
                    )
                    accum_conc = gen_res.text

                return accum_conc

            if self.inference_semaphore:
                with self.inference_semaphore:
                    synthesis_text = _run_synthesis()
            else:
                synthesis_text = _run_synthesis()

            clean_text = re.sub(r"<think>.*?</think>", "", synthesis_text, flags=re.DOTALL).strip()
            # Parse JSON
            raw = clean_text or synthesis_text.strip()
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if match:
                raw = match.group(1).strip()
            else:
                fb = raw.find("{")
                lb = raw.rfind("}")
                if fb != -1 and lb != -1 and lb > fb:
                    raw = raw[fb : lb + 1]

            parsed = json.loads(raw)

            # Enforce status rules
            reported_status = str(parsed.get("status", "")).strip().lower()
            if reported_status not in ("completed", "partially_completed", "blocked", "failed", "inconclusive"):
                reported_status = "partially_completed" if self.iteration_limit_reached else "completed"

            # If iteration limit was reached, status cannot be unconditionally reported as completed
            if self.iteration_limit_reached and reported_status == "completed":
                reported_status = "partially_completed"

            structured = AgentConclusion(
                status=reported_status,
                summary=str(parsed.get("summary") or f"Agent finished on VM '{self.vm_id}'."),
                findings=[str(f) for f in parsed.get("findings", []) if f],
                evidence=[str(e) for e in parsed.get("evidence", []) if e],
                errors=[str(err) for err in parsed.get("errors", []) if err],
                unresolved_items=[str(u) for u in parsed.get("unresolved_items", []) if u],
                iteration_limit_reached=self.iteration_limit_reached,
            )

        except Exception as e:
            # Edge Case P: Deterministic Fallback on LLM failure
            logger.warning(f"LLM conclusion generation failed for agent '{self.agent_id}': {e}. Using deterministic fallback.")
            fallback_findings = [f"Step {r.iteration} ({r.tool_name}): {r.result[:120]}" for r in self.execution_records if r.success]
            fallback_evidence = [r.stdout[:150] for r in self.execution_records if r.stdout]
            fallback_unresolved = [f"Remaining objective checks not completed due to iteration limit ({self.iteration_limit})"] if self.iteration_limit_reached else []

            fallback_status = "stopped_iteration_limit" if self.iteration_limit_reached else ("partially_completed" if all_errors else "completed")

            structured = AgentConclusion(
                status=fallback_status,
                summary=f"Deterministic fallback (LLM conclusion generation failed: {e}). Agent executed {len(self.history)} steps on VM '{self.vm_id}'.",
                findings=fallback_findings,
                evidence=fallback_evidence,
                errors=all_errors,
                unresolved_items=fallback_unresolved,
                iteration_limit_reached=self.iteration_limit_reached,
            )

        self.structured_conclusion = structured
        self.final_conclusion = structured.summary

        # Update AgentStatus to match conclusion and iteration-limit semantics
        if self._stop_requested:
            if self.status != AgentStatus.CANCELLED:
                self.status = AgentStatus.STOPPED
        elif self.iteration_limit_reached:
            self.status = AgentStatus.STOPPED_ITERATION_LIMIT
        elif structured.status == "completed":
            self.status = AgentStatus.COMPLETED
        elif structured.status == "partially_completed":
            self.status = AgentStatus.PARTIALLY_COMPLETED
        elif structured.status == "blocked":
            self.status = AgentStatus.BLOCKED
        elif structured.status == "failed":
            self.status = AgentStatus.FAILED
        else:
            self.status = AgentStatus.COMPLETED

        self._emit_event(
            event_type=AgentEventType.AGENT_FINAL_CONCLUSION,
            content=self.final_conclusion,
            conclusion=self.final_conclusion,
            status=self.status.value,
            data={
                "conclusion": self.final_conclusion,
                "vm_id": self.vm_id,
                "structured_conclusion": self.structured_conclusion.model_dump(),
            },
        )
        return self.final_conclusion

    def run_all(self) -> AgentState:
        """Run the autonomous loop until completion, stop, or iteration limit."""
        self.status = AgentStatus.RUNNING
        self._touch()
        self._emit_event(
            event_type=AgentEventType.AGENT_STARTED,
            status="running",
            content=f"Agent '{self.agent_id}' started autonomous execution",
            data={"iteration_limit": self.iteration_limit, "vm_id": self.vm_id},
        )

        while self.current_iteration < self.iteration_limit:
            if self._stop_requested:
                if self.status != AgentStatus.CANCELLED:
                    self.status = AgentStatus.STOPPED
                break

            step = self.step()

            if self.status in (AgentStatus.COMPLETED, AgentStatus.STOPPED, AgentStatus.CANCELLED, AgentStatus.FAILED):
                break

        # Check if iteration limit reached
        if self.status == AgentStatus.RUNNING:
            if self.current_iteration >= self.iteration_limit:
                self.iteration_limit_reached = True
                self.status = AgentStatus.STOPPED_ITERATION_LIMIT
                self.error_message = f"Reached maximum iteration limit ({self.iteration_limit})."
                self._emit_event(
                    event_type=AgentEventType.AGENT_STOPPED,
                    status=AgentStatus.STOPPED_ITERATION_LIMIT.value,
                    content=f"Reached maximum configured iteration limit ({self.iteration_limit}). No further actions executed.",
                    data={"total_iterations": self.current_iteration, "iteration_limit_reached": True},
                )

        # Agent-level final synthesis (runs after loop exits; does NOT execute additional tools)
        try:
            self.synthesize_final_conclusion()
        except Exception as syn_err:
            logger.warning(f"Agent synthesis error: {syn_err}")

        self._touch()
        return self.get_state()
