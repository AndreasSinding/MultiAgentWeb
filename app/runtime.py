# app/runtime.py
from __future__ import annotations
import os, importlib
from typing import Dict, Any

# Environment-driven paths (fallbacks align with your main.py)
TOOLS_DIR = os.getenv("TOOLS_DIR", "crew/tools")
AGENTS_DIR = os.getenv("AGENTS_DIR", "crew/agents")
TASKS_DIR = os.getenv("TASKS_DIR", "crew/tasks")
CREW_YAML_PATH = os.getenv("CREW_YAML_PATH", "crew/crews/market_insights.yaml")
LLM_YAML_PATH  = os.getenv("LLM_YAML_PATH",  "config/llm.yaml")

CREW_STATE: Dict[str, Any] = {"ready": False, "error": None, "crew": None, "llm": None}

def build_llm_and_crew_once() -> Dict[str, Any]:
    """Build (or reuse) LLM & Crew deterministically; never raise."""
    if CREW_STATE["ready"] and CREW_STATE["crew"] is not None:
        return CREW_STATE
    try:
        # Import module, not symbols — avoids “cannot import name …” if partially initialized
        loader = importlib.import_module("app.loader")

        missing = [n for n in ("load_llm","load_tools","load_agents","load_tasks","load_crew")
                   if not hasattr(loader, n)]
        if missing:
            CREW_STATE.update({"ready": False, "error": f"Missing in app.loader: {', '.join(missing)}"})
            return CREW_STATE

        llm   = loader.load_llm(LLM_YAML_PATH)
        tools = loader.load_tools(TOOLS_DIR)
        agents= loader.load_agents(AGENTS_DIR, llm, tools)
        tasks = loader.load_tasks(TASKS_DIR, agents)
        crew  = loader.load_crew(CREW_YAML_PATH, agents, tasks)

        CREW_STATE.update({"llm": llm, "crew": crew, "ready": True, "error": None})
    except Exception as e:
        CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})
    return CREW_STATE
