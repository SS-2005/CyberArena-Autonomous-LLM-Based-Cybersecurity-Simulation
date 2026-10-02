import asyncio
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.agents.agent import Agent
from backend.agents.events import event_broadcaster, AgentEventBroadcaster
from backend.schemas.agent import (
    AgentCreateRequest,
    AgentStatus,
    AgentEvent,
    AgentEventType,
    AgentActionRequest,
)
from backend.schemas.llm import LLMGenerationResponse, LLMTestRequest
from backend.services.agent_service import AgentService
from backend.services.llm_service import LLMService
from backend.virtualization.base import VMProvider, CommandExecutionResult
from backend.api.agent_routes import stream_agent_events
from backend.api.llm_routes import stream_test_model
from backend.api.deps import get_agent_service, get_llm_service


@pytest.fixture
def test_client():
    return TestClient(app)


def test_delete_agent_endpoint(test_client):
    """Verify DELETE /agents/{agent_id} removes agent runtime cleanly and returns 404 afterwards."""
    # 1. Create an agent
    create_res = test_client.post(
        "/agents",
        json={
            "role": "Agent to be deleted",
            "vm_id": "vm-01",
            "model_id": "local-qwen3-4b",
        },
    )
    assert create_res.status_code == 201
    agent_id = create_res.json()["agent_id"]

    # 2. Verify agent exists
    get_res = test_client.get(f"/agents/{agent_id}")
    assert get_res.status_code == 200

    # 3. Delete agent
    del_res = test_client.delete(f"/agents/{agent_id}")
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["operation"] == "delete"
    assert del_data["success"] is True

    # 4. Verify agent no longer exists
    get_res2 = test_client.get(f"/agents/{agent_id}")
    assert get_res2.status_code == 404

    # 5. Verify deleting nonexistent agent returns 404
    del_nonexistent = test_client.delete(f"/agents/{agent_id}")
    assert del_nonexistent.status_code == 404


def test_delete_running_agent(test_client):
    """Verify deleting a running agent signals stop and cleans up background task."""
    create_res = test_client.post(
        "/agents",
        json={
            "role": "Running Agent to be deleted",
            "vm_id": "vm-01",
            "model_id": "local-qwen3-4b",
        },
    )
    agent_id = create_res.json()["agent_id"]

    # Delete while running or idle
    del_res = test_client.delete(f"/agents/{agent_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True


def test_sse_events_endpoint_404(test_client):
    """Verify GET /agents/{agent_id}/events returns 404 for invalid agent."""
    invalid_res = test_client.get("/agents/nonexistent-agent/events")
    assert invalid_res.status_code == 404


@pytest.mark.asyncio
async def test_sse_events_generator_emission():
    """Verify stream_agent_events yields initial connected comment and historical agent events."""
    agent_service = get_agent_service()
    agent_state = agent_service.create_agent(
        AgentCreateRequest(role="SSE Telemetry Direct Test", vm_id="vm-01")
    )
    resp = await stream_agent_events(agent_state.agent_id, agent_service)
    assert resp.media_type == "text/event-stream"

    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
        if len(chunks) >= 2:
            break

    assert any(": connected" in c for c in chunks)
    assert any("agent_created" in c for c in chunks)


def test_multi_agent_event_isolation():
    """Verify that events published for Agent 1 NEVER appear in Agent 2's subscriber stream or history."""
    broadcaster = AgentEventBroadcaster()

    # Emit events for Agent 1
    evt1 = AgentEvent(
        agent_id="agent-01-iso",
        event_type=AgentEventType.LLM_STARTED.value,
        iteration=1,
        timestamp="2026-09-30T14:00:00Z",
        content="Agent 1 event",
    )
    broadcaster.publish(evt1)

    # Emit events for Agent 2
    evt2 = AgentEvent(
        agent_id="agent-02-iso",
        event_type=AgentEventType.TOOL_STARTED.value,
        iteration=1,
        timestamp="2026-09-30T14:00:01Z",
        content="Agent 2 event",
    )
    broadcaster.publish(evt2)

    # Check histories are strictly isolated
    h1 = broadcaster.get_history("agent-01-iso")
    h2 = broadcaster.get_history("agent-02-iso")

    assert len(h1) == 1
    assert h1[0].agent_id == "agent-01-iso"
    assert h1[0].content == "Agent 1 event"

    assert len(h2) == 1
    assert h2[0].agent_id == "agent-02-iso"
    assert h2[0].content == "Agent 2 event"


@pytest.mark.asyncio
async def test_llm_stream_test_endpoint():
    """Verify test_model_stream returns SSE StreamingResponse."""
    llm_service = get_llm_service()
    req = LLMTestRequest(prompt="Test streaming ping", model_id="local-qwen3-4b")
    resp = await stream_test_model(req, llm_service)
    assert resp.media_type == "text/event-stream"
    assert resp.status_code == 200



def test_agent_event_emission_sequence():
    """Verify that an Agent step emits the full lifecycle of events in the correct order."""
    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate.return_value = LLMGenerationResponse(
        text='{"thought": "Run hostname", "tool": "execute_command", "parameters": {"command": "hostname"}, "summary": "Get host"}',
        duration=0.1,
        model_name="qwen3:4b",
    )
    # Configure generate_stream to yield chunks followed by done
    mock_llm.generate_stream.return_value = iter([
        {"chunk": '{"thought": "Run hostname", ', "done": False},
        {"chunk": '"tool": "execute_command", ', "done": False},
        {"chunk": '"parameters": {"command": "hostname"}, "summary": "Get host"}', "done": True},
    ])

    mock_vm = MagicMock(spec=VMProvider)
    mock_vm.execute_command.return_value = CommandExecutionResult(
        vm_id="vm-01",
        command="hostname",
        exit_code=0,
        stdout="cyberarena-vm-01\n",
        stderr="",
        duration=0.02,
    )

    agent = Agent(
        agent_id="agent-seq-test",
        role="Sequence test",
        vm_id="vm-01",
        model_id="local-qwen3-4b",
        llm_service=mock_llm,
        vm_provider=mock_vm,
    )

    emitted_types = []

    def mock_publish(event: AgentEvent):
        if event.agent_id == "agent-seq-test":
            emitted_types.append(event.event_type)

    with patch.object(event_broadcaster, "publish", side_effect=mock_publish):
        step = agent.step()

    assert step.success is True
    assert "agent_iteration_started" in emitted_types
    assert "llm_started" in emitted_types
    assert "llm_chunk" in emitted_types
    assert "llm_completed" in emitted_types
    assert "tool_requested" in emitted_types
    assert "tool_started" in emitted_types
    assert "tool_completed" in emitted_types
    assert "observation_received" in emitted_types
