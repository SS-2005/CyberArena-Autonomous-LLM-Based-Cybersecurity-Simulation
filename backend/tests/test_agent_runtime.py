import pytest
from unittest.mock import MagicMock

from backend.agents.agent import Agent
from backend.schemas.agent import AgentStatus
from backend.schemas.llm import LLMGenerationResponse
from backend.services.llm_service import LLMService
from backend.virtualization.base import VMProvider, CommandExecutionResult
from backend.tools.registry import ToolRegistry


@pytest.fixture
def mock_llm_service():
    service = MagicMock(spec=LLMService)
    return service


@pytest.fixture
def mock_vm_provider():
    provider = MagicMock(spec=VMProvider)
    provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="id",
        exit_code=0,
        stdout="uid=1000(labuser) gid=1000(labuser)\n",
        stderr="",
        duration=0.01,
    )
    return provider


def test_agent_initialization(mock_llm_service, mock_vm_provider):
    agent = Agent(
        agent_id="test-agent-01",
        role="Audit network configuration and services",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=5,
    )
    assert agent.status == AgentStatus.IDLE
    assert agent.role == "Audit network configuration and services"
    assert agent.current_iteration == 0
    assert len(agent.allowed_tools) > 0


def test_agent_single_step_execution(mock_llm_service, mock_vm_provider):
    # LLM returns structured action
    mock_llm_service.generate.return_value = LLMGenerationResponse(
        text='{"thought": "Check user identity", "tool": "execute_command", "parameters": {"command": "id"}, "summary": "Check user id"}',
        duration=0.5,
        model_name="qwen3:4b",
    )

    agent = Agent(
        agent_id="agent-01",
        role="Identify current user privileges",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
    )

    step = agent.step()
    assert step.step_number == 1
    assert step.action.tool == "execute_command"
    assert step.success is True
    assert "uid=1000" in step.observation
    assert len(agent.history) == 1
    assert agent.current_iteration == 1


def test_agent_malformed_llm_output_recovery(mock_llm_service, mock_vm_provider):
    # First step LLM produces garbage
    mock_llm_service.generate.side_effect = [
        LLMGenerationResponse(
            text="Sorry, I cannot answer in JSON right now.",
            duration=0.2,
            model_name="qwen3:4b",
        ),
        # Second step LLM corrects itself
        LLMGenerationResponse(
            text='{"thought": "Corrected format", "tool": "finish", "parameters": {"summary": "Done"}, "summary": "Finish"}',
            duration=0.2,
            model_name="qwen3:4b",
        ),
    ]

    agent = Agent(
        agent_id="agent-err",
        role="Test self-correction",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=5,
    )

    step1 = agent.step()
    assert step1.success is False
    assert "validation error" in step1.observation.lower()
    assert agent.status == AgentStatus.IDLE

    step2 = agent.step()
    assert step2.success is True
    assert step2.action.tool == "finish"
    assert agent.status == AgentStatus.COMPLETED


def test_agent_autonomous_run_completion(mock_llm_service, mock_vm_provider):
    # Agent runs tool then finishes
    mock_llm_service.generate.side_effect = [
        LLMGenerationResponse(
            text='{"thought": "Step 1 check", "tool": "execute_command", "parameters": {"command": "hostname"}, "summary": "Check hostname"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
        LLMGenerationResponse(
            text='{"thought": "All done", "tool": "finish", "parameters": {"summary": "System inspected."}, "summary": "Completed inspection"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
    ]

    agent = Agent(
        agent_id="agent-run",
        role="Inspect system",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=5,
    )

    state = agent.run_all()
    assert state.status == AgentStatus.COMPLETED
    assert state.current_iteration == 2
    assert len(state.history) == 2


def test_agent_iteration_limit(mock_llm_service, mock_vm_provider):
    # LLM keeps looping without calling finish
    mock_llm_service.generate.return_value = LLMGenerationResponse(
        text='{"thought": "Still working", "tool": "execute_command", "parameters": {"command": "uptime"}, "summary": "Check uptime"}',
        duration=0.1,
        model_name="qwen3:4b",
    )

    agent = Agent(
        agent_id="agent-loop",
        role="Continuous monitoring",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=3,
    )

    state = agent.run_all()
    assert state.current_iteration == 3
    assert state.status in (AgentStatus.STOPPED_ITERATION_LIMIT, AgentStatus.PARTIALLY_COMPLETED)
    assert state.status != AgentStatus.COMPLETED
    assert "iteration limit" in state.error_message


def test_agent_stop_signal(mock_llm_service, mock_vm_provider):
    agent = Agent(
        agent_id="agent-stop",
        role="Long task",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
    )
    agent.request_stop()
    step = agent.step()
    assert agent.status == AgentStatus.STOPPED
    assert step.action.tool == "stop"


def test_agent_invalid_tool_rejected(mock_llm_service, mock_vm_provider):
    """Verify tool not in allowed_tools is rejected safely and fed back as observation."""
    mock_llm_service.generate.return_value = LLMGenerationResponse(
        text='{"thought": "Try arbitrary tool", "tool": "forbidden_tool", "parameters": {}, "summary": "Try forbidden"}',
        duration=0.1,
        model_name="qwen3:4b",
    )
    agent = Agent(
        agent_id="agent-invalid-tool",
        role="Test security",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        allowed_tools=["execute_command"],
    )
    step = agent.step()
    assert step.success is False
    assert "not in allowed tools list" in step.observation


def test_agent_assigned_vmid_immutable_by_llm(mock_llm_service, mock_vm_provider):
    """Verify LLM cannot redirect execution by specifying a different vm_id in parameters."""
    mock_llm_service.generate.return_value = LLMGenerationResponse(
        text='{"thought": "Try targeting host or vm-02", "tool": "execute_command", "parameters": {"command": "id", "vm_id": "vm-02"}, "summary": "Bypass"}',
        duration=0.1,
        model_name="qwen3:4b",
    )
    agent = Agent(
        agent_id="agent-vm-immutable",
        role="Test VM immutability",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
    )
    agent.step()
    call_args = mock_vm_provider.execute_command.call_args
    assert call_args[0][0] == "vm-01"
    assert call_args[0][1] == "id"


def test_agent_tool_execution_failure_handling(mock_llm_service, mock_vm_provider):
    """Verify non-zero exit code or error is captured in observation without crashing."""
    mock_llm_service.generate.return_value = LLMGenerationResponse(
        text='{"thought": "Run failing command", "tool": "execute_command", "parameters": {"command": "cat /nonexistent"}, "summary": "Fail"}',
        duration=0.1,
        model_name="qwen3:4b",
    )
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="cat /nonexistent",
        exit_code=1,
        stdout="",
        stderr="No such file or directory",
        duration=0.01,
    )
    agent = Agent(
        agent_id="agent-fail",
        role="Test error handling",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
    )
    step = agent.step()
    assert step.success is False
    assert "No such file or directory" in step.observation


def test_agent_llm_failure_handling(mock_llm_service, mock_vm_provider):
    """Verify LLM provider network or timeout failure does not crash the agent."""
    mock_llm_service.generate.side_effect = TimeoutError("Ollama inference timed out after 120s")
    agent = Agent(
        agent_id="agent-timeout",
        role="Test timeout handling",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
    )
    step = agent.step()
    assert step.success is False
    assert "timed out" in step.observation

