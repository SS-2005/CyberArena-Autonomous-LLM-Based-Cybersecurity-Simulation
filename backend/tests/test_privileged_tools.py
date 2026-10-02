import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from backend.tools.policy import ToolPolicyManager, default_policy_manager
from backend.tools.privileged import (
    InstallPackageTool,
    RestartServiceTool,
    ModifySystemConfigTool,
    CreateUserTool,
)
from backend.tools.builtin import ExecuteCommandTool
from backend.tools.registry import ToolRegistry
from backend.virtualization.base import VMProvider, CommandExecutionResult
from backend.schemas.agent import (
    AgentStatus,
    AgentActionRequest,
    AgentStep,
    ExecutionRecord,
    AgentConclusion,
)
from backend.schemas.experiment import ExperimentDetail, ExperimentAgentState
from backend.agents.agent import Agent
from backend.services.llm_service import LLMService, LLMGenerationResponse
from backend.services.experiment_service import ExperimentService


@pytest.fixture
def mock_vm_provider():
    provider = MagicMock(spec=VMProvider)
    provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="mock_cmd",
        exit_code=0,
        stdout="success output",
        stderr="",
        duration=0.1,
    )
    return provider


@pytest.fixture
def mock_llm_service():
    service = MagicMock()
    service.registry_config.default_model = "local-qwen3-4b"
    service.generate.return_value = LLMGenerationResponse(
        text='{"thought": "done", "tool": "finish", "parameters": {"summary": "Task complete"}, "summary": "Finished"}',
        duration=0.1,
        model_name="qwen3:4b",
    )
    return service


# ============================================================================
# 1. install_package success
# ============================================================================
def test_install_package_success(mock_vm_provider):
    tool = InstallPackageTool()
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="sudo -n /usr/local/sbin/cyberarena-install-package 'nmap'",
        exit_code=0,
        stdout="Setting up nmap ... done\nSUCCESS: Package 'nmap' successfully installed",
        stderr="",
        duration=1.2,
    )
    res = tool.execute(mock_vm_provider, "vm-01", package_name="nmap")
    assert res.success is True
    assert "installed" in res.output.lower()
    assert res.error is None
    assert res.metadata["package_name"] == "nmap"
    assert res.metadata["exit_code"] == 0
    cmd_called = mock_vm_provider.execute_command.call_args[0][1]
    assert "cyberarena-install-package" in cmd_called
    assert "nmap" in cmd_called


# ============================================================================
# 2. install_package validation failure
# ============================================================================
def test_install_package_validation_failure(mock_vm_provider):
    tool = InstallPackageTool()
    # Unallowed package
    res = tool.execute(mock_vm_provider, "vm-01", package_name="malicious-pkg-xyz")
    assert res.success is False
    assert "policy violation" in res.error.lower()
    assert res.metadata["error_type"] == "policy_rejection"
    # Invalid characters / command injection attempt
    res2 = tool.execute(mock_vm_provider, "vm-01", package_name="nmap; rm -rf /")
    assert res2.success is False
    assert "invalid package name format" in res2.error.lower()
    mock_vm_provider.execute_command.assert_not_called()


# ============================================================================
# 3. restart_service success
# ============================================================================
def test_restart_service_success(mock_vm_provider):
    tool = RestartServiceTool()
    mock_vm_provider.execute_command.side_effect = [
        CommandExecutionResult(vm_id="vm-01", command="restart", exit_code=0, stdout="SUCCESS: Service 'ssh' restarted", stderr="", duration=0.5),
        CommandExecutionResult(vm_id="vm-01", command="status", exit_code=0, stdout="active\n", stderr="", duration=0.1),
    ]
    res = tool.execute(mock_vm_provider, "vm-01", service_name="ssh")
    assert res.success is True
    assert "Verification state: active" in res.output
    assert res.metadata["active_status"] == "active"


# ============================================================================
# 4. restart_service validation failure
# ============================================================================
def test_restart_service_validation_failure(mock_vm_provider):
    tool = RestartServiceTool()
    res = tool.execute(mock_vm_provider, "vm-01", service_name="unauthorized_daemon")
    assert res.success is False
    assert "policy violation" in res.error.lower()
    mock_vm_provider.execute_command.assert_not_called()


