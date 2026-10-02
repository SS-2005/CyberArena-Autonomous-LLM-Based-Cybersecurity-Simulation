import json
import pytest
from pathlib import Path
from backend.schemas.vm import SystemRegistryConfig, VMConfig, SSHAuthMethod
from backend.configs.settings import load_registry_config, get_vm_secret
from backend.services.vm_service import VMService, VMNotFoundError
from backend.virtualization.virtualbox import VirtualBoxProvider


def test_registry_loads_default_config():
    """Verify registry loads correctly and contains valid VM configurations."""
    config = load_registry_config()
    assert config is not None
    assert isinstance(config.max_vm, int)
    assert config.max_vm >= 1
    assert len(config.vms) <= config.max_vm


def test_registry_enforces_max_vm_limit(tmp_path, monkeypatch):
    """Verify that when configured VMs exceed max_vm, registry truncates to max_vm."""
    test_config = {
        "max_vm": 2,
        "default_provider": "virtualbox",
        "vms": [
            {
                "vm_id": f"vm-0{i}",
                "vm_provider": "virtualbox",
                "virtualbox_vm_name": f"test-vm-0{i}",
                "ssh_host": f"192.168.56.10{i}",
                "ssh_port": 22,
                "ssh_username": "labuser",
                "ssh_auth_method": "password",
            }
            for i in range(1, 5)  # 4 VMs configured, but max_vm is 2
        ]
    }
    config_file = tmp_path / "vms.json"
    config_file.write_text(json.dumps(test_config), encoding="utf-8")

    from backend.configs.settings import settings
    monkeypatch.setattr(settings, "max_vm_override", None)
    loaded = load_registry_config(str(config_file))
    assert loaded.max_vm == 2
    assert len(loaded.vms) == 2
    assert loaded.vms[0].vm_id == "vm-01"
    assert loaded.vms[1].vm_id == "vm-02"


def test_registry_dynamic_max_vm_expansion(tmp_path, monkeypatch):
    """Verify that max_vm can be dynamically set to higher values without breaking."""
    test_config = {
        "max_vm": 5,
        "default_provider": "virtualbox",
        "vms": [
            {
                "vm_id": f"vm-0{i}",
                "vm_provider": "virtualbox",
                "virtualbox_vm_name": f"test-vm-0{i}",
                "ssh_host": f"192.168.56.10{i}",
                "ssh_port": 22,
                "ssh_username": "labuser",
                "ssh_auth_method": "password",
            }
            for i in range(1, 5)
        ]
    }
    config_file = tmp_path / "vms_expanded.json"
    config_file.write_text(json.dumps(test_config), encoding="utf-8")

    from backend.configs.settings import settings
    monkeypatch.setattr(settings, "max_vm_override", None)
    loaded = load_registry_config(str(config_file))
    assert loaded.max_vm == 5
    assert len(loaded.vms) == 4


def test_get_vm_secret_resolution(monkeypatch):
    """Verify secrets are securely resolved from environment and not hardcoded."""
    vm_cfg = VMConfig(
        vm_id="vm-01",
        vm_provider="virtualbox",
        virtualbox_vm_name="cyberarena-vm-01",
        ssh_host="192.168.56.101",
        ssh_port=22,
        ssh_username="labuser",
        ssh_auth_method=SSHAuthMethod.PASSWORD,
        ssh_password_env="CYBERARENA_TEST_PW",
        ssh_key_path_env="CYBERARENA_TEST_KEY",
    )

    monkeypatch.setenv("CYBERARENA_TEST_PW", "super_secret_lab_pass")
    monkeypatch.setenv("CYBERARENA_TEST_KEY", "/path/to/key.pem")

    secrets = get_vm_secret(vm_cfg)
    assert secrets["password"] == "super_secret_lab_pass"
    assert secrets["key_path"] == "/path/to/key.pem"


def test_vm_service_lookup_and_invalid_vm():
    """Verify VMService correctly looks up configured VMs and rejects invalid ones."""
    dummy_vms = [
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
    registry = SystemRegistryConfig(max_vm=2, vms=dummy_vms)
    provider = VirtualBoxProvider(vms=dummy_vms)
    service = VMService(provider=provider, registry_config=registry)

    # Valid VM lookup
    vm = service.get_vm("vm-01")
    assert vm.vm_id == "vm-01"
    assert vm.virtualbox_vm_name == "cyberarena-vm-01"

    # Invalid VM lookup must raise VMNotFoundError
    with pytest.raises(VMNotFoundError):
        service.get_vm("non-existent-vm")

    with pytest.raises(VMNotFoundError):
        service.start_vm("invalid-id")

    with pytest.raises(VMNotFoundError):
        service.stop_vm("invalid-id")

    with pytest.raises(VMNotFoundError):
        service.snapshot("invalid-id", "snap1")

    with pytest.raises(VMNotFoundError):
        service.restore_snapshot("invalid-id", "snap1")

    with pytest.raises(VMNotFoundError):
        service.execute_command("invalid-id", "ls")
