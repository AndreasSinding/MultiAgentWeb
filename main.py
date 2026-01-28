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

# --- HOT-SWAP SQLITE FOR CHROMA ---
try:
    import pysqlite3 as sqlite3
    sys.modules['sqlite3'] = sqlite3
    print("Using pysqlite3-binary as sqlite3 backend")
except Exception as e:
    print("WARNING: sqlite3 hot-swap failed:", e)
# -----------------------------------

load_dotenv(override=True)
BASE = os.path.dirname(__file__)

app = FastAPI(title="Market Insights – Multi-Agent Crew API")

# Health
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/health")
def health():
    return {"status": "ok"}

# Only LLM path (since you don't have tools/agents/tasks)
LLM_YAML_PATH = os.getenv("LLM_YAML_PATH", "config/llm.yaml")

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

def build_llm_and_crew_once() -> Dict[str, Any]:
    """
    Build LLM and Crew one time, with graceful fallbacks depending on what
    exists in app.loader. Never throws; stores errors in CREW_STATE.
    """
    if CREW_STATE["ready"] and CREW_STATE["crew"] is not None:
        return CREW_STATE

    try:
        # Try to import available loaders
        try:
            from app.loader import load_llm
        except ImportError:
            load_llm = None

        try:
            from app.loader import load_crew
        except ImportError:
            load_crew = None

        # Optional loaders (you said you don't have these)
        try:
            from app.loader import load_tools
        except ImportError:
            load_tools = None
        try:
            from app.loader import load_agents
        except ImportError:
            load_agents = None
        try:
            from app.loader import load_tasks
        except ImportError:
            load_tasks = None

        # 1) LLM
        llm = None
        if load_llm is not None:
            # Prefer calling with LLM_YAML_PATH; if loader doesn't need a path, it will use no-arg
            try:
                llm = _call_with_optional_path(load_llm, LLM_YAML_PATH)
            except Exception:
                llm = load_llm()
        CREW_STATE["llm"] = llm

        # 2) Optional components (only if functions exist)
        tools = load_tools(llm) if (load_tools and len(inspect.signature(load_tools).parameters) >= 1) else (load_tools() if load_tools else None)

        agents = None
        if load_agents:
            sig = inspect.signature(load_agents)
            if len(sig.parameters) >= 2:
                agents = load_agents(llm, tools)
            elif len(sig.parameters) >= 1:
                # If it expects a path but you don't have agents.yaml, call without args
                try:
                    agents = load_agents("config/agents.yaml")
                except Exception:
                    agents = load_agents()

        tasks = None
        if load_tasks:
            sig = inspect.signature(load_tasks)
            if len(sig.parameters) >= 1:
                # If it expects a path but you don't have tasks.yaml, call without args
                try:
                    tasks = load_tasks("config/tasks.yaml")
                except Exception:
                    tasks = load_tasks()
            else:
                tasks = load_tasks()

        # 3) Crew
        crew = None
        if load_crew is None:
            raise RuntimeError("No load_crew() found in app.loader")

        # Try common signatures: load_crew(agents, tasks), load_crew(llm), load_crew()
        try:
            sig_crew = inspect.signature(load_crew)
            n = len(sig_crew.parameters)
            if n >= 2 and agents is not None and tasks is not None:
                crew = load_crew(agents, tasks)
            elif n >= 1 and llm is not None:
                crew = load_crew(llm)
            elif n == 0:
                crew = load_crew()
            else:
                # Fallback: try simplest first
                try:
                    crew = load_crew()
                except Exception:
                    if llm is not None:
                        crew = load_crew(llm)
        except Exception as e:
            raise RuntimeError(f"load_crew failed: {e}")

        CREW_STATE.update({"crew": crew, "ready": True, "error": None})
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
