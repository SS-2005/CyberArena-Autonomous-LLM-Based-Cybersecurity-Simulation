from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router as vm_router
from backend.api.llm_routes import router as llm_router
from backend.api.agent_routes import router as agent_router
from backend.api.experiment_routes import router as experiment_router
from backend.configs.settings import settings
from backend.utils.logger import logger

app = FastAPI(
    title="CyberArena API",
    description="Backend API, Virtual Machine Infrastructure, Autonomous Agent Runtime & Multi-Agent Experiment Orchestrator for CyberArena",
    version="1.0.0",
)

# Configure CORS for local development and browser frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers at root prefix and /api prefix
for r in (vm_router, llm_router, agent_router, experiment_router):
    app.include_router(r)
    app.include_router(r, prefix="/api")


@app.get("/", tags=["System"])
def root():
    return {
        "name": "CyberArena API",
        "version": "1.0.0",
        "phase": "Phase 3: Multi-Agent Concurrency & Experiment Orchestration",
        "docs_url": "/docs",
    }


@app.get("/health", tags=["System"])
def health():
    return {
        "status": "healthy",
        "service": "cyberarena-backend",
        "env": settings.env,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=True)
