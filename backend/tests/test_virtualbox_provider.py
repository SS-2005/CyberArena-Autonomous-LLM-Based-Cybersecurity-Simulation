from unittest.mock import MagicMock
import pytest
from backend.schemas.vm import VMConfig, VMState, SSHAuthMethod
from backend.virtualization.virtualbox import VirtualBoxProvider


@pytest.fixture
def mock_provider():
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
    provider = VirtualBoxProvider(vms=vms, vboxmanage_path="mock_vboxmanage.exe")
    return provider


def test_get_state_running(mock_provider, monkeypatch):
    """Verify parsing of running VMState from VBoxManage showvminfo."""
    mock_provider._run_vboxmanage = MagicMock(return_value=(
        0,
        'name="cyberarena-vm-01"\nVMState="running"\nVMStateChangeTime="2026-09-29T10:00:00.000000000"',
        ""
    ))
    state = mock_provider.get_state("vm-01")
    assert state == VMState.RUNNING


def test_get_state_stopped(mock_provider):
    """Verify parsing of poweroff VMState."""
    mock_provider._run_vboxmanage = MagicMock(return_value=(
        0,
        'name="cyberarena-vm-01"\nVMState="poweroff"\n',
        ""
    ))
    state = mock_provider.get_state("vm-01")
    assert state == VMState.STOPPED


def test_start_vm_success(mock_provider):
    """Verify starting a stopped VM invokes headless start."""
    mock_provider.get_state = MagicMock(return_value=VMState.STOPPED)
    mock_provider._run_vboxmanage = MagicMock(return_value=(0, "Waiting for VM to power on...", ""))

    res = mock_provider.start_vm("vm-01")
    assert res.success is True
    assert res.operation == "start"
    mock_provider._run_vboxmanage.assert_called_once_with(["startvm", "cyberarena-vm-01", "--type", "headless"])


def test_start_vm_already_running(mock_provider):
    """Verify starting an already running VM is a no-op."""
    mock_provider.get_state = MagicMock(return_value=VMState.RUNNING)
    mock_provider._run_vboxmanage = MagicMock()

    res = mock_provider.start_vm("vm-01")
    assert res.success is True
    assert "already running" in res.message
    mock_provider._run_vboxmanage.assert_not_called()


def test_stop_vm_acpi_and_force(mock_provider):
    """Verify graceful ACPI stop and force poweroff."""
    mock_provider.get_state = MagicMock(return_value=VMState.RUNNING)
    mock_provider._run_vboxmanage = MagicMock(return_value=(0, "Success", ""))

    # Graceful stop
    res_graceful = mock_provider.stop_vm("vm-01", force=False)
    assert res_graceful.success is True
    mock_provider._run_vboxmanage.assert_called_with(["controlvm", "cyberarena-vm-01", "acpipowerbutton"])

    # Force stop
    res_force = mock_provider.stop_vm("vm-01", force=True)
    assert res_force.success is True
    mock_provider._run_vboxmanage.assert_called_with(["controlvm", "cyberarena-vm-01", "poweroff"])


def test_snapshot_creation(mock_provider):
    """Verify snapshot command generation."""
    mock_provider._run_vboxmanage = MagicMock(return_value=(0, "0%... 100%", ""))

    res = mock_provider.snapshot("vm-01", "clean_state", description="Baseline pre-experiment")
    assert res.success is True
    assert res.operation == "snapshot"
    mock_provider._run_vboxmanage.assert_called_once_with([
        "snapshot", "cyberarena-vm-01", "take", "clean_state", "--description", "Baseline pre-experiment"
    ])


def test_snapshot_restore(mock_provider):
    """Verify snapshot restore powers off running VM if needed before restoring."""
    mock_provider.get_state = MagicMock(return_value=VMState.RUNNING)
    mock_provider.stop_vm = MagicMock(return_value=MagicMock(success=True))
    mock_provider._run_vboxmanage = MagicMock(return_value=(0, "Restoring snapshot...", ""))

    res = mock_provider.restore_snapshot("vm-01", "clean_state")
    assert res.success is True
    assert res.operation == "restore_snapshot"
    mock_provider.stop_vm.assert_called_once_with("vm-01", force=True)
    mock_provider._run_vboxmanage.assert_called_once_with([
        "snapshot", "cyberarena-vm-01", "restore", "clean_state"
    ])


def test_execute_on_stopped_vm_rejected(mock_provider):
    """Verify that command execution is rejected if VM is stopped."""
    mock_provider.get_state = MagicMock(return_value=VMState.STOPPED)
    res = mock_provider.execute("vm-01", "uname -a")
    assert res.exit_code != 0
    assert "VM 'vm-01' is stopped" in res.stderr
