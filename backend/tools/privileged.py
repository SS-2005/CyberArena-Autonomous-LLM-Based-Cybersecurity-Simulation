import base64
import shlex
import time
from typing import Dict, Any, List, Optional

from backend.tools.base import BaseTool, ToolExecutionResult
from backend.tools.policy import default_policy_manager, ToolPolicyManager
from backend.virtualization.base import VMProvider
from backend.utils.logger import logger


class InstallPackageTool(BaseTool):
    name = "install_package"
    description = (
        "Install a software package inside the assigned VM environment without requiring interactive passwords. "
        "Supports standard packages and libraries (e.g. sysbench, nmap, curl, wget, net-tools, tcpdump, etc.)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "package_name": {
                "type": "string",
                "description": "Name of the software package to install (e.g. 'nmap', 'tcpdump', 'curl')",
            }
        },
        "required": ["package_name"],
    }

    def __init__(self, policy_manager: Optional[ToolPolicyManager] = None):
        self.policy_manager = policy_manager or default_policy_manager

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        package_name = kwargs.get("package_name")
        valid, err = self.policy_manager.validate_package(package_name)
        if not valid:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Policy violation: {err}",
                metadata={"vm_id": vm_id, "package_name": package_name, "error_type": "policy_rejection"},
            )

        pkg = str(package_name).strip()
        safe_pkg = shlex.quote(pkg)
        cmd = f"sudo /usr/local/sbin/cyberarena-install-package {safe_pkg}"
        output_callback = kwargs.get("output_callback")

        start_time = time.time()
        try:
            if output_callback is not None:
                try:
                    res = vm_provider.execute_command(vm_id, cmd, output_callback=output_callback)
                except TypeError:
                    res = vm_provider.execute_command(vm_id, cmd)
            else:
                res = vm_provider.execute_command(vm_id, cmd)

            duration = round(time.time() - start_time, 3)
            success = (res.exit_code == 0)
            output = res.stdout if success else (res.stderr or res.stdout)
            err_msg = res.stderr if not success and res.stderr else None

            return ToolExecutionResult(
                success=success,
                output=output or (f"Package '{pkg}' installed successfully." if success else "Installation failed."),
                error=err_msg,
                metadata={
                    "vm_id": vm_id,
                    "package_name": pkg,
                    "exit_code": res.exit_code,
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                    "duration": duration,
                },
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to install package '{pkg}' on VM '{vm_id}': {e}",
                metadata={"vm_id": vm_id, "package_name": pkg, "error_type": "execution_exception"},
            )


class RestartServiceTool(BaseTool):
    name = "restart_service"
    description = (
        "Restart a system service inside the assigned VM environment and verify its status (e.g. ssh, systemd-resolved, ufw, auditd, fail2ban, cron, etc.)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "service_name": {
                "type": "string",
                "description": "Name of the service to restart (e.g. 'ssh', 'systemd-resolved', 'ufw')",
            }
        },
        "required": ["service_name"],
    }

    def __init__(self, policy_manager: Optional[ToolPolicyManager] = None):
        self.policy_manager = policy_manager or default_policy_manager

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        service_name = kwargs.get("service_name")
        valid, err = self.policy_manager.validate_service(service_name)
        if not valid:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Policy violation: {err}",
                metadata={"vm_id": vm_id, "service_name": service_name, "error_type": "policy_rejection"},
            )

        svc = str(service_name).strip()
        safe_svc = shlex.quote(svc)
        cmd = f"sudo /usr/local/sbin/cyberarena-restart-service {safe_svc}"
        output_callback = kwargs.get("output_callback")

        start_time = time.time()
        try:
            if output_callback is not None:
                try:
                    res = vm_provider.execute_command(vm_id, cmd, output_callback=output_callback)
                except TypeError:
                    res = vm_provider.execute_command(vm_id, cmd)
            else:
                res = vm_provider.execute_command(vm_id, cmd)

            duration = round(time.time() - start_time, 3)
            success = (res.exit_code == 0)

            # Verification check
            verify_cmd = f"systemctl is-active {safe_svc}"
            verify_res = vm_provider.execute_command(vm_id, verify_cmd)
            is_active = verify_res.stdout.strip() if verify_res.stdout else "unknown"

            combined_output = (res.stdout.strip() + f"\nVerification state: {is_active}").strip()

            return ToolExecutionResult(
                success=success,
                output=combined_output if success else (res.stderr or combined_output),
                error=res.stderr if not success and res.stderr else None,
                metadata={
                    "vm_id": vm_id,
                    "service_name": svc,
                    "exit_code": res.exit_code,
                    "active_status": is_active,
                    "duration": duration,
                },
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to restart service '{svc}' on VM '{vm_id}': {e}",
                metadata={"vm_id": vm_id, "service_name": svc, "error_type": "execution_exception"},
            )


