
# main.py   
import os
import sys
import json
import threading
import inspect
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from ui.routes_ppt import router as ppt_router

# --- OPTIONAL: HOT-SWAP SQLITE FOR CHROMA ---
USE_PYSQLITE3 = os.getenv("USE_PYSQLITE3", "0") == "1"
if USE_PYSQLITE3:
    try:
        import pysqlite3 as sqlite3
        sys.modules['sqlite3'] = sqlite3
        print("Using pysqlite3-binary as sqlite3 backend")
    except Exception as e:
        print("WARNING: sqlite3 hot-swap failed:", e)


load_dotenv(override=True)
BASE = os.path.dirname(__file__)

app = FastAPI(title="Market Insights – Multi-Agent Crew API")

# include your other routers first if any...
app.include_router(ppt_router)  # <-- make sure this line exists

# Health
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/health")
def health():
    return {"status": "ok"}

TOOLS_DIR = os.getenv("TOOLS_DIR", "crew/tools")
AGENTS_DIR = os.getenv("AGENTS_DIR", "crew/agents")
TASKS_DIR = os.getenv("TASKS_DIR", "crew/tasks")
CREW_YAML_PATH = os.getenv("CREW_YAML_PATH", "crew/crews/market_insights.yaml")

# Only LLM path (since you don't have tools/agents/tasks)
LLM_YAML_PATH = os.getenv("LLM_YAML_PATH", "config/llm.yaml")
#CREW_YAML_PATH = os.getenv("CREW_YAML_PATH", "config/crew.yaml")  # use if you have a crew yaml

# Shared readiness state
CREW_STATE: Dict[str, Any] = {"ready": False, "error": None, "crew": None, "llm": None}



def _call_with_optional_path(func, path: Optional[str] = None):
    """
    If the function appears to take arguments, pass 'path';
    otherwise call it with no arguments.
    """
    try:
        sig = inspect.signature(func)
        if path is not None and len(sig.parameters) >= 1:
            return func(path)
        return func()
    except TypeError:
        # Fallback: try no-arg if path failed
        return func()

#Replace guessing logic in build_llm_and_crew_once

def build_llm_and_crew_once() -> Dict[str, Any]:
    if CREW_STATE["ready"] and CREW_STATE["crew"] is not None:
        return CREW_STATE

    try:
        from app.loader import load_llm, load_tools, load_agents, load_tasks, load_crew

        # Build components deterministically
        llm    = load_llm(LLM_YAML_PATH)
        tools  = load_tools(TOOLS_DIR)
        agents = load_agents(AGENTS_DIR, llm, tools)
        tasks  = load_tasks(TASKS_DIR, agents)
        crew   = load_crew(CREW_YAML_PATH, agents, tasks)

        CREW_STATE.update({"llm": llm, "crew": crew, "ready": True, "error": None})
    except Exception as e:
        CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})
        print("Crew init failed:", e)

    return CREW_STATE

# Warm-up in background so startup is instant
@app.on_event("startup")
def warm_in_background():
    def _warm():
        try:
            build_llm_and_crew_once()
        except Exception as e:
            CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})
    threading.Thread(target=_warm, daemon=True).start()

# Status (never 500)
@app.get("/status")
@app.get("/status/")
def status():
    state = build_llm_and_crew_once()
    return {"crew_ready": bool(state.get("ready")), "error": state.get("error")}

# ---------- Pipeline helpers ----------
def ensure_keys():
    required = ["GROQ_API_KEY"]  # add OPENAI_API_KEY etc. if needed
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing environment variables: {', '.join(missing)}")

def run_crew_pipeline(topic: str) -> dict:
    ensure_keys()
    state = build_llm_and_crew_once()
    if not state["ready"] or state["crew"] is None:
        raise HTTPException(status_code=500, detail=f"Crew not ready: {state['error']}")
    crew = state["crew"]
    result = crew.kickoff({"topic": topic})

    runs_dir = os.path.join(BASE, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    outfile = os.path.join(runs_dir, "latest_output.json")
    try:
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except TypeError:
        with open(outfile, "w", encoding="utf-8") as f:
            f.write(str(result))
    return result

# ---------- Schemas ----------
class RunRequest(BaseModel):
    topic: str

# ---------- Endpoints ----------
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Market Insights – Multi-Agent Crew API",
        "endpoints": ["/run (POST)", "/latest (GET)", "/status (GET)", "/healthz (GET)"]
    }

@app.post("/run")
def run(req: RunRequest):
    try:
        output = run_crew_pipeline(req.topic)
        return {"topic": req.topic, "result": output}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/latest")
def latest():
    path = os.path.join(BASE, "runs/latest_output.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No previous run stored.")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        with open(path, "r", encoding="utf-8") as f:
            return {"raw": f.read()}
