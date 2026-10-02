from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.schemas.vm import (
    VMConfig,
    VMInfo,
    VMState,
    SSHAuthMethod,
    VMOperationResult,
    CommandExecutionResult,
    HealthCheckResult,
    SystemRegistryConfig,
)
from backend.services.vm_service import VMService
from backend.api.deps import set_vm_service


@pytest.fixture
def mock_service():
    vms = [
        VMConfig(
            vm_id="vm-01",
            vm_provider="virtualbox",
            virtualbox_vm_name="cyberarena-vm-01",
            ssh_host="192.168.56.101",
            ssh_port=22,
            ssh_username="labuser",
            ssh_auth_method=SSHAuthMethod.PASSWORD,
        ),
        VMConfig(
            vm_id="vm-02",
            vm_provider="virtualbox",
            virtualbox_vm_name="cyberarena-vm-02",
            ssh_host="192.168.56.102",
            ssh_port=22,
            ssh_username="labuser",
            ssh_auth_method=SSHAuthMethod.PASSWORD,
        ),
    ]
    registry = SystemRegistryConfig(max_vm=2, vms=vms)
    mock_provider = MagicMock()
    service = VMService(provider=mock_provider, registry_config=registry)

    # Provide default mock returns
    mock_provider.list_vms.return_value = [
        VMInfo(
            vm_id="vm-01",
            vm_provider="virtualbox",
            virtualbox_vm_name="cyberarena-vm-01",
            state=VMState.RUNNING,
            ssh_host="192.168.56.101",
            ssh_port=22,
            ssh_username="labuser",
            ssh_auth_method="password",
        ),
        VMInfo(
            vm_id="vm-02",
            vm_provider="virtualbox",
            virtualbox_vm_name="cyberarena-vm-02",
            state=VMState.STOPPED,
            ssh_host="192.168.56.102",
            ssh_port=22,
            ssh_username="labuser",
            ssh_auth_method="password",
        ),
    ]

    mock_provider.get_vm.side_effect = lambda vid: next((v for v in mock_provider.list_vms.return_value if v.vm_id == vid), None)

    mock_provider.start_vm.return_value = VMOperationResult(
        vm_id="vm-01", operation="start", success=True, message="Started", timestamp="2026-09-29T12:00:00Z"
    )
    mock_provider.stop_vm.return_value = VMOperationResult(
        vm_id="vm-01", operation="stop", success=True, message="Stopped", timestamp="2026-09-29T12:00:00Z"
    )
    mock_provider.snapshot.return_value = VMOperationResult(
        vm_id="vm-01", operation="snapshot", success=True, message="Snapshot created", timestamp="2026-09-29T12:00:00Z"
    )
    mock_provider.restore_snapshot.return_value = VMOperationResult(
        vm_id="vm-01", operation="restore_snapshot", success=True, message="Snapshot restored", timestamp="2026-09-29T12:00:00Z"
    )
    mock_provider.execute.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="id",
        stdout="uid=1000(labuser) gid=1000(labuser)\n",
        stderr="",
        exit_code=0,
        duration=0.05,
        timestamp="2026-09-29T12:00:00Z",
    )
    mock_provider.health_check.return_value = HealthCheckResult(
        vm_id="vm-01",
        state=VMState.RUNNING,
        is_running=True,
        ssh_reachable=True,
        latency_ms=1.5,
        message="Healthy",
        timestamp="2026-09-29T12:00:00Z",
    )

    set_vm_service(service)
    return service


@pytest.fixture
def client(mock_service):
    return TestClient(app)


def test_get_config(client):
    """Verify GET /config returns dynamic max_vm and configured VM count."""
    res = client.get("/config")
    assert res.status_code == 200
    data = res.json()
    assert "max_vm" in data
    assert data["max_vm"] == 2
    assert data["configured_vm_count"] == 2
    assert len(data["vms"]) == 2


def test_list_vms(client):
    """Verify GET /vms returns list of configured VMs."""
    res = client.get("/vms")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    assert data[0]["vm_id"] == "vm-01"


def test_get_vm_success_and_not_found(client):
    """Verify GET /vms/{vm_id}."""
    res = client.get("/vms/vm-01")
    assert res.status_code == 200
    assert res.json()["vm_id"] == "vm-01"

    # Invalid ID must return 404
    res_404 = client.get("/vms/invalid-id")
    assert res_404.status_code == 404


def test_start_and_stop_vm(client):
    """Verify POST /vms/{vm_id}/start and /stop."""
    res_start = client.post("/vms/vm-01/start")
    assert res_start.status_code == 200
    assert res_start.json()["success"] is True

    res_stop = client.post("/vms/vm-01/stop?force=true")
    assert res_stop.status_code == 200
    assert res_stop.json()["success"] is True


def test_snapshot_and_restore(client):
    """Verify POST /vms/{vm_id}/snapshot and /restore."""
    res_snap = client.post("/vms/vm-01/snapshot", json={"snapshot_name": "baseline_snap", "description": "init"})
    assert res_snap.status_code == 200
    assert res_snap.json()["success"] is True

    res_restore = client.post("/vms/vm-01/restore", json={"snapshot_name": "baseline_snap"})
    assert res_restore.status_code == 200
    assert res_restore.json()["success"] is True


def test_snapshot_name_validation(client):
    """Verify invalid snapshot names with malicious characters are rejected by Pydantic."""
    res = client.post("/vms/vm-01/snapshot", json={"snapshot_name": "snap; rm -rf /"})
    assert res.status_code == 422  # Validation error


def test_execute_command(client):
    """Verify POST /vms/{vm_id}/execute returns structured data."""
    res = client.post("/vms/vm-01/execute", json={"command": "id", "timeout": 15})
    assert res.status_code == 200
    data = res.json()
    assert data["vm_id"] == "vm-01"
    assert data["command"] == "id"
    assert data["exit_code"] == 0
    assert "labuser" in data["stdout"]
    assert "duration" in data
    assert "timestamp" in data


def test_health_check_endpoint(client):
    """Verify GET /vms/{vm_id}/health."""
    res = client.get("/vms/vm-01/health")
    assert res.status_code == 200
    data = res.json()
    assert data["vm_id"] == "vm-01"
    assert data["is_running"] is True
    assert data["ssh_reachable"] is True


def test_command_url_structure_regression(client, mock_service):
    """
    REGRESSION TEST:
    Verify that the command ('hostname', 'whoami', etc.) must NEVER become the vm_id path parameter.
    1. POST /vms/hostname/execute must return 404 because 'hostname' is not a configured vm_id.
    2. POST /vms/{vm_id}/execute with body {"command": "hostname"} must succeed and target the configured VM.
    """
    # 1. Erroneous request where command becomes path parameter must be rejected with 404
    res_err = client.post("/vms/hostname/execute", json={"command": "uptime"})
    assert res_err.status_code == 404
    assert "not configured in the registry" in res_err.json()["detail"]

    # 2. Correct request where selected vm_id is in path and 'hostname' is in request body
    mock_service.provider.execute.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="hostname",
        stdout="cyberarena-vm-01\n",
        stderr="",
        exit_code=0,
        duration=0.04,
        timestamp="2026-09-29T12:00:00Z",
    )
    res_ok = client.post("/vms/vm-01/execute", json={"command": "hostname"})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["vm_id"] == "vm-01"
    assert data["command"] == "hostname"
    assert data["stdout"].strip() == "cyberarena-vm-01"

