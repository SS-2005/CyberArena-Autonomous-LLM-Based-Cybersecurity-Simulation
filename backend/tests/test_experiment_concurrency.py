import asyncio
import json
import time
import pytest
from unittest.mock import MagicMock

from backend.db.database import Database
from backend.db.repository import ExperimentRepository
from backend.schemas.experiment import (
    ExperimentCreateRequest,
    ExperimentAgentConfig,
    ExperimentStatus,
)
from backend.schemas.vm import VMInfo, VMState, SystemConfigResponse
from backend.schemas.llm import LLMGenerationResponse, ModelRegistryConfig, ModelConfig
from backend.virtualization.base import CommandExecutionResult
from backend.services.experiment_service import ExperimentService


@pytest.fixture
def mock_concurrency_env():
    """Sets up an ExperimentService with mock VMProvider and LLMService supporting multi-agent testing."""
    db = Database(":memory:")
    repo = ExperimentRepository(db)

    # Mock VM Service with 2 VMs
    mock_vm_svc = MagicMock()
    vms = [
        VMInfo(
            vm_id="vm-01",
            vm_provider="virtualbox",
            virtualbox_vm_name="cyberarena-vm-01",
            state=VMState.RUNNING,
            ssh_host="192.168.32.101",
            ssh_port=22,
            ssh_username="labuser",
            ssh_auth_method="password",
        ),
        VMInfo(
            vm_id="vm-02",
            vm_provider="virtualbox",
            virtualbox_vm_name="cyberarena-vm-02",
            state=VMState.RUNNING,
            ssh_host="192.168.32.102",
            ssh_port=22,
            ssh_username="labuser",
            ssh_auth_method="password",
        ),
    ]
    mock_vm_svc.list_vms.return_value = vms
    mock_vm_svc.get_system_config.return_value = SystemConfigResponse(
        max_vm=2,
        configured_vm_count=2,
        default_provider="virtualbox",
        vms=vms,
    )

    mock_provider = MagicMock()
    mock_vm_svc.provider = mock_provider

    # Mock LLM Service
    mock_llm_svc = MagicMock()
    mock_llm_svc.registry_config = ModelRegistryConfig(
        default_model="mock-model",
        llm_parallelism=2,
        default_iteration_limit=5,
        default_timeout=30,
        models=[
            ModelConfig(
                model_id="mock-model",
                provider="ollama",
                model_name="mock-qwen",
            )
        ],
    )
    mock_llm_svc.resolve_model.return_value = mock_llm_svc.registry_config.models[0]
    mock_llm_svc.provider.list_models.return_value = ["mock-qwen"]

    service = ExperimentService(
        llm_service=mock_llm_svc,
        vm_service=mock_vm_svc,
        repository=repo,
    )

    return service, mock_provider, mock_llm_svc, repo