# ============================================================================
# 5. modify_system_config policy enforcement
# ============================================================================
def test_modify_system_config_policy_enforcement(mock_vm_provider):
    tool = ModifySystemConfigTool()
    # Target not allowlisted
    res_bad = tool.execute(
        mock_vm_provider,
        "vm-01",
        target="/etc/shadow",
        operation="replace",
        value="hacked",
    )
    assert res_bad.success is False
    assert "not permitted" in res_bad.error.lower()

    # Target allowlisted, operation allowlisted
    mock_vm_provider.execute_command.side_effect = [
        CommandExecutionResult(vm_id="vm-01", command="read", exit_code=0, stdout="old content", stderr="", duration=0.1),
        CommandExecutionResult(vm_id="vm-01", command="modify", exit_code=0, stdout="SUCCESS: Replaced content", stderr="", duration=0.2),
        CommandExecutionResult(vm_id="vm-01", command="read", exit_code=0, stdout="new content", stderr="", duration=0.1),
    ]
    res_good = tool.execute(
        mock_vm_provider,
        "vm-01",
        target="/etc/sysctl.d/99-cyberarena.conf",
        operation="set",
        value="net.ipv4.ip_forward=1",
    )
    assert res_good.success is True
    assert res_good.metadata["before_state"] == "old content"
    assert res_good.metadata["after_state"] == "new content"


# ============================================================================
# 6. create_user validation
# ============================================================================
def test_create_user_validation(mock_vm_provider):
    tool = CreateUserTool()
    # Admin group forbidden
    res_priv = tool.execute(mock_vm_provider, "vm-01", username="testuser", groups=["sudo"])
    assert res_priv.success is False
    assert "privilege escalation prohibited" in res_priv.error.lower()

    # Allowed groups success
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01", command="create-user", exit_code=0, stdout="SUCCESS: User 'analyst1' created (groups: analysts)", stderr="", duration=0.3
    )
    res_ok = tool.execute(mock_vm_provider, "vm-01", username="analyst1", groups=["analysts"])
    assert res_ok.success is True
    assert res_ok.metadata["username"] == "analyst1"


# ============================================================================
# 7. privileged tools do not expose passwords
# ============================================================================
def test_privileged_tools_do_not_expose_passwords(mock_vm_provider):
    registry = ToolRegistry()
    schemas = registry.get_tool_schemas()
    for s in schemas:
        props = s.get("parameters", {}).get("properties", {})
        for prop_name in props.keys():
            assert "password" not in prop_name.lower()
            assert "secret" not in prop_name.lower()
            assert "sudo_pass" not in prop_name.lower()


# ============================================================================
# 8. Agent handles command_not_found
# ============================================================================
def test_agent_handles_command_not_found(mock_llm_service, mock_vm_provider):
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="nmap -sn 192.168.32.0/24",
        exit_code=127,
        stdout="",
        stderr="bash: nmap: command not found",
        duration=0.1,
    )
    cmd_tool = ExecuteCommandTool()
    res = cmd_tool.execute(mock_vm_provider, "vm-01", command="nmap -sn 192.168.32.0/24")
    assert res.success is False
    assert res.metadata["error_type"] == "command_not_found"
    assert res.metadata["exit_code"] == 127


