import asyncio
import json
import time
from datetime import datetime, timezone
import pytest

from backend.services.vm_service import VMService
from backend.services.llm_service import LLMService
from backend.services.experiment_service import ExperimentService
from backend.schemas.experiment import (
    ExperimentCreateRequest,
    ExperimentAgentConfig,
    ExperimentStatus,
)
from backend.db.repository import ExperimentRepository
from backend.db.database import get_database


@pytest.mark.asyncio
async def test_real_concurrent_experiment_execution():
    """
    Real Phase 3 Acceptance Verification:
    Executes a real 2-agent experiment against cyberarena-vm-01 and cyberarena-vm-02 simultaneously
    using host Ollama inference (qwen3:4b).
    Collects overlapping timestamps to verify concurrent execution.
    """
    vm_service = VMService()
    llm_service = LLMService()
    db = get_database()
    repo = ExperimentRepository(db)
    exp_service = ExperimentService(
        llm_service=llm_service,
        vm_service=vm_service,
        repository=repo,
    )

    # 1. Verify environment prerequisites
    vms = vm_service.list_vms()
    assert len(vms) >= 2, f"Need at least 2 VMs configured, found {len(vms)}"
    vm1 = next((v for v in vms if v.vm_id == "vm-01"), None)
    vm2 = next((v for v in vms if v.vm_id == "vm-02"), None)
    assert vm1 is not None and vm1.state == "running", "vm-01 must be running"
    assert vm2 is not None and vm2.state == "running", "vm-02 must be running"

    # Verify Ollama model
    models = llm_service.list_models()
    available_models = [m.model_name for m in models if m.available]
    assert any("qwen3:4b" in m for m in available_models), f"qwen3:4b must be available in Ollama: {available_models}"

    # 2. Build multi-agent experiment request
    req = ExperimentCreateRequest(
        name="Real Concurrent Lab Experiment Phase 3",
        description="Dual-node concurrent offensive reconnaissance and defensive audit",
        agents=[
            ExperimentAgentConfig(
                role="Offensive Reconnaissance: Check hostname, inspect current user with whoami, and check network addresses on the assigned VM. Call finish when done.",
                vm_id="vm-01",
                iteration_limit=3,
                command_timeout=120,
            ),
            ExperimentAgentConfig(
                role="Defensive Security Audit: Check hostname, inspect system uptime, and check running processes with ps aux on the assigned VM. Call finish when done.",
                vm_id="vm-02",
                iteration_limit=3,
                command_timeout=120,
            ),
        ],
    )

    # 3. Create experiment
    created_exp = exp_service.create_experiment(req)
    exp_id = created_exp.id
    print(f"\n[PHASE 3 VERIFICATION] Created Experiment: {exp_id}")
    print(f"  Agent 1 target VM: vm-01 ({vm1.ssh_host})")
    print(f"  Agent 2 target VM: vm-02 ({vm2.ssh_host})")

    # 4. Subscribe to events to collect timestamps
    recorded_events = []

    def event_collector(evt):
        recorded_events.append(evt)

    # 5. Start concurrent experiment
    t_start = time.time()
    op = await exp_service.start_experiment(exp_id)
    assert op.success is True
    print(f"[PHASE 3 VERIFICATION] Started concurrent execution at {datetime.now(timezone.utc).isoformat()}")

    # 6. Await completion of both agents
    task = exp_service._active_tasks.get(exp_id)
    assert task is not None
    await task
    t_end = time.time()
    total_duration = round(t_end - t_start, 2)
    print(f"[PHASE 3 VERIFICATION] Concurrent experiment finished in {total_duration}s")

    # 7. Fetch final detail from SQLite
    detail = exp_service.get_experiment(exp_id)
    assert detail.status in (ExperimentStatus.COMPLETED, ExperimentStatus.STOPPED)
    assert len(detail.agents) == 2

    ag1 = next(a for a in detail.agents if a.vm_id == "vm-01")
    ag2 = next(a for a in detail.agents if a.vm_id == "vm-02")

    print(f"\n=== AGENT 1 (vm-01: {vm1.ssh_host}) Results ===")
    print(f"Status: {ag1.status} | Iterations: {ag1.current_iteration} | Steps: {len(ag1.history)}")
    for s in ag1.history:
        print(f"  Step {s.step_number}: Tool='{s.action.tool}' Summary='{s.action.summary}' Time={s.timestamp}")
        print(f"  Output snippet: {s.observation[:120]}...")

    print(f"\n=== AGENT 2 (vm-02: {vm2.ssh_host}) Results ===")
    print(f"Status: {ag2.status} | Iterations: {ag2.current_iteration} | Steps: {len(ag2.history)}")
    for s in ag2.history:
        print(f"  Step {s.step_number}: Tool='{s.action.tool}' Summary='{s.action.summary}' Time={s.timestamp}")
        print(f"  Output snippet: {s.observation[:120]}...")

    # 8. Concurrency Proof: Overlapping timestamps
    all_events = repo.get_events(exp_id, limit=200)
    ag1_events = [e for e in all_events if e.agent_id == ag1.agent_id]
    ag2_events = [e for e in all_events if e.agent_id == ag2.agent_id]

    print(f"\n=== CONCURRENCY & TIMING PROOF ===")
    print(f"Agent 1 event count: {len(ag1_events)}")
    print(f"Agent 2 event count: {len(ag2_events)}")

    if ag1_events and ag2_events:
        ag1_start = ag1_events[0].timestamp
        ag1_end = ag1_events[-1].timestamp
        ag2_start = ag2_events[0].timestamp
        ag2_end = ag2_events[-1].timestamp
        print(f"Agent 1 active interval: {ag1_start} --> {ag1_end}")
        print(f"Agent 2 active interval: {ag2_start} --> {ag2_end}")

        # Both agents must have active execution periods overlapping
        assert ag1_start <= ag2_end and ag2_start <= ag1_end, "Agent execution intervals must overlap"
        print("OVERLAPPING ACTIVE EXECUTION VERIFIED!")


if __name__ == "__main__":
    asyncio.run(test_real_concurrent_experiment_execution())
