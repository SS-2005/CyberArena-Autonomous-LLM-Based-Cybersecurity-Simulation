import pytest
from backend.services.vm_service import VMService
from backend.services.llm_service import LLMService
from backend.services.agent_service import AgentService
from backend.schemas.agent import AgentCreateRequest, AgentStatus
from backend.schemas.vm import VMState


def test_real_ollama_integration():
    """Verify real Ollama provider connectivity and model listing."""
    llm_service = LLMService()
    health = llm_service.get_health()
    if health.status != "healthy":
        pytest.skip(f"Local Ollama is not healthy: {health.message}")

    models = llm_service.list_models()
    available_models = [m for m in models if m.available]
    assert len(available_models) > 0, "No configured and installed models found in Ollama"
    assert any("qwen3" in m.model_name for m in available_models)


def test_real_agent_vm01_execution():
    """
    Execute a real generic autonomous agent against the live cyberarena-vm-01.
    Role: Harmless reconnaissance of system metrics.
    Enforces isolation, tool execution through VMProvider, and clean termination.
    """
    vm_service = VMService()
    llm_service = LLMService()

    # Pre-check Ollama health
    health = llm_service.get_health()
    if health.status != "healthy":
        pytest.skip(f"Ollama is unreachable: {health.message}")

    # Pre-check VM-01 state
    vm_state = vm_service.get_vm("vm-01").state
    if vm_state != VMState.RUNNING:
        pytest.skip(f"VM vm-01 is not running (state={vm_state}). Start vm-01 first.")

    agent_service = AgentService(llm_service=llm_service, vm_service=vm_service)

    req = AgentCreateRequest(
        role="Report the hostname, current user, operating system, and available memory of the assigned VM.",
        vm_id="vm-01",
        iteration_limit=4,
        command_timeout=120,
    )

    agent_state = agent_service.create_agent(req)
    agent_id = agent_state.agent_id
    assert agent_state.status == AgentStatus.IDLE

    # Run agent synchronously for integration verification
    final_state = agent_service.start_agent_sync(agent_id)

    # Verifications
    assert final_state.status in (AgentStatus.COMPLETED, AgentStatus.STOPPED, AgentStatus.STOPPED_ITERATION_LIMIT)
    assert final_state.current_iteration >= 1
    assert len(final_state.history) >= 1

    # Verify at least one tool was executed against vm-01
    successful_vm_steps = [
        s for s in final_state.history
        if s.success and s.action.tool in (
            "execute_command", "read_file", "process_info", "network_info", "service_status", "list_directory"
        )
    ]
    # Check that any VM step yielded real guest data
    assert len(successful_vm_steps) >= 1, "Agent did not execute any tool inside the VM successfully"
    combined_output = " ".join(s.observation for s in final_state.history)
    # Check for guest indicators (cyberarena-vm-01, labuser, Linux, or memory info)
    guest_indicators = ["cyberarena", "labuser", "linux", "ubuntu", "mem", "total", "kernel"]
    found = any(ind in combined_output.lower() for ind in guest_indicators)
    assert found, f"No guest indicators found in observations: {combined_output[:300]}"
