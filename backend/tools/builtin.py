import base64
import re
import shlex
from typing import Dict, Any, Optional

from backend.tools.base import BaseTool, ToolExecutionResult
from backend.virtualization.base import VMProvider


class ExecuteCommandTool(BaseTool):
    name = "execute_command"
    description = "Execute a shell command inside the assigned VM environment."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute inside the VM (e.g. 'uname -a', 'free -m', 'cat /etc/os-release')",
            }
        },
        "required": ["command"],
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        command = kwargs.get("command")
        if not command or not isinstance(command, str) or not command.strip():
            return ToolExecutionResult(
                success=False,
                output="",
                error="Parameter 'command' must be a non-empty string.",
            )

        cmd = command.strip()

        # Security Constraint 1: Prohibit password fabrication, placeholder passwords, and password piping
        pwd_patterns = [
            r"(?i)\b(your_password|<password>|yourpassword|password_here|root_password)\b",
            r"(?i)echo\s+['\"][^'\"]*['\"]\s*\|\s*sudo",
            r"(?i)sudo\s+-[Ss]",
        ]
        for pattern in pwd_patterns:
            if re.search(pattern, cmd):
                return ToolExecutionResult(
                    success=False,
                    output="",
                    error=(
                        "Security policy rejection: Password fabrication or injection is strictly prohibited. "
                        "Credentials are protected backend secrets and never passed via shell commands. "
                        "You have passwordless sudo configured; run sudo directly without password piping."
                    ),
                    metadata={"error_type": "password_injection_rejected", "exit_code": 1},
                )

        # Security Constraint 2: Prohibit arbitrary root shell execution via sudo bash/sh and credential theft
        if re.search(r"(?i)\bsudo\s+(?:bash|sh|zsh|dash|su\b|-i|-s)\b", cmd) or "cat /etc/shadow" in cmd:
            return ToolExecutionResult(
                success=False,
                output="",
                error=(
                    "Security policy rejection: Arbitrary privileged execution via 'sudo' is prohibited. "
                    "Use direct commands or dedicated privileged tools: install_package, restart_service, modify_system_config, create_user."
                ),
                metadata={"error_type": "arbitrary_privileged_shell_rejected", "exit_code": 1},
            )

        # Security Constraint 3: Prohibit ONLY destructive operations that permanently damage or brick the VM
        destructive_patterns = [
            # Root filesystem wipe: rm -rf / or rm -rf /*
            r"(?i)\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|--recursive\s+--force|-f[a-zA-Z]*r[a-zA-Z]*)\s+(/|/\*|/bin|/sbin|/usr|/lib|/boot|/sys|/proc|--no-preserve-root)(?:\s|$)",
            # Filesystem formatting / raw disk block device overwrite
            r"(?i)\bmkfs(?:\.[a-z0-9]+)?\s+/dev/(?:[shv]d[a-z]|nvme|loop|mapper)",
            r"(?i)\bdd\s+.*of=/dev/(?:[shv]d[a-z]|nvme|mem|kmem)",
            # Fork bomb
            r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
            # System shutdown/halt that kills the VM unexpectedly
            r"(?i)\b(?:shutdown|poweroff|halt|init\s+0)\b",
            # Raw disk partition deletion
            r"(?i)\b(?:fdisk|parted|sfdisk)\s+/dev/(?:[shv]d[a-z]|nvme)",
        ]
        for pattern in destructive_patterns:
            if re.search(pattern, cmd):
                return ToolExecutionResult(
                    success=False,
                    output="",
                    error=(
                        "Security policy rejection: Potentially destructive operation blocked. "
                        "Operations that can permanently wipe disk data, destroy the filesystem, or crash the VM environment are prohibited."
                    ),
                    metadata={"error_type": "destructive_operation_rejected", "exit_code": 1},
                )

        output_callback = kwargs.get("output_callback")
        try:
            if output_callback is not None:
                try:
                    res = vm_provider.execute_command(vm_id, cmd, output_callback=output_callback)
                except TypeError:
                    res = vm_provider.execute_command(vm_id, cmd)
            else:
                res = vm_provider.execute_command(vm_id, cmd)

            # Auto-elevation for non-sudo commands that hit 'Permission denied'
            # (e.g. touch /root/sahil.txt -> Permission denied -> auto retry with sudo touch /root/sahil.txt)
            if (
                res.exit_code != 0
                and "permission denied" in (res.stderr or "").lower()
                and not cmd.startswith("sudo ")
                and not cmd.startswith("sudo\t")
            ):
                elevated_cmd = f"sudo {cmd}"
                try:
                    if output_callback is not None:
                        try:
                            elev_res = vm_provider.execute_command(vm_id, elevated_cmd, output_callback=output_callback)
                        except TypeError:
                            elev_res = vm_provider.execute_command(vm_id, elevated_cmd)
                    else:
                        elev_res = vm_provider.execute_command(vm_id, elevated_cmd)
                    if elev_res.exit_code == 0:
                        res = elev_res
                        cmd = elevated_cmd
                except Exception:
                    pass
            success = (res.exit_code == 0)
            output = res.stdout if res.stdout else ""
            error = res.stderr if not success and res.stderr else None

            # Detect command_not_found or non-zero exit codes
            error_type = None
            if not success:
                err_text = (res.stderr or "").lower()
                if res.exit_code == 127 or "command not found" in err_text or "not found" in err_text:
                    error_type = "command_not_found"
                else:
                    error_type = "command_failed"

            # If stdout is empty and stderr has content, return stderr in output for context
            if not output and res.stderr:
                output = res.stderr

            metadata: Dict[str, Any] = {
                "exit_code": res.exit_code,
                "duration": res.duration,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
            if error_type:
                metadata["error_type"] = error_type

            return ToolExecutionResult(
                success=success,
                output=output,
                error=error,
                metadata=metadata,
            )
        except Exception as e:
            err_str = str(e)
            err_type = "ssh_failure" if "ssh" in err_str.lower() or "connection" in err_str.lower() else "execution_exception"
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Command execution error in VM {vm_id}: {e}",
                metadata={"error_type": err_type, "exit_code": -1},
            )


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the contents of a file inside the assigned VM environment."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path of the file to read (e.g. '/etc/os-release')",
            },
            "lines": {
                "type": "integer",
                "description": "Maximum number of lines to read from the beginning (default: 100)",
                "default": 100,
            },
        },
        "required": ["path"],
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        path = kwargs.get("path")
        lines = kwargs.get("lines", 100)
        if not path or not isinstance(path, str) or not path.strip():
            return ToolExecutionResult(
                success=False,
                output="",
                error="Parameter 'path' must be a non-empty string.",
            )

        try:
            line_count = int(lines) if lines else 100
        except (ValueError, TypeError):
            line_count = 100

        safe_path = shlex.quote(path.strip())
        cmd = f"head -n {line_count} {safe_path}"

        try:
            res = vm_provider.execute_command(vm_id, cmd)
            if res.exit_code != 0 and "permission denied" in (res.stderr or "").lower():
                res = vm_provider.execute_command(vm_id, f"sudo head -n {line_count} {safe_path}")
            return ToolExecutionResult(
                success=(res.exit_code == 0),
                output=res.stdout if res.exit_code == 0 else res.stderr,
                error=res.stderr if res.exit_code != 0 else None,
                metadata={"exit_code": res.exit_code, "path": path},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to read file {path} in VM {vm_id}: {e}",
            )


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write text content to a file inside the assigned VM environment."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Target file path inside the VM",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file",
            },
            "append": {
                "type": "boolean",
                "description": "Whether to append to the file instead of overwriting (default: false)",
                "default": False,
            },
        },
        "required": ["path", "content"],
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        path = kwargs.get("path")
        content = kwargs.get("content")
        append = bool(kwargs.get("append", False))

        if not path or not isinstance(path, str) or not path.strip():
            return ToolExecutionResult(
                success=False,
                output="",
                error="Parameter 'path' must be a non-empty string.",
            )
        if content is None or not isinstance(content, str):
            return ToolExecutionResult(
                success=False,
                output="",
                error="Parameter 'content' must be a string.",
            )

        safe_path = shlex.quote(path.strip())
        # Base64 encode content to safely transfer special characters and newlines without escaping issues
        b64_content = base64.b64encode(content.encode("utf-8")).decode("ascii")
        operator = ">>" if append else ">"
        cmd = f"echo '{b64_content}' | base64 -d {operator} {safe_path}"

        try:
            res = vm_provider.execute_command(vm_id, cmd)
            if res.exit_code != 0 and "permission denied" in (res.stderr or "").lower():
                tee_flag = "-a" if append else ""
                elev_cmd = f"echo '{b64_content}' | base64 -d | sudo tee {tee_flag} {safe_path} > /dev/null"
                res = vm_provider.execute_command(vm_id, elev_cmd)
            return ToolExecutionResult(
                success=(res.exit_code == 0),
                output=f"Successfully wrote {len(content)} bytes to {path}" if res.exit_code == 0 else res.stderr,
                error=res.stderr if res.exit_code != 0 else None,
                metadata={"exit_code": res.exit_code, "path": path, "bytes": len(content)},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to write file {path} in VM {vm_id}: {e}",
            )


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = "List files and directories in a given path inside the assigned VM."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list (default: '.')",
                "default": ".",
            }
        },
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        path = kwargs.get("path", ".")
        if not path or not isinstance(path, str):
            path = "."

        safe_path = shlex.quote(path.strip())
        cmd = f"ls -la {safe_path}"

        try:
            res = vm_provider.execute_command(vm_id, cmd)
            if res.exit_code != 0 and "permission denied" in (res.stderr or "").lower():
                res = vm_provider.execute_command(vm_id, f"sudo ls -la {safe_path}")
            return ToolExecutionResult(
                success=(res.exit_code == 0),
                output=res.stdout if res.exit_code == 0 else res.stderr,
                error=res.stderr if res.exit_code != 0 else None,
                metadata={"exit_code": res.exit_code, "path": path},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to list directory {path} in VM {vm_id}: {e}",
            )


