import pytest
from unittest.mock import MagicMock

from backend.virtualization.base import VMProvider, CommandExecutionResult
from backend.tools.builtin import (
    ExecuteCommandTool,
    ReadFileTool,
    WriteFileTool,
    ListDirectoryTool,
    ProcessInfoTool,
    ServiceStatusTool,
    NetworkInfoTool,
)
from backend.tools.registry import ToolRegistry


@pytest.fixture
def mock_vm_provider():
    provider = MagicMock(spec=VMProvider)
    # Default to successful response
    provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="test",
        exit_code=0,
        stdout="success_output\n",
        stderr="",
        duration=0.05,
    )
    return provider


def test_execute_command_tool(mock_vm_provider):
    tool = ExecuteCommandTool()

    # Empty command validation
    res = tool.execute(mock_vm_provider, "vm-01", command="")
    assert res.success is False
    assert "non-empty" in res.error

    # Normal command
    res = tool.execute(mock_vm_provider, "vm-01", command="whoami")
    assert res.success is True
    assert res.output == "success_output\n"
    mock_vm_provider.execute_command.assert_called_with("vm-01", "whoami")

    # Command error exit code handling
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="invalid_cmd",
        exit_code=127,
        stdout="",
        stderr="command not found",
        duration=0.02,
    )
    res = tool.execute(mock_vm_provider, "vm-01", command="invalid_cmd")
    assert res.success is False
    assert "command not found" in res.error
    assert res.metadata["exit_code"] == 127


def test_read_file_tool(mock_vm_provider):
    tool = ReadFileTool()

    # Validation
    res = tool.execute(mock_vm_provider, "vm-01", path="")
    assert res.success is False

    # Valid read
    tool.execute(mock_vm_provider, "vm-01", path="/etc/os-release", lines=10)
    mock_vm_provider.execute_command.assert_called_with("vm-01", "head -n 10 /etc/os-release")


def test_write_file_tool(mock_vm_provider):
    tool = WriteFileTool()

    # Validation
    res = tool.execute(mock_vm_provider, "vm-01", path="", content="data")
    assert res.success is False

    # Valid write using base64 transfer
    res = tool.execute(mock_vm_provider, "vm-01", path="/tmp/test.txt", content="hello world\nline2")
    assert res.success is True
    call_args = mock_vm_provider.execute_command.call_args[0]
    assert call_args[0] == "vm-01"
    assert "base64 -d" in call_args[1]
    assert "> /tmp/test.txt" in call_args[1]


def test_list_directory_tool(mock_vm_provider):
    tool = ListDirectoryTool()
    tool.execute(mock_vm_provider, "vm-01", path="/var/log")
    mock_vm_provider.execute_command.assert_called_with("vm-01", "ls -la /var/log")


def test_process_info_tool(mock_vm_provider):
    tool = ProcessInfoTool()
    # Unfiltered
    tool.execute(mock_vm_provider, "vm-01")
    mock_vm_provider.execute_command.assert_called_with("vm-01", "ps aux --sort=-%mem | head -n 30")

    # Filtered
    tool.execute(mock_vm_provider, "vm-01", filter="ssh")
    mock_vm_provider.execute_command.assert_called_with("vm-01", "ps aux | grep -i ssh | grep -v grep")


def test_service_status_tool(mock_vm_provider):
    tool = ServiceStatusTool()
    tool.execute(mock_vm_provider, "vm-01", service_name="ssh")
    mock_vm_provider.execute_command.assert_called_with("vm-01", "systemctl status ssh --no-pager")


def test_network_info_tool(mock_vm_provider):
    tool = NetworkInfoTool()
    # Interfaces
    tool.execute(mock_vm_provider, "vm-01", info_type="interfaces")
    mock_vm_provider.execute_command.assert_called_with("vm-01", "ip -4 addr")

    # Ports
    tool.execute(mock_vm_provider, "vm-01", info_type="ports")
    mock_vm_provider.execute_command.assert_called_with("vm-01", "ss -tuln")

    # Routes
    tool.execute(mock_vm_provider, "vm-01", info_type="routes")
    mock_vm_provider.execute_command.assert_called_with("vm-01", "ip route")


def test_tool_registry_dispatch(mock_vm_provider):
    registry = ToolRegistry()
    assert "execute_command" in registry.list_tool_names()
    assert "network_info" in registry.list_tool_names()

    # Unknown tool
    res = registry.execute("non_existent_tool", mock_vm_provider, "vm-01", {})
    assert res.success is False
    assert "not recognized" in res.error

    # Known tool
    res = registry.execute("execute_command", mock_vm_provider, "vm-01", {"command": "uname -a"})
    assert res.success is True
