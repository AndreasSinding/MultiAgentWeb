
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

# FastAPI app (ASGI variable must be named `app`)
app = FastAPI(title="Market Insights – Multi-Agent Crew API")

# --- Health (rask) ---
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/health")
def health():
    return {"status": "ok"}

# --- Konfig: YAML-stier (leses fra App Settings; har defaults) ---
LLM_YAML_PATH    = os.getenv("LLM_YAML_PATH",    "app/config/llm.yaml")
TOOLS_YAML_PATH  = os.getenv("TOOLS_YAML_PATH",  "app/config/tools.yaml")
AGENTS_YAML_PATH = os.getenv("AGENTS_YAML_PATH", "app/config/agents.yaml")
TASKS_YAML_PATH  = os.getenv("TASKS_YAML_PATH",  "app/config/tasks.yaml")

# --- Global state for readiness og feilmelding ---
CREW_STATE: Dict[str, Any] = {"ready": False, "error": None, "crew": None}

def _maybe_call_with_path(func, path):
    """
    Kall 'func' med filsti hvis signaturen tydelig forventer argumenter;
    ellers kall uten. Robust mot ulike loader-signaturer.
    """
    try:
        sig = inspect.signature(func)
        # Hvis signaturen har minst ett parameter, prøv med sti
        if len(sig.parameters) >= 1:
            return func(path)
        return func()
    except TypeError:
        # Hvis implementasjonen ikke aksepterer path, prøv uten
        return func()

def _build_agents(load_agents, llm, tools):
    """
    load_agents kan ha ulike signaturer:
      - load_agents(path)
      - load_agents(llm, tools)
      - load_agents()  (sjeldent)
    Vi deduserer basert på parameter-navn og antall.
    """
    try:
        sig = inspect.signature(load_agents)
        params = list(sig.parameters.values())
        names  = [p.name for p in params]

        # Hvis den ser ut til å forvente (llm, tools)
        if ("llm" in names or "tools" in names) and len(params) >= 2:
            return load_agents(llm, tools)

        # Hvis den ser ut til å forvente en sti
        if len(params) >= 1:
            return load_agents(AGENTS_YAML_PATH)

        # Ellers uten argumenter
        return load_agents()
    except TypeError:
        # Fallback: prøv først med sti, deretter med (llm, tools)
        try:
            return load_agents(AGENTS_YAML_PATH)
        except TypeError:
            return load_agents(llm, tools)

def _init_crew_once() -> Dict[str, Any]:
    """
    Bygger crew én gang. Fanger unntak og legger feil i CREW_STATE
    slik at /status aldri returnerer 500.
    """
    if CREW_STATE["crew"] is not None:
        CREW_STATE["ready"] = True
        return CREW_STATE

    try:
        from app.loader import load_llm, load_tools, load_agents, load_tasks, load_crew

        # LLM / Tools / Tasks: prøv med sti hvis nødvendig, ellers uten
        llm    = _maybe_call_with_path(load_llm,    LLM_YAML_PATH)
        tools  = _maybe_call_with_path(load_tools,  TOOLS_YAML_PATH)
        tasks  = _maybe_call_with_path(load_tasks,  TASKS_YAML_PATH)

        # Agents: datadrevet valg av signatur
        agents = _build_agents(load_agents, llm, tools)

        # Crew: typisk load_crew(agents, tasks) eller load_crew(path, agents, tasks)
        try:
            sig = inspect.signature(load_crew)
            params = list(sig.parameters.values())
            if len(params) >= 3:
                crew = load_crew("app/config/crew.yaml", agents, tasks)  # just-in-case; tilpass hvis du har en egen crew-fil
            elif len(params) == 2:
                crew = load_crew(agents, tasks)
            elif len(params) == 1:
                crew = load_crew("app/config/crew.yaml")
            else:
                crew = load_crew()
        except Exception:
            # Fallback: mest vanlig er (agents, tasks)
            crew = load_crew(agents, tasks)

        CREW_STATE.update({"crew": crew, "ready": True, "error": None})
    except Exception as e:
        CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})
        print("Crew init failed:", e)

    return CREW_STATE

# --- Warm-up i bakgrunnen (blokkerer ikke oppstart) ---
@app.on_event("startup")
def warm_in_background():
    threading.Thread(target=_init_crew_once, daemon=True).start()

# --- Rask, robust status; både /status og /status/ ---
@app.get("/status")
@app.get("/status/")
def system_status():
    state = _init_crew_once()  # trigge init, men aldri kaste ut feil
    return {"crew_ready": bool(state.get("ready")), "error": state.get("error")}

# ---------- Helpers ----------
def ensure_keys():
    required = ["GROQ_API_KEY"]  # legg til OPENAI_API_KEY hvis nødvendig
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing environment variables: {', '.join(missing)}"
        )

def run_crew_pipeline(topic: str) -> dict:
    ensure_keys()

    # Sørg for at crew finnes
    state = _init_crew_once()
    if not state["ready"] or state["crew"] is None:
        raise HTTPException(status_code=500, detail=f"Crew not ready: {state['error']}")

    crew = state["crew"]

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
