from io import BytesIO
from unittest.mock import MagicMock, patch
import pytest
import paramiko
from backend.schemas.vm import VMConfig, SSHAuthMethod
from backend.virtualization.ssh_client import VMSSHClient, SSHExecutionError


@pytest.fixture
def vm_config():
    return VMConfig(
        vm_id="vm-01",
        vm_provider="virtualbox",
        virtualbox_vm_name="cyberarena-vm-01",
        ssh_host="192.168.56.101",
        ssh_port=22,
        ssh_username="labuser",
        ssh_auth_method=SSHAuthMethod.PASSWORD,
        ssh_password_env="CYBERARENA_TEST_PW",
    )


def test_ssh_successful_execution(vm_config, monkeypatch):
    """Verify structured command result on successful execution."""
    monkeypatch.setenv("CYBERARENA_TEST_PW", "valid_pass")
    ssh_client = VMSSHClient(vm_config=vm_config)

    mock_client = MagicMock()
    mock_channel = MagicMock()
    mock_channel.recv_exit_status.return_value = 0

    mock_stdout = MagicMock()
    mock_stdout.read.return_value = b"Linux cyberarena-vm-01 6.8.0-generic x86_64\n"
    mock_stdout.channel = mock_channel

    mock_stderr = MagicMock()
    mock_stderr.read.return_value = b""

    mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

    with patch.object(ssh_client, "_create_client", return_value=(mock_client, {"hostname": "192.168.56.101"})):
        result = ssh_client.execute_command("uname -a")

    assert result.vm_id == "vm-01"
    assert result.command == "uname -a"
    assert "Linux cyberarena-vm-01" in result.stdout
    assert result.stderr == ""
    assert result.exit_code == 0
    assert result.duration >= 0.0
    assert result.timestamp is not None


def test_ssh_command_failure_exit_code(vm_config, monkeypatch):
    """Verify non-zero exit code and stderr capture."""
    monkeypatch.setenv("CYBERARENA_TEST_PW", "valid_pass")
    ssh_client = VMSSHClient(vm_config=vm_config)

    mock_client = MagicMock()
    mock_channel = MagicMock()
    mock_channel.recv_exit_status.return_value = 2

    mock_stdout = MagicMock()
    mock_stdout.read.return_value = b""
    mock_stdout.channel = mock_channel

    mock_stderr = MagicMock()
    mock_stderr.read.return_value = b"cat: /etc/fakefile: No such file or directory\n"

    mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

    with patch.object(ssh_client, "_create_client", return_value=(mock_client, {"hostname": "192.168.56.101"})):
        result = ssh_client.execute_command("cat /etc/fakefile")

    assert result.exit_code == 2
    assert "No such file or directory" in result.stderr


def test_ssh_timeout_handling(vm_config, monkeypatch):
    """Verify TimeoutError returns structured error result."""
    monkeypatch.setenv("CYBERARENA_TEST_PW", "valid_pass")
    ssh_client = VMSSHClient(vm_config=vm_config)

    mock_client = MagicMock()
    mock_client.connect.side_effect = TimeoutError("Connection timed out")

    with patch.object(ssh_client, "_create_client", return_value=(mock_client, {"hostname": "192.168.56.101"})):
        result = ssh_client.execute_command("sleep 100", timeout=2)

    assert result.exit_code == 124
    assert "timed out" in result.stderr


def test_ssh_authentication_failure(vm_config, monkeypatch):
    """Verify AuthenticationException returns structured error result."""
    monkeypatch.setenv("CYBERARENA_TEST_PW", "wrong_pass")
    ssh_client = VMSSHClient(vm_config=vm_config)

    mock_client = MagicMock()
    mock_client.connect.side_effect = paramiko.AuthenticationException("Permission denied")

    with patch.object(ssh_client, "_create_client", return_value=(mock_client, {"hostname": "192.168.56.101"})):
        result = ssh_client.execute_command("whoami")

    assert result.exit_code == 255
    assert "authentication failed" in result.stderr.lower()


def test_ssh_missing_credential_raises_structured_error(vm_config, monkeypatch):
    """Verify missing password in environment raises clean error without crash."""
    monkeypatch.delenv("CYBERARENA_TEST_PW", raising=False)
    monkeypatch.delenv("CYBERARENA_PASSWORD_VM_01", raising=False)

    ssh_client = VMSSHClient(vm_config=vm_config)
    result = ssh_client.execute_command("whoami")
    assert result.exit_code == 255
    assert "Authentication error" in result.stderr
