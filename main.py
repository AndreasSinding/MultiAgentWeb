# main.py
# Market Insights – Multi-Agent Crew API

import os
import sys
import json
import warnings
import threading
import inspect
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

# --- HOT-SWAP SQLITE FOR CHROMA ---
try:
    import pysqlite3 as sqlite3  # loads bundled SQLite >= 3.35
    sys.modules['sqlite3'] = sqlite3
    print("Using pysqlite3-binary as sqlite3 backend")
except Exception as e:
    print("WARNING: sqlite3 hot-swap failed:", e)
# -----------------------------------

# Load environment variables (.env locally; overridden by Azure App Settings in production)
load_dotenv(override=True)

BASE = os.path.dirname(__file__)
app = FastAPI(title="Market Insights – Multi-Agent Crew API")

# ---------- Health ----------
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/health")
def health():
    return {"status": "ok"}

# ---------- YAML path config (Azure App Settings or defaults) ----------
LLM_YAML_PATH    = os.getenv("LLM_YAML_PATH",    "app/config/llm.yaml")
TOOLS_YAML_PATH  = os.getenv("TOOLS_YAML_PATH",  "app/config/tools.yaml")
AGENTS_YAML_PATH = os.getenv("AGENTS_YAML_PATH", "app/config/agents.yaml")
TASKS_YAML_PATH  = os.getenv("TASKS_YAML_PATH",  "app/config/tasks.yaml")

# ---------- Global state ----------
CREW_STATE: Dict[str, Any] = {"ready": False, "error": None, "crew": None}

def _maybe_call_with_path(func, path):
    """
    Kall 'func' med path hvis signaturen tilsier at den tar argumenter, ellers kall uten argument.
    Robust mot ulike varianter av loader-funksjoner.
    """
    try:
        sig = inspect.signature(func)
        if len(sig.parameters) >= 1:
            return func(path)
        return func()
    except TypeError:
        # Fallback: prøv uten path
        return func()

def _build_agents(load_agents, llm, tools):
    """
    load_agents kan ha ulike signaturer:
      - load_agents(path)
      - load_agents(llm, tools)
      - load_agents()
    Velg variant datadrevet.
    """
    try:
        sig = inspect.signature(load_agents)
        params = list(sig.parameters.values())
        names  = [p.name for p in params]

        # Hvis den tydelig vil ha (llm, tools)
        if ("llm" in names or "tools" in names) and len(params) >= 2:
            return load_agents(llm, tools)

        # Hvis den ser ut til å forvente en sti
        if len(params) >= 1:
            return load_agents(AGENTS_YAML_PATH)

        # Ellers uten argumenter
        return load_agents()
    except TypeError:
        # Fallback: prøv først med sti, hvis ikke: (llm, tools)
        try:
            return load_agents(AGENTS_YAML_PATH)
        except TypeError:
            return load_agents(llm, tools)

# ---------- Lazy-init som faktisk brukes av kjørende kode ----------
from functools import lru_cache

@lru_cache(maxsize=1)
def get_crew_bootstrap() -> Dict[str, Any]:
    """
    Importerer og initialiserer først når den faktisk kalles.
    Kaller loader-funksjonene med YAML-sti hvis nødvendig (ellers uten).
    Returnerer dict med llm/tools/agents/tasks/crew.
    Kaster ev. exception (fanget av /status-route).
    """
    from app.loader import load_llm, load_tools, load_agents, load_tasks, load_crew

    # LLM/Tools/Tasks: prøv med sti hvis signatur tilsier det, ellers uten.
    llm    = _maybe_call_with_path(load_llm,   LLM_YAML_PATH)
    tools  = _maybe_call_with_path(load_tools, TOOLS_YAML_PATH)
    tasks  = _maybe_call_with_path(load_tasks, TASKS_YAML_PATH)

    # Agents: datadrevet deteksjon
    agents = _build_agents(load_agents, llm, tools)

    # Crew: vanligst er load_crew(agents, tasks). Hvis ikke, støtt enklere varianter.
    try:
        sig = inspect.signature(load_crew)
        params = list(sig.parameters.values())
        if len(params) >= 3:
            crew = load_crew("app/config/crew.yaml", agents, tasks)  # tilpass ved behov
        elif len(params) == 2:
            crew = load_crew(agents, tasks)
        elif len(params) == 1:
            crew = load_crew("app/config/crew.yaml")
        else:
            crew = load_crew()
    except Exception:
        # Fallback: mest vanlig
        crew = load_crew(agents, tasks)

    return {"llm": llm, "tools": tools, "agents": agents, "tasks": tasks, "crew": crew}

# ---------- Status (aldri 500) ----------
@app.get("/status")
@app.get("/status/")
def system_status():
    try:
        state = get_crew_bootstrap()  # trigger lazy-init
        CREW_STATE.update({"crew": state["crew"], "ready": True, "error": None})
    except Exception as e:
        CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})
    return {"crew_ready": CREW_STATE["ready"], "error": CREW_STATE["error"]}

# ---------- Start warm-up i bakgrunnen, uten å blokkere oppstart ----------
@app.on_event("startup")
def warm_in_background():
    def _init():
        try:
            state = get_crew_bootstrap()
            CREW_STATE.update({"crew": state["crew"], "ready": True, "error": None})
        except Exception as e:
            CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})
            print("Warm-up failed:", e)
    threading.Thread(target=_init, daemon=True).start()

# ---------- Helpers ----------
def ensure_keys():
    required = ["GROQ_API_KEY"]  # legg til OPENAI_API_KEY osv. ved behov
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing environment variables: {', '.join(missing)}")

def run_crew_pipeline(topic: str) -> dict:
    ensure_keys()
    # sørg for at crew finnes
    if not CREW_STATE["ready"] or CREW_STATE["crew"] is None:
        # forsøk en init på stedet
        try:
            state = get_crew_bootstrap()
            CREW_STATE.update({"crew": state["crew"], "ready": True, "error": None})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Crew not ready: {type(e).__name__}: {e}")

    crew = CREW_STATE["crew"]
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
