# main.py
import os
import json
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Pipeline utilities
from app.pipeline import (
    build_llm_and_crew_once,
    warm_async,
    run_crew_pipeline,
)

# Optional: hot-swap sqlite3 backend (Azure/Linux safe)
USE_PYSQLITE3 = os.getenv("USE_PYSQLITE3", "0") == "1"
if USE_PYSQLITE3:
    try:
        import pysqlite3 as sqlite3  # noqa: F401
        import sys

        sys.modules["sqlite3"] = sqlite3
        print("Using pysqlite3-binary as sqlite3 backend")
    except Exception as e:
        print("WARNING: sqlite3 hot-swap failed:", e)

# Load env
load_dotenv(override=True)
BASE = os.path.dirname(__file__)

# ------------------------------------------------------------------------------
# Optional hardening toggles
#   - DISABLE_DOCS=1   → Hide Swagger/Redoc in prod emergencies
# ------------------------------------------------------------------------------
DISABLE_DOCS = os.getenv("DISABLE_DOCS", "0") == "1"

app = FastAPI(
    title="Market Insights – Multi-Agent Crew API",
    docs_url=None if DISABLE_DOCS else "/docs",
    redoc_url=None if DISABLE_DOCS else "/redoc",
)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

# ------------------------------------------------------------------------------
# CORS
# ------------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# Guarded import for PPT routes (schema-safe)
#   - ENABLE_PPT_ROUTES=1 → include PPT endpoints
#   - If import fails, app still boots and /docs stays healthy
# ------------------------------------------------------------------------------
ENABLE_PPT_ROUTES = os.getenv("ENABLE_PPT_ROUTES", "0") == "1"
ppt_router = None
if ENABLE_PPT_ROUTES:
    try:
        # ui/routes_ppt.py is the schema-safe router (lazy imports, StreamingResponse)
        from ui.routes_ppt import router as ppt_router
    except Exception as e:
        print(f"WARNING: PPT routes not loaded: {e}")
        ppt_router = None

if ppt_router:
    app.include_router(ppt_router)

# ------------------------------------------------------------------------------
# Warm crew on startup (non-blocking background warm-up)
# ------------------------------------------------------------------------------
@app.on_event("startup")
def warm_in_background():
    warm_async()

# ------------------------------------------------------------------------------
# Health / Status endpoints (lightweight; safe for Azure warmup checks)
# ------------------------------------------------------------------------------
health_router = APIRouter()

@health_router.get("/healthz", tags=["health"])
def healthz():
    return {"ok": True}

@health_router.get("/health", tags=["health"])
def health():
    return {"status": "ok"}

@health_router.get("/status", tags=["health"])
@health_router.get("/status/", tags=["health"])
def status():
    """
    Lightweight health endpoint for Azure / smoke tests.
    - Does NOT initialize LLMs, crews, or heavy objects.
    - Always returns quickly and reliably.
    """
    return {
        "status": "ok",
        "message": "Service is running",
    }

# Register router with your main FastAPI app
app.include_router(health_router)

# ------------------------------------------------------------------------------
# Request Schema
# ------------------------------------------------------------------------------
class RunRequest(BaseModel):
    topic: str

# ------------------------------------------------------------------------------
# Root
# ------------------------------------------------------------------------------
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Market Insights – Multi-Agent Crew API",
        "endpoints": ["/run (POST)", "/latest (GET)", "/status (GET)", "/healthz (GET)"],
    }

# ------------------------------------------------------------------------------
# Run Pipeline
# ------------------------------------------------------------------------------
@app.post("/run")
def run(req: RunRequest):
    """
    Executes the multi-agent pipeline on the given topic.
    """
    try:
        output = run_crew_pipeline(req.topic)

        # unified structure for PPT pipeline + latest endpoint
        packaged = {
            "topic": req.topic,
            "result": output   # full crew output dict

        # Also persist output here (pipeline already does it)
        try:
            runs_dir = os.path.join(BASE, "runs")
            os.makedirs(runs_dir, exist_ok=True)
            outfile = os.path.join(runs_dir, "latest_output.json")
            tmpfile = outfile + ".tmp"
            with open(tmpfile, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            os.replace(tmpfile, outfile)
        except Exception as _e:
            print("WARNING: Could not persist latest_output.json from /run:", _e)

        return packaged

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------------------
# Latest saved output
# ------------------------------------------------------------------------------
@app.get("/latest")
def latest():
    """
    Returns the most recent pipeline output.
    """
    path = os.path.join(BASE, "runs/latest_output.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No previous run stored.")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        with open(path, "r", encoding="utf-8") as f:
            return {"raw": f.read()}
