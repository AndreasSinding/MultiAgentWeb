
import os
import uuid
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from app.loader import load_llm, load_tools, load_agents, load_tasks, load_crew

load_dotenv(override=True)

BASE = os.path.dirname(os.path.dirname(__file__))

# ------------------------------
# Build Crew once at startup
# ------------------------------
CREW = None
def build_crew():
    llm    = load_llm(os.path.join(BASE, "config/llm.yaml"))
    tools  = load_tools(os.path.join(BASE, "crew/tools"))
    agents = load_agents(os.path.join(BASE, "crew/agents"), llm, tools)
    tasks  = load_tasks(os.path.join(BASE, "crew/tasks"), agents)
    return load_crew(os.path.join(BASE, "crew/crews/market_insights.yaml"), agents, tasks)

# ------------------------------
# FastAPI App
# ------------------------------
app = FastAPI(title="Market Insights – CrewAI API")

# CORS (open for now, restrict in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)

# Serve static files (browser UI)
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "web", "static")), name="static")

# In-memory job store
JOBS = {}   # job_id → {status, result, error}


@app.on_event("startup")
def startup_event():
    global CREW
    CREW = build_crew()


# ------------------------------
# Request / Response Models
# ------------------------------
class RunRequest(BaseModel):
    topic: str

class RunResponse(BaseModel):
    job_id: str
    status: str = "queued"

class StatusResponse(BaseModel):
    job_id: str
    status: str
    result: dict | str | None = None
    error: str | None = None


# ------------------------------
# Background job runner
# ------------------------------
def run_job(job_id: str, topic: str):
    try:
        JOBS[job_id]["status"] = "running"
        result = CREW.kickoff({"topic": topic})
        JOBS[job_id]["status"] = "completed"
        JOBS[job_id]["result"] = result
    except Exception as e:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)


# ------------------------------
# API Endpoints
# ------------------------------
@app.get("/health")
def health():
    return {
        "ok": True,
        "model": CREW.agents[0].llm.model if CREW else "not_loaded"
    }


@app.post("/api/run", response_model=RunResponse, status_code=202)
def run_task(req: RunRequest, bg: BackgroundTasks):
    if not req.topic.strip():
        raise HTTPException(400, "Topic cannot be empty")

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "queued", "result": None, "error": None}

    bg.add_task(run_job, job_id, req.topic.strip())

    return RunResponse(job_id=job_id, status="queued")


@app.get("/api/status/{job_id}", response_model=StatusResponse)
def get_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return StatusResponse(job_id=job_id, **job)
