
# main.py  
# --- HOT-SWAP SQLITE FOR CHROMA ---
import os
import json
import warnings
import sys
from functools import lru_cache
from typing import Tuple, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

try:
    import pysqlite3 as sqlite3  # loads bundled SQLite >= 3.35
    sys.modules['sqlite3'] = sqlite3
    print("Using pysqlite3-binary as sqlite3 backend")
except Exception as e:
    print("WARNING: sqlite3 hot-swap failed:", e)
# -----------------------------------

# FastAPI app (ASGI variable must be named `app`)
app = FastAPI(title="Market Insights – Multi-Agent Crew API")


@app.get("/healthz")
def healthz():
    return {"ok": True}

# Silence only this specific Pydantic V2 migration warning from CrewAI internals
#warnings.filterwarnings(
 #   "ignore",
  #  message="Valid config keys have changed in V2",
   # category=UserWarning,
    #module="pydantic._internal._config",
#)


# Load environment variables (.env locally; overridden by Azure App Settings in production)
load_dotenv(override=True)

BASE = os.path.dirname(__file__)

# Import your loaders
# from app.loader import load_llm, load_tools, load_agents, load_tasks, load_crew  # noqa: E402

# 2) Lettvekts health-endpoint (svarer alltid raskt)
@app.get("/healthz")
def healthz():
    return {"ok": True}

# 3) Lazy-init: importer tunge ting først når vi trenger dem
@lru_cache(maxsize=1)
def get_crew_bootstrap():
    """
    Importerer og initialiserer først når den faktisk kalles.
    Gjør app-oppstart (og SSH) rask og stabil.
    """
    # Flytt alle tunge imports hit
    from app.loader import (
        load_llm, load_tools, load_agents, load_tasks, load_crew
    )

    llm = load_llm()
    tools = load_tools()
    agents = load_agents(llm, tools)
    tasks = load_tasks()
    crew = load_crew(agents, tasks)
    return {
        "llm": llm,
        "tools": tools,
        "agents": agents,
        "tasks": tasks,
        "crew": crew
    }



# Ny, enkel root-status for drift/monitorering
@app.get("/status")
@app.get("/status/")
def system_status():
    state = get_crew_bootstrap()
    return {"crew_ready": state["crew"] is not None}

# (Valgfritt) pre-warm i bakgrunnen ved oppstart
@app.on_event("startup")
def warm_in_background():
    import threading
    threading.Thread(target=get_crew_bootstrap, daemon=True).start()
# --------------------------------------------------------------


# ---------- Helpers ----------
def ensure_keys():
    required = ["GROQ_API_KEY"]  # add OPENAI_API_KEY, etc. if needed
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing environment variables: {', '.join(missing)}"
        )


#@lru_cache(maxsize=1)
#def get_components() -> Tuple[Any, Dict[str, Any], Dict[str, Any], Dict[str, Any], Any]:
    """
    Load and cache llm, tools, agents, tasks, and crew.
    Cache is per-process (reused across requests until container restarts).
    """
 #   llm = load_llm(os.path.join(BASE, "config/llm.yaml"))
  #  tools = load_tools(os.path.join(BASE, "crew/tools"))
   # agents = load_agents(os.path.join(BASE, "crew/agents"), llm, tools)
    #tasks = load_tasks(os.path.join(BASE, "crew/tasks"), agents)
    #crew = load_crew(os.path.join(BASE, "crew/crews/market_insights.yaml"), agents, tasks)
    #return llm, tools, agents, tasks, crew


def run_crew_pipeline(topic: str) -> dict:
    ensure_keys()

    # Get cached components
    _, _, _, _, crew = get_components()

    # Execute (CrewAI 1.8+)
    result = crew.kickoff({"topic": topic})

    # Persist to /runs/latest_output.json
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

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Market Insights – Multi-Agent Crew API",
        "endpoints": ["/run (POST)", "/latest (GET)"]
    }


app.get("/status")
def status():
    state = get_crew_bootstrap()
    return {"crew_ready": state["crew"] is not None}

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
