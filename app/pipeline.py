# app/pipeline.py
from __future__ import annotations
import os
import json
import threading
import importlib
import traceback
from typing import Dict, Any
from fastapi import HTTPException

# Root dir
BASE = os.path.dirname(os.path.dirname(__file__))

# Paths (from env or defaults)
TOOLS_DIR = os.getenv("TOOLS_DIR", "crew/tools")
AGENTS_DIR = os.getenv("AGENTS_DIR", "crew/agents")
TASKS_DIR = os.getenv("TASKS_DIR", "crew/tasks")
CREW_YAML_PATH = os.getenv("CREW_YAML_PATH", "crew/crews/market_insights.yaml")
LLM_YAML_PATH = os.getenv("LLM_YAML_PATH", "config/llm.yaml")

# Shared state
CREW_STATE: Dict[str, Any] = {"ready": False, "error": None, "crew": None, "llm": None}


# ---------------------------------------------------------------------
# BUILD CREW (one-time)
# ---------------------------------------------------------------------
def build_llm_and_crew_once() -> Dict[str, Any]:
    if CREW_STATE["ready"] and CREW_STATE["crew"] is not None:
        return CREW_STATE

    try:
        loader = importlib.import_module("app.loader")

        required = ("load_llm", "load_tools", "load_agents", "load_tasks", "load_crew")
        missing = [name for name in required if not hasattr(loader, name)]
        if missing:
            CREW_STATE.update(
                {"ready": False, "error": f"Missing in app.loader: {', '.join(missing)}"}
            )
            return CREW_STATE

        llm = loader.load_llm(LLM_YAML_PATH)
        tools = loader.load_tools(TOOLS_DIR)
        agents = loader.load_agents(AGENTS_DIR, llm, tools)
        tasks = loader.load_tasks(TASKS_DIR, agents)
        crew = loader.load_crew(CREW_YAML_PATH, agents, tasks)

        CREW_STATE.update({"llm": llm, "crew": crew, "ready": True, "error": None})

    except Exception as e:
                
        tb = traceback.format_exc()
        CREW_STATE.update(
            {"ready": False, "error": f"{type(e).__name__}: {e}\nTRACE:\n{tb}"}
        )


    return CREW_STATE


# ---------------------------------------------------------------------
# BACKGROUND WARMUP
# ---------------------------------------------------------------------
def warm_async():
    def _warm():
        try:
            build_llm_and_crew_once()
        except Exception as e:
            CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})

    threading.Thread(target=_warm, daemon=True).start()


# ---------------------------------------------------------------------
# ENV CHECK
# ---------------------------------------------------------------------
def ensure_keys():
    required = ["GROQ_API_KEY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing environment variables: {', '.join(missing)}",
        )


# ---------------------------------------------------------------------
# PIPELINE EXECUTION
# ---------------------------------------------------------------------
def run_crew_pipeline(topic: str) -> Dict[str, Any]:
    ensure_keys()

    state = build_llm_and_crew_once()
    if not state["ready"] or state.get("crew") is None:
        raise HTTPException(
            status_code=500, detail=f"Crew not ready: {state['error']}"
        )

    crew = state["crew"]
    llm = state.get("llm")

    # 1) Run the crew
    raw_result = crew.kickoff({"topic": topic})
    raw_text = raw_result if isinstance(raw_result, str) else str(raw_result)
    raw_text = (raw_text or "").strip()

    # 2) Wrap into tasks_output
    tasks_output = [{"content": raw_text}]

    # 3) Best-effort summary
    summary = None
    if llm:
        prompt = (
            "Summarize the following text (from a multi-agent research pipeline) "
            "in exactly 5–7 bullet points.\nAvoid headings. Only bullet points.\n\n"
            f"TEXT:\n{raw_text}\n"
        )
        try:
            summary = llm(prompt)
            summary = summary if isinstance(summary, str) else str(summary)
        except Exception:
            summary = None

    if not summary or not summary.strip():
        first_lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        summary = "\n".join([f"- {ln[:200]}" for ln in first_lines[:7]]) or "- (no summary)"

    enriched = {
        "summary": summary.strip(),
        "tasks_output": tasks_output,
    }

    # 4) Persist output
    runs_dir = os.path.join(BASE, "runs")
    os.makedirs(runs_dir, exist_ok=True)

    outfile = os.path.join(runs_dir, "latest_output.json")
    tmpfile = outfile + ".tmp"

    with open(tmpfile, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    os.replace(tmpfile, outfile)

    return enriched
