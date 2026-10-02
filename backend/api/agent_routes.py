import json
import asyncio
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.agents.events import event_broadcaster
from backend.utils.logger import logger

from backend.api.deps import get_agent_service
from backend.services.agent_service import AgentService
from backend.schemas.agent import (
    AgentCreateRequest,
    AgentState,
    AgentStep,
    AgentOperationResponse,
    ToolDefinitionSchema,
)

router = APIRouter(prefix="", tags=["Agents"])


@router.get("/agents/tools", response_model=List[ToolDefinitionSchema])
def list_available_tools(agent_service: AgentService = Depends(get_agent_service)):
    """List all available tools that can be assigned to agents with their schemas."""
    tools = agent_service.tool_registry.list_tools()
    return [t.to_schema() for t in tools]


@router.post("/agents", response_model=AgentState, status_code=201)
def create_agent(req: AgentCreateRequest, agent_service: AgentService = Depends(get_agent_service)):
    """Create a new autonomous agent assigned to a laboratory VM."""
    try:
        return agent_service.create_agent(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {e}")


@router.get("/agents", response_model=List[AgentState])
def list_agents(agent_service: AgentService = Depends(get_agent_service)):
    """List all registered agents and their current lifecycle states."""
    return agent_service.list_agents()


@router.get("/agents/{agent_id}", response_model=AgentState)
def get_agent(agent_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """Get the current state and metrics of an agent."""
    try:
        return agent_service.get_agent_state(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/agents/{agent_id}/start", response_model=AgentOperationResponse)
async def start_agent(agent_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """Launch the agent's autonomous observation/reasoning/tool execution loop."""
    try:
        return await agent_service.start_agent_async(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start agent: {e}")


@router.post("/agents/{agent_id}/stop", response_model=AgentOperationResponse)
def stop_agent(agent_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """Signal the running agent to cleanly halt execution after its current step."""
    try:
        return agent_service.stop_agent(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/agents/{agent_id}/status")
def get_agent_status(agent_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """Get status summary and iteration count for an agent."""
    try:
        state = agent_service.get_agent_state(agent_id)
        return {
            "agent_id": state.agent_id,
            "status": state.status,
            "current_iteration": state.current_iteration,
            "iteration_limit": state.iteration_limit,
            "updated_at": state.updated_at,
            "error_message": state.error_message,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/agents/{agent_id}/history", response_model=List[AgentStep])
def get_agent_history(agent_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """Retrieve the full sequence of actions, tool invocations, and observations for an agent."""
    try:
        return agent_service.get_agent_history(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/agents/{agent_id}/events")
async def stream_agent_events(agent_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """
    Real-time Server-Sent Events (SSE) telemetry stream for a specific agent.
    Emits state transitions, LLM chunks, tool execution, and observations.
    """
    try:
        agent_service.get_agent(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    async def _event_generator():
        # Flush headers immediately
        yield ": connected\n\n"
        try:
            async for event in event_broadcaster.subscribe(agent_id):
                if event.event_type == "ping":
                    yield ": keep-alive\n\n"
                else:
                    data_str = json.dumps(event.model_dump())
                    yield f"data: {data_str}\n\n"
        except asyncio.CancelledError:
            logger.debug(f"SSE client disconnected from agent '{agent_id}'")

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/agents/{agent_id}", response_model=AgentOperationResponse)
def delete_agent(agent_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """
    Delete an autonomous agent's runtime state and history.
    Does NOT affect the assigned VM, snapshots, or VM filesystem.
    """
    try:
        return agent_service.delete_agent(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete agent: {e}")