class ModifySystemConfigTool(BaseTool):
    name = "modify_system_config"
    description = (
        "Modify an allowlisted system configuration file inside the assigned VM environment using controlled operations. "
        "Allowed targets: /etc/ssh/sshd_config.d/cyberarena.conf, /etc/sysctl.d/99-cyberarena.conf, "
        "/etc/security/limits.d/cyberarena.conf, /etc/cyberarena/lab.conf. "
        "Operations: set, append, replace."
    )
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Path to the configuration file (must be on the policy allowlist)",
            },
            "operation": {
                "type": "string",
                "enum": ["set", "append", "replace"],
                "description": "Operation to perform: 'set', 'append', or 'replace'",
            },
            "value": {
                "type": "string",
                "description": "Text content or configuration directive to write",
            },
        },
        "required": ["target", "operation", "value"],
    }

    def __init__(self, policy_manager: Optional[ToolPolicyManager] = None):
        self.policy_manager = policy_manager or default_policy_manager

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        target = kwargs.get("target")
        operation = kwargs.get("operation")
        value = kwargs.get("value", "")

        valid, err = self.policy_manager.validate_config(target, operation, value)
        if not valid:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Policy violation: {err}",
                metadata={"vm_id": vm_id, "target": target, "operation": operation, "error_type": "policy_rejection"},
            )

        tgt = str(target).strip()
        op = str(operation).strip().lower()
        val = str(value)
        safe_tgt = shlex.quote(tgt)
        safe_op = shlex.quote(op)

        # Read before state
        before_res = vm_provider.execute_command(vm_id, f"cat {safe_tgt} 2>/dev/null || true")
        before_state = before_res.stdout.strip() if before_res.exit_code == 0 else ""

        # Base64 encode value to prevent shell manipulation or escaping flaws
        b64_val = base64.b64encode(val.encode("utf-8")).decode("ascii")
        cmd = f"sudo /usr/local/sbin/cyberarena-modify-config {safe_tgt} {safe_op} '{b64_val}'"

        start_time = time.time()
        try:
            res = vm_provider.execute_command(vm_id, cmd)
            duration = round(time.time() - start_time, 3)
            success = (res.exit_code == 0)

            # Read after state
            after_res = vm_provider.execute_command(vm_id, f"cat {safe_tgt} 2>/dev/null || true")
            after_state = after_res.stdout.strip() if after_res.exit_code == 0 else ""

            output = (
                f"Successfully updated '{tgt}' ({op}).\n"
                f"--- Before State ---\n{before_state or '(empty)'}\n"
                f"--- After State ---\n{after_state or '(empty)'}"
            ) if success else (res.stderr or "Config modification failed.")

            return ToolExecutionResult(
                success=success,
                output=output,
                error=res.stderr if not success and res.stderr else None,
                metadata={
                    "vm_id": vm_id,
                    "target": tgt,
                    "operation": op,
                    "before_state": before_state,
                    "after_state": after_state,
                    "exit_code": res.exit_code,
                    "duration": duration,
                },
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to modify config '{tgt}' on VM '{vm_id}': {e}",
                metadata={"vm_id": vm_id, "target": tgt, "error_type": "execution_exception"},
            )


class CreateUserTool(BaseTool):
    name = "create_user"
    description = (
        "Create a new user account with restricted group membership inside the assigned VM environment. "
        "Allowed groups: users, developers, analysts, operators, testers. "
        "Administrative groups (sudo, root, wheel, admin, etc.) are strictly forbidden."
    )
    parameters = {
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "Username to create (lowercase alphanumeric, 2-32 characters)",
            },
            "groups": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of non-administrative groups (e.g. ['analysts', 'testers'])",
            },
        },
        "required": ["username"],
    }

    def __init__(self, policy_manager: Optional[ToolPolicyManager] = None):
        self.policy_manager = policy_manager or default_policy_manager

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        username = kwargs.get("username")
        groups = kwargs.get("groups", [])
        if isinstance(groups, str):
            groups = [g.strip() for g in groups.split(",") if g.strip()]
        elif not isinstance(groups, list):
            groups = []

        valid, err = self.policy_manager.validate_user(username, groups)
        if not valid:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Policy violation: {err}",
                metadata={"vm_id": vm_id, "username": username, "groups": groups, "error_type": "policy_rejection"},
            )

        usr = str(username).strip()
        groups_str = ",".join([str(g).strip() for g in groups])
        safe_usr = shlex.quote(usr)
        safe_groups = shlex.quote(groups_str) if groups_str else "''"

        cmd = f"sudo /usr/local/sbin/cyberarena-create-user {safe_usr} {safe_groups}"
        start_time = time.time()
        try:
            res = vm_provider.execute_command(vm_id, cmd)
            duration = round(time.time() - start_time, 3)
            success = (res.exit_code == 0)

            return ToolExecutionResult(
                success=success,
                output=res.stdout if success else (res.stderr or res.stdout),
                error=res.stderr if not success and res.stderr else None,
                metadata={
                    "vm_id": vm_id,
                    "username": usr,
                    "groups": groups,
                    "exit_code": res.exit_code,
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                    "duration": duration,
                },
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to create user '{usr}' on VM '{vm_id}': {e}",
                metadata={"vm_id": vm_id, "username": usr, "error_type": "execution_exception"},
            )
