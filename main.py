# =============================================================================
# main.py — OrgOS FastAPI application entry point
# Creates the FastAPI app, registers middleware, mounts all routers.
# Uses the lifespan pattern (FastAPI 0.115+) for startup/shutdown.
# Run: uvicorn main:app --reload --host 0.0.0.0 --port 8000
# Depends on: config.py, graph/client.py, grc/router.py, agents/extractor/router.py
# =============================================================================

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import configure_logging, settings
from graph import client as graph_client
from grc.router import router as grc_router
from agents.extractor.router import router as extractor_router
from sharepoint.router import router as sharepoint_router
from review_queue.router import router as queue_router
from lifecycle.router import router as lifecycle_router
from control_register.router import router as control_router
from evidence_tracker.router import router as evidence_router
from standards_map.router import router as standards_router
from strategic_risks.router import router as risks_router
from gap_analysis.router import router as gap_router
from agents.classifier.router import router as classifier_router
from agents.cdi_checker.router import router as cdi_router

# Configure logging before anything else
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    Code before `yield` runs on startup.
    Code after `yield` runs on shutdown.
    This replaces the deprecated @app.on_event("startup") pattern.
    """
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info(f"OrgOS starting — environment={settings.environment}")
    await graph_client.startup()
    # Pre-fetch JWKS on startup so first request does not fail
    try:
        from auth.validator import _get_jwks
        await _get_jwks()
        logger.info("JWKS pre-fetched successfully")
    except Exception as e:
        logger.warning(f"JWKS pre-fetch failed — will retry on first request: {e}")
    logger.info("OrgOS ready")
    

    yield  # Application runs here

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("OrgOS shutting down")
    await graph_client.shutdown()
    logger.info("OrgOS shutdown complete")


# =============================================================================
#  Application
# =============================================================================

app = FastAPI(
    title="OrgOS — GRC API",
    description=(
        "Dragnet Solutions OrgOS GRC Orchestration Module. "
        "Tier 1: Document Register, Role Register, Compliance Calendar, Contract Register."
    ),
    version="1.0.0",
    docs_url="/docs",        # Swagger UI at http://localhost:8000/docs
    redoc_url="/redoc",      # ReDoc at http://localhost:8000/redoc
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# =============================================================================
#  CORS — allow the React frontend to call this API
# =============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


app.include_router(grc_router)
app.include_router(extractor_router)
app.include_router(sharepoint_router)
app.include_router(queue_router)
app.include_router(lifecycle_router)
app.include_router(control_router)
app.include_router(evidence_router)
app.include_router(standards_router)
app.include_router(risks_router)
app.include_router(gap_router)
app.include_router(classifier_router)
app.include_router(cdi_router)
# =============================================================================
#  Health endpoints (no auth required — for monitoring)
# =============================================================================

@app.get("/health", tags=["Health"], summary="Application health check")
async def health() -> JSONResponse:
    """Basic health check. Returns 200 if the app is running."""
    return JSONResponse(
        content={
            "status": "ok",
            "environment": settings.environment,
            "version": "1.0.0",
        }
    )


@app.get(
    "/api/v1/health/graph",
    tags=["Health"],
    summary="Microsoft Graph API connectivity check",
)
async def graph_health() -> JSONResponse:
    """
    Verifies the backend can acquire a Graph API token and reach SharePoint.
    Returns 503 if Graph API is unreachable or credentials are invalid.
    """
    result = await graph_client.check_graph_connectivity()
    status_code = 200 if result["status"] == "ok" else 503
    return JSONResponse(content=result, status_code=status_code)
