import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.services.vm_service import VMService, VMNotFoundError
from backend.schemas.vm import VMConfig, SystemRegistryConfig, SSHAuthMethod
from backend.virtualization.virtualbox import VirtualBoxProvider


def test_no_host_execution_endpoints():
    """Verify that no host execution endpoints exist on the FastAPI application."""
    client = TestClient(app)
    # Check that forbidden host execution paths return 404
    assert client.post("/execute-host-command").status_code in (404, 405)
    assert client.post("/api/execute-host-command").status_code in (404, 405)
    assert client.post("/exec-host").status_code in (404, 405)
    assert client.post("/run-powershell").status_code in (404, 405)
    assert client.post("/run-cmd").status_code in (404, 405)


def test_arbitrary_ip_or_unregistered_vm_rejected():
    """Verify that caller cannot pass arbitrary IP or unregistered VM to execute commands."""
    vms = [
        VMConfig(
            vm_id="vm-01",
            vm_provider="virtualbox",
            virtualbox_vm_name="cyberarena-vm-01",
            ssh_host="192.168.56.101",
            ssh_port=22,
            ssh_username="labuser",
            ssh_auth_method=SSHAuthMethod.PASSWORD,
        )
    ]
    registry = SystemRegistryConfig(max_vm=2, vms=vms)
    provider = VirtualBoxProvider(vms=vms)
    service = VMService(provider=provider, registry_config=registry)

    # Attempting to target an arbitrary external IP or unconfigured host
    with pytest.raises(VMNotFoundError):
        service.execute_command("8.8.8.8", "whoami")

    with pytest.raises(VMNotFoundError):
        service.execute_command("127.0.0.1", "whoami")

    with pytest.raises(VMNotFoundError):
        service.execute_command("localhost", "whoami")

    with pytest.raises(VMNotFoundError):
        service.execute_command("victim-server.internal", "whoami")


def test_vboxmanage_never_uses_shell_true():
    """Verify VirtualBoxProvider explicitly specifies shell=False in subprocess execution."""
    import inspect
    from backend.virtualization.virtualbox import VirtualBoxProvider
    source = inspect.getsource(VirtualBoxProvider._run_vboxmanage)
    assert "shell=False" in source
    assert "shell=True" not in source


def test_vm_execution_path_uses_paramiko_not_subprocess():
    """Verify that guest execute path uses VMSSHClient and never calls subprocess."""
    import inspect
    from backend.virtualization.virtualbox import VirtualBoxProvider
    source = inspect.getsource(VirtualBoxProvider.execute)
    assert "VMSSHClient" in source
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "os.popen" not in source
