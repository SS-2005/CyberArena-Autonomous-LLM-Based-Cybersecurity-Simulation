"""
Live verification script for Phase 3 privileged tools and agent execution on real VMs.
"""
import os
import sys
import logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()

from backend.services.vm_service import VMService
from backend.tools.registry import default_tool_registry
from backend.tools.privileged import (
    InstallPackageTool,
    RestartServiceTool,
    ModifySystemConfigTool,
    CreateUserTool,
)
from backend.tools.builtin import ExecuteCommandTool
from backend.services.llm_service import LLMService
from backend.agents.agent import Agent
from backend.schemas.agent import AgentStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("real_verification")

def main():
    logger.info("Initializing VM Service...")
    vm_service = VMService()
    provider = vm_service.provider

    # 1. Check VM-01 & VM-02 connectivity
    for vm_id in ["vm-01", "vm-02"]:
        logger.info(f"Checking health of {vm_id}...")
        health = vm_service.health_check(vm_id)
        logger.info(f"Health of {vm_id}: running={health.is_running}, ssh={health.ssh_reachable}, latency={health.latency_ms}ms")
        if not health.ssh_reachable:
            logger.error(f"{vm_id} SSH not reachable!")
            return 1

    # 2. Test restart_service on vm-01
    logger.info("Testing RestartServiceTool on vm-01 for 'ssh'...")
    rst_tool = RestartServiceTool()
    rst_res = rst_tool.execute(provider, "vm-01", service_name="ssh")
    logger.info(f"Restart service result: success={rst_res.success}, output={rst_res.output}")
    assert rst_res.success, f"Restart service failed: {rst_res.error}"

    # 3. Test modify_system_config on vm-01
    logger.info("Testing ModifySystemConfigTool on vm-01...")
    cfg_tool = ModifySystemConfigTool()
    cfg_res = cfg_tool.execute(
        provider,
        "vm-01",
        target="/etc/sysctl.d/99-cyberarena.conf",
        operation="set",
        value="net.ipv4.ip_forward=1",
    )
    logger.info(f"Modify system config result: success={cfg_res.success}, output={cfg_res.output}")
    assert cfg_res.success, f"Modify config failed: {cfg_res.error}"

    # 4. Test security protections on ExecuteCommandTool
    logger.info("Testing security rejections on ExecuteCommandTool...")
    cmd_tool = ExecuteCommandTool()
    # 4a. Password injection attempt
    pwd_res = cmd_tool.execute(provider, "vm-01", command="echo 'your_password' | sudo -S ls /root")
    assert not pwd_res.success, "Password injection was not rejected!"
    assert pwd_res.metadata["error_type"] == "password_injection_rejected"
    logger.info(f"Password injection rejection verified: {pwd_res.error}")

    # 4b. Arbitrary sudo rejection
    sudo_res = cmd_tool.execute(provider, "vm-01", command="sudo cat /etc/shadow")
    assert not sudo_res.success, "Arbitrary sudo was not rejected!"
    assert sudo_res.metadata["error_type"] == "arbitrary_privileged_shell_rejected"
    logger.info(f"Arbitrary sudo rejection verified: {sudo_res.error}")

    # 5. Test real agent with local Ollama
    logger.info("Testing Real Agent with local Ollama on vm-01...")
    llm_service = LLMService()
    health = llm_service.get_health()
    logger.info(f"Ollama health: {health}")
    if getattr(health, "status", None) != "healthy" and getattr(health, "available", None) is not True:
        logger.warning("Ollama is not healthy, skipping real LLM test")
        return 0

    agent = Agent(
        agent_id="real-test-agent",
        role="Audit the network configuration of the VM and check active network interfaces and routing table.",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=llm_service,
        vm_provider=provider,
        iteration_limit=3,
    )
    logger.info(f"Running agent '{agent.agent_id}' for up to 3 iterations...")
    final_state = agent.run_all()
    logger.info(f"Agent finished with status: {final_state.status}")
    logger.info(f"Agent iterations completed: {final_state.current_iteration}/{final_state.iteration_limit}")
    logger.info(f"Agent history steps: {len(final_state.history)}")
    if final_state.structured_conclusion:
        logger.info(f"Structured conclusion status: {final_state.structured_conclusion.status}")
        logger.info(f"Findings: {final_state.structured_conclusion.findings}")
        logger.info(f"Evidence: {final_state.structured_conclusion.evidence}")
        logger.info(f"Errors: {final_state.structured_conclusion.errors}")
        logger.info(f"Summary: {final_state.structured_conclusion.summary}")
    else:
        logger.warning(f"No structured conclusion generated; final_conclusion={final_state.final_conclusion}")

    logger.info("=== ALL REAL VM INTEGRATION CHECKS PASSED ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
