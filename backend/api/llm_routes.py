import json
import asyncio
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.deps import get_llm_service
from backend.services.llm_service import LLMService
from backend.schemas.llm import (
    ModelStatus,
    LLMHealthResponse,
    LLMTestRequest,
    LLMTestResponse,
)

router = APIRouter(prefix="", tags=["LLM"])


@router.get("/llm/health", response_model=LLMHealthResponse)
def get_llm_health(llm_service: LLMService = Depends(get_llm_service)):
    """Health check for configured local LLM provider (Ollama)."""
    return llm_service.get_health()


@router.get("/llm/models", response_model=List[ModelStatus])
def list_models(llm_service: LLMService = Depends(get_llm_service)):
    """
    List all models and their status:
    Distinguishes configured, installed, available, and unavailable models.
    """
    return llm_service.list_models()


@router.post("/llm/test", response_model=LLMTestResponse)
def test_model(req: LLMTestRequest, llm_service: LLMService = Depends(get_llm_service)):
    """Execute a simple prompt test against the local LLM."""
    try:
        return llm_service.test_model(model_id=req.model_id, prompt=req.prompt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"LLM request timed out: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM test error: {e}")


@router.post("/llm/test/stream")
async def stream_test_model(req: LLMTestRequest, llm_service: LLMService = Depends(get_llm_service)):
    """Stream token chunks for real-time model test via SSE."""
    try:
        llm_service.resolve_model(req.model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _sync_generator():
        for chunk in llm_service.test_model_stream(model_id=req.model_id, prompt=req.prompt):
            yield f"data: {json.dumps(chunk)}\n\n"

    async def _async_stream():
        loop = asyncio.get_running_loop()
        # Run generator in thread pool so it does not block the async event loop
        gen = _sync_generator()
        while True:
            try:
                item = await loop.run_in_executor(None, next, gen, None)
                if item is None:
                    break
                yield item
            except Exception as e:
                err_data = json.dumps({"error": str(e), "done": True})
                yield f"data: {err_data}\n\n"
                break

    return StreamingResponse(
        _async_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

