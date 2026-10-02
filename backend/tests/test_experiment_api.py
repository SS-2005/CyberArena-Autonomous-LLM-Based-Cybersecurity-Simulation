import pytest
import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.api.deps import set_experiment_service, set_vm_service, set_llm_service
from backend.services.experiment_service import ExperimentService
from backend.db.database import Database
from backend.db.repository import ExperimentRepository
from backend.schemas.vm import VMInfo, VMState, SystemConfigResponse
from backend.schemas.llm import LLMGenerationResponse, ModelRegistryConfig, ModelConfig
from backend.virtualization.base import CommandExecutionResult


@pytest.fixture
def mock_deps():
    """Setup isolated in-memory DB and mocked VM/LLM services for API tests."""
    db = Database(":memory:")
    repo = ExperimentRepository(db)

    # Mock VM Service
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
    mock_vm_svc.provider = MagicMock()

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

    # Experiment Service with in-memory DB
    exp_svc = ExperimentService(
        llm_service=mock_llm_svc,
        vm_service=mock_vm_svc,
        repository=repo,
    )

    set_vm_service(mock_vm_svc)
    set_llm_service(mock_llm_svc)
    set_experiment_service(exp_svc)

    client = TestClient(app)
    return client, exp_svc, mock_vm_svc, mock_llm_svc


def test_create_experiment_success(mock_deps):
    client, _, _, _ = mock_deps
    payload = {
        "name": "Integration Test Experiment",
        "description": "Multi-agent dual VM test",
        "agents": [
            {
                "role": "Reconnaissance",
                "vm_id": "vm-01",
                "iteration_limit": 3,
            },
            {
                "role": "Defense Monitor",
                "vm_id": "vm-02",
                "iteration_limit": 3,
            },
        ],
    }
    resp = client.post("/experiments", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Integration Test Experiment"
    assert data["status"] == "created"
    assert len(data["agents"]) == 2
    assert data["agents"][0]["vm_id"] == "vm-01"
    assert data["agents"][1]["vm_id"] == "vm-02"


def test_create_experiment_duplicate_vm_rejected(mock_deps):
    client, _, _, _ = mock_deps
    payload = {
        "name": "Invalid Duplicate VM Experiment",
        "agents": [
            {"role": "Agent 1", "vm_id": "vm-01"},
            {"role": "Agent 2", "vm_id": "vm-01"},  # duplicate!
        ],
    }
    resp = client.post("/experiments", json=payload)
    assert resp.status_code == 400
    assert "unique VM" in resp.json()["detail"]


def test_create_experiment_exceeds_max_vm(mock_deps):
    client, _, _, _ = mock_deps
    payload = {
        "name": "Exceeds Max VM",
        "agents": [
            {"role": "Agent 1", "vm_id": "vm-01"},
            {"role": "Agent 2", "vm_id": "vm-02"},
            {"role": "Agent 3", "vm_id": "vm-03"},  # exceeds max_vm=2!
        ],
    }
    resp = client.post("/experiments", json=payload)
    assert resp.status_code == 400
    assert "maximum of 2" in resp.json()["detail"]


def test_list_and_get_experiments(mock_deps):
    client, _, _, _ = mock_deps
    create_payload = {
        "name": "Fetch Test",
        "agents": [{"role": "Single Agent", "vm_id": "vm-01"}],
    }
    created = client.post("/experiments", json=create_payload).json()
    exp_id = created["id"]

    # List experiments
    list_resp = client.get("/experiments")
    assert list_resp.status_code == 200
    exp_list = list_resp.json()
    assert any(e["id"] == exp_id for e in exp_list)

    # Get experiment detail
    detail_resp = client.get(f"/experiments/{exp_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == exp_id
    assert detail_resp.json()["agents"][0]["vm_id"] == "vm-01"


def test_start_and_stop_experiment_lifecycle(mock_deps):
    client, exp_svc, _, _ = mock_deps
    create_payload = {
        "name": "Lifecycle Test",
        "agents": [{"role": "Agent 1", "vm_id": "vm-01"}],
    }
    created = client.post("/experiments", json=create_payload).json()
    exp_id = created["id"]

    # Start experiment
    start_resp = client.post(f"/experiments/{exp_id}/start")
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "running"

    # Stop experiment
    stop_resp = client.post(f"/experiments/{exp_id}/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["status"] == "stopped"


def test_delete_experiment(mock_deps):
    client, _, _, _ = mock_deps
    created = client.post("/experiments", json={"name": "Delete Me", "agents": [{"role": "Audit", "vm_id": "vm-01"}]}).json()
    exp_id = created["id"]

    del_resp = client.delete(f"/experiments/{exp_id}")
    assert del_resp.status_code == 200

    # Verify 404 after deletion
    get_resp = client.get(f"/experiments/{exp_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_experiment_sse_telemetry(mock_deps):
    from backend.api.experiment_routes import stream_experiment_events
    client, exp_svc, _, _ = mock_deps
    created = client.post("/experiments", json={"name": "SSE Test", "agents": [{"role": "Audit", "vm_id": "vm-01"}]}).json()
    exp_id = created["id"]

    resp = await stream_experiment_events(exp_id, exp_svc)
    assert resp.media_type == "text/event-stream"
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
        if len(chunks) >= 2:
            break

    assert any(": connected" in c for c in chunks)


def test_experiment_websocket_telemetry(mock_deps):
    client, _, _, _ = mock_deps
    created = client.post("/experiments", json={"name": "WS Test", "agents": [{"role": "Audit", "vm_id": "vm-01"}]}).json()
    exp_id = created["id"]

    with client.websocket_connect(f"/ws/experiments/{exp_id}") as websocket:
        websocket.send_text("ping")
        data = websocket.receive_text()
        parsed = json.loads(data)
        assert parsed.get("type") == "pong" or "experiment_id" in parsed