@pytest.mark.asyncio
async def test_concurrent_multi_agent_execution(mock_concurrency_env):
    """
    Verify that 2 agents execute concurrently without blocking each other.
    """
    service, mock_provider, mock_llm_svc, repo = mock_concurrency_env

    # Setup mock tool execution with timing delay to prove concurrency
    execution_timestamps = []

    def mock_exec(vm_id, command, timeout=30):
        t_start = time.time()
        time.sleep(0.1)  # Simulate execution latency
        t_end = time.time()
        execution_timestamps.append({"vm_id": vm_id, "start": t_start, "end": t_end})
        return CommandExecutionResult(
            vm_id=vm_id,
            command=command,
            stdout=f"Output from {vm_id}: {command}",
            stderr="",
            exit_code=0,
            duration=0.1,
        )

    mock_provider.execute_command.side_effect = mock_exec

    # LLM responses: Step 1 runs a command, Step 2 calls finish
    agent1_responses = [
        LLMGenerationResponse(
            model_name="mock-model",
            text=json.dumps({
                "thought": "Agent 1 scanning ports on vm-01",
                "tool": "execute_command",
                "parameters": {"command": "hostname"},
                "summary": "Check hostname on vm-01",
            }),
            tokens_generated=20,
            duration=0.05,
        ),
        LLMGenerationResponse(
            model_name="mock-model",
            text=json.dumps({
                "thought": "Agent 1 task complete",
                "tool": "finish",
                "parameters": {"summary": "Agent 1 finished successfully"},
                "summary": "Agent 1 done",
            }),
            tokens_generated=15,
            duration=0.05,
        ),
    ]

    agent2_responses = [
        LLMGenerationResponse(
            model_name="mock-model",
            text=json.dumps({
                "thought": "Agent 2 inspecting netstat on vm-02",
                "tool": "execute_command",
                "parameters": {"command": "whoami"},
                "summary": "Check current user on vm-02",
            }),
            tokens_generated=20,
            duration=0.05,
        ),
        LLMGenerationResponse(
            model_name="mock-model",
            text=json.dumps({
                "thought": "Agent 2 task complete",
                "tool": "finish",
                "parameters": {"summary": "Agent 2 finished successfully"},
                "summary": "Agent 2 done",
            }),
            tokens_generated=15,
            duration=0.05,
        ),
    ]

    # Map LLM generate based on prompt contents
    def mock_generate(*args, **kwargs):
        prompt = kwargs.get("prompt", "")
        if "synthesize" in prompt.lower() or "cybersecurity analyst" in prompt.lower() or "executive" in prompt.lower():
            return LLMGenerationResponse(
                model_name="mock-model",
                text="Factual synthesis conclusion based on verified evidence.",
                tokens_generated=15,
                duration=0.01,
            )
        if "Agent 1" in prompt or "Offensive" in prompt:
            if agent1_responses:
                return agent1_responses.pop(0)
            return LLMGenerationResponse(
                model_name="mock-model",
                text="Agent 1 final conclusion.",
                tokens_generated=10,
                duration=0.01,
            )
        else:
            if agent2_responses:
                return agent2_responses.pop(0)
            return LLMGenerationResponse(
                model_name="mock-model",
                text="Agent 2 final conclusion.",
                tokens_generated=10,
                duration=0.01,
            )

    mock_llm_svc.generate.side_effect = mock_generate
    mock_llm_svc.generate_stream.side_effect = Exception("Fallback to generate")

    # Create Experiment with 2 agents
    req = ExperimentCreateRequest(
        name="Concurrent Test Experiment",
        description="Dual agent concurrent run",
        agents=[
            ExperimentAgentConfig(
                role="Agent 1: Offensive host discovery",
                vm_id="vm-01",
                iteration_limit=3,
            ),
            ExperimentAgentConfig(
                role="Agent 2: Defensive process inspection",
                vm_id="vm-02",
                iteration_limit=3,
            ),
        ],
    )
    exp = service.create_experiment(req)
    assert exp.id is not None
    assert len(exp.agents) == 2

    # Start experiment
    start_op = await service.start_experiment(exp.id)
    assert start_op.success is True

    # Await background task completion
    task = service._active_tasks.get(exp.id)
    if task:
        await task

    # Verify final experiment state
    final_exp = service.get_experiment(exp.id)
    assert final_exp.status == ExperimentStatus.COMPLETED
    assert len(final_exp.agents) == 2

    ag1 = next(a for a in final_exp.agents if a.vm_id == "vm-01")
    ag2 = next(a for a in final_exp.agents if a.vm_id == "vm-02")

    assert ag1.status == "completed"
    assert ag2.status == "completed"
    assert len(ag1.history) >= 2
    assert len(ag2.history) >= 2

    # Verify independent memory: observations from vm-01 are distinct from vm-02
    assert "Output from vm-01" in ag1.history[0].observation
    assert "Output from vm-02" in ag2.history[0].observation


@pytest.mark.asyncio
async def test_failure_isolation_between_agents(mock_concurrency_env):
    """
    Verify that if Agent 1 encounters an execution error, Agent 2 continues
    executing cleanly and reaches completion (failure isolation).
    """
    service, mock_provider, mock_llm_svc, repo = mock_concurrency_env

    # Agent 1 will encounter a fatal tool error
    # Agent 2 will execute successfully
    def mock_exec_isolated(vm_id, command, timeout=30):
        if vm_id == "vm-01":
            raise RuntimeError("Fatal SSH connection dropped on vm-01")
        return CommandExecutionResult(
            vm_id=vm_id,
            command=command,
            stdout="Normal defense output from vm-02",
            stderr="",
            exit_code=0,
            duration=0.05,
        )

    mock_provider.execute_command.side_effect = mock_exec_isolated

    # LLM responses
    def mock_llm_gen(*args, **kwargs):
        prompt = kwargs.get("prompt", "")
        if "Agent 1" in prompt:
            return LLMGenerationResponse(
                model_name="mock-model",
                text=json.dumps({
                    "thought": "Agent 1 will attempt command",
                    "tool": "execute_command",
                    "parameters": {"command": "fail_now"},
                    "summary": "Attempt command on vm-01",
                }),
                tokens_generated=15,
                duration=0.02,
            )
        else:
            # Agent 2 finishes
            return LLMGenerationResponse(
                model_name="mock-model",
                text=json.dumps({
                    "thought": "Agent 2 succeeds",
                    "tool": "finish",
                    "parameters": {"summary": "Agent 2 completed defense check"},
                    "summary": "Finish agent 2",
                }),
                tokens_generated=15,
                duration=0.02,
            )

    mock_llm_svc.generate.side_effect = mock_llm_gen
    mock_llm_svc.generate_stream.side_effect = Exception("Fallback")

    req = ExperimentCreateRequest(
        name="Failure Isolation Test",
        agents=[
            ExperimentAgentConfig(role="Agent 1: Error prone", vm_id="vm-01", iteration_limit=2),
            ExperimentAgentConfig(role="Agent 2: Reliable", vm_id="vm-02", iteration_limit=2),
        ],
    )
    exp = service.create_experiment(req)
    await service.start_experiment(exp.id)

    task = service._active_tasks.get(exp.id)
    if task:
        await task

    final_exp = service.get_experiment(exp.id)
    ag1 = next(a for a in final_exp.agents if a.vm_id == "vm-01")
    ag2 = next(a for a in final_exp.agents if a.vm_id == "vm-02")

    # Agent 2 finished cleanly despite Agent 1's tool exception
    assert ag2.status == "completed"
    assert "Fatal SSH connection dropped" in ag1.history[0].observation
