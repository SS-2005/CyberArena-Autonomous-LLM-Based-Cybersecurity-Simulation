import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.api.deps import set_vm_service, set_llm_service, set_agent_service
from backend.services.vm_service import VMService
from backend.services.llm_service import LLMService
from backend.services.agent_service import AgentService
from backend.schemas.vm import VMInfo, VMState
from backend.schemas.llm import (
    LLMHealthResponse,
    LLMGenerationResponse,
    ModelStatus,
    LLMTestResponse,
    ModelRegistryConfig,
    ModelConfig,
)
from backend.virtualization.base import VMProvider, CommandExecutionResult


@pytest.fixture(autouse=True)
def setup_mock_services():
    mock_provider = MagicMock(spec=VMProvider)
    mock_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="whoami",
        exit_code=0,
        stdout="labuser\n",
        stderr="",
        duration=0.02,
    )

    mock_vm_service = MagicMock(spec=VMService)
    mock_vm_service.provider = mock_provider
    mock_vm_service.list_vms.return_value = [
        VMInfo(
            vm_id="vm-01",
            vm_provider="virtualbox",
            virtualbox_vm_name="cyberarena-vm-01",
            state=VMState.RUNNING,
            ssh_host="192.168.32.101",
            ssh_port=22,
            ssh_username="labuser",
            ssh_auth_method="password",
        )
    ]

    mock_llm_service = MagicMock()
    mock_llm_service.registry_config = ModelRegistryConfig(
        default_model="local-qwen3-4b",
        llm_parallelism=1,
        default_iteration_limit=10,
        default_timeout=60,
        models=[
            ModelConfig(model_id="local-qwen3-4b", provider="ollama", model_name="qwen3:4b", enabled=True)
        ],
    )

    mock_llm_service.get_health.return_value = LLMHealthResponse(
        status="healthy",
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        installed_models=["qwen3:4b"],
        message="Ollama operational",
        timestamp="2026-09-30T12:00:00Z",
    )
    mock_llm_service.list_models.return_value = [
        ModelStatus(
            model_id="local-qwen3-4b",
            provider="ollama",
            model_name="qwen3:4b",
            configured=True,
            installed=True,
            available=True,
        )
    ]
    mock_model_cfg = MagicMock()
    mock_model_cfg.model_id = "local-qwen3-4b"
    mock_model_cfg.model_name = "qwen3:4b"
    mock_llm_service.resolve_model.return_value = mock_model_cfg

    mock_llm_service.test_model.return_value = LLMTestResponse(
        model_id="local-qwen3-4b",
        model_name="qwen3:4b",
        response="pong",
        duration=0.5,
        timestamp="2026-09-30T12:00:00Z",
    )
    mock_llm_service.generate.return_value = LLMGenerationResponse(
        text='{"thought": "Inspect", "tool": "finish", "parameters": {"summary": "Done"}, "summary": "Finished"}',
        duration=0.1,
        model_name="qwen3:4b",
    )

    agent_service = AgentService(
        llm_service=mock_llm_service,
        vm_service=mock_vm_service,
    )

    set_vm_service(mock_vm_service)
    set_llm_service(mock_llm_service)
    set_agent_service(agent_service)

    yield

    set_vm_service(None)
    set_llm_service(None)
    set_agent_service(None)


@pytest.fixture
def client():
    return TestClient(app)


def test_api_llm_health(client):
    res = client.get("/llm/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"

    # Also test /api prefix
    res_api = client.get("/api/llm/health")
    assert res_api.status_code == 200


def test_api_llm_models(client):
    res = client.get("/llm/models")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["model_id"] == "local-qwen3-4b"
    assert data[0]["available"] is True


def test_api_llm_test(client):
    res = client.post("/llm/test", json={"model_id": "local-qwen3-4b", "prompt": "ping"})
    assert res.status_code == 200
    assert res.json()["response"] == "pong"


def test_api_agent_tools(client):
    res = client.get("/agents/tools")
    assert res.status_code == 200
    tools = res.json()
    tool_names = [t["name"] for t in tools]
    assert "execute_command" in tool_names
    assert "network_info" in tool_names
    assert "read_file" in tool_names


def test_api_create_agent(client):
    payload = {
        "agent_id": "agent-test-01",
        "role": "Perform network reconnaissance",
        "vm_id": "vm-01",
        "model_id": "local-qwen3-4b",
        "iteration_limit": 5,
    }
    res = client.post("/agents", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["agent_id"] == "agent-test-01"
    assert data["status"] == "idle"
    assert data["vm_id"] == "vm-01"


def test_api_create_agent_invalid_vm(client):
    payload = {
        "role": "Test invalid",
        "vm_id": "non-existent-vm",
    }
    res = client.post("/agents", json=payload)
    assert res.status_code == 400
    assert "not in configured VM registry" in res.json()["detail"]


def test_api_agent_lifecycle(client):
    # Create
    create_res = client.post("/agents", json={
        "agent_id": "agent-life",
        "role": "Check status",
        "vm_id": "vm-01",
    })
    assert create_res.status_code == 201

    # Get state
    get_res = client.get("/agents/agent-life")
    assert get_res.status_code == 200
    assert get_res.json()["agent_id"] == "agent-life"

    # Start
    start_res = client.post("/agents/agent-life/start")
    assert start_res.status_code == 200
    assert start_res.json()["operation"] == "start"

    # Stop
    stop_res = client.post("/agents/agent-life/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["operation"] == "stop"

    # Status
    status_res = client.get("/agents/agent-life/status")
    assert status_res.status_code == 200

    # History
    history_res = client.get("/agents/agent-life/history")
    assert history_res.status_code == 200
    assert isinstance(history_res.json(), list)