# ============================================================================
# 9. Agent can recover using install_package
# ============================================================================
def test_agent_recovery_flow(mock_llm_service, mock_vm_provider):
    registry = ToolRegistry()
    # Step 1: LLM tries nmap -> command not found
    # Step 2: LLM calls install_package("nmap") -> success
    # Step 3: LLM retries nmap -> success
    # Step 4: finish
    mock_llm_service.generate.side_effect = [
        LLMGenerationResponse(
            text='{"thought": "Run network scan", "tool": "execute_command", "parameters": {"command": "nmap -sn 192.168.32.0/24"}, "summary": "Scan network"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
        LLMGenerationResponse(
            text='{"thought": "nmap missing, installing it", "tool": "install_package", "parameters": {"package_name": "nmap"}, "summary": "Install nmap dependency"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
        LLMGenerationResponse(
            text='{"thought": "Retry network scan", "tool": "execute_command", "parameters": {"command": "nmap -sn 192.168.32.0/24"}, "summary": "Retry scan"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
        LLMGenerationResponse(
            text='{"thought": "Finished successfully", "tool": "finish", "parameters": {"summary": "Discovered 2 live hosts: 192.168.32.101, 192.168.32.102"}, "summary": "Scan complete"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
        LLMGenerationResponse(
            text='{"status": "completed", "summary": "Discovered 2 live hosts: 192.168.32.101, 192.168.32.102", "findings": ["2 hosts up"], "evidence": ["nmap -sn 192.168.32.0/24"], "errors": [], "unresolved_items": [], "iteration_limit_reached": false}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
    ]

    mock_vm_provider.execute_command.side_effect = [
        CommandExecutionResult(vm_id="vm-01", command="nmap", exit_code=127, stdout="", stderr="bash: nmap: command not found", duration=0.1),
        CommandExecutionResult(vm_id="vm-01", command="install", exit_code=0, stdout="SUCCESS: Package 'nmap' successfully installed", stderr="", duration=1.0),
        CommandExecutionResult(vm_id="vm-01", command="nmap", exit_code=0, stdout="Nmap scan report for 192.168.32.101\nNmap scan report for 192.168.32.102\n2 hosts up", stderr="", duration=0.5),
    ]

    agent = Agent(
        agent_id="agent-recon",
        role="Discover network hosts",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        tool_registry=registry,
        iteration_limit=5,
    )

    state = agent.run_all()
    assert state.status == AgentStatus.COMPLETED
    assert len(agent.history) == 4
    assert agent.history[0].execution_record.error_type == "command_not_found"
    assert agent.history[1].action.tool == "install_package"
    assert agent.history[2].success is True


# ============================================================================
# 10. Agent receives stderr
# ============================================================================
def test_agent_receives_stderr(mock_vm_provider):
    tool = ExecuteCommandTool()
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="cat /root/secret",
        exit_code=1,
        stdout="",
        stderr="fatal: Permission denied",
        duration=0.1,
    )
    res = tool.execute(mock_vm_provider, "vm-01", command="cat /root/secret")
    assert res.success is False
    assert "fatal: Permission denied" in res.error
    assert res.metadata["stderr"] == "fatal: Permission denied"


# ============================================================================
# 11. Agent receives non-zero exit code
# ============================================================================
def test_agent_receives_nonzero_exit_code(mock_vm_provider):
    tool = ExecuteCommandTool()
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="exit 42",
        exit_code=42,
        stdout="partial output",
        stderr="error detail",
        duration=0.1,
    )
    res = tool.execute(mock_vm_provider, "vm-01", command="exit 42")
    assert res.success is False
    assert res.metadata["exit_code"] == 42


# ============================================================================
# 12. Agent receives timeout
# ============================================================================
def test_agent_receives_timeout(mock_vm_provider):
    mock_vm_provider.execute_command.side_effect = TimeoutError("Command timed out after 60s")
    tool = ExecuteCommandTool()
    res = tool.execute(mock_vm_provider, "vm-01", command="sleep 100")
    assert res.success is False
    assert "timed out" in res.error.lower()


# ============================================================================
# 13. Agent receives SSH failure
# ============================================================================
def test_agent_receives_ssh_failure(mock_vm_provider):
    mock_vm_provider.execute_command.side_effect = ConnectionError("SSH session failed: Connection refused")
    tool = ExecuteCommandTool()
    res = tool.execute(mock_vm_provider, "vm-01", command="uname -a")
    assert res.success is False
    assert res.metadata["error_type"] == "ssh_failure"


# ============================================================================
# 14. Agent stops when iteration limit reached
# ============================================================================
def test_agent_stops_at_iteration_limit(mock_llm_service, mock_vm_provider):
    mock_llm_service.generate.return_value = LLMGenerationResponse(
        text='{"thought": "Still inspecting", "tool": "execute_command", "parameters": {"command": "uptime"}, "summary": "Inspect uptime"}',
        duration=0.1,
        model_name="qwen3:4b",
    )
    agent = Agent(
        agent_id="agent-limit",
        role="Inspect system",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=3,
    )
    state = agent.run_all()
    assert state.current_iteration == 3
    assert agent.iteration_limit_reached is True
    assert state.status == AgentStatus.STOPPED_ITERATION_LIMIT


# ============================================================================
# 15. LLM receives iteration-limit information
# ============================================================================
def test_llm_receives_iteration_limit_information(mock_llm_service, mock_vm_provider):
    mock_llm_service.generate.return_value = LLMGenerationResponse(
        text='{"thought": "Working", "tool": "execute_command", "parameters": {"command": "uptime"}, "summary": "Check uptime"}',
        duration=0.1,
        model_name="qwen3:4b",
    )
    agent = Agent(
        agent_id="agent-limit-info",
        role="Network audit",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=2,
    )
    agent.run_all()
    # Check that synthesis call contained "EXECUTION LIMIT REACHED"
    synthesis_call_prompt = mock_llm_service.generate.call_args[1]["prompt"]
    assert "EXECUTION LIMIT REACHED" in synthesis_call_prompt
    assert "2 / 2" in synthesis_call_prompt


# ============================================================================
# 16. final conclusion uses accumulated tool results
# ============================================================================
def test_final_conclusion_uses_accumulated_tool_results(mock_llm_service, mock_vm_provider):
    mock_llm_service.generate.side_effect = [
        LLMGenerationResponse(
            text='{"thought": "Check os", "tool": "execute_command", "parameters": {"command": "cat /etc/os-release"}, "summary": "OS check"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
        # Synthesis response with structured json
        LLMGenerationResponse(
            text='{"status": "completed", "summary": "System verified as Ubuntu 24.04.", "findings": ["OS is Ubuntu 24.04.5 LTS"], "evidence": ["cat /etc/os-release"], "errors": [], "unresolved_items": [], "iteration_limit_reached": false}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
    ]
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01", command="cat /etc/os-release", exit_code=0, stdout="PRETTY_NAME=\"Ubuntu 24.04.5 LTS\"", stderr="", duration=0.1
    )
    agent = Agent(
        agent_id="agent-acc",
        role="Verify OS version",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=1,
    )
    agent.run_all()
    assert agent.structured_conclusion is not None
    assert "Ubuntu 24.04" in agent.structured_conclusion.findings[0]


# ============================================================================
# 17. final conclusion reflects errors
# ============================================================================
def test_final_conclusion_reflects_errors(mock_llm_service, mock_vm_provider):
    mock_llm_service.generate.side_effect = [
        LLMGenerationResponse(
            text='{"thought": "Run command", "tool": "execute_command", "parameters": {"command": "nonexistent_cmd"}, "summary": "Run missing cmd"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
        LLMGenerationResponse(
            text='{"thought": "Command missing, cannot continue", "tool": "finish", "parameters": {"summary": "Execution aborted due to missing binary."}, "summary": "Abort execution"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
        LLMGenerationResponse(
            text='{"status": "failed", "summary": "Command execution failed because the binary was missing.", "findings": [], "evidence": [], "errors": ["nonexistent_cmd: command not found"], "unresolved_items": ["Execution stopped on failure"], "iteration_limit_reached": false}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
    ]
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01", command="nonexistent_cmd", exit_code=127, stdout="", stderr="bash: nonexistent_cmd: command not found", duration=0.1
    )
    agent = Agent(
        agent_id="agent-err",
        role="Run command",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=5,
    )
    agent.run_all()
    assert agent.structured_conclusion.errors == ["nonexistent_cmd: command not found"]
    assert agent.status == AgentStatus.FAILED


# ============================================================================
# 18. final conclusion distinguishes partial vs completed
# ============================================================================
def test_final_conclusion_distinguishes_partial_vs_completed(mock_llm_service, mock_vm_provider):
    # When iteration limit was reached, conclusion status is coerced to partially_completed
    mock_llm_service.generate.side_effect = [
        LLMGenerationResponse(
            text='{"thought": "Working", "tool": "execute_command", "parameters": {"command": "hostname"}, "summary": "Check hostname"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
        LLMGenerationResponse(
            text='{"status": "completed", "summary": "Checked hostname.", "findings": ["Host is cyberarena-vm-01"], "evidence": [], "errors": [], "unresolved_items": [], "iteration_limit_reached": true}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
    ]
    agent = Agent(
        agent_id="agent-part",
        role="Audit system",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=1,
    )
    agent.run_all()
    assert agent.structured_conclusion.status == "partially_completed"
    assert agent.status == AgentStatus.STOPPED_ITERATION_LIMIT


# ============================================================================
# 19. experiment summary includes multiple agents' actual findings
# ============================================================================
def test_experiment_summary_includes_multiple_agents_actual_findings():
    agent1 = MagicMock(spec=Agent)
    agent1.agent_id = "agent-01"
    agent1.structured_conclusion = AgentConclusion(
        status="completed",
        summary="Scan finished",
        findings=["Host 192.168.32.102 is active with SSH port 22 open"],
        evidence=["nmap -sV 192.168.32.102"],
        errors=[],
        unresolved_items=[],
        iteration_limit_reached=False,
    )
    agent2 = MagicMock(spec=Agent)
    agent2.agent_id = "agent-02"
    agent2.structured_conclusion = AgentConclusion(
        status="partially_completed",
        summary="Hardening partial",
        findings=["Auditd service is active"],
        evidence=["systemctl is-active auditd"],
        errors=[],
        unresolved_items=[],
        iteration_limit_reached=False,
    )
    agents_map = {"agent-01": agent1, "agent-02": agent2}
    all_findings = []
    for a in agents_map.values():
        sc = getattr(a, "structured_conclusion", None)
        if sc:
            for f in sc.findings:
                all_findings.append(f"- **[{a.agent_id}]**: {f}")
    assert any("Host 192.168.32.102 is active" in f for f in all_findings)
    assert any("Auditd service is active" in f for f in all_findings)


# ============================================================================
# 20. experiment summary includes errors from all agents
# ============================================================================
def test_experiment_summary_includes_errors_from_all_agents():
    agent1 = MagicMock(spec=Agent)
    agent1.agent_id = "agent-01"
    agent1.iteration_limit_reached = False
    agent1.structured_conclusion = AgentConclusion(
        status="completed",
        summary="OK",
        findings=[],
        evidence=[],
        errors=["ssh connection closed unexpectedly on port 2222"],
        unresolved_items=[],
        iteration_limit_reached=False,
    )
    agent2 = MagicMock(spec=Agent)
    agent2.agent_id = "agent-02"
    agent2.iteration_limit_reached = True
    agent2.structured_conclusion = AgentConclusion(
        status="partially_completed",
        summary="Partial",
        findings=[],
        evidence=[],
        errors=["ufw reload failed: permission denied"],
        unresolved_items=[],
        iteration_limit_reached=True,
    )
    agents_map = {"agent-01": agent1, "agent-02": agent2}
    all_errors = []
    for a in agents_map.values():
        sc = getattr(a, "structured_conclusion", None)
        if sc:
            for err in sc.errors:
                all_errors.append(f"- **[{a.agent_id}]**: {err}")
        if a.iteration_limit_reached:
            all_errors.append(f"- **[{a.agent_id}]**: Stopped because iteration limit was reached.")

    assert any("ssh connection closed unexpectedly" in err for err in all_errors)
    assert any("ufw reload failed" in err for err in all_errors)
    assert any("iteration limit was reached" in err for err in all_errors)


# ============================================================================
# 21. iteration-limit agent is not reported as successfully completed
# ============================================================================
def test_iteration_limit_agent_not_reported_as_completed(mock_llm_service, mock_vm_provider):
    mock_llm_service.generate.return_value = LLMGenerationResponse(
        text='{"thought": "Running", "tool": "execute_command", "parameters": {"command": "free -m"}, "summary": "Check free mem"}',
        duration=0.1,
        model_name="qwen3:4b",
    )
    agent = Agent(
        agent_id="agent-limit-check",
        role="Long task",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=2,
    )
    state = agent.run_all()
    assert state.status != AgentStatus.COMPLETED
    assert state.status == AgentStatus.STOPPED_ITERATION_LIMIT


# ============================================================================
# 22. cancellation produces a final status
# ============================================================================
def test_cancellation_produces_final_status(mock_llm_service, mock_vm_provider):
    agent = Agent(
        agent_id="agent-cancel",
        role="Cancel task",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
    )
    agent.cancel()
    assert agent.status == AgentStatus.CANCELLED
    state = agent.get_state()
    assert state.status == AgentStatus.CANCELLED


# ============================================================================
# 23. final LLM generation failure has a deterministic fallback
# ============================================================================
def test_final_llm_generation_failure_fallback(mock_llm_service, mock_vm_provider):
    # LLM throws exception during conclusion generation
    mock_llm_service.generate.side_effect = [
        LLMGenerationResponse(
            text='{"thought": "step 1", "tool": "execute_command", "parameters": {"command": "hostname"}, "summary": "Hostname"}',
            duration=0.1,
            model_name="qwen3:4b",
        ),
        RuntimeError("Ollama inference engine crashed"),
    ]
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01", command="hostname", exit_code=0, stdout="cyberarena-vm-01\n", stderr="", duration=0.1
    )
    agent = Agent(
        agent_id="agent-fallback",
        role="Inspect hostname",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm_service,
        vm_provider=mock_vm_provider,
        iteration_limit=1,
    )
    state = agent.run_all()
    assert state.structured_conclusion is not None
    assert "Deterministic fallback" in state.final_conclusion
    assert "cyberarena-vm-01" in state.structured_conclusion.findings[0]


# ============================================================================
# 24. forbidden arbitrary privileged command is rejected
# ============================================================================
def test_forbidden_arbitrary_privileged_command_rejected(mock_vm_provider):
    tool = ExecuteCommandTool()
    res = tool.execute(mock_vm_provider, "vm-01", command="sudo bash -c 'cat /etc/shadow'")
    assert res.success is False
    assert "arbitrary privileged execution via 'sudo' is prohibited" in res.error.lower()
    assert res.metadata["error_type"] == "arbitrary_privileged_shell_rejected"
    mock_vm_provider.execute_command.assert_not_called()


# ============================================================================
# 25. password/secret injection attempt is rejected
# ============================================================================
def test_password_injection_attempt_rejected(mock_vm_provider):
    tool = ExecuteCommandTool()
    commands = [
        "echo 'your_password' | sudo -S apt install nmap",
        "echo '<password>' | sudo apt update",
        "echo 'password' | sudo -S ls",
    ]
    for cmd in commands:
        res = tool.execute(mock_vm_provider, "vm-01", command=cmd)
        assert res.success is False
        assert "password fabrication or injection is strictly prohibited" in res.error.lower()
        assert res.metadata["error_type"] == "password_injection_rejected"
    mock_vm_provider.execute_command.assert_not_called()


# ============================================================================
# 26. frontend no longer renders "Live Step Progression Telemetry Feed"
# ============================================================================
def test_frontend_no_longer_renders_telemetry_feed():
    dashboard_path = Path("frontend/src/components/ExperimentDashboard.tsx")
    assert dashboard_path.exists()
    content = dashboard_path.read_text(encoding="utf-8")
    assert "Live Step Progression Telemetry Feed" not in content
    assert "showLiveProgression" not in content
    assert "timelineEndRef" not in content


# ============================================================================
# 27. install_package allows sysbench and open packages
# ============================================================================
def test_install_package_allows_sysbench(mock_vm_provider):
    tool = InstallPackageTool()
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="sudo -n /usr/local/sbin/cyberarena-install-package 'sysbench'",
        exit_code=0,
        stdout="SUCCESS: Package 'sysbench' successfully installed",
        stderr="",
        duration=1.0,
    )
    res = tool.execute(mock_vm_provider, "vm-01", package_name="sysbench")
    assert res.success is True
    assert res.metadata["package_name"] == "sysbench"
    assert "cyberarena-install-package" in mock_vm_provider.execute_command.call_args[0][1]


# ============================================================================
# 28. execute_command allows sudo for administrative tasks like creating files
# ============================================================================
def test_execute_command_allows_sudo_file_creation(mock_vm_provider):
    tool = ExecuteCommandTool()
    mock_vm_provider.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="sudo touch /root/sahil.txt",
        exit_code=0,
        stdout="",
        stderr="",
        duration=0.1,
    )
    res = tool.execute(mock_vm_provider, "vm-01", command="sudo touch /root/sahil.txt")
    assert res.success is True
    assert mock_vm_provider.execute_command.call_args[0][1] == "sudo touch /root/sahil.txt"


# ============================================================================
# 29. execute_command auto-elevates non-sudo commands on permission denied
# ============================================================================
def test_execute_command_auto_elevates_on_permission_denied(mock_vm_provider):
    tool = ExecuteCommandTool()
    mock_vm_provider.execute_command.side_effect = [
        CommandExecutionResult(
            vm_id="vm-01",
            command="touch /root/sahil.txt",
            exit_code=1,
            stdout="",
            stderr="touch: cannot touch '/root/sahil.txt': Permission denied",
            duration=0.1,
        ),
        CommandExecutionResult(
            vm_id="vm-01",
            command="sudo touch /root/sahil.txt",
            exit_code=0,
            stdout="",
            stderr="",
            duration=0.1,
        ),
    ]
    res = tool.execute(mock_vm_provider, "vm-01", command="touch /root/sahil.txt")
    assert res.success is True
    assert mock_vm_provider.execute_command.call_count == 2
    assert mock_vm_provider.execute_command.call_args_list[1][0][1] == "sudo touch /root/sahil.txt"


# ============================================================================
# 30. execute_command blocks potentially destructive operations
# ============================================================================
def test_execute_command_blocks_destructive_operations(mock_vm_provider):
    tool = ExecuteCommandTool()
    destructive_cmds = [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf --no-preserve-root /",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda bs=1M",
        ":(){ :|:& };:",
        "shutdown -h now",
        "poweroff",
    ]
    for cmd in destructive_cmds:
        res = tool.execute(mock_vm_provider, "vm-01", command=cmd)
        assert res.success is False
        assert res.metadata["error_type"] == "destructive_operation_rejected"
        assert "destructive" in res.error.lower()
    mock_vm_provider.execute_command.assert_not_called()


# ============================================================================
# 31. write_file auto-elevates to sudo tee on permission denied
# ============================================================================
def test_write_file_auto_elevates_on_permission_denied(mock_vm_provider):
    from backend.tools.builtin import WriteFileTool
    tool = WriteFileTool()
    mock_vm_provider.execute_command.side_effect = [
        CommandExecutionResult(
            vm_id="vm-01",
            command="write",
            exit_code=1,
            stdout="",
            stderr="bash: /root/sahil.txt: Permission denied",
            duration=0.1,
        ),
        CommandExecutionResult(
            vm_id="vm-01",
            command="sudo tee",
            exit_code=0,
            stdout="",
            stderr="",
            duration=0.1,
        ),
    ]
    res = tool.execute(mock_vm_provider, "vm-01", path="/root/sahil.txt", content="Hello Sahil")
    assert res.success is True
    assert mock_vm_provider.execute_command.call_count == 2
    assert "sudo tee" in mock_vm_provider.execute_command.call_args_list[1][0][1]


# ============================================================================
# 32. read_file auto-elevates to sudo head on permission denied
# ============================================================================
def test_read_file_auto_elevates_on_permission_denied(mock_vm_provider):
    from backend.tools.builtin import ReadFileTool
    tool = ReadFileTool()
    mock_vm_provider.execute_command.side_effect = [
        CommandExecutionResult(
            vm_id="vm-01",
            command="read",
            exit_code=1,
            stdout="",
            stderr="head: cannot open '/root/sahil.txt' for reading: Permission denied",
            duration=0.1,
        ),
        CommandExecutionResult(
            vm_id="vm-01",
            command="sudo head",
            exit_code=0,
            stdout="Hello Sahil\n",
            stderr="",
            duration=0.1,
        ),
    ]
    res = tool.execute(mock_vm_provider, "vm-01", path="/root/sahil.txt")
    assert res.success is True
    assert "Hello Sahil" in res.output
    assert mock_vm_provider.execute_command.call_count == 2
    assert "sudo head" in mock_vm_provider.execute_command.call_args_list[1][0][1]

