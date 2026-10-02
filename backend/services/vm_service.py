from typing import List, Optional
from backend.schemas.vm import (
    VMInfo,
    VMOperationResult,
    CommandExecutionResult,
    HealthCheckResult,
    SystemConfigResponse,
    SystemRegistryConfig,
)
from backend.virtualization.base import VMProvider
from backend.virtualization.virtualbox import VirtualBoxProvider
from backend.configs.settings import load_registry_config, settings
from backend.utils.logger import logger


class VMNotFoundError(Exception):
    """Raised when an operation is requested on an unregistered vm_id."""
    pass


class VMService:
    """
    Core VM Service and Registry coordinator.
    Validates dynamic constraints (such as max_vm) and delegates lifecycle
    and guest execution to the configured VMProvider.
    """

    def __init__(self, provider: Optional[VMProvider] = None, registry_config: Optional[SystemRegistryConfig] = None):
        self.registry_config = registry_config or load_registry_config()
        self.max_vm = self.registry_config.max_vm

        if provider is not None:
            self.provider = provider
        else:
            # Instantiate VirtualBoxProvider with configured VMs
            self.provider = VirtualBoxProvider(vms=self.registry_config.vms)

    def reload_config(self) -> None:
        """Reload configuration from disk and re-register VMs."""
        self.registry_config = load_registry_config()
        self.max_vm = self.registry_config.max_vm
        if isinstance(self.provider, VirtualBoxProvider):
            self.provider._vms.clear()
            for vm in self.registry_config.vms:
                self.provider.register_vm(vm)
        logger.info(f"Reloaded VM registry: {len(self.registry_config.vms)} configured (max_vm={self.max_vm})")

    def _validate_vm_id(self, vm_id: str) -> None:
        """Enforce validation that vm_id exists in registry."""
        configured_ids = [vm.vm_id for vm in self.registry_config.vms]
        if vm_id not in configured_ids:
            raise VMNotFoundError(f"Virtual Machine with id '{vm_id}' is not configured in the registry.")

    def get_system_config(self) -> SystemConfigResponse:
        """Retrieve system configuration including dynamic max_vm and configured VMs."""
        vms = self.provider.list_vms()
        return SystemConfigResponse(
            max_vm=self.max_vm,
            configured_vm_count=len(vms),
            default_provider=self.registry_config.default_provider,
            vms=vms,
        )

    def list_vms(self) -> List[VMInfo]:
        """List all configured virtual machines."""
        return self.provider.list_vms()

    def get_vm(self, vm_id: str) -> VMInfo:
        """Retrieve a specific VM by vm_id."""
        self._validate_vm_id(vm_id)
        vm = self.provider.get_vm(vm_id)
        if not vm:
            raise VMNotFoundError(f"VM '{vm_id}' not found.")
        return vm

    def start_vm(self, vm_id: str) -> VMOperationResult:
        """Start a virtual machine."""
        self._validate_vm_id(vm_id)
        return self.provider.start_vm(vm_id)

    def stop_vm(self, vm_id: str, force: bool = False) -> VMOperationResult:
        """Stop a virtual machine."""
        self._validate_vm_id(vm_id)
        return self.provider.stop_vm(vm_id, force=force)

    def snapshot(self, vm_id: str, snapshot_name: str, description: Optional[str] = None) -> VMOperationResult:
        """Take a snapshot of a virtual machine."""
        self._validate_vm_id(vm_id)
        return self.provider.snapshot(vm_id, snapshot_name=snapshot_name, description=description)

    def restore_snapshot(self, vm_id: str, snapshot_name: str) -> VMOperationResult:
        """Restore a virtual machine to a snapshot."""
        self._validate_vm_id(vm_id)
        return self.provider.restore_snapshot(vm_id, snapshot_name=snapshot_name)

    def execute_command(self, vm_id: str, command: str, timeout: Optional[int] = None) -> CommandExecutionResult:
        """Execute a command strictly inside the assigned VM via SSH."""
        self._validate_vm_id(vm_id)
        return self.provider.execute(vm_id, command=command, timeout=timeout)

    def health_check(self, vm_id: str) -> HealthCheckResult:
        """Run health check on a specific VM."""
        self._validate_vm_id(vm_id)
        return self.provider.health_check(vm_id)
