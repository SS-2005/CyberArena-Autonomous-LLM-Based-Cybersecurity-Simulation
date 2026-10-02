import os
import time
import subprocess
from datetime import datetime, timezone
from typing import List, Optional, Dict, Tuple, Callable
from backend.schemas.vm import (
    VMConfig,
    VMInfo,
    VMState,
    VMOperationResult,
    CommandExecutionResult,
    HealthCheckResult,
)
from backend.virtualization.base import VMProvider
from backend.virtualization.ssh_client import VMSSHClient
from backend.configs.settings import settings, find_vboxmanage
from backend.utils.logger import logger


class VirtualBoxProvider(VMProvider):
    """
    VirtualBox implementation of VMProvider.
    Uses VBoxManage strictly for hypervisor lifecycle control (headless VMs).
    Guest commands are strictly executed over SSH via Paramiko.
    """

    def __init__(
        self,
        vms: Optional[List[VMConfig]] = None,
        vboxmanage_path: Optional[str] = None,
    ):
        self.vboxmanage_path = vboxmanage_path or settings.vboxmanage_path or find_vboxmanage()
        self._vms: Dict[str, VMConfig] = {}
        self._state_cache: Dict[str, Tuple[float, VMState]] = {}
        if vms:
            for vm in vms:
                self.register_vm(vm)

    def register_vm(self, vm_config: VMConfig) -> None:
        """Register a VM configuration mapping logical vm_id to hypervisor target."""
        self._vms[vm_config.vm_id] = vm_config

    def get_config(self, vm_id: str) -> Optional[VMConfig]:
        """Get the configuration for a registered vm_id."""
        return self._vms.get(vm_id)

    def _run_vboxmanage(self, args: List[str], timeout: int = 20) -> Tuple[int, str, str]:
        """
        Execute controlled VBoxManage commands with strictly parameterized arguments.
        Never invokes a host shell (shell=False). Only runs fixed hypervisor binary.
        """
        if not self.vboxmanage_path:
            raise FileNotFoundError(
                "VBoxManage executable path not set. "
                "Please install VirtualBox or set VBOX_MANAGE_PATH environment variable."
            )

        cmd = [self.vboxmanage_path] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                shell=False,  # Strict: Never run in shell
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", f"VBoxManage command timed out after {timeout} seconds: {' '.join(args)}"
        except Exception as e:
            return -1, "", f"Failed to execute VBoxManage: {str(e)}"

    def list_vms(self) -> List[VMInfo]:
        """List all configured virtual machines with their live states."""
        results: List[VMInfo] = []
        for vm_id in self._vms:
            vm_info = self.get_vm(vm_id)
            if vm_info:
                results.append(vm_info)
        return results

    def get_vm(self, vm_id: str) -> Optional[VMInfo]:
        """Retrieve details and live state of a configured VM."""
        vm_config = self._vms.get(vm_id)
        if not vm_config:
            return None

        state = self.get_state(vm_id)
        return VMInfo(
            vm_id=vm_config.vm_id,
            vm_provider=vm_config.vm_provider,
            virtualbox_vm_name=vm_config.virtualbox_vm_name,
            state=state,
            ssh_host=vm_config.ssh_host,
            ssh_port=vm_config.ssh_port,
            ssh_username=vm_config.ssh_username,
            ssh_auth_method=vm_config.ssh_auth_method.value,
            description=vm_config.description,
            last_checked=datetime.now(timezone.utc).isoformat(),
        )

    def get_state(self, vm_id: str, force_refresh: bool = False) -> VMState:
        """Query state of VM from VirtualBox with a short TTL cache."""
        vm_config = self._vms.get(vm_id)
        if not vm_config:
            return VMState.UNKNOWN

        if not force_refresh and vm_id in self._state_cache:
            ts, cached_state = self._state_cache[vm_id]
            if time.time() - ts < 3.0:
                return cached_state

        if not self.vboxmanage_path:
            return VMState.UNKNOWN

        code, stdout, _ = self._run_vboxmanage(["showvminfo", vm_config.virtualbox_vm_name, "--machinereadable"])
        if code != 0:
            return VMState.UNKNOWN

        resolved_state = VMState.UNKNOWN
        for line in stdout.splitlines():
            if line.startswith("VMState="):
                raw_state = line.split("=", 1)[1].strip('"').lower()
                if raw_state == "running":
                    resolved_state = VMState.RUNNING
                elif raw_state in ("poweroff", "powered off", "aborted", "saved"):
                    resolved_state = VMState.STOPPED
                elif raw_state == "paused":
                    resolved_state = VMState.PAUSED
                elif raw_state in ("starting", "restoring"):
                    resolved_state = VMState.STARTING
                elif raw_state in ("stopping", "saving"):
                    resolved_state = VMState.STOPPING
                break

        self._state_cache[vm_id] = (time.time(), resolved_state)
        return resolved_state

    def start_vm(self, vm_id: str) -> VMOperationResult:
        """Start VM in headless mode."""
        vm_config = self._vms.get(vm_id)
        now = datetime.now(timezone.utc).isoformat()
        if not vm_config:
            return VMOperationResult(
                vm_id=vm_id,
                operation="start",
                success=False,
                message=f"VM '{vm_id}' is not configured in the registry.",
                timestamp=now,
            )

        current_state = self.get_state(vm_id)
        if current_state == VMState.RUNNING:
            return VMOperationResult(
                vm_id=vm_id,
                operation="start",
                success=True,
                message=f"VM '{vm_id}' is already running.",
                timestamp=now,
            )

        code, stdout, stderr = self._run_vboxmanage([
            "startvm",
            vm_config.virtualbox_vm_name,
            "--type",
            "headless",
        ])

        success = code == 0
        self._state_cache.pop(vm_id, None)
        message = stdout if success else f"Failed to start VM: {stderr}"
        return VMOperationResult(
            vm_id=vm_id,
            operation="start",
            success=success,
            message=message,
            timestamp=now,
            details={"exit_code": code},
        )

    def stop_vm(self, vm_id: str, force: bool = False) -> VMOperationResult:
        """Stop VM gracefully (ACPI button) or force poweroff."""
        vm_config = self._vms.get(vm_id)
        now = datetime.now(timezone.utc).isoformat()
        if not vm_config:
            return VMOperationResult(
                vm_id=vm_id,
                operation="stop",
                success=False,
                message=f"VM '{vm_id}' is not configured in the registry.",
                timestamp=now,
            )

        current_state = self.get_state(vm_id)
        if current_state == VMState.STOPPED:
            return VMOperationResult(
                vm_id=vm_id,
                operation="stop",
                success=True,
                message=f"VM '{vm_id}' is already stopped.",
                timestamp=now,
            )

        action = "poweroff" if force else "acpipowerbutton"
        code, stdout, stderr = self._run_vboxmanage([
            "controlvm",
            vm_config.virtualbox_vm_name,
            action,
        ])

        success = code == 0
        self._state_cache.pop(vm_id, None)
        message = f"Stop request ({action}) completed." if success else f"Failed to stop VM: {stderr}"
        return VMOperationResult(
            vm_id=vm_id,
            operation="stop",
            success=success,
            message=message,
            timestamp=now,
            details={"exit_code": code, "action": action},
        )

    def snapshot(self, vm_id: str, snapshot_name: str, description: Optional[str] = None) -> VMOperationResult:
        """Create a snapshot of the virtual machine state."""
        vm_config = self._vms.get(vm_id)
        now = datetime.now(timezone.utc).isoformat()
        if not vm_config:
            return VMOperationResult(
                vm_id=vm_id,
                operation="snapshot",
                success=False,
                message=f"VM '{vm_id}' is not configured in the registry.",
                timestamp=now,
            )

        args = [
            "snapshot",
            vm_config.virtualbox_vm_name,
            "take",
            snapshot_name,
        ]
        if description:
            args.extend(["--description", description])

        code, stdout, stderr = self._run_vboxmanage(args)
        success = code == 0
        message = f"Snapshot '{snapshot_name}' created successfully." if success else f"Failed to create snapshot: {stderr}"
        return VMOperationResult(
            vm_id=vm_id,
            operation="snapshot",
            success=success,
            message=message,
            timestamp=now,
            details={"snapshot_name": snapshot_name, "exit_code": code},
        )

    def restore_snapshot(self, vm_id: str, snapshot_name: str) -> VMOperationResult:
        """
        Restore the virtual machine to a specified snapshot.
        If the VM is running, it must be powered off before snapshot restoration.
        """
        vm_config = self._vms.get(vm_id)
        now = datetime.now(timezone.utc).isoformat()
        if not vm_config:
            return VMOperationResult(
                vm_id=vm_id,
                operation="restore_snapshot",
                success=False,
                message=f"VM '{vm_id}' is not configured in the registry.",
                timestamp=now,
            )

        # Ensure VM is stopped before restore
        current_state = self.get_state(vm_id)
        if current_state == VMState.RUNNING:
            stop_res = self.stop_vm(vm_id, force=True)
            if not stop_res.success:
                return VMOperationResult(
                    vm_id=vm_id,
                    operation="restore_snapshot",
                    success=False,
                    message=f"Cannot restore snapshot: Failed to stop running VM ({stop_res.message})",
                    timestamp=now,
                )

        code, stdout, stderr = self._run_vboxmanage([
            "snapshot",
            vm_config.virtualbox_vm_name,
            "restore",
            snapshot_name,
        ])

        success = code == 0
        self._state_cache.pop(vm_id, None)
        message = f"Snapshot '{snapshot_name}' restored successfully." if success else f"Failed to restore snapshot: {stderr}"
        return VMOperationResult(
            vm_id=vm_id,
            operation="restore_snapshot",
            success=success,
            message=message,
            timestamp=now,
            details={"snapshot_name": snapshot_name, "exit_code": code},
        )

    def execute(
        self,
        vm_id: str,
        command: str,
        timeout: Optional[int] = None,
        output_callback: Optional[Callable[[str, str], None]] = None,
    ) -> CommandExecutionResult:
        """
        Execute command strictly inside the assigned VM via Paramiko SSH.
        Refuses execution if the VM is not running.
        Host OS is NEVER an execution target.
        """
        now = datetime.now(timezone.utc).isoformat()
        vm_config = self._vms.get(vm_id)
        if not vm_config:
            return CommandExecutionResult(
                vm_id=vm_id,
                command=command,
                stdout="",
                stderr=f"VM '{vm_id}' not found in registry.",
                exit_code=1,
                duration=0.0,
                timestamp=now,
            )

        current_state = self.get_state(vm_id)
        # Note: If state detection is unknown, allow attempt if host is configured, but if known STOPPED, reject
        if current_state == VMState.STOPPED:
            return CommandExecutionResult(
                vm_id=vm_id,
                command=command,
                stdout="",
                stderr=f"VM '{vm_id}' is stopped. Start the VM before executing commands.",
                exit_code=1,
                duration=0.0,
                timestamp=now,
            )

        ssh_client = VMSSHClient(vm_config=vm_config, default_timeout=timeout or settings.default_ssh_timeout)
        return ssh_client.execute_command(command, timeout=timeout, output_callback=output_callback)

    def health_check(self, vm_id: str) -> HealthCheckResult:
        """Perform health check: hypervisor state + SSH probe."""
        now = datetime.now(timezone.utc).isoformat()
        vm_config = self._vms.get(vm_id)
        if not vm_config:
            return HealthCheckResult(
                vm_id=vm_id,
                state=VMState.UNKNOWN,
                is_running=False,
                ssh_reachable=False,
                message=f"VM '{vm_id}' is not in the registry.",
                timestamp=now,
            )

        state = self.get_state(vm_id)
        is_running = state == VMState.RUNNING

        ssh_reachable = False
        latency = None
        ssh_message = "SSH check skipped (VM not running)"

        if is_running:
            ssh_client = VMSSHClient(vm_config=vm_config)
            ssh_reachable, latency, ssh_message = ssh_client.test_connection(timeout=5)

        summary_msg = f"Hypervisor State: {state.value}. SSH: {ssh_message}"
        return HealthCheckResult(
            vm_id=vm_id,
            state=state,
            is_running=is_running,
            ssh_reachable=ssh_reachable,
            latency_ms=latency,
            message=summary_msg,
            timestamp=now,
        )
