import pytest
from unittest.mock import MagicMock, patch
from backend.services.llm_service import LLMService
from backend.services.experiment_service import ExperimentService
from backend.schemas.experiment import ExperimentCreateRequest, ExperimentAgentConfig, ExperimentStatus
from backend.schemas.llm import ModelConfig, ModelRegistryConfig, LLMGenerationResponse
from backend.agents.agent import Agent
from backend.schemas.agent import AgentStatus, AgentEventType


@pytest.fixture
def mock_multi_registry():
    return ModelRegistryConfig(
        default_model="local-qwen25-1.5b",
        llm_parallelism=4,
        default_iteration_limit=5,
        default_timeout=60,
        models=[
            ModelConfig(
                model_id="local-qwen25-1.5b",
                provider="ollama",
                model_name="qwen2.5:1.5b",
                display_name="Qwen 2.5 1.5B (Ultra-Fast)",
                size="986 MB",
                thinking_supported=False,
                think=False,
                enabled=True,
            ),
            ModelConfig(
                model_id="local-llama32-1b",
                provider="ollama",
                model_name="llama3.2:1b",
                display_name="Llama 3.2 1B (Fast)",
                size="1.3 GB",
                thinking_supported=False,
                think=False,
                enabled=True,
            ),
            ModelConfig(
                model_id="local-llama32-3b",
                provider="ollama",
                model_name="llama3.2:3b",
                display_name="Llama 3.2 3B",
                size="2.0 GB",
                thinking_supported=False,
                think=False,
                enabled=True,
            ),
            ModelConfig(
                model_id="local-qwen3-4b",
                provider="ollama",
                model_name="qwen3:4b",
                display_name="Qwen 3 4B (Reasoning)",
                size="2.5 GB",
                thinking_supported=True,
                think=False,
                enabled=True,
            ),
            ModelConfig(
                model_id="local-uninstalled-model",
                provider="ollama",
                model_name="mistral:7b",
                display_name="Mistral 7B (Missing)",
                size="4.1 GB",
                thinking_supported=False,
                think=False,
                enabled=True,
            ),
        ],
    )


def test_list_models_enriches_capabilities_and_installed_status(mock_multi_registry):
    mock_provider = MagicMock()
    mock_provider.list_models.return_value = ["qwen2.5:1.5b", "llama3.2:1b", "qwen3:4b"]
    mock_provider.list_models_detailed.return_value = {
        "qwen2.5:1.5b": {"size_formatted": "986 MB", "thinking_supported": False},
        "llama3.2:1b": {"size_formatted": "1.3 GB", "thinking_supported": False},
        "qwen3:4b": {"size_formatted": "2.5 GB", "thinking_supported": True},
    }

    service = LLMService(provider=mock_provider, registry_config=mock_multi_registry)
    models = service.list_models()

    assert len(models) == 5
    m_qwen25 = next(m for m in models if m.model_id == "local-qwen25-1.5b")
    assert m_qwen25.installed is True
    assert m_qwen25.available is True
    assert m_qwen25.thinking_supported is False

    m_qwen3 = next(m for m in models if m.model_id == "local-qwen3-4b")
    assert m_qwen3.installed is True
    assert m_qwen3.thinking_supported is True

    m_missing = next(m for m in models if m.model_id == "local-uninstalled-model")
    assert m_missing.installed is False
    assert m_missing.available is False


def test_per_agent_model_resolution(mock_multi_registry):
    mock_provider = MagicMock()
    service = LLMService(provider=mock_provider, registry_config=mock_multi_registry)

    cfg1 = service.resolve_model("local-qwen25-1.5b")
    assert cfg1.model_name == "qwen2.5:1.5b"

    cfg2 = service.resolve_model("local-llama32-1b")
    assert cfg2.model_name == "llama3.2:1b"

    # Default fallback
    cfg_def = service.resolve_model(None)
    assert cfg_def.model_id == "local-qwen25-1.5b"

    # Invalid model rejection
    with pytest.raises(ValueError, match="not configured"):
        service.resolve_model("nonexistent-model-xyz")


@pytest.mark.asyncio
async def test_start_experiment_rejects_uninstalled_model_cleanly(mock_multi_registry):
    mock_provider = MagicMock()
    # Only qwen2.5 is installed; llama3.2 is not
    mock_provider.list_models.return_value = ["qwen2.5:1.5b"]

    llm_service = LLMService(provider=mock_provider, registry_config=mock_multi_registry)
    vm_service = MagicMock()
    mock_sys_config = MagicMock()
    mock_sys_config.max_vm = 2
    mock_vm1 = MagicMock()
    mock_vm1.vm_id = "vm-01"
    mock_vm2 = MagicMock()
    mock_vm2.vm_id = "vm-02"
    mock_sys_config.vms = [mock_vm1, mock_vm2]
    vm_service.get_system_config.return_value = mock_sys_config

    repository = MagicMock()
    exp_detail = MagicMock()
    exp_detail.status = ExperimentStatus.CREATED
    agent1_state = MagicMock()
    agent1_state.agent_id = "agent-1"
    agent1_state.vm_id = "vm-01"
    agent1_state.model_id = "local-qwen25-1.5b"

    agent2_state = MagicMock()
    agent2_state.agent_id = "agent-2"
    agent2_state.vm_id = "vm-02"
    agent2_state.model_id = "local-uninstalled-model"

    exp_detail.agents = [agent1_state, agent2_state]
    repository.get_experiment.return_value = exp_detail

    exp_service = ExperimentService(llm_service=llm_service, vm_service=vm_service, repository=repository)

    with pytest.raises(ValueError, match="not installed in local Ollama"):
        await exp_service.start_experiment("exp-test-fail")


def test_agent_iteration_completed_event_contains_step_record():
    mock_llm_service = MagicMock()
    mock_llm_service.resolve_model.return_value = ModelConfig(
        model_id="local-qwen25-1.5b",
        provider="ollama",
        model_name="qwen2.5:1.5b",
        think=False,
    )
    mock_llm_service.generate_stream.return_value = [
        {"chunk": '{"thought": "Check user", "tool": "finish", "parameters": {"summary": "Done"}, "summary": "Done"}', "type": "response", "done": True}
    ]
    mock_vm_provider = MagicMock()

    emitted_events = []
    def _event_cb(ev):
        emitted_events.append(ev)

    agent = Agent(
        agent_id="agent-ev-test",
        role="Test event emission",
        vm_id="vm-01",
        model_id="local-qwen25-1.5b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=1,
        event_callback=_event_cb,
    )

    agent.step()

    iter_completed = next((e for e in emitted_events if e.event_type == AgentEventType.AGENT_ITERATION_COMPLETED), None)
    assert iter_completed is not None
    assert "step_record" in iter_completed.data
    assert iter_completed.data["step_record"]["step_number"] == 1
    assert iter_completed.data["agent_id"] == "agent-ev-test"
