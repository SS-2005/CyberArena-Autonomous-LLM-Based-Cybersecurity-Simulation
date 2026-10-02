import os
import shutil
import pytest
from backend.configs.settings import load_registry_config, find_vboxmanage
from backend.virtualization.virtualbox import VirtualBoxProvider
from backend.schemas.vm import VMState


@pytest.fixture
def real_vbox_provider():
    vbox_path = find_vboxmanage()
    if not vbox_path or not os.path.isfile(vbox_path):
        pytest.skip("VBoxManage executable not found on host machine. Skipping live VirtualBox integration tests.")

    config = load_registry_config()
    if not config.vms:
        pytest.skip("No VMs configured in registry. Skipping live VirtualBox integration tests.")

    provider = VirtualBoxProvider(vms=config.vms, vboxmanage_path=vbox_path)
    return provider, config


def test_real_virtualbox_state_detection(real_vbox_provider):
    """
    Query real VirtualBox hypervisor on the host machine.
    Verifies that real VBoxManage executes and returns valid VMState.
    """
    provider, config = real_vbox_provider
    first_vm = config.vms[0]

    state = provider.get_state(first_vm.vm_id)
    assert isinstance(state, VMState)
    # The VM on host will typically be STOPPED or UNKNOWN if not yet imported
    assert state in (VMState.RUNNING, VMState.STOPPED, VMState.UNKNOWN)


def test_real_virtualbox_ssh_if_running(real_vbox_provider):
    """
    If a configured VM is currently RUNNING on the host, test live SSH command execution.
    If no configured VM is running, skip gracefully.
    """
    provider, config = real_vbox_provider
    first_vm = config.vms[0]

    state = provider.get_state(first_vm.vm_id)
    if state != VMState.RUNNING:
        pytest.skip(
            f"Configured VM '{first_vm.virtualbox_vm_name}' is not currently running (state: {state.value}). "
            "Skipping live SSH guest command execution."
        )

    result = provider.execute(first_vm.vm_id, "uname -a")
    assert result.vm_id == first_vm.vm_id
    assert result.exit_code == 0
    assert len(result.stdout) > 0