class ProcessInfoTool(BaseTool):
    name = "process_info"
    description = "Inspect running processes inside the assigned VM environment."
    parameters = {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Optional search term to filter processes (e.g. 'ssh', 'python')",
            }
        },
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        proc_filter = kwargs.get("filter")
        if proc_filter and isinstance(proc_filter, str) and proc_filter.strip():
            safe_term = shlex.quote(proc_filter.strip())
            cmd = f"ps aux | grep -i {safe_term} | grep -v grep"
        else:
            cmd = "ps aux --sort=-%mem | head -n 30"

        try:
            res = vm_provider.execute_command(vm_id, cmd)
            output = res.stdout
            if not output and res.exit_code != 0:
                output = f"No processes matching filter '{proc_filter}' found."
            return ToolExecutionResult(
                success=True,
                output=output or "No matching processes found.",
                error=None,
                metadata={"exit_code": res.exit_code},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to retrieve process info in VM {vm_id}: {e}",
            )


class ServiceStatusTool(BaseTool):
    name = "service_status"
    description = "Check the status of a system service using systemctl inside the VM."
    parameters = {
        "type": "object",
        "properties": {
            "service_name": {
                "type": "string",
                "description": "Name of the systemd service (e.g. 'ssh', 'cron', 'systemd-resolved')",
            }
        },
        "required": ["service_name"],
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        service_name = kwargs.get("service_name")
        if not service_name or not isinstance(service_name, str) or not service_name.strip():
            return ToolExecutionResult(
                success=False,
                output="",
                error="Parameter 'service_name' must be a non-empty string.",
            )

        safe_service = shlex.quote(service_name.strip())
        cmd = f"systemctl status {safe_service} --no-pager"

        try:
            res = vm_provider.execute_command(vm_id, cmd)
            # systemctl status returns 0 if active, 3 if inactive/dead, 4 if not found
            return ToolExecutionResult(
                success=(res.exit_code in (0, 3)),
                output=res.stdout if res.stdout else res.stderr,
                error=res.stderr if res.exit_code not in (0, 3) else None,
                metadata={"exit_code": res.exit_code, "service": service_name},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to check service {service_name} in VM {vm_id}: {e}",
            )


class NetworkInfoTool(BaseTool):
    name = "network_info"
    description = "Inspect network interfaces, IP addresses, listening ports, or routing tables inside the VM."
    parameters = {
        "type": "object",
        "properties": {
            "info_type": {
                "type": "string",
                "enum": ["all", "interfaces", "ports", "routes"],
                "description": "Type of network information to gather (default: 'all')",
                "default": "all",
            }
        },
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        info_type = kwargs.get("info_type", "all")
        if info_type == "interfaces":
            cmd = "ip -4 addr"
        elif info_type == "ports":
            cmd = "ss -tuln"
        elif info_type == "routes":
            cmd = "ip route"
        else:
            cmd = "echo '=== INTERFACES ===' && ip -4 addr && echo '\n=== LISTENING PORTS ===' && ss -tuln && echo '\n=== ROUTES ===' && ip route"

        try:
            res = vm_provider.execute_command(vm_id, cmd)
            return ToolExecutionResult(
                success=(res.exit_code == 0),
                output=res.stdout if res.exit_code == 0 else res.stderr,
                error=res.stderr if res.exit_code != 0 else None,
                metadata={"exit_code": res.exit_code, "info_type": info_type},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to gather network info in VM {vm_id}: {e}",
            )


class SystemInfoTool(BaseTool):
    name = "system_info"
    description = "Gather OS distribution, kernel release, and hardware architecture summary from the assigned VM."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        cmd = "uname -srm && cat /etc/os-release | grep -E '^(PRETTY_NAME|NAME|VERSION)='"
        try:
            res = vm_provider.execute_command(vm_id, cmd)
            return ToolExecutionResult(
                success=(res.exit_code == 0),
                output=res.stdout if res.exit_code == 0 else res.stderr,
                error=res.stderr if res.exit_code != 0 else None,
                metadata={"exit_code": res.exit_code},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to gather system info in VM {vm_id}: {e}",
            )


class MemoryInfoTool(BaseTool):
    name = "memory_info"
    description = "Inspect memory (RAM) usage, swap space, and memory availability in human-readable format inside the VM."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        cmd = "free -h"
        try:
            res = vm_provider.execute_command(vm_id, cmd)
            return ToolExecutionResult(
                success=(res.exit_code == 0),
                output=res.stdout if res.exit_code == 0 else res.stderr,
                error=res.stderr if res.exit_code != 0 else None,
                metadata={"exit_code": res.exit_code},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to retrieve memory info in VM {vm_id}: {e}",
            )


class DiskUsageTool(BaseTool):
    name = "disk_usage"
    description = "Check filesystem disk space utilization, mount points, and available capacity inside the VM."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        cmd = "df -h -x tmpfs -x devtmpfs"
        try:
            res = vm_provider.execute_command(vm_id, cmd)
            return ToolExecutionResult(
                success=(res.exit_code == 0),
                output=res.stdout if res.exit_code == 0 else res.stderr,
                error=res.stderr if res.exit_code != 0 else None,
                metadata={"exit_code": res.exit_code},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to check disk usage in VM {vm_id}: {e}",
            )


class ListeningPortsTool(BaseTool):
    name = "listening_ports"
    description = "Inspect active TCP and UDP listening ports and network sockets inside the VM."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        cmd = "ss -tuln"
        try:
            res = vm_provider.execute_command(vm_id, cmd)
            return ToolExecutionResult(
                success=(res.exit_code == 0),
                output=res.stdout if res.exit_code == 0 else res.stderr,
                error=res.stderr if res.exit_code != 0 else None,
                metadata={"exit_code": res.exit_code},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to check listening ports in VM {vm_id}: {e}",
            )


class UptimeTool(BaseTool):
    name = "uptime"
    description = "Check system uptime, active user sessions, and CPU load averages inside the VM."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def execute(self, vm_provider: VMProvider, vm_id: str, **kwargs) -> ToolExecutionResult:
        cmd = "uptime"
        try:
            res = vm_provider.execute_command(vm_id, cmd)
            return ToolExecutionResult(
                success=(res.exit_code == 0),
                output=res.stdout if res.exit_code == 0 else res.stderr,
                error=res.stderr if res.exit_code != 0 else None,
                metadata={"exit_code": res.exit_code},
            )
        except Exception as e:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Failed to check uptime in VM {vm_id}: {e}",
            )
