from abc import ABC, abstractmethod
from typing import List, Optional, Callable
from backend.schemas.vm import (
    VMInfo,
    VMState,
    VMOperationResult,
    CommandExecutionResult,
    HealthCheckResult,
)


class VMProvider(ABC):
    """
    Abstract interface for Virtual Machine Providers in CyberArena.
    Decouples higher-level services and orchestrators from the underlying hypervisor.
    """

    @abstractmethod
    def list_vms(self) -> List[VMInfo]:
        """List all configured virtual machines and their current state."""
        pass

    @abstractmethod
    def get_vm(self, vm_id: str) -> Optional[VMInfo]:
        """Retrieve details and state for a specific virtual machine."""
        pass

    @abstractmethod
    def get_state(self, vm_id: str) -> VMState:
        """Query the runtime state (running, stopped, paused, etc.) of a VM."""
        pass

    @abstractmethod
    def start_vm(self, vm_id: str) -> VMOperationResult:
        """Start a virtual machine in headless mode."""
        pass

    @abstractmethod
    def stop_vm(self, vm_id: str, force: bool = False) -> VMOperationResult:
        """Stop or gracefully power down a virtual machine."""
        pass

    @abstractmethod
    def execute(
        self,
        vm_id: str,
        command: str,
        timeout: Optional[int] = None,
        output_callback: Optional[Callable[[str, str], None]] = None,
    ) -> CommandExecutionResult:
        """
        Execute a command inside the assigned guest VM.
        Execution must occur through an isolated guest channel (SSH), never on the host.
        """
        pass

    def execute_command(
        self,
        vm_id: str,
        command: str,
        timeout: Optional[int] = None,
        output_callback: Optional[Callable[[str, str], None]] = None,
    ) -> CommandExecutionResult:
        """Alias for execute() for tool compatibility."""
        return self.execute(vm_id, command, timeout=timeout, output_callback=output_callback)

    @abstractmethod
    def snapshot(self, vm_id: str, snapshot_name: str, description: Optional[str] = None) -> VMOperationResult:
        """Create a state snapshot for isolation and rollback."""
        pass

    @abstractmethod
    def restore_snapshot(self, vm_id: str, snapshot_name: str) -> VMOperationResult:
        """Restore a virtual machine to a specified snapshot."""
        pass

    @abstractmethod
    def health_check(self, vm_id: str) -> HealthCheckResult:
        """Perform a comprehensive health check on hypervisor state and connectivity."""
        pass
