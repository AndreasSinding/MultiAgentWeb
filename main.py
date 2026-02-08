# main.py
import os
import json
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Import pipeline singletons/utilities
from app.pipeline import build_llm_and_crew_once, warm_async, run_crew_pipeline

# Routers (PPT endpoints)
from ui.routes_ppt import router as ppt_router

# Optional: hot-swap sqlite3 backend (Azure/Linux safe)
USE_PYSQLITE3 = os.getenv("USE_PYSQLITE3", "0") == "1"
if USE_PYSQLITE3:
    try:
        import pysqlite3 as sqlite3  # noqa: F401
        import sys
        sys.modules['sqlite3'] = sqlite3
        print("Using pysqlite3-binary as sqlite3 backend")
    except Exception as e:
        print("WARNING: sqlite3 hot-swap failed:", e)

load_dotenv(override=True)

BASE = os.path.dirname(__file__)

app = FastAPI(
    title="Market Insights – Multi-Agent Crew API",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(ppt_router)

# Warm-up on startup (non-blocking)
@app.on_event("startup")
def warm_in_background():
    warm_async()

# Simple health endpoints
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/health")
def health():
    return {"status": "ok"}

# Status (never 500)
@app.get("/status")
@app.get("/status/")
def status():
    state = build_llm_and_crew_once()
    return {"crew_ready": bool(state.get("ready")), "error": state.get("error")}

# Request schema
class RunRequest(BaseModel):
    topic: str

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Market Insights – Multi-Agent Crew API",
        "endpoints": ["/run (POST)", "/latest (GET)", "/status (GET)", "/healthz (GET)"]
    }

@app.post("/run")
def run(req: RunRequest):
    """Run the pipeline and return consolidated output."""
    try:
        output = run_crew_pipeline(req.topic)

        # Best-effort: persist again here (pipeline already writes /runs/latest_output.json)
        try:
            runs_dir = os.path.join(BASE, "runs")
            os.makedirs(runs_dir, exist_ok=True)
            outfile = os.path.join(runs_dir, "latest_output.json")
            tmpfile = outfile + ".tmp"
            with open(tmpfile, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            os.replace(tmpfile, outfile)
        except Exception as _e:
            print("WARNING: could not persist latest_output.json from /run:", _e)

        return {"topic": req.topic, "result": output}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/latest")
def latest():
    """Return the last persisted output (if any)."""
    path = os.path.join(BASE, "runs/latest_output.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No previous run stored.")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        with open(path, "r", encoding="utf-8") as f:
            return {"raw": f.read()}
