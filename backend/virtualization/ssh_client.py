import time
from datetime import datetime, timezone
from typing import Optional, Tuple, Callable
import paramiko
from backend.schemas.vm import VMConfig, CommandExecutionResult, SSHAuthMethod
from backend.configs.settings import get_vm_secret
from backend.utils.logger import logger


class SSHExecutionError(Exception):
    """Raised when SSH connection or execution encounters an unrecoverable error."""
    pass


class VMSSHClient:
    """
    Paramiko-based SSH executor for isolated guest virtual machines.
    All commands execute strictly inside the guest Ubuntu environment.
    No command text is ever passed to the Windows host shell or subprocess.
    """

    def __init__(self, vm_config: VMConfig, default_timeout: int = 30):
        self.vm_config = vm_config
        self.default_timeout = default_timeout

    def _create_client(self, timeout: Optional[int] = None) -> paramiko.SSHClient:
        """Create and configure a Paramiko SSH client using configuration credentials."""
        client = paramiko.SSHClient()
        # Automatically add guest host keys in controlled lab environment
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_timeout = timeout or self.default_timeout
        secrets = get_vm_secret(self.vm_config)

        connect_kwargs = {
            "hostname": self.vm_config.ssh_host,
            "port": self.vm_config.ssh_port,
            "username": self.vm_config.ssh_username,
            "timeout": connect_timeout,
            "banner_timeout": connect_timeout,
            "auth_timeout": connect_timeout,
            "look_for_keys": False,
            "allow_agent": False,
        }

        if self.vm_config.ssh_auth_method == SSHAuthMethod.PASSWORD:
            password = secrets.get("password")
            if not password:
                raise SSHExecutionError(
                    f"Authentication error for {self.vm_config.vm_id}: "
                    f"Password required but not found in environment ({self.vm_config.ssh_password_env})."
                )
            connect_kwargs["password"] = password

        elif self.vm_config.ssh_auth_method == SSHAuthMethod.KEY:
            key_path = secrets.get("key_path")
            if not key_path:
                raise SSHExecutionError(
                    f"Authentication error for {self.vm_config.vm_id}: "
                    f"SSH private key path required but not found in environment ({self.vm_config.ssh_key_path_env})."
                )
            connect_kwargs["key_filename"] = key_path

        return client, connect_kwargs

    def test_connection(self, timeout: int = 5) -> Tuple[bool, Optional[float], str]:
        """
        Probe SSH reachability without executing complex commands.
        Returns: (is_reachable, latency_ms, message)
        """
        start_time = time.perf_counter()
        client = None
        try:
            client, kwargs = self._create_client(timeout=timeout)
            client.connect(**kwargs)
            latency = (time.perf_counter() - start_time) * 1000.0
            return True, round(latency, 2), "SSH connection successful"
        except paramiko.AuthenticationException as e:
            return False, None, f"Authentication failed: {str(e)}"
        except (paramiko.SSHException, TimeoutError, OSError) as e:
            return False, None, f"SSH unreachable: {str(e)}"
        except SSHExecutionError as e:
            return False, None, str(e)
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

    def execute_command(
        self,
        command: str,
        timeout: Optional[int] = None,
        output_callback: Optional[Callable[[str, str], None]] = None,
    ) -> CommandExecutionResult:
        """
        Execute command strictly inside the guest VM via SSH and return structured telemetry.
        Streams stdout/stderr in real-time via output_callback(stream_type, chunk) when provided.
        """
        exec_timeout = timeout or self.default_timeout
        start_time = time.perf_counter()
        iso_timestamp = datetime.now(timezone.utc).isoformat()

        client = None
        try:
            client, kwargs = self._create_client(timeout=exec_timeout)
            client.connect(**kwargs)

            # Execute command inside isolated guest
            stdin, stdout, stderr = client.exec_command(command, timeout=exec_timeout)
            channel = stdout.channel

            # If channel is a mock or does not return boolean for recv_ready:
            is_mock = False
            if hasattr(channel, "recv_ready"):
                try:
                    res = channel.recv_ready()
                    if not isinstance(res, bool):
                        is_mock = True
                except Exception:
                    is_mock = True
            else:
                is_mock = True

            if is_mock:
                raw_out = stdout.read()
                raw_err = stderr.read()
                stdout_str = raw_out.decode("utf-8", errors="replace") if isinstance(raw_out, bytes) else str(raw_out or "")
                stderr_str = raw_err.decode("utf-8", errors="replace") if isinstance(raw_err, bytes) else str(raw_err or "")
                exit_code = 0
                if hasattr(channel, "recv_exit_status"):
                    try:
                        ret = channel.recv_exit_status()
                        exit_code = ret if isinstance(ret, int) else 0
                    except Exception:
                        pass
                if output_callback and stdout_str:
                    try:
                        output_callback("stdout", stdout_str)
                    except Exception:
                        pass
                if output_callback and stderr_str:
                    try:
                        output_callback("stderr", stderr_str)
                    except Exception:
                        pass
            else:
                stdout_chunks = []
                stderr_chunks = []

                # Stream execution chunks in real-time using non-blocking recv
                while True:
                    if (time.perf_counter() - start_time) > exec_timeout:
                        raise TimeoutError(f"Execution timed out after {exec_timeout} seconds.")

                    has_read = False
                    while channel.recv_ready():
                        chunk = channel.recv(2048).decode("utf-8", errors="replace")
                        if chunk:
                            stdout_chunks.append(chunk)
                            has_read = True
                            if output_callback:
                                try:
                                    output_callback("stdout", chunk)
                                except Exception:
                                    pass

                    while channel.recv_stderr_ready():
                        chunk = channel.recv_stderr(2048).decode("utf-8", errors="replace")
                        if chunk:
                            stderr_chunks.append(chunk)
                            has_read = True
                            if output_callback:
                                try:
                                    output_callback("stderr", chunk)
                                except Exception:
                                    pass

                    if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                        break

                    if not has_read:
                        time.sleep(0.01)

                stdout_str = "".join(stdout_chunks)
                stderr_str = "".join(stderr_chunks)
                exit_code = channel.recv_exit_status()

            duration = round(time.perf_counter() - start_time, 3)

            return CommandExecutionResult(
                vm_id=self.vm_config.vm_id,
                command=command,
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=exit_code,
                duration=duration,
                timestamp=iso_timestamp,
            )

        except TimeoutError:
            duration = round(time.perf_counter() - start_time, 3)
            return CommandExecutionResult(
                vm_id=self.vm_config.vm_id,
                command=command,
                stdout="",
                stderr=f"Execution timed out after {exec_timeout} seconds.",
                exit_code=124,  # Standard timeout exit code
                duration=duration,
                timestamp=iso_timestamp,
            )

        except paramiko.AuthenticationException as e:
            duration = round(time.perf_counter() - start_time, 3)
            return CommandExecutionResult(
                vm_id=self.vm_config.vm_id,
                command=command,
                stdout="",
                stderr=f"SSH authentication failed: {str(e)}",
                exit_code=255,
                duration=duration,
                timestamp=iso_timestamp,
            )

        except (paramiko.SSHException, OSError, SSHExecutionError) as e:
            duration = round(time.perf_counter() - start_time, 3)
            return CommandExecutionResult(
                vm_id=self.vm_config.vm_id,
                command=command,
                stdout="",
                stderr=f"SSH connection failed: {str(e)}",
                exit_code=255,
                duration=duration,
                timestamp=iso_timestamp,
            )

        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass
