import json
import asyncio
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import StreamingResponse

from backend.api.deps import get_experiment_service
from backend.services.experiment_service import ExperimentService
from backend.schemas.experiment import (
    ExperimentCreateRequest,
    ExperimentDetail,
    ExperimentSummary,
    ExperimentOperationResponse,
    ExperimentEvent,
)
from backend.utils.logger import logger

router = APIRouter(tags=["Experiments"])


@router.post("/experiments", response_model=ExperimentDetail, status_code=201)
def create_experiment(
    req: ExperimentCreateRequest,
    service: ExperimentService = Depends(get_experiment_service),
):
    """
    Create a new multi-agent experiment with dynamic agent-to-VM assignments (1 -> max_vm).
    Persists configuration and initial agent records into SQLite.
    """
    try:
        return service.create_experiment(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create experiment: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create experiment: {e}")


@router.get("/experiments", response_model=List[ExperimentSummary])
def list_experiments(
    service: ExperimentService = Depends(get_experiment_service),
):
    """List all experiments and their statuses ordered by creation date."""
    return service.list_experiments()


@router.get("/experiments/{experiment_id}", response_model=ExperimentDetail)
def get_experiment(
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
):
    """Get full details of an experiment, including agent statuses and step histories."""
    try:
        return service.get_experiment(experiment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/experiments/{experiment_id}/start", response_model=ExperimentOperationResponse)
async def start_experiment(
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
):
    """
    Launch concurrent autonomous execution of all agents in the experiment.
    Runs agents concurrently in isolated tasks against assigned VMs.
    """
    try:
        return await service.start_experiment(experiment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start experiment '{experiment_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start experiment: {e}")


@router.post("/experiments/{experiment_id}/stop", response_model=ExperimentOperationResponse)
def stop_experiment(
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
):
    """Cleanly signal all running agents in the experiment to halt execution."""
    try:
        return service.stop_experiment(experiment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/experiments/{experiment_id}", response_model=ExperimentOperationResponse)
def delete_experiment(
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
):
    """Delete experiment records, agents, and event history from persistence."""
    try:
        return service.delete_experiment(experiment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/experiments/{experiment_id}/events/history", response_model=List[ExperimentEvent])
def get_experiment_event_history(
    experiment_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
    service: ExperimentService = Depends(get_experiment_service),
):
    """Fetch stored event history for an experiment from SQLite."""
    try:
        # Check existence
        service.get_experiment(experiment_id)
        return service.repository.get_events(experiment_id, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/experiments/{experiment_id}/events")
async def stream_experiment_events(
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
):
    """
    Real-time Server-Sent Events (SSE) telemetry stream for a multi-agent experiment.
    Emits experiment lifecycle, agent thoughts, tool execution, and VM observations.
    """
    try:
        service.get_experiment(experiment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    async def _event_generator():
        yield ": connected\n\n"
        try:
            async for event in service.broadcaster.subscribe_sse(experiment_id):
                if event.event_type == "ping":
                    yield ": keep-alive\n\n"
                else:
                    data_str = json.dumps(event.model_dump())
                    yield f"data: {data_str}\n\n"
        except asyncio.CancelledError:
            logger.debug(f"SSE client disconnected from experiment '{experiment_id}'")

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/ws/experiments/{experiment_id}")
async def websocket_experiment_events(
    websocket: WebSocket,
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
):
    """
    Bidirectional WebSocket connection for live multi-agent experiment streaming and controls.
    Replays recent event history upon connection and continuously pushes new events via dedicated FIFO queue.
    """
    await websocket.accept()
    logger.info(f"WebSocket client connected to experiment '{experiment_id}'")

    # Replay past lifecycle events from repository (exclude ephemeral streaming chunks)
    try:
        past_events = [
            pe for pe in service.repository.get_events(experiment_id, limit=200)
            if pe.event_type not in ("llm_chunk", "agent_tool_output_chunk")
        ]
        for pe in past_events:
            await websocket.send_text(json.dumps(pe.model_dump()))
    except Exception as e:
        logger.debug(f"Error replaying past events over WebSocket: {e}")

    ws_queue = service.broadcaster.register_ws_queue(experiment_id)

    async def sender():
        try:
            while True:
                msg = await ws_queue.get()
                if msg is None:
                    break
                await websocket.send_text(msg)
        except Exception:
            pass

    async def receiver():
        try:
            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    pong_msg = json.dumps({
                        "experiment_id": experiment_id,
                        "event_type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "data": {}
                    })
                    await websocket.send_text(pong_msg)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    sender_task = asyncio.create_task(sender())
    receiver_task = asyncio.create_task(receiver())

    try:
        done, pending = await asyncio.wait(
            [sender_task, receiver_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    finally:
        service.broadcaster.unregister_ws_queue(experiment_id, ws_queue)
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info(f"WebSocket client disconnected from experiment '{experiment_id}'")


@router.websocket("/experiments/{experiment_id}/ws")
async def websocket_experiment_events_alt(
    websocket: WebSocket,
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
):
    """Alternative WebSocket URL path."""
    await websocket_experiment_events(websocket, experiment_id, service)
